import importlib.util
import json
import os
import subprocess
import sys
from urllib.parse import urljoin

from backend.app.core.config import get_settings
from backend.app.core.extraction import ExtractionError, MAX_LINK_BYTES
from backend.app.core.network_security import NetworkSecurityError, strip_url_credentials, validate_public_http_url, validate_public_ip_address

BROWSER_TIMEOUT_SECONDS = 18
BROWSER_NAVIGATION_TIMEOUT_MS = 12_000
BROWSER_TEXT_TIMEOUT_MS = 5_000
BROWSER_REQUEST_BUDGET = 80
BROWSER_MAX_TEXT_BYTES = MAX_LINK_BYTES
BROWSER_MAX_WORKER_JSON_BYTES = MAX_LINK_BYTES + 64 * 1024
BROWSER_BLOCKED_RESOURCE_TYPES = {"eventsource", "fetch", "font", "image", "media", "websocket", "xhr"}


class BrowserIngestionError(ExtractionError):
    pass


def browser_fallback_available() -> bool:
    return get_settings().enable_dynamic_web_ingestion and importlib.util.find_spec("playwright") is not None


def browser_ingestion_diagnostics() -> dict:
    runtime_available = importlib.util.find_spec("playwright") is not None
    return {
        "available": browser_fallback_available(),
        "enabled": get_settings().enable_dynamic_web_ingestion,
        "runtime_available": runtime_available,
        "isolated_worker": True,
        "timeout_seconds": BROWSER_TIMEOUT_SECONDS,
        "navigation_timeout_ms": BROWSER_NAVIGATION_TIMEOUT_MS,
        "request_budget": BROWSER_REQUEST_BUDGET,
        "max_text_bytes": BROWSER_MAX_TEXT_BYTES,
        "downloads_allowed": False,
        "blocked_resource_types": sorted(BROWSER_BLOCKED_RESOURCE_TYPES),
    }


def browser_derived_security(final_url: str) -> dict:
    return {
        "provenance": "browser_derived",
        "trust_tier": "low_trust_web",
        "security_labels": ["external_web", "browser_derived", "low_trust", "external_untrusted"],
        "browser_isolation": browser_ingestion_diagnostics(),
        "final_url": strip_url_credentials(final_url),
    }


def static_web_security(final_url: str) -> dict:
    return {
        "provenance": "web_static",
        "trust_tier": "imported_web",
        "security_labels": ["external_web", "static_http"],
        "final_url": strip_url_credentials(final_url),
    }


def extract_dynamic_text_from_url_isolated(url: str) -> tuple[str, str, str | None, dict] | None:
    sanitized_url = strip_url_credentials(url)
    try:
        validate_public_http_url(sanitized_url)
    except NetworkSecurityError as exc:
        raise BrowserIngestionError(str(exc)) from exc
    if not browser_fallback_available():
        return None

    command = [sys.executable, "-m", "backend.app.core.browser_worker", sanitized_url]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=BROWSER_TIMEOUT_SECONDS,
            env=_browser_worker_env(),
        )
    except subprocess.TimeoutExpired as exc:
        raise BrowserIngestionError("Browser worker timed out") from exc
    except OSError as exc:
        raise BrowserIngestionError(f"Browser worker failed to launch: {exc}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "Browser worker failed").strip()
        raise BrowserIngestionError(detail[:500])
    raw = completed.stdout.encode("utf-8")
    if len(raw) > BROWSER_MAX_WORKER_JSON_BYTES:
        raise BrowserIngestionError("Browser worker output exceeded the allowed size")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise BrowserIngestionError("Browser worker returned malformed JSON") from exc
    validated = validate_browser_worker_output(payload)
    security = browser_derived_security(validated["final_url"])
    security["request_count"] = validated["request_count"]
    return validated["title"], validated["text"], validated.get("cover_image_url"), security


def validate_browser_worker_output(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise BrowserIngestionError("Browser worker returned invalid output")
    title = payload.get("title")
    text = payload.get("text")
    final_url = strip_url_credentials(str(payload.get("final_url") or ""))
    cover = payload.get("cover_image_url")
    request_count = payload.get("request_count", 0)
    if not isinstance(title, str):
        raise BrowserIngestionError("Browser worker output missing title")
    if not isinstance(text, str) or not text.strip():
        raise BrowserIngestionError("Browser worker produced no readable text")
    if len(text.encode("utf-8")) > BROWSER_MAX_TEXT_BYTES:
        raise BrowserIngestionError("Browser worker text exceeded the allowed size")
    try:
        validate_public_http_url(final_url)
    except NetworkSecurityError as exc:
        raise BrowserIngestionError(str(exc)) from exc
    if cover is not None and not isinstance(cover, str):
        raise BrowserIngestionError("Browser worker cover URL is invalid")
    cover_url = urljoin(final_url, cover) if cover else None
    if cover_url:
        try:
            validate_public_http_url(cover_url)
        except NetworkSecurityError:
            cover_url = None
    if not isinstance(request_count, int) or request_count < 0 or request_count > BROWSER_REQUEST_BUDGET:
        raise BrowserIngestionError("Browser worker request count exceeded the allowed budget")
    return {
        "title": title.strip()[:240],
        "text": text.replace("\x00", "").strip(),
        "final_url": final_url,
        "cover_image_url": cover_url,
        "request_count": request_count,
    }


def browser_worker_extract(url: str) -> dict:
    try:
        validate_public_http_url(url)
    except NetworkSecurityError as exc:
        raise BrowserIngestionError(str(exc)) from exc
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise BrowserIngestionError("Playwright runtime is not installed") from exc

    request_count = 0
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=False)
        page = context.new_page()

        def route_guard(route):
            nonlocal request_count
            request = route.request
            request_count += 1
            if request_count > BROWSER_REQUEST_BUDGET:
                route.abort()
                return
            if request.resource_type in BROWSER_BLOCKED_RESOURCE_TYPES:
                route.abort()
                return
            try:
                validate_public_http_url(strip_url_credentials(request.url))
            except NetworkSecurityError:
                route.abort()
                return
            route.continue_()

        page.route("**/*", route_guard)
        page.on("download", lambda download: download.cancel())
        response = page.goto(url, wait_until="networkidle", timeout=BROWSER_NAVIGATION_TIMEOUT_MS)
        final_url = strip_url_credentials(page.url)
        validate_public_http_url(final_url)
        if response is not None:
            validate_public_http_url(strip_url_credentials(response.url))
            server_addr_fn = getattr(response, "server_addr", None)
            server_addr = server_addr_fn() if callable(server_addr_fn) else None
            if server_addr and server_addr.get("ipAddress"):
                try:
                    validate_public_ip_address(str(server_addr["ipAddress"]))
                except NetworkSecurityError as exc:
                    raise BrowserIngestionError(str(exc)) from exc
            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > BROWSER_MAX_TEXT_BYTES:
                raise BrowserIngestionError("Browser response is too large to ingest safely")
        title = page.title()
        text = page.locator("body").inner_text(timeout=BROWSER_TEXT_TIMEOUT_MS).strip()
        cover = page.locator("meta[property='og:image']").first.get_attribute("content", timeout=1000)
        browser.close()

    if len(text.encode("utf-8")) > BROWSER_MAX_TEXT_BYTES:
        raise BrowserIngestionError("Browser-rendered text is too large to ingest safely")
    if not text:
        raise BrowserIngestionError("Browser worker produced no readable text")
    return {
        "title": title or final_url,
        "text": text,
        "cover_image_url": cover,
        "final_url": final_url,
        "request_count": request_count,
    }


def _browser_worker_env() -> dict[str, str]:
    env = os.environ.copy()
    env["CML_BROWSER_WORKER"] = "1"
    for key in list(env):
        upper = key.upper()
        if upper in {"CML_API_TOKEN", "CML_BRIDGE_TOKEN"}:
            env.pop(key, None)
        elif upper.startswith("CML_") and upper not in {"CML_BROWSER_WORKER"}:
            env.pop(key, None)
    return env
