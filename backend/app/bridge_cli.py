import argparse
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def main() -> int:
    parser = argparse.ArgumentParser(description="Request context from the local CML Bridge.")
    parser.add_argument("query", help="Question or topic to retrieve context for.")
    parser.add_argument("--backend", default=os.getenv("CML_BACKEND_URL", "http://127.0.0.1:7343"))
    parser.add_argument("--token", default=os.getenv("CML_BRIDGE_TOKEN", ""))
    parser.add_argument("--vault-id", default=None)
    parser.add_argument("--cluster-id", default=None)
    parser.add_argument("--client-name", default="cml-cli")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--json", action="store_true", help="Print the raw JSON response.")
    args = parser.parse_args()

    payload = {
        "query": args.query,
        "vault_id": args.vault_id,
        "cluster_id": args.cluster_id,
        "client_name": args.client_name,
        "limit": args.limit,
    }
    response = bridge_request(args.backend, args.token, payload)
    if args.json:
        print(json.dumps(response, indent=2))
        return 0
    print(format_context(response))
    return 0


def bridge_request(backend_url: str, token: str, payload: dict) -> dict:
    request = Request(
        backend_url.rstrip("/") + api_path("/bridge/context"),
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-cml-bridge-token": token,
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise SystemExit(f"Bridge request failed: HTTP {exc.code}") from exc
    except URLError as exc:
        raise SystemExit(f"Bridge is not reachable: {exc.reason}") from exc


def api_path(suffix: str) -> str:
    api_prefix = _normalize_api_prefix(os.getenv("CML_API_PREFIX", "/api/v1"))
    return f"{api_prefix.rstrip('/')}/{suffix.lstrip('/')}"


def _normalize_api_prefix(value: str) -> str:
    raw = str(value or "/api/v1").strip()
    prefixed = raw if raw.startswith("/") else f"/{raw}"
    return prefixed.rstrip("/") or "/api/v1"


def format_context(response: dict) -> str:
    packet_text = str(response.get("packet_text") or "").strip()
    if packet_text:
        return packet_text
    lines = [f"CML context for: {response.get('query', '')}", ""]
    warnings = response.get("warnings") or []
    if warnings:
        lines.append("Warnings:")
        lines.extend(f"- {warning}" for warning in warnings)
        lines.append("")
    clusters = response.get("selected_clusters") or []
    if clusters:
        lines.append("Clusters:")
        lines.extend(f"- {cluster.get('name', cluster.get('id', 'unknown'))}" for cluster in clusters)
        lines.append("")
    sources = response.get("source_snippets") or []
    if sources:
        lines.append("Sources:")
        for index, source in enumerate(sources, start=1):
            text = source.get("extracted_text") or source.get("summary") or source.get("raw_text") or ""
            snippet = " ".join(text.split())[:700]
            lines.append(f"{index}. {source.get('title', 'Untitled')}")
            if snippet:
                lines.append(f"   {snippet}")
    return "\n".join(lines).strip()


if __name__ == "__main__":
    sys.exit(main())
