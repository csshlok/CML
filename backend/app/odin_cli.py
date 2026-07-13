from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


EXIT_BACKEND_UNAVAILABLE = 3
EXIT_AUTHENTICATION = 4
EXIT_INVALID_INPUT = 5
EXIT_PARTIAL = 6
EXIT_CANCELLED = 7
EXIT_INTERNAL = 10


class OdinClientError(RuntimeError):
    def __init__(self, message: str, exit_code: int = EXIT_INTERNAL):
        super().__init__(message)
        self.exit_code = exit_code


class OdinClient:
    def __init__(self, backend_url: str, token: str):
        self.backend_url = backend_url.rstrip("/")
        self.token = token
        self.api_prefix = _normalize_api_prefix(os.getenv("ODIN_API_PREFIX") or os.getenv("CML_API_PREFIX"))

    def request(self, method: str, path: str, payload: dict | None = None) -> object:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = Request(
            f"{self.backend_url}{self.api_prefix}/{path.lstrip('/')}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=120) as response:
                raw = response.read()
                return json.loads(raw.decode("utf-8")) if raw else None
        except HTTPError as exc:
            detail = _http_error_detail(exc)
            code = EXIT_AUTHENTICATION if exc.code in {401, 403} else EXIT_INVALID_INPUT
            raise OdinClientError(detail, code) from exc
        except URLError as exc:
            raise OdinClientError(
                "CML is not running. Open CML and retry, or start the local backend.",
                EXIT_BACKEND_UNAVAILABLE,
            ) from exc

    def projects(self, vault_id: str | None = None) -> list[dict]:
        query = f"?{urlencode({'vault_id': vault_id})}" if vault_id else ""
        return list(self.request("GET", f"projects{query}") or [])


def main() -> int:
    parser = build_parser()
    args = parser.parse_args(_normalize_global_args(sys.argv[1:]))
    backend_url = args.backend or os.getenv("ODIN_BACKEND_URL") or os.getenv("CML_BACKEND_URL") or "http://127.0.0.1:7343"
    token = args.token or os.getenv("ODIN_API_TOKEN") or os.getenv("CML_API_TOKEN") or ""
    client = OdinClient(backend_url, token)
    try:
        result = dispatch(client, args)
    except OdinClientError as exc:
        _print_error(str(exc), as_json=getattr(args, "json", False), exit_code=exc.exit_code)
        return exc.exit_code
    except KeyboardInterrupt:
        _print_error("Odin was cancelled.", as_json=getattr(args, "json", False), exit_code=EXIT_CANCELLED)
        return EXIT_CANCELLED
    except Exception as exc:
        _print_error(f"Odin failed: {exc}", as_json=getattr(args, "json", False), exit_code=EXIT_INTERNAL)
        return EXIT_INTERNAL

    if result is not None:
        if getattr(args, "json", False):
            print(json.dumps({"version": 1, "result": result}, indent=2))
        else:
            print(format_result(args, result))
    if isinstance(result, dict) and result.get("status") == "partial":
        return EXIT_PARTIAL
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="odin",
        description="Odin indexes local code projects into your CML vault without modifying repository files.",
    )
    parser.add_argument("--backend", help="CML backend URL. Defaults to ODIN_BACKEND_URL or CML_BACKEND_URL.")
    parser.add_argument("--token", help=argparse.SUPPRESS)
    parser.add_argument("--json", action="store_true", help="Return versioned JSON output.")
    commands = parser.add_subparsers(dest="command", required=True)

    auth = commands.add_parser("auth", help="Inspect Odin authentication.")
    auth_commands = auth.add_subparsers(dest="auth_command", required=True)
    auth_commands.add_parser("status", help="Verify the local backend session.")
    auth_commands.add_parser("pair", help="Pair Odin with CML Desktop.")

    project = commands.add_parser("project", help="Register and maintain code projects.")
    project_commands = project.add_subparsers(dest="project_command", required=True)

    add = project_commands.add_parser("add", help="Register and index a local project.")
    add.add_argument("path", nargs="?", default=".")
    add.add_argument("--name")
    add.add_argument("--vault-id")
    add.add_argument("--no-sync", action="store_true")

    listing = project_commands.add_parser("list", help="List registered projects.")
    listing.add_argument("--vault-id")

    status = project_commands.add_parser("status", help="Show project indexing status.")
    _add_project_target(status)

    sync = project_commands.add_parser("sync", help="Reconcile the current working tree.")
    _add_project_target(sync)

    reindex = project_commands.add_parser("reindex", help="Rebuild selected Odin-derived data.")
    _add_project_target(reindex)
    reindex.add_argument("--layer", choices=("structure", "retrieval", "interpretation", "full"), default="full")
    reindex.add_argument("--full", action="store_true", help="Rebuild all currently implemented layers.")

    rename = project_commands.add_parser("rename", help="Rename a project and its primary cluster.")
    _add_project_target(rename)
    rename.add_argument("name")

    link = project_commands.add_parser("link", help="Link a project to another cluster.")
    _add_project_target(link)
    link.add_argument("--cluster", required=True)
    link.add_argument("--cluster-id")

    unlink = project_commands.add_parser("unlink", help="Remove a non-primary cluster link.")
    _add_project_target(unlink)
    unlink.add_argument("--cluster", required=True)
    unlink.add_argument("--cluster-id")

    links = project_commands.add_parser("links", help="List a project's cluster links.")
    _add_project_target(links)

    explain = project_commands.add_parser("explain", help="Explain an indexed symbol and its immediate relationships.")
    _add_project_target(explain)
    explain.add_argument("symbol")
    explain.add_argument("--edge-type", action="append", default=[])

    path_query = project_commands.add_parser("path", help="Find a bounded evidence-backed path between two indexed symbols.")
    _add_project_target(path_query)
    path_query.add_argument("source")
    path_query.add_argument("target")
    path_query.add_argument("--max-depth", type=int, default=4)
    path_query.add_argument("--edge-type", action="append", default=[])

    graph = project_commands.add_parser("graph", help="Render a bounded relationship graph for a person or LLM.")
    _add_project_target(graph)
    graph.add_argument("--query", default="")
    graph.add_argument("--depth", type=int, default=2)
    graph.add_argument("--max-nodes", type=int, default=120)
    graph.add_argument("--edge-type", action="append", default=[])
    graph.add_argument("--format", choices=("markdown", "json"), default="markdown")

    tree = project_commands.add_parser("tree", help="Render a bounded project and symbol tree.")
    _add_project_target(tree)
    tree.add_argument("--root", default="")
    tree.add_argument("--query", default="")
    tree.add_argument("--max-nodes", type=int, default=160)
    tree.add_argument("--format", choices=("markdown", "json"), default="markdown")

    remove = project_commands.add_parser("remove", help="Remove an Odin index. Repository files are untouched.")
    _add_project_target(remove)
    remove.add_argument("--yes", action="store_true")

    context = commands.add_parser("context", help="Retrieve an evidence-backed context packet from one project.")
    context.add_argument("query")
    context.add_argument("--project", default=".")
    context.add_argument("--project-id")
    return parser


def dispatch(client: OdinClient, args: argparse.Namespace) -> object:
    if args.command == "auth":
        if args.auth_command == "status":
            health = _health(client.backend_url)
            vaults = client.request("GET", "vaults")
            return {"authenticated": True, "backend": health, "vault_count": len(vaults or [])}
        raise OdinClientError(
            "Desktop pairing is not enabled in this foundation build. Use the desktop-managed CML_API_TOKEN for local development.",
            EXIT_AUTHENTICATION,
        )
    if args.command == "context":
        project = _resolve_project(client, args.project_id, args.project)
        return client.request(
            "POST",
            f"projects/{project['id']}/context",
            {"query": args.query, "limit": 6, "mode": "context"},
        )
    if args.command != "project":
        raise OdinClientError("Unknown Odin command.", EXIT_INVALID_INPUT)

    action = args.project_command
    if action == "add":
        root = _resolved_directory(args.path)
        vault_id = args.vault_id or _active_vault_id(client)
        return client.request(
            "POST",
            "projects",
            {"vault_id": vault_id, "root_path": str(root), "name": args.name, "sync": not args.no_sync},
        )
    if action == "list":
        return client.projects(args.vault_id)

    project = _resolve_project(client, args.project_id, args.path)
    project_id = str(project["id"])
    if action == "status":
        return client.request("GET", f"projects/{project_id}")
    if action == "sync":
        return client.request("POST", f"projects/{project_id}/sync", {})
    if action == "reindex":
        layer = "full" if args.full else args.layer
        return client.request("POST", f"projects/{project_id}/reindex", {"layer": layer})
    if action == "rename":
        return client.request("PATCH", f"projects/{project_id}", {"name": args.name})
    if action in {"link", "unlink"}:
        cluster_id = args.cluster_id or _resolve_cluster_id(client, project["vault_id"], args.cluster)
        if action == "link":
            return client.request("POST", f"projects/{project_id}/links", {"cluster_id": cluster_id})
        client.request("DELETE", f"projects/{project_id}/links/{cluster_id}")
        return {"project_id": project_id, "cluster_id": cluster_id, "unlinked": True}
    if action == "links":
        return client.request("GET", f"projects/{project_id}/links")
    if action == "explain":
        nodes = client.request("GET", f"projects/{project_id}/graph/nodes?{urlencode({'q': args.symbol, 'limit': 5})}") or []
        exact = [node for node in nodes if str(node["display_label"]).casefold() == args.symbol.casefold() or str(node["qualified_id"]).casefold() == args.symbol.casefold()]
        if len(exact) != 1:
            raise OdinClientError("Symbol was not found or is ambiguous; use its qualified ID.", EXIT_INVALID_INPUT)
        query = [("edge_type", item) for item in args.edge_type]
        suffix = f"?{urlencode(query)}" if query else ""
        return client.request("GET", f"projects/{project_id}/graph/nodes/{exact[0]['id']}/neighbors{suffix}")
    if action == "path":
        query = [
            ("source", args.source),
            ("target", args.target),
            ("max_depth", str(args.max_depth)),
            *[("edge_type", item) for item in args.edge_type],
        ]
        return client.request("GET", f"projects/{project_id}/graph/path?{urlencode(query)}")
    if action in {"graph", "tree"}:
        query = [
            ("mode", action),
            ("q", args.query),
            ("max_nodes", str(args.max_nodes)),
        ]
        if action == "graph":
            query.extend([("max_depth", str(args.depth)), *[("edge_type", item) for item in args.edge_type]])
        else:
            query.append(("root", args.root))
        view = client.request("GET", f"projects/{project_id}/graph/view?{urlencode(query)}")
        if args.format == "json":
            return view
        return _format_graph_markdown(dict(view))
    if action == "remove":
        if not args.yes and sys.stdin.isatty():
            print(f"Remove {project['name']} from CML?")
            print("This deletes Odin's imported index. Repository files will not be changed.")
            confirmation = input(f"Type {project['name']} to continue: ").strip()
            if confirmation != project["name"]:
                raise OdinClientError("Removal cancelled.", EXIT_CANCELLED)
        elif not args.yes:
            raise OdinClientError("Non-interactive removal requires --yes.", EXIT_INVALID_INPUT)
        client.request("DELETE", f"projects/{project_id}", {"confirmation_name": project["name"]})
        return {"project_id": project_id, "removed": True, "repository_files_changed": False}
    raise OdinClientError("Unknown project command.", EXIT_INVALID_INPUT)


def format_result(args: argparse.Namespace, result: object) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, list):
        if not result:
            return "No Odin projects found."
        if args.command == "project" and args.project_command == "links":
            return "\n".join(f"{item['cluster_name']}  {item['role']}  {item['cluster_id']}" for item in result)
        return "\n".join(_project_line(item) for item in result)
    if not isinstance(result, dict):
        return str(result)
    if "project" in result and isinstance(result["project"], dict):
        project = result["project"]
        run = result.get("run") or {}
        suffix = f"\nRun: {run.get('status', 'queued')} · {run.get('completed_count', 0)}/{run.get('eligible_total', 0)} files"
        return _project_detail(project) + suffix
    if "name" in result and "primary_cluster_id" in result:
        return _project_detail(result)
    if result.get("authenticated"):
        return f"Odin is authenticated to {result['backend']['service']} · {result['vault_count']} vault(s) available."
    if result.get("removed"):
        return "Project removed from CML. Repository files were not changed."
    return json.dumps(result, indent=2)


def _format_graph_markdown(view: dict) -> str:
    lines = [
        f"# Odin {str(view['mode']).title()} Context",
        "",
        f"Snapshot: {view['snapshot_id']}",
        f"Scope: {view.get('query') or view.get('root') or 'major project areas'}",
        f"Bounded: {'yes' if view.get('truncated') else 'no'}",
        "",
        "## Nodes",
    ]
    for node in view.get("nodes", []):
        location = str(node.get("relative_path") or "project")
        if node.get("start_line"):
            location += f":{node['start_line']}"
        lines.append(f"- [{node['id']}] {node['kind']} {node['label']} ({location})")
    lines.extend(["", "## Relationships"])
    for edge in view.get("edges", []):
        lines.append(f"- [{edge['source']}] --{edge['type']}--> [{edge['target']}]")
    for warning in view.get("warnings", []):
        lines.append(f"\nNote: {warning}")
    return "\n".join(lines)


def _project_line(project: dict) -> str:
    return f"{project['name']}  {project['status']}  {project.get('source_count', 0)} files  {project['root_path']}"


def _project_detail(project: dict) -> str:
    commit = str(project.get("indexed_commit") or "")[:7] or "folder snapshot"
    languages = ", ".join(list((project.get("languages") or {}).keys())[:3]) or "not detected"
    return "\n".join(
        [
            f"{project['name']} · {project['status']}",
            f"Root: {project['root_path']}",
            f"Snapshot: {commit} · {project.get('source_count', 0)} indexed files",
            f"Languages: {languages}",
            f"Structure: {project['structure_status']} · Search: {project['retrieval_status']} · Brief: {project['interpretation_status']}",
        ]
    )


def _add_project_target(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--project-id")


def _resolve_project(client: OdinClient, project_id: str | None, path: str) -> dict:
    if project_id:
        return dict(client.request("GET", f"projects/{project_id}"))
    root = _resolved_directory(path)
    normalized = os.path.normcase(os.path.normpath(str(root)))
    for project in client.projects():
        candidate = os.path.normcase(os.path.normpath(str(project["root_path"])))
        if candidate == normalized:
            return project
    raise OdinClientError("This folder is not registered with Odin. Run `odin project add . --name NAME`.", EXIT_INVALID_INPUT)


def _resolve_cluster_id(client: OdinClient, vault_id: str, name: str) -> str:
    clusters = client.request("GET", f"clusters?{urlencode({'vault_id': vault_id, 'limit': 1000})}") or []
    matches = [item for item in clusters if str(item["name"]).casefold() == name.casefold()]
    if len(matches) != 1:
        raise OdinClientError("Cluster name was not found or is ambiguous; use --cluster-id.", EXIT_INVALID_INPUT)
    return str(matches[0]["id"])


def _active_vault_id(client: OdinClient) -> str:
    vaults = list(client.request("GET", "vaults") or [])
    if len(vaults) == 1:
        return str(vaults[0]["id"])
    if not vaults:
        raise OdinClientError("No vault is open. Create or open a vault in CML first.", EXIT_INVALID_INPUT)
    raise OdinClientError("More than one vault is available; pass --vault-id.", EXIT_INVALID_INPUT)


def _resolved_directory(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.exists() or not path.is_dir():
        raise OdinClientError("Project path must be an existing directory.", EXIT_INVALID_INPUT)
    return path.resolve()


def _health(backend_url: str) -> dict:
    try:
        with urlopen(backend_url.rstrip("/") + "/health", timeout=3) as response:
            return json.loads(response.read().decode("utf-8"))
    except (URLError, HTTPError) as exc:
        raise OdinClientError("CML is not running. Open CML and retry.", EXIT_BACKEND_UNAVAILABLE) from exc


def _normalize_api_prefix(value: str | None) -> str:
    raw = (value or "/api/v1").strip()
    return "/" + raw.strip("/")


def _normalize_global_args(argv: list[str]) -> list[str]:
    """Allow PowerShell users to place global options before or after subcommands."""
    globals_: list[str] = []
    remainder: list[str] = []
    index = 0
    while index < len(argv):
        argument = argv[index]
        if argument == "--json":
            globals_.append(argument)
            index += 1
            continue
        if argument in {"--backend", "--token"} and index + 1 < len(argv):
            globals_.extend([argument, argv[index + 1]])
            index += 2
            continue
        remainder.append(argument)
        index += 1
    return [*globals_, *remainder]


def _http_error_detail(exc: HTTPError) -> str:
    try:
        payload = json.loads(exc.read().decode("utf-8"))
        detail = payload.get("detail")
        if isinstance(detail, str) and detail:
            return detail
    except (ValueError, UnicodeDecodeError):
        pass
    return f"Odin request failed with HTTP {exc.code}."


def _print_error(message: str, *, as_json: bool, exit_code: int) -> None:
    if as_json:
        print(json.dumps({"version": 1, "error": {"message": message, "exit_code": exit_code}}, indent=2), file=sys.stderr)
    else:
        print(message, file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
