import json
import sys
from urllib.parse import urljoin

from backend.app.core.browser_ingestion import (
    _browser_worker_extract_with_browser,
    browser_worker_extract,
)


def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] == "--server":
        return server_main()
    if len(sys.argv) != 2:
        print("Usage: python -m backend.app.core.browser_worker <url>", file=sys.stderr)
        return 2
    try:
        payload = browser_worker_extract(sys.argv[1])
    except Exception as exc:
        print(str(exc)[:500], file=sys.stderr)
        return 1
    if payload.get("cover_image_url"):
        payload["cover_image_url"] = urljoin(payload.get("final_url") or sys.argv[1], payload["cover_image_url"])
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def server_main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        print(json.dumps({"id": "", "ok": False, "error": str(exc)[:500]}), flush=True)
        return 1
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for line in sys.stdin:
                request_id = ""
                try:
                    request = json.loads(line)
                    request_id = str(request.get("id") or "")
                    url = str(request.get("url") or "")
                    payload = _browser_worker_extract_with_browser(browser, url)
                    if payload.get("cover_image_url"):
                        payload["cover_image_url"] = urljoin(
                            payload.get("final_url") or url, payload["cover_image_url"]
                        )
                    response = {"id": request_id, "ok": True, "payload": payload}
                except Exception as exc:
                    response = {"id": request_id, "ok": False, "error": str(exc)[:500]}
                print(json.dumps(response, ensure_ascii=False), flush=True)
        finally:
            browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
