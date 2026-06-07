import json
import sys
from urllib.parse import urljoin

from backend.app.core.browser_ingestion import browser_worker_extract


def main() -> int:
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


if __name__ == "__main__":
    raise SystemExit(main())
