from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import psutil


EXIT_BACKEND_UNAVAILABLE = 3
EXIT_AUTHENTICATION = 4
EXIT_INVALID_INPUT = 5
EXIT_PARTIAL = 6
EXIT_CANCELLED = 7
EXIT_INTERNAL = 10


class OdinClientError(RuntimeError):
    def __init__(
        self,
        message: str,
        exit_code: int = EXIT_INTERNAL,
        *,
        code: str = "odin_error",
        next_action: str = "",
    ):
        super().__init__(message)
        self.exit_code = exit_code
        self.code = code
        self.next_action = next_action


DEFAULT_CLI_SCOPES = [
    "cluster:link",
    "context:read",
    "project:read",
    "project:write",
    "source:read",
]
BUSY_RETRY_ATTEMPTS = 4
BUSY_RETRY_SECONDS = 1.0


class OdinClient:
    def __init__(self, backend_url: str, token: str, *, api_prefix: str | None = None):
        self.backend_url = backend_url.rstrip("/")
        self.token = token
        self.api_prefix = _normalize_api_prefix(
            api_prefix or os.getenv("ODIN_API_PREFIX") or os.getenv("CML_API_PREFIX")
        )
        self.auth_context: dict | None = None

    def request(
        self, method: str, path: str, payload: dict | None = None, *, headers: dict | None = None
    ) -> object:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request_headers = {"Accept": "application/json"}
        if body is not None:
            request_headers["Content-Type"] = "application/json"
        if self.token:
            request_headers["Authorization"] = f"Bearer {self.token}"
        request_headers.update(headers or {})
        request = Request(
            f"{self.backend_url}{self.api_prefix}/{path.lstrip('/')}",
            data=body,
            headers=request_headers,
            method=method,
        )
        for attempt in range(BUSY_RETRY_ATTEMPTS):
            try:
                with urlopen(request, timeout=120) as response:
                    raw = response.read()
                    return json.loads(raw.decode("utf-8")) if raw else None
            except HTTPError as exc:
                detail = _http_error_detail(exc)
                if exc.code == 503 and detail == "cli_auth_store_busy":
                    if attempt + 1 < BUSY_RETRY_ATTEMPTS:
                        time.sleep(BUSY_RETRY_SECONDS)
                        continue
                    raise OdinClientError(
                        "CML is busy indexing. Wait a moment and retry Odin pairing.",
                        EXIT_BACKEND_UNAVAILABLE,
                        code="cli_auth_store_busy",
                        next_action="retry",
                    ) from exc
                if detail in {
                    "executable_fingerprint_mismatch",
                    "Executable fingerprint mismatch.",
                }:
                    raise OdinClientError(
                        "Odin changed since this computer approved it. Repair Odin in Vault Settings, then pair it again.",
                        EXIT_AUTHENTICATION,
                        code="executable_fingerprint_mismatch",
                        next_action="repair_and_pair",
                    ) from exc
                code = EXIT_AUTHENTICATION if exc.code in {401, 403} else EXIT_INVALID_INPUT
                raise OdinClientError(
                    detail,
                    code,
                    code=_machine_error_code(detail),
                    next_action="pair" if exc.code in {401, 403} else "review_input",
                ) from exc
            except URLError as exc:
                raise OdinClientError(
                    "CML is not running. Open CML and retry, or start the local backend.",
                    EXIT_BACKEND_UNAVAILABLE,
                ) from exc
        raise OdinClientError(
            "CML is busy indexing. Wait a moment and retry Odin pairing.",
            EXIT_BACKEND_UNAVAILABLE,
        )

    def projects(self, vault_id: str | None = None) -> list[dict]:
        query = f"?{urlencode({'vault_id': vault_id})}" if vault_id else ""
        return list(self.request("GET", f"projects{query}") or [])


def main() -> int:
    parser = build_parser()
    args = parser.parse_args(_normalize_global_args(sys.argv[1:]))
    try:
        if args.command == "auth" and args.auth_command in {"logout", "forget"}:
            result = _credential_helper("forget")
            result["authenticated"] = False
            result["client_registration_retained"] = True
            if getattr(args, "json", False):
                print(json.dumps({"version": 1, "result": result}, indent=2))
            else:
                print(
                    "Odin is signed out on this computer. You can revoke its retained client access in Vault Settings."
                )
            return 0
        if args.command == "doctor":
            result = _doctor(args.backend)
        else:
            descriptor = _load_runtime_descriptor(args.backend)
            client = OdinClient(descriptor["backend_url"], "", api_prefix=descriptor["api_prefix"])
            if args.command == "auth" and args.auth_command == "pair":
                result = _pair(client, descriptor, as_json=getattr(args, "json", False))
            else:
                development_token = _development_token(args)
                if development_token:
                    client.token = development_token
                else:
                    _establish_cli_session(client, descriptor)
                result = dispatch(client, args)
    except OdinClientError as exc:
        _print_error(
            str(exc),
            as_json=getattr(args, "json", False),
            exit_code=exc.exit_code,
            code=exc.code,
            next_action=exc.next_action,
        )
        return exc.exit_code
    except KeyboardInterrupt:
        _print_error(
            "Odin was cancelled.", as_json=getattr(args, "json", False), exit_code=EXIT_CANCELLED
        )
        return EXIT_CANCELLED
    except Exception as exc:
        _print_error(
            f"Odin failed: {exc}", as_json=getattr(args, "json", False), exit_code=EXIT_INTERNAL
        )
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
    parser.add_argument(
        "--backend", help="CML backend URL. Defaults to ODIN_BACKEND_URL or CML_BACKEND_URL."
    )
    parser.add_argument("--token", help=argparse.SUPPRESS)
    parser.add_argument("--json", action="store_true", help="Return versioned JSON output.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "doctor",
        help="Check the local Odin launcher, Vault connection, and approval without reading project files.",
    )

    auth = commands.add_parser("auth", help="Inspect Odin authentication.")
    auth_commands = auth.add_subparsers(dest="auth_command", required=True)
    auth_commands.add_parser("status", help="Verify the local backend session.")
    auth_commands.add_parser("pair", help="Pair Odin with CML Desktop.")
    auth_commands.add_parser("logout", help="Remove this computer's stored Odin credential.")
    auth_commands.add_parser(
        "forget", help="Forget a stale local pairing without changing Vault access."
    )

    project = commands.add_parser("project", help="Register and maintain code projects.")
    project_commands = project.add_subparsers(dest="project_command", required=True)

    add = project_commands.add_parser("add", help="Register and index a local project.")
    add.add_argument("path", nargs="?", default=".")
    add.add_argument("--name")
    add.add_argument("--vault-id")
    add.add_argument(
        "--scope",
        choices=("context", "code"),
        default="context",
        help="Index code plus project context (default), or code files only.",
    )
    add.add_argument("--no-sync", action="store_true")
    add.add_argument("--no-wait", action="store_true")

    listing = project_commands.add_parser("list", help="List registered projects.")
    listing.add_argument("--vault-id")

    status = project_commands.add_parser("status", help="Show project indexing status.")
    _add_project_target(status)

    changes = project_commands.add_parser(
        "changes",
        help="Show new, changed, and removed files without rebuilding the project index.",
    )
    _add_project_target(changes)
    changes.add_argument("--max-paths", type=int, default=5000)

    sync = project_commands.add_parser("sync", help="Reconcile the current working tree.")
    _add_project_target(sync)
    sync.add_argument(
        "--scope",
        choices=("context", "code"),
        help="Persist a new discovery scope before synchronizing.",
    )
    sync.add_argument(
        "--full",
        action="store_true",
        help="Rebuild every project layer instead of applying changed files.",
    )
    sync.add_argument(
        "--changed",
        action="store_true",
        help="Apply changed files only (the default when --scope and --full are omitted).",
    )
    sync.add_argument("--no-wait", action="store_true")

    reindex = project_commands.add_parser("reindex", help="Rebuild selected Odin-derived data.")
    _add_project_target(reindex)
    reindex.add_argument(
        "--layer", choices=("structure", "retrieval", "interpretation", "full"), default="full"
    )
    reindex.add_argument(
        "--full", action="store_true", help="Rebuild all currently implemented layers."
    )
    reindex.add_argument("--no-wait", action="store_true")

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

    explain = project_commands.add_parser(
        "explain", help="Explain an indexed symbol and its immediate relationships."
    )
    _add_project_target(explain)
    explain.add_argument("symbol")
    explain.add_argument("--edge-type", action="append", default=[])

    path_query = project_commands.add_parser(
        "path", help="Find a bounded evidence-backed path between two indexed symbols."
    )
    _add_project_target(path_query)
    path_query.add_argument("source")
    path_query.add_argument("target")
    path_query.add_argument("--max-depth", type=int, default=4)
    path_query.add_argument("--edge-type", action="append", default=[])

    graph = project_commands.add_parser(
        "graph", help="Render a bounded relationship graph for a person or LLM."
    )
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

    for operation, help_text in (
        ("overview", "Show the evidence-backed project overview."),
        ("state", "Show live Git and indexed repository state."),
        ("change-context", "Explain current changes and their test impact."),
        ("decisions", "List active and stale architectural decisions."),
    ):
        command = project_commands.add_parser(operation, help=help_text)
        _add_project_target(command)
        command.add_argument("--expanded", action="store_true")
    code_context = project_commands.add_parser(
        "code-context", help="Find structural code context for a question."
    )
    _add_project_target(code_context)
    code_context.add_argument("query")
    code_context.add_argument("--expanded", action="store_true")
    blast = project_commands.add_parser(
        "blast-radius", help="Show bounded upstream impact for a symbol or path."
    )
    _add_project_target(blast)
    blast.add_argument("target")
    blast.add_argument("--expanded", action="store_true")
    coverage = project_commands.add_parser(
        "coverage", help="Show coverage state or test impact for changed paths."
    )
    _add_project_target(coverage)
    coverage.add_argument("--changed-path", action="append", default=[])
    coverage.add_argument("--import-lcov", default="")
    coverage.add_argument("--expanded", action="store_true")

    remove = project_commands.add_parser(
        "remove", help="Remove an Odin index. Repository files are untouched."
    )
    _add_project_target(remove)
    remove.add_argument("--yes", action="store_true")

    context = commands.add_parser(
        "context", help="Retrieve an evidence-backed context packet from one project."
    )
    context.add_argument("query")
    context.add_argument("--project", default=".")
    context.add_argument("--project-id")
    context.add_argument("--project-name")
    context.add_argument(
        "--require-fresh",
        action="store_true",
        help="Synchronize detected project changes before retrieving context.",
    )
    return parser


def dispatch(client: OdinClient, args: argparse.Namespace) -> object:
    if args.command == "auth":
        if args.auth_command == "status":
            health = _health(client.backend_url)
            me = client.auth_context or dict(client.request("GET", "cli-auth/me"))
            return {
                "authenticated": True,
                "backend": health,
                "client": me,
                "vault_count": len(me.get("allowed_vault_ids", [])),
            }
        raise OdinClientError("Unknown Odin authentication command.", EXIT_INVALID_INPUT)
    if args.command == "context":
        project = _resolve_project(client, args.project_id, args.project, args.project_name)
        if args.require_fresh:
            project = _ensure_fresh_project(client, project)
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
        created = client.request(
            "POST",
            "projects",
            {
                "vault_id": vault_id,
                "root_path": str(root),
                "name": args.name,
                "discovery_scope": args.scope,
                "sync": not args.no_sync,
            },
        )
        if args.no_sync or args.no_wait:
            return created
        runs = list(client.request("GET", f"projects/{created['id']}/runs?limit=1&offset=0") or [])
        return _wait_for_project_run(client, dict(created), runs[0]) if runs else created
    if action == "list":
        return client.projects(args.vault_id)

    project = _resolve_project(client, args.project_id, args.path, args.project_name)
    project_id = str(project["id"])
    if action == "status":
        return client.request("GET", f"projects/{project_id}")
    if action == "changes":
        return client.request(
            "GET",
            f"projects/{project_id}/changes?{urlencode({'max_paths': args.max_paths})}",
        )
    if action == "sync":
        if args.changed and (args.full or args.scope):
            raise OdinClientError(
                "--changed cannot be combined with --full or --scope.",
                EXIT_INVALID_INPUT,
            )
        if not args.full and not args.scope:
            report = dict(client.request("POST", f"projects/{project_id}/sync-changes", {}))
            if not report.get("changed") or args.no_wait:
                return report
            current_project = dict(client.request("GET", f"projects/{project_id}"))
            run_id = current_project.get("active_run_id")
            if not run_id:
                return report
            run = dict(client.request("GET", f"projects/{project_id}/runs/{run_id}"))
            return _wait_for_project_run(client, current_project, run)
        body = {"discovery_scope": args.scope} if args.scope else {}
        queued = dict(client.request("POST", f"projects/{project_id}/sync", body))
        return (
            queued
            if args.no_wait
            else _wait_for_project_run(client, queued["project"], queued["run"])
        )
    if action == "reindex":
        layer = "full" if args.full else args.layer
        queued = dict(client.request("POST", f"projects/{project_id}/reindex", {"layer": layer}))
        if args.no_wait or "run" not in queued:
            return queued
        return _wait_for_project_run(client, queued["project"], queued["run"])
    if action == "rename":
        return client.request("PATCH", f"projects/{project_id}", {"name": args.name})
    if action in {"link", "unlink"}:
        cluster_id = args.cluster_id or _resolve_cluster_id(
            client, project["vault_id"], args.cluster
        )
        if action == "link":
            return client.request(
                "POST", f"projects/{project_id}/links", {"cluster_id": cluster_id}
            )
        client.request("DELETE", f"projects/{project_id}/links/{cluster_id}")
        return {"project_id": project_id, "cluster_id": cluster_id, "unlinked": True}
    if action == "links":
        return client.request("GET", f"projects/{project_id}/links")
    if action == "explain":
        nodes = (
            client.request(
                "GET",
                f"projects/{project_id}/graph/nodes?{urlencode({'q': args.symbol, 'limit': 5})}",
            )
            or []
        )
        exact = [
            node
            for node in nodes
            if str(node["display_label"]).casefold() == args.symbol.casefold()
            or str(node["qualified_id"]).casefold() == args.symbol.casefold()
        ]
        if len(exact) != 1:
            raise OdinClientError(
                "Symbol was not found or is ambiguous; use its qualified ID.", EXIT_INVALID_INPUT
            )
        query = [("edge_type", item) for item in args.edge_type]
        suffix = f"?{urlencode(query)}" if query else ""
        return client.request(
            "GET", f"projects/{project_id}/graph/nodes/{exact[0]['id']}/neighbors{suffix}"
        )
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
            query.extend(
                [("max_depth", str(args.depth)), *[("edge_type", item) for item in args.edge_type]]
            )
        else:
            query.append(("root", args.root))
        view = client.request("GET", f"projects/{project_id}/graph/view?{urlencode(query)}")
        if args.format == "json":
            return view
        return _format_graph_markdown(dict(view))
    operation_names = {
        "overview": "overview",
        "state": "project_state",
        "change-context": "change_context",
        "code-context": "code_context",
        "blast-radius": "blast_radius",
        "decisions": "decisions",
        "coverage": "coverage",
    }
    if action in operation_names:
        if action == "coverage" and args.import_lcov:
            return client.request(
                "POST",
                f"projects/{project_id}/coverage/import",
                {"artifact_path": str(Path(args.import_lcov).resolve())},
            )
        body = {"operation": operation_names[action], "compact": not args.expanded}
        if action == "code-context":
            body["query"] = args.query
        if action == "blast-radius":
            body["target"] = args.target
        if action == "coverage":
            body["changed_paths"] = args.changed_path
        return client.request("POST", f"projects/{project_id}/operations", body)
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


def _wait_for_project_run(client: OdinClient, project: dict, run: dict) -> dict:
    project_id = str(project["id"])
    run_id = str(run["id"])
    last_signature: tuple | None = None
    try:
        while True:
            current = dict(client.request("GET", f"projects/{project_id}/runs/{run_id}"))
            signature = (
                current.get("status"),
                current.get("phase"),
                current.get("phase_completed_count"),
                current.get("phase_total_count"),
            )
            if signature != last_signature:
                _print_run_progress(current)
                last_signature = signature
            status = str(current.get("status") or "")
            if status in {"succeeded", "partial", "failed", "cancelled"}:
                refreshed = dict(client.request("GET", f"projects/{project_id}"))
                if status == "failed":
                    raise OdinClientError(
                        f"Odin indexing failed during {current.get('phase') or 'indexing'}. The previous active index remains available.",
                        EXIT_INTERNAL,
                    )
                if status == "cancelled":
                    raise OdinClientError(
                        "Odin indexing was cancelled. The previous active index remains available.",
                        EXIT_CANCELLED,
                    )
                return {"project": refreshed, "run": current, "status": status}
            time.sleep(max(0.1, float(os.getenv("ODIN_RUN_POLL_SECONDS", "0.5"))))
    except KeyboardInterrupt as exc:
        try:
            cancelled = dict(client.request("POST", f"projects/{project_id}/cancel", {}))
            active = project.get("active_snapshot_id") or "the previous snapshot"
            raise OdinClientError(
                f"Cancellation requested for {cancelled['id']}. {active} remains active.",
                EXIT_CANCELLED,
            ) from exc
        except OdinClientError:
            raise
        except Exception as cancel_error:
            raise OdinClientError(
                "Odin was interrupted before cancellation could be confirmed. Check `odin project status`.",
                EXIT_CANCELLED,
            ) from cancel_error


def _print_run_progress(run: dict) -> None:
    event = {
        "version": 1,
        "type": "odin.project.progress",
        "run_id": run.get("id"),
        "status": run.get("status"),
        "phase": run.get("phase"),
        "completed": run.get("phase_completed_count", 0),
        "total": run.get("phase_total_count", 0),
    }
    if sys.stderr.isatty():
        total = int(event["total"] or 0)
        progress = f" {event['completed']}/{total}" if total else ""
        print(f"Odin: {event['phase']} / {event['status']}{progress}", file=sys.stderr)
    else:
        print(json.dumps(event, separators=(",", ":")), file=sys.stderr)


def format_result(args: argparse.Namespace, result: object) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, list):
        if not result:
            return "No Odin projects found."
        if args.command == "project" and args.project_command == "links":
            return "\n".join(
                f"{item['cluster_name']}  {item['role']}  {item['cluster_id']}" for item in result
            )
        return "\n".join(_project_line(item) for item in result)
    if not isinstance(result, dict):
        return str(result)
    if args.command == "doctor":
        lines = [f"Odin check: {result.get('status', 'unknown')}"]
        for check in result.get("checks", []):
            lines.append(
                f"- {check.get('name')}: {check.get('status')}"
                + (f" — {check.get('detail')}" if check.get("detail") else "")
            )
        if result.get("next_action"):
            lines.append(f"Next: {result['next_action']}")
        return "\n".join(lines)
    if "evidence_summary" in result and "retrieval_authority" in result:
        evidence = result.get("evidence_summary") or {}
        freshness = result.get("freshness") or {}
        lines = [
            f"{result.get('project_name', 'Project')} context",
            (
                f"Evidence: {evidence.get('implementation_files', 0)} implementation, "
                f"{evidence.get('test_files', 0)} test, "
                f"{evidence.get('documentation_files', 0)} documentation files"
            ),
            (
                f"Snapshot: {freshness.get('retrieval_snapshot_id') or result.get('snapshot_id')} · "
                f"Authority: {'verified' if result.get('retrieval_authority') else 'limited'}"
            ),
        ]
        for snippet in (result.get("source_snippets") or [])[:6]:
            text = (
                str(snippet.get("text") or snippet.get("snippet") or "").strip()
                if isinstance(snippet, dict)
                else str(snippet).strip()
            )
            if text:
                lines.append(f"\n{text}")
        limitations = list(result.get("limitations") or [])
        if limitations:
            lines.append("\nLimits:")
            lines.extend(f"- {item}" for item in limitations)
        return "\n".join(lines)
    if "project" in result and isinstance(result["project"], dict):
        project = result["project"]
        run = result.get("run") or {}
        suffix = f"\nRun: {run.get('status', 'queued')} · {run.get('completed_count', 0)}/{run.get('eligible_total', 0)} files"
        return _project_detail(project) + suffix
    if "name" in result and "primary_cluster_id" in result:
        return _project_detail(result)
    if "changed_paths" in result and "detection_mode" in result:
        paths = list(result.get("changed_paths") or [])
        heading = (
            f"{len(paths)} changed path{'s' if len(paths) != 1 else ''}"
            if result.get("changed")
            else "Project files are current"
        )
        details = [heading, f"Detection: {result['detection_mode']}"]
        details.extend(f"- {path}" for path in paths)
        if result.get("requires_full_scan"):
            details.append(
                "A lightweight fingerprint found changes; synchronization will verify the folder."
            )
        if result.get("truncated"):
            details.append("More changed paths exist. Use --max-paths to raise the limit.")
        return "\n".join(details)
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
    lines = [
        f"{project['name']} · {project['status']}",
        f"Root: {project['root_path']}",
        f"Scope: {project.get('discovery_scope', 'context')}",
        f"Snapshot: {commit} · {project.get('source_count', 0)} indexed files",
        f"Languages: {languages}",
        f"Structure: {project['structure_status']} · Search: {project['retrieval_status']} · Brief: {project['interpretation_status']}",
        f"Automatic sync: {'on' if project.get('auto_sync_enabled', True) else 'off'}",
        (
            f"Last change check: {project.get('last_change_checked_at')}"
            if project.get("last_change_checked_at")
            else "Last change check: not yet"
        ),
    ]
    if project.get("structure_status") == "stale" and project.get("retrieval_status") == "ready":
        lines.append(
            "Freshness: search includes the latest file changes; run `odin project sync .` "
            "when you need a current structure map."
        )
    return "\n".join(lines)


def _add_project_target(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--project-id")
    parser.add_argument("--project-name")


def _resolve_project(
    client: OdinClient,
    project_id: str | None,
    path: str,
    project_name: str | None = None,
) -> dict:
    if project_id:
        return dict(client.request("GET", f"projects/{project_id}"))
    if project_name:
        matches = [
            project
            for project in client.projects()
            if str(project.get("name") or "").casefold() == project_name.strip().casefold()
        ]
        if len(matches) == 1:
            return dict(matches[0])
        if not matches:
            raise OdinClientError(
                f"No registered project is named {project_name!r}. Use `odin project list`.",
                EXIT_INVALID_INPUT,
            )
        choices = ", ".join(str(project["id"]) for project in matches[:5])
        raise OdinClientError(
            f"More than one project is named {project_name!r}. Use --project-id ({choices}).",
            EXIT_INVALID_INPUT,
        )
    root = _resolved_directory(path)
    normalized = os.path.normcase(os.path.normpath(str(root)))
    for project in client.projects():
        candidate = os.path.normcase(os.path.normpath(str(project["root_path"])))
        if candidate == normalized:
            return project
    raise OdinClientError(
        "This folder is not registered with Odin. Run `odin project add . --name NAME`.",
        EXIT_INVALID_INPUT,
    )


def _ensure_fresh_project(client: OdinClient, project: dict) -> dict:
    project_id = str(project["id"])
    report = dict(client.request("POST", f"projects/{project_id}/sync-changes", {}))
    if not report.get("changed"):
        return dict(client.request("GET", f"projects/{project_id}"))
    current = dict(client.request("GET", f"projects/{project_id}"))
    run_id = current.get("active_run_id")
    if not run_id:
        raise OdinClientError(
            "Project changes were detected, but synchronization did not start.",
            EXIT_PARTIAL,
        )
    run = dict(client.request("GET", f"projects/{project_id}/runs/{run_id}"))
    result = _wait_for_project_run(client, current, run)
    return dict(result["project"])


def _resolve_cluster_id(client: OdinClient, vault_id: str, name: str) -> str:
    clusters = (
        client.request("GET", f"clusters?{urlencode({'vault_id': vault_id, 'limit': 1000})}") or []
    )
    matches = [item for item in clusters if str(item["name"]).casefold() == name.casefold()]
    if len(matches) != 1:
        raise OdinClientError(
            "Cluster name was not found or is ambiguous; use --cluster-id.", EXIT_INVALID_INPUT
        )
    return str(matches[0]["id"])


def _active_vault_id(client: OdinClient) -> str:
    allowed = list((client.auth_context or {}).get("allowed_vault_ids", []))
    if len(allowed) == 1:
        return str(allowed[0])
    if not allowed:
        raise OdinClientError(
            "No vault is open. Create or open a vault in CML first.", EXIT_INVALID_INPUT
        )
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
        raise OdinClientError(
            "CML is not running. Open CML and retry.", EXIT_BACKEND_UNAVAILABLE
        ) from exc


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


def _load_runtime_descriptor(explicit_backend: str | None = None) -> dict:
    candidates: list[Path] = []
    override = os.getenv("ODIN_RUNTIME_FILE")
    if override:
        candidates.append(Path(override).expanduser())
    app_data = os.getenv("APPDATA")
    if app_data:
        candidates.append(Path(app_data) / "Vault" / "odin-runtime.json")
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            descriptor = json.loads(candidate.read_text(encoding="utf-8"))
            _validate_runtime_descriptor(descriptor, explicit_backend=explicit_backend)
            return descriptor
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            continue
    raise OdinClientError(
        "Vault Desktop is not available. Open Vault and retry.", EXIT_BACKEND_UNAVAILABLE
    )


def _validate_runtime_descriptor(descriptor: dict, *, explicit_backend: str | None = None) -> None:
    if int(descriptor["version"]) != 1:
        raise ValueError("unsupported runtime descriptor")
    backend_url = str(descriptor["backend_url"]).rstrip("/")
    if not backend_url.startswith(("http://127.0.0.1:", "http://localhost:", "http://[::1]:")):
        raise ValueError("backend is not loopback")
    if explicit_backend and backend_url != explicit_backend.rstrip("/"):
        raise ValueError("explicit backend does not match desktop runtime")
    if datetime.fromisoformat(str(descriptor["expires_at"]).replace("Z", "+00:00")) <= datetime.now(
        UTC
    ):
        raise ValueError("runtime descriptor expired")
    if not str(descriptor["backend_instance_id"]):
        raise ValueError("backend identity missing")
    desktop_pid = int(descriptor["desktop_pid"])
    if desktop_pid <= 0 or not _process_exists(desktop_pid):
        raise ValueError("desktop PID invalid")


def _process_exists(process_id: int) -> bool:
    try:
        process = psutil.Process(process_id)
        return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
    except psutil.AccessDenied:
        return True
    except (psutil.NoSuchProcess, psutil.ZombieProcess, ValueError):
        return False


def _development_token(args: argparse.Namespace) -> str:
    token = args.token or os.getenv("ODIN_API_TOKEN") or os.getenv("CML_API_TOKEN") or ""
    if not token:
        return ""
    if os.getenv("ODIN_ALLOW_DEVELOPMENT_TOKEN") != "1":
        raise OdinClientError(
            "Direct API tokens are disabled. Run `odin auth pair`.", EXIT_AUTHENTICATION
        )
    return token


def _doctor(explicit_backend: str | None = None) -> dict:
    checks: list[dict[str, str]] = [
        {
            "name": "launcher",
            "status": "ready",
            "detail": str(Path(sys.argv[0]).resolve()),
        }
    ]
    try:
        descriptor = _load_runtime_descriptor(explicit_backend)
    except OdinClientError as exc:
        checks.append({"name": "vault", "status": "unavailable", "detail": str(exc)})
        return {
            "status": "attention",
            "checks": checks,
            "error_code": exc.code,
            "next_action": exc.next_action or "open_vault",
            "reads_project_content": False,
        }
    checks.append(
        {
            "name": "vault",
            "status": "ready",
            "detail": "The local Vault runtime is available.",
        }
    )
    try:
        _credential_helper("read")
    except OdinClientError as exc:
        checks.append(
            {
                "name": "approval",
                "status": "missing",
                "detail": "This computer has not stored an Odin approval.",
            }
        )
        return {
            "status": "attention",
            "checks": checks,
            "error_code": exc.code,
            "next_action": "pair",
            "reads_project_content": False,
        }
    client = OdinClient(
        descriptor["backend_url"],
        "",
        api_prefix=descriptor["api_prefix"],
    )
    try:
        _establish_cli_session(client, descriptor)
    except OdinClientError as exc:
        checks.append({"name": "approval", "status": "repair_needed", "detail": str(exc)})
        return {
            "status": "attention",
            "checks": checks,
            "error_code": exc.code,
            "next_action": exc.next_action or "pair",
            "reads_project_content": False,
        }
    checks.append(
        {
            "name": "approval",
            "status": "ready",
            "detail": "The launcher matches its approved identity.",
        }
    )
    return {
        "status": "ready",
        "checks": checks,
        "next_action": "none",
        "reads_project_content": False,
    }


def _pair(client: OdinClient, descriptor: dict, *, as_json: bool) -> dict:
    verifier = secrets.token_urlsafe(48)
    verifier_hash = hashlib.sha256(verifier.encode("utf-8")).hexdigest()
    fingerprint = _executable_fingerprint()
    challenge = dict(
        client.request(
            "POST",
            "cli-auth/pairing-challenges",
            {
                "verifier_hash": verifier_hash,
                "requested_scopes": DEFAULT_CLI_SCOPES,
                "requester_name": f"Odin CLI on {os.environ.get('COMPUTERNAME', 'this computer')}",
                "executable_fingerprint": fingerprint,
                "runtime_instance_id": descriptor["backend_instance_id"],
            },
        )
    )
    if not as_json:
        print("Approve this Odin request in Vault Settings. Waiting for up to five minutes...")
    deadline = time.monotonic() + 300
    interval = max(0.1, float(os.getenv("ODIN_PAIR_POLL_SECONDS", "1")))
    while time.monotonic() < deadline:
        status = dict(
            client.request(
                "GET",
                f"cli-auth/pairing-challenges/{challenge['id']}/status",
                headers={"X-Odin-Pairing-Verifier": verifier},
            )
        )
        if status["status"] == "approved":
            consumed = dict(
                client.request(
                    "POST",
                    f"cli-auth/pairing-challenges/{challenge['id']}/consume",
                    {"verifier": verifier},
                )
            )
            _credential_helper(
                "store", client_id=consumed["client"]["id"], secret=consumed["credential"]
            )
            _establish_cli_session(client, descriptor)
            return {"paired": True, "client": client.auth_context}
        if status["status"] in {"denied", "expired"}:
            raise OdinClientError(
                f"The Odin pairing request was {status['status']}.", EXIT_AUTHENTICATION
            )
        time.sleep(interval)
    raise OdinClientError(
        "The Odin pairing request expired before it was approved.", EXIT_AUTHENTICATION
    )


def _establish_cli_session(client: OdinClient, descriptor: dict) -> None:
    stored = _credential_helper("read")
    session = dict(
        client.request(
            "POST",
            "cli-auth/sessions",
            {
                "client_id": stored["client_id"],
                "credential": stored["credential"],
                "executable_fingerprint": _executable_fingerprint(),
            },
        )
    )
    client.token = session["session_token"]
    me = dict(client.request("GET", "cli-auth/me"))
    if me.get("backend_instance_id") != descriptor["backend_instance_id"]:
        client.token = ""
        raise OdinClientError(
            "Vault restarted while Odin was connecting. Retry the command.", EXIT_AUTHENTICATION
        )
    client.auth_context = me


def _credential_helper(
    command: str, *, client_id: str | None = None, secret: str | None = None
) -> dict:
    module = f"{__package__}.odin_credential_helper"
    arguments = [sys.executable, "-m", module, command]
    if client_id:
        arguments.extend(["--client-id", client_id])
    completed = subprocess.run(
        arguments,
        input=secret,
        text=True,
        capture_output=True,
        check=False,
        timeout=15,
    )
    if completed.returncode != 0:
        try:
            message = json.loads(completed.stderr).get("error")
        except (ValueError, AttributeError):
            message = None
        raise OdinClientError(
            message or "Odin could not access its Windows credential.", EXIT_AUTHENTICATION
        )
    return dict(json.loads(completed.stdout))


def _executable_fingerprint() -> str:
    digest = hashlib.sha256()
    executable = Path(sys.executable).resolve()
    digest.update(str(executable).encode("utf-8"))
    try:
        stat = executable.stat()
        digest.update(f"{stat.st_size}:{stat.st_mtime_ns}".encode("ascii"))
    except OSError:
        pass
    digest.update(Path(__file__).read_bytes())
    return digest.hexdigest()


def _http_error_detail(exc: HTTPError) -> str:
    try:
        payload = json.loads(exc.read().decode("utf-8"))
        detail = payload.get("detail")
        if isinstance(detail, str) and detail:
            return detail
    except (ValueError, UnicodeDecodeError):
        pass
    return f"Odin request failed with HTTP {exc.code}."


def _machine_error_code(detail: str) -> str:
    normalized = detail.strip().casefold().replace(" ", "_").replace("-", "_").rstrip("._")
    if normalized and all(character.isalnum() or character == "_" for character in normalized):
        return normalized[:80]
    return "odin_request_failed"


def _print_error(
    message: str,
    *,
    as_json: bool,
    exit_code: int,
    code: str = "odin_error",
    next_action: str = "",
) -> None:
    if as_json:
        error = {"code": code, "message": message, "exit_code": exit_code}
        if next_action:
            error["next_action"] = next_action
        print(json.dumps({"version": 1, "error": error}, indent=2), file=sys.stderr)
    else:
        print(message, file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
