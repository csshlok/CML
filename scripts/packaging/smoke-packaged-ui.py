"""Rendered packaged-Electron smoke through its Chromium debugging endpoint."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
from urllib.request import urlopen

import psutil
from playwright.sync_api import sync_playwright


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def read_cdp_targets(endpoint: str) -> list[dict[str, object]]:
    with urlopen(f"{endpoint}/json/list", timeout=1) as response:
        return json.loads(response.read().decode("utf-8"))


def wait_for_cdp(port: int, timeout: float = 45) -> str:
    deadline = time.monotonic() + timeout
    endpoint = f"http://127.0.0.1:{port}"
    while time.monotonic() < deadline:
        try:
            with urlopen(f"{endpoint}/json/version", timeout=1) as response:
                if response.status == 200:
                    return endpoint
        except Exception:
            time.sleep(0.2)
    raise RuntimeError("Packaged Electron did not expose its local test endpoint.")


def stop_tree(pid: int) -> None:
    try:
        parent = psutil.Process(pid)
    except psutil.Error:
        return
    processes = parent.children(recursive=True)
    for process in reversed(processes):
        try:
            process.terminate()
        except psutil.Error:
            pass
    try:
        parent.terminate()
    except psutil.Error:
        pass
    _, alive = psutil.wait_procs([*processes, parent], timeout=8)
    for process in alive:
        try:
            process.kill()
        except psutil.Error:
            pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", required=True)
    parser.add_argument("--report", default="tmp/packaged-ui-smoke.json")
    parser.add_argument("--screenshot", default="tmp/packaged-ui-smoke.png")
    args = parser.parse_args()
    package_root = Path(args.package_root).resolve()
    executable = package_root / "CML.exe"
    if not executable.is_file():
        raise SystemExit(f"Packaged app is missing: {executable}")
    repo_root = Path(__file__).resolve().parents[2]
    report_path = (repo_root / args.report).resolve()
    screenshot_path = (repo_root / args.screenshot).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
    user_data = Path(tempfile.mkdtemp(prefix="cml-packaged-ui-"))
    port = free_port()
    child_environment = os.environ.copy()
    # Codex and some Electron test runners set this globally. Passing it to the
    # packaged application turns CML.exe into a Node process, so no renderer or
    # debugging endpoint can ever start.
    child_environment.pop("ELECTRON_RUN_AS_NODE", None)
    process = subprocess.Popen(
        [
            str(executable),
            f"--remote-debugging-port={port}",
            f"--user-data-dir={user_data}",
        ],
        cwd=package_root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=child_environment,
    )
    try:
        endpoint = wait_for_cdp(port)
        renderer_deadline = time.monotonic() + 90
        observed_urls: set[str] = set()
        while time.monotonic() < renderer_deadline:
            try:
                targets = read_cdp_targets(endpoint)
                observed_urls.update(
                    str(target.get("url", ""))
                    for target in targets
                    if target.get("type") == "page"
                )
                if any(
                    target.get("type") == "page"
                    and not str(target.get("url", "")).startswith("data:text/html")
                    for target in targets
                ):
                    break
            except Exception:
                pass
            time.sleep(0.2)
        else:
            raise RuntimeError(
                "Packaged renderer never left the local startup document. "
                f"Observed URLs: {sorted(observed_urls)}"
            )
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(endpoint)
            console_errors: list[str] = []
            pages = [item for context in browser.contexts for item in context.pages]
            page = next(
                (
                    candidate
                    for candidate in pages
                    if not candidate.url.startswith("data:text/html")
                ),
                None,
            )
            if page is None:
                raise RuntimeError(
                    "Renderer target appeared but Playwright could not attach to it."
                )
            page.on(
                "console",
                lambda message: console_errors.append(message.text[:500])
                if message.type == "error"
                else None,
            )
            page.set_viewport_size({"width": 1024, "height": 680})
            page.wait_for_load_state("domcontentloaded")
            page.locator("body").wait_for(state="visible", timeout=30_000)
            page.wait_for_timeout(1_000)
            body_text = page.locator("body").inner_text()
            buttons = page.get_by_role("button").all()
            layout = page.evaluate(
                """() => ({
                  clientWidth: document.documentElement.clientWidth,
                  scrollWidth: document.documentElement.scrollWidth,
                  clientHeight: document.documentElement.clientHeight,
                  scrollHeight: document.documentElement.scrollHeight,
                  activeElement: document.activeElement?.tagName || ""
                })"""
            )
            page.screenshot(path=str(screenshot_path), full_page=True)
            title = page.title()
            renderer_url = page.url
            browser.close()
        pass_value = (
            "Vault" in title
            and len(body_text.strip()) > 20
            and len(buttons) > 0
            and layout["scrollWidth"] <= layout["clientWidth"]
            and not console_errors
        )
        report = {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "package_root": str(package_root),
            "title": title,
            "renderer_url": renderer_url,
            "viewport": {"width": 1024, "height": 680},
            "layout": layout,
            "button_count": len(buttons),
            "body_text_length": len(body_text),
            "console_errors": console_errors,
            "screenshot": str(screenshot_path),
            "pass": pass_value,
        }
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 0 if pass_value else 1
    finally:
        stop_tree(process.pid)


if __name__ == "__main__":
    raise SystemExit(main())
