import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from backend.app.core.cluster_bundle import build_cluster_bundle_context
from backend.app.core.database import connect
from backend.app.core.project_graph import (
    GraphQueryError,
    find_nodes,
    graph_view,
    graph_view_markdown,
    graph_summary,
    node_neighbors,
    shortest_path,
)
from backend.app.core.project_intelligence import get_project_intelligence
from backend.app.core.project_decisions import create_project_decision, relate_project_decisions, set_decision_status
from backend.app.core.project_operations import enqueue_project_intelligence_layers, run_project_operation, route_project_intent

from backend.app.core.projects import (
    ProjectError,
    cancel_project_run,
    get_project,
    get_project_run,
    inspect_project_changes,
    link_project,
    list_project_links,
    list_project_runs,
    list_projects,
    list_projects_page,
    register_project,
    probe_project_changes,
    reindex_project,
    remove_project,
    sync_project,
    sync_project_delta,
    unlink_project,
    update_project,
)
from backend.app.schemas import (
    ProjectCreate,
    ProjectIndexRunRead,
    ProjectIntelligenceSnapshotRead,
    ProjectLinkCreate,
    ProjectLinkRead,
    ProjectRead,
    ProjectReindexRequest,
    ProjectRemoveRequest,
    ProjectSyncResponse,
    ProjectSyncRequest,
    ProjectTargetedSyncRequest,
    ProjectUpdate,
)


def _enforce_cli_project_vault(request: Request, project_id: str | None = None) -> None:
    context = getattr(request.state, "cli_auth", None)
    if not context or not project_id:
        return
    with connect() as conn:
        row = conn.execute(
            "SELECT vault_id FROM projects WHERE id = ? AND deleted_at IS NULL",
            (project_id,),
        ).fetchone()
    if row is not None and row["vault_id"] not in context["allowed_vault_ids"]:
        raise HTTPException(status_code=403, detail="CLI client is not approved for this vault")


def _enforce_cli_vault(request: Request, vault_id: str) -> None:
    context = getattr(request.state, "cli_auth", None)
    if context and vault_id not in context["allowed_vault_ids"]:
        raise HTTPException(status_code=403, detail="CLI client is not approved for this vault")


router = APIRouter(
    prefix="/projects",
    tags=["projects"],
    dependencies=[Depends(_enforce_cli_project_vault)],
)


class ProjectOperationRequest(BaseModel):
    operation: str = Field(pattern="^(overview|code_context|project_state|change_context|blast_radius|decisions|coverage)$")
    query: str = Field(default="", max_length=8_000)
    target: str = Field(default="", max_length=1_000)
    targets: list[str] = Field(default_factory=list, max_length=100)
    changed_paths: list[str] = Field(default_factory=list, max_length=5_000)
    changed_lines: dict[str, list[int]] = Field(default_factory=dict)
    compact: bool = True


class ProjectIntentRequest(BaseModel):
    query: str = Field(min_length=1, max_length=8_000)


class ProjectDecisionCreateRequest(BaseModel):
    statement: str = Field(min_length=1, max_length=2_000)
    rationale: str = Field(default="", max_length=4_000)
    governed_paths: list[str] = Field(default_factory=list, max_length=200)
    idempotency_key: str = Field(default="", max_length=240)


class ProjectDecisionStatusRequest(BaseModel):
    status: str = Field(pattern="^(active|superseded|dismissed)$")


class ProjectDecisionRelationshipRequest(BaseModel):
    target_decision_id: str = Field(min_length=1, max_length=240)
    relationship_type: str = Field(pattern="^(supersedes|refines|relates_to|conflicts_with)$")
    confirmed: bool = False


class ProjectCoverageImportRequest(BaseModel):
    artifact_path: str = Field(min_length=1, max_length=4_000)


class ProjectContextRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    limit: int = Field(default=6, ge=1, le=12)
    mode: str = "context"


@router.get("", response_model=list[ProjectRead])
def project_list(
    request: Request,
    vault_id: str | None = None,
    cluster_id: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[dict]:
    context = getattr(request.state, "cli_auth", None)
    if vault_id:
        _enforce_cli_vault(request, vault_id)
    rows = list_projects(vault_id=vault_id, cluster_id=cluster_id, limit=limit, offset=offset)
    if context and not vault_id:
        rows = [row for row in rows if row["vault_id"] in context["allowed_vault_ids"]]
    return rows


@router.get("/page")
def project_list_page(
    request: Request,
    vault_id: str | None = None,
    cluster_id: str | None = None,
    limit: int = 100,
    cursor: str | None = None,
) -> dict:
    context = getattr(request.state, "cli_auth", None)
    if vault_id:
        _enforce_cli_vault(request, vault_id)
    page = list_projects_page(
        vault_id=vault_id,
        cluster_id=cluster_id,
        limit=limit,
        cursor=cursor,
    )
    if context and not vault_id:
        allowed = set(context["allowed_vault_ids"])
        page["items"] = [row for row in page["items"] if row["vault_id"] in allowed]
        # A scoped CLI may need to continue past a page containing only projects
        # outside its allowlist, so preserve the underlying continuation token.
    return page


@router.get("/project-run-summary")
def project_run_summary(limit: int = 200, active_only: bool = False) -> dict:
    safe_limit = max(1, min(int(limit), 500))
    status_clause = "AND r.status IN ('queued', 'running')" if active_only else ""
    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT
                p.id AS joined_project_id,
                p.name AS project_name,
                p.vault_id AS project_vault_id,
                r.*
            FROM project_index_runs r
            JOIN projects p ON p.id = r.project_id
            WHERE p.deleted_at IS NULL {status_clause}
            ORDER BY
                CASE WHEN r.status IN ('queued', 'running') THEN 0 ELSE 1 END,
                r.updated_at DESC,
                r.id DESC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
    return {
        "items": [
            {
                "project": {
                    "id": row["joined_project_id"],
                    "name": row["project_name"],
                    "vault_id": row["project_vault_id"],
                },
                "run": {
                    key: row[key]
                    for key in row.keys()
                    if key not in {"joined_project_id", "project_name", "project_vault_id"}
                },
            }
            for row in rows
        ],
        "limit": safe_limit,
    }


@router.get("/cluster-membership-summary")
def project_cluster_membership_summary(request: Request, vault_id: str) -> dict:
    _enforce_cli_vault(request, vault_id)
    with connect() as conn:
        if conn.execute("SELECT id FROM vaults WHERE id = ?", (vault_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="Vault not found")
        rows = conn.execute(
            """
            SELECT DISTINCT primary_cluster_id AS cluster_id
            FROM projects
            WHERE vault_id = ? AND deleted_at IS NULL
            ORDER BY primary_cluster_id
            """,
            (vault_id,),
        ).fetchall()
    return {"cluster_ids": [str(row["cluster_id"]) for row in rows]}


@router.post("", response_model=ProjectRead)
def project_create(payload: ProjectCreate, request: Request) -> dict:
    _enforce_cli_vault(request, payload.vault_id)
    try:
        return register_project(
            vault_id=payload.vault_id,
            root_path=payload.root_path,
            name=payload.name,
            discovery_scope=payload.discovery_scope,
            auto_sync_enabled=payload.auto_sync_enabled,
            sync_mode=payload.sync_mode,
            sync=payload.sync,
        )
    except ProjectError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{project_id}", response_model=ProjectRead)
def project_get(project_id: str) -> dict:
    try:
        return get_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc


@router.get("/{project_id}/intelligence", response_model=ProjectIntelligenceSnapshotRead)
def project_intelligence_get(project_id: str) -> dict:
    try:
        return get_project_intelligence(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc


@router.post("/{project_id}/intelligence/refresh", status_code=202)
def project_intelligence_refresh(project_id: str, layer: str = Query(default="all", pattern="^(all|overview|graph|git|decisions)$")) -> dict:
    try:
        layers = ["overview", "graph", "git", "decisions"] if layer == "all" else [layer]
        return enqueue_project_intelligence_layers(project_id, layers=layers, user_initiated=True)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc


@router.post("/{project_id}/intent")
def project_intent(project_id: str, payload: ProjectIntentRequest) -> dict:
    try:
        get_project(project_id)
        return {"project_id": project_id, **route_project_intent(payload.query, project_id=project_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc


@router.post("/{project_id}/operations")
def project_operation(project_id: str, payload: ProjectOperationRequest) -> dict:
    try:
        return run_project_operation(project_id, payload.operation, query=payload.query, target=payload.target,
                                     targets=payload.targets,
                                     changed_paths=payload.changed_paths, changed_lines=payload.changed_lines,
                                     compact=payload.compact)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project or target not found") from exc
    except (ValueError, GraphQueryError, ProjectError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{project_id}/decisions", status_code=201)
def project_decision_create(project_id: str, payload: ProjectDecisionCreateRequest) -> dict:
    try:
        return create_project_decision(project_id, statement=payload.statement, rationale=payload.rationale,
                                       governed_paths=payload.governed_paths, idempotency_key=payload.idempotency_key)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/{project_id}/decisions/{decision_id}")
def project_decision_status(project_id: str, decision_id: str, payload: ProjectDecisionStatusRequest) -> dict:
    try:
        return set_decision_status(project_id, decision_id, payload.status)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Decision not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{project_id}/decisions/{decision_id}/relationships")
def project_decision_relationship(project_id: str, decision_id: str, payload: ProjectDecisionRelationshipRequest) -> dict:
    try:
        return relate_project_decisions(project_id, decision_id, payload.target_decision_id,
                                        payload.relationship_type, confirmed=payload.confirmed)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Decision not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{project_id}/coverage/import", status_code=202)
def project_coverage_import(project_id: str, payload: ProjectCoverageImportRequest) -> dict:
    try:
        return enqueue_project_intelligence_layers(project_id, layers=["coverage"],
                                                   artifact_path=payload.artifact_path, user_initiated=True)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{project_id}/changes")
def project_changes(project_id: str, max_paths: int = 5000) -> dict:
    try:
        return inspect_project_changes(project_id, max_paths=max_paths)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except ProjectError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/{project_id}", response_model=ProjectRead)
def project_update(project_id: str, payload: ProjectUpdate) -> dict:
    try:
        return update_project(
            project_id,
            name=payload.name,
            root_path=payload.root_path,
            discovery_scope=payload.discovery_scope,
            auto_sync_enabled=payload.auto_sync_enabled,
            sync_mode=payload.sync_mode,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except ProjectError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{project_id}/sync", response_model=ProjectSyncResponse, status_code=202)
def project_sync(project_id: str, payload: ProjectSyncRequest | None = None) -> dict:
    try:
        return sync_project(
            project_id,
            discovery_scope=payload.discovery_scope if payload is not None else None,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except ProjectError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{project_id}/sync-changes", status_code=202)
def project_sync_changes(project_id: str) -> dict:
    try:
        return probe_project_changes(project_id, force_sync=True)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except ProjectError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{project_id}/sync-targeted", status_code=202)
def project_sync_targeted(project_id: str, payload: ProjectTargetedSyncRequest) -> dict:
    try:
        report = inspect_project_changes(project_id, max_paths=5000)
        available = {str(path) for path in report.get("changed_paths") or []}
        requested = list(dict.fromkeys(str(path).replace("\\", "/") for path in payload.paths))
        unsupported = [path for path in requested if path not in available]
        if unsupported:
            raise ProjectError("Targeted sync paths must come from the current project change set.")
        if report.get("detection_mode") != "snapshot_git_delta" or report.get("truncated"):
            raise ProjectError("Targeted sync is unavailable until Vault can compute a complete Git delta.")
        queued = sync_project_delta(
            project_id,
            changed_paths=requested,
            trigger_source="question_targeted",
        )
        return {
            **queued,
            "freshness_token": str(queued.get("snapshot_id") or queued.get("job_id") or ""),
            "targeted_paths": requested,
            "next_action": "wait_for_freshness",
        }
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except ProjectError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{project_id}/freshness/{freshness_token}")
def project_freshness(project_id: str, freshness_token: str) -> dict:
    with connect() as conn:
        project = conn.execute(
            """
            SELECT active_retrieval_snapshot_id, candidate_snapshot_id, active_run_id
            FROM projects
            WHERE id = ? AND deleted_at IS NULL
            """,
            (project_id,),
        ).fetchone()
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        if project["active_retrieval_snapshot_id"] == freshness_token:
            return {
                "project_id": project_id,
                "freshness_token": freshness_token,
                "status": "current",
                "next_action": "answer_question",
            }
        run = (
            conn.execute(
                "SELECT status, failure_category FROM project_index_runs WHERE id = ?",
                (project["active_run_id"],),
            ).fetchone()
            if project["active_run_id"]
            else None
        )
    if project["candidate_snapshot_id"] == freshness_token and run is not None:
        return {
            "project_id": project_id,
            "freshness_token": freshness_token,
            "status": str(run["status"]),
            "failure_category": str(run["failure_category"] or ""),
            "next_action": (
                "wait"
                if str(run["status"]) in {"queued", "running"}
                else "retry_sync"
            ),
        }
    return {
        "project_id": project_id,
        "freshness_token": freshness_token,
        "status": "superseded",
        "next_action": "refresh_changes",
    }


@router.post("/{project_id}/reindex", status_code=202)
def project_reindex(project_id: str, payload: ProjectReindexRequest) -> dict:
    try:
        return reindex_project(project_id, layer=payload.layer)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except ProjectError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{project_id}/cancel")
def project_cancel(project_id: str) -> dict:
    try:
        return cancel_project_run(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except ProjectError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{project_id}/links", response_model=list[ProjectLinkRead])
def project_links(project_id: str) -> list[dict]:
    try:
        return list_project_links(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc


@router.post("/{project_id}/links", response_model=ProjectLinkRead)
def project_link(project_id: str, payload: ProjectLinkCreate) -> dict:
    try:
        return link_project(project_id, payload.cluster_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except ProjectError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{project_id}/links/{cluster_id}", status_code=204)
def project_unlink(project_id: str, cluster_id: str) -> Response:
    try:
        unlink_project(project_id, cluster_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project link not found") from exc
    except ProjectError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(status_code=204)


@router.get("/{project_id}/runs", response_model=list[ProjectIndexRunRead])
def project_runs(project_id: str, limit: int = 50, offset: int = 0) -> list[dict]:
    try:
        get_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    return list_project_runs(project_id, limit=limit, offset=offset)


@router.get("/{project_id}/runs/{run_id}", response_model=ProjectIndexRunRead)
def project_run(project_id: str, run_id: str) -> dict:
    try:
        get_project(project_id)
        run = get_project_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project run not found") from exc
    if run["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="Project run not found")
    return run


@router.delete("/{project_id}", status_code=204)
def project_remove(project_id: str, payload: ProjectRemoveRequest) -> Response:
    try:
        remove_project(project_id, confirmation_name=payload.confirmation_name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except ProjectError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(status_code=204)


@router.get("/{project_id}/graph/summary")
def project_graph_summary(project_id: str) -> dict:
    try:
        return graph_summary(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except GraphQueryError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{project_id}/graph/view")
def project_graph_view(
    project_id: str,
    mode: str = "graph",
    q: str = Query(default="", max_length=500),
    root: str = Query(default="", max_length=500),
    max_depth: int = 2,
    max_nodes: int = 120,
    edge_type: list[str] | None = Query(default=None),
    direction: str = Query(default="outbound", pattern="^(outbound|inbound|balanced)$"),
) -> dict:
    try:
        return graph_view(
            project_id, mode=mode, query=q, root=root, max_depth=max_depth,
            max_nodes=max_nodes, edge_types=edge_type, direction=direction,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except GraphQueryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{project_id}/graph/export")
def project_graph_export(
    project_id: str,
    format: str = Query(default="markdown", pattern="^(markdown|json)$"),
    mode: str = "graph",
    q: str = Query(default="", max_length=500),
    root: str = Query(default="", max_length=500),
    max_depth: int = 2,
    max_nodes: int = 160,
    edge_type: list[str] | None = Query(default=None),
    direction: str = Query(default="outbound", pattern="^(outbound|inbound|balanced)$"),
):
    try:
        view = graph_view(
            project_id, mode=mode, query=q, root=root, max_depth=max_depth,
            max_nodes=max_nodes, edge_types=edge_type, direction=direction,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except GraphQueryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if format == "json":
        return view
    return PlainTextResponse(graph_view_markdown(view), media_type="text/markdown")


@router.post("/{project_id}/context")
def project_context(project_id: str, payload: ProjectContextRequest) -> dict:
    try:
        project = get_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    bundle = build_cluster_bundle_context(
        vault_id=project["vault_id"],
        query=payload.query,
        cluster_id=project["primary_cluster_id"],
        token_budget=payload.limit,
        mode=payload.mode,
    )
    structural_candidates: dict[str, tuple[int, dict]] = {}
    terms = _context_query_terms(payload.query)
    for term in terms:
        try:
            candidates = find_nodes(project_id, term, limit=5)
        except GraphQueryError:
            continue
        for candidate in candidates:
            score = _context_candidate_score(candidate, term)
            existing = structural_candidates.get(candidate["id"])
            if existing is None or score < existing[0]:
                structural_candidates[candidate["id"]] = (score, candidate)
    structural_hits = [candidate for _score, candidate in sorted(
        structural_candidates.values(),
        key=lambda item: (item[0], len(str(item[1]["display_label"])), str(item[1]["qualified_id"])),
    )[:12]]
    structural_question = _is_structural_project_question(payload.query)
    citations = list(bundle.get("citations") or [])
    evidence = _project_evidence_summary(project_id, citations)
    if (
        evidence["implementation_files"] == 0
        and len(citations) < max(1, int(payload.limit))
        and (structural_question or _is_project_overview_question(payload.query))
    ):
        orientation = _project_orientation_evidence(project_id)
        if orientation is not None:
            citations.append(orientation["citation"])
            bundle.setdefault("source_snippets", []).append(orientation["source_snippet"])
            evidence = _project_evidence_summary(project_id, citations)
    stale_retrieval = int(project.get("changed_file_count") or 0) > 0
    stale_structure = project.get("structure_status") == "stale"
    limitations: list[str] = []
    if not citations:
        limitations.append("No indexed project files matched this question.")
    if evidence["implementation_files"] == 0:
        limitations.append("No implementation file was included in the evidence.")
    if structural_question and not structural_hits:
        limitations.append("No matching code symbol or relationship was found.")
    if stale_retrieval:
        limitations.append("Local project changes are not included in this snapshot.")
    if structural_question and stale_structure:
        limitations.append("The project map is older than the searchable file snapshot.")
    authority = (
        bool(bundle.get("retrieval_authority", False))
        and bool(citations)
        and evidence["implementation_files"] > 0
        and not stale_retrieval
        and (not structural_question or (bool(structural_hits) and not stale_structure))
    )
    return {
        "project_id": project_id,
        "project_name": project["name"],
        "snapshot_id": project["active_retrieval_snapshot_id"],
        "structure_snapshot_id": project["active_structure_snapshot_id"],
        "indexed_commit": project["indexed_commit"],
        "query": payload.query,
        "citations": citations,
        "source_snippets": bundle.get("source_snippets") or [],
        "structural_hits": structural_hits,
        "warnings": [*(bundle.get("warnings") or []), *limitations],
        "retrieval_authority": authority,
        "evidence_summary": evidence,
        "freshness": {
            "retrieval_status": project["retrieval_status"],
            "structure_status": project["structure_status"],
            "changed_file_count": int(project.get("changed_file_count") or 0),
            "includes_unindexed_changes": False,
            "retrieval_snapshot_id": project["active_retrieval_snapshot_id"],
            "structure_snapshot_id": project["active_structure_snapshot_id"],
        },
        "limitations": limitations,
        "token_estimate": bundle.get("token_estimate") or {},
        "bundle_status": bundle.get("bundle_status") or {},
    }


def _project_evidence_summary(project_id: str, citations: list[dict]) -> dict:
    source_ids = sorted({
        str(citation.get("source_id") or "")
        for citation in citations
        if str(citation.get("source_id") or "")
    })
    if not source_ids:
        return {
            "files_read": 0,
            "implementation_files": 0,
            "test_files": 0,
            "documentation_files": 0,
            "configuration_files": 0,
            "files": [],
        }
    placeholders = ",".join("?" for _ in source_ids)
    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT ps.source_id, ps.relative_path, ps.file_role
            FROM project_sources ps
            WHERE ps.project_id = ? AND ps.source_id IN ({placeholders})
            ORDER BY ps.relative_path
            """,
            [project_id, *source_ids],
        ).fetchall()
    files = []
    counts = {
        "implementation": 0,
        "test": 0,
        "documentation": 0,
        "configuration": 0,
    }
    for row in rows:
        relative_path = str(row["relative_path"])
        role = str(row["file_role"] or "source")
        suffix = relative_path.rsplit(".", 1)[-1].casefold() if "." in relative_path else ""
        if role == "test":
            evidence_role = "test"
        elif suffix in {"md", "mdx", "rst", "adoc"}:
            evidence_role = "documentation"
        elif role in {"configuration", "workspace_manifest"}:
            evidence_role = "configuration"
        else:
            evidence_role = "implementation"
        counts[evidence_role] += 1
        files.append({
            "source_id": str(row["source_id"]),
            "path": relative_path,
            "role": evidence_role,
        })
    return {
        "files_read": len(files),
        "implementation_files": counts["implementation"],
        "test_files": counts["test"],
        "documentation_files": counts["documentation"],
        "configuration_files": counts["configuration"],
        "files": files,
    }


def _project_orientation_evidence(project_id: str) -> dict | None:
    """Return one bounded active implementation excerpt for project-orientation questions."""

    with connect() as conn:
        row = conn.execute(
            """
            SELECT ps.source_id, ps.relative_path, ps.file_role,
                   sources.title, sources.source_type, sources.cluster_id,
                   sources.provenance, sources.trust_tier, sources.security_labels,
                   chunks.id AS chunk_id, chunks.page_id, pages.page_number,
                   chunks.text
            FROM project_sources ps
            JOIN projects ON projects.id = ps.project_id
            JOIN sources ON sources.id = ps.source_id
            JOIN source_chunks chunks ON chunks.source_id = sources.id
            LEFT JOIN source_pages pages ON pages.id = chunks.page_id
            WHERE ps.project_id = ?
              AND sources.deleted_at IS NULL
              AND sources.activation_state = 'active'
              AND sources.project_snapshot_id = projects.active_retrieval_snapshot_id
              AND chunks.activation_state = 'active'
              AND chunks.project_snapshot_id = projects.active_retrieval_snapshot_id
              AND ps.file_role NOT IN ('test', 'documentation', 'configuration', 'workspace_manifest')
            ORDER BY
                CASE ps.file_role
                    WHEN 'entrypoint' THEN 0
                    WHEN 'source' THEN 1
                    ELSE 2
                END,
                ps.relative_path,
                chunks.chunk_index
            LIMIT 1
            """,
            (project_id,),
        ).fetchone()
    if row is None:
        return None
    snippet = " ".join(str(row["text"] or "").split())[:900]
    if not snippet:
        return None
    source_id = str(row["source_id"])
    title = str(row["title"] or row["relative_path"] or "Project source")
    trust_tier = str(row["trust_tier"] or "trusted_local")
    source_type = str(row["source_type"] or "code")
    return {
        "citation": {
            "source_id": source_id,
            "source_title": title,
            "chunk_id": row["chunk_id"],
            "page_id": row["page_id"],
            "page_number": row["page_number"],
            "snippet": snippet,
            "score": 0.0,
            "provenance": str(row["provenance"] or "local_import"),
            "trust_tier": trust_tier,
            "security_labels": row["security_labels"] or "[]",
            "low_trust": False,
            "state": "current",
            "source_type": source_type,
            "evidence_role": "project_orientation",
        },
        "source_snippet": {
            "id": source_id,
            "title": title,
            "source_type": source_type,
            "trust_tier": trust_tier,
            "summary": snippet[:320],
            "cluster_id": row["cluster_id"],
        },
    }


def _is_structural_project_question(query: str) -> bool:
    normalized = str(query or "").casefold()
    return any(
        phrase in normalized
        for phrase in (
            "architecture", "call flow", "dependency", "dependencies", "depends on",
            "function", "method", "class", "route", "handler", "implemented",
            "implementation", "where is", "how does", "entrypoint", "entry point",
            "graph", "map", "relationship",
        )
    )


def _is_project_overview_question(query: str) -> bool:
    normalized = " ".join(str(query or "").casefold().split())
    subject = any(
        term in normalized
        for term in ("project", "repository", "repo", "codebase", "application", "app")
    )
    orientation = any(
        phrase in normalized
        for phrase in (
            "what does",
            "what is",
            "purpose",
            "overview",
            "summarize",
            "summary",
            "about",
        )
    )
    return subject and orientation


_CONTEXT_STOPWORDS = {
    "about", "code", "codebase", "does", "from", "function", "have", "how",
    "method", "project", "system", "that", "this", "using", "what", "where",
    "which", "with", "work", "working", "works",
}


def _context_query_terms(query: str) -> list[str]:
    candidates: list[tuple[int, str]] = []
    seen: set[str] = set()
    for index, term in enumerate(re.findall(r"[A-Za-z_$][A-Za-z0-9_$]*", query)):
        folded = term.casefold()
        identifier_like = "_" in term or "$" in term or any(character.isupper() for character in term[1:])
        if folded in _CONTEXT_STOPWORDS or (len(term) < 5 and not identifier_like):
            continue
        if folded in seen:
            continue
        seen.add(folded)
        priority = 0 if identifier_like else 1
        candidates.append((priority * 1000 + index, term))
    candidates.sort(key=lambda item: item[0])
    return [term for _priority, term in candidates[:12]]


def _context_candidate_score(candidate: dict, term: str) -> int:
    needle = term.casefold()
    label = str(candidate.get("display_label") or "").casefold()
    qualified = str(candidate.get("qualified_id") or "").casefold()
    path = str(candidate.get("relative_path") or "").replace("\\", "/").casefold()
    basename = path.rsplit("/", 1)[-1]
    stem = basename.rsplit(".", 1)[0]
    if label == needle or stem == needle:
        score = 0
    elif label.startswith(needle):
        score = 2
    elif needle in label:
        score = 4
    elif f"/{needle}/" in f"/{path}/" or needle in qualified:
        score = 6
    else:
        score = 8
    if not ("_" in term or "$" in term or any(character.isupper() for character in term[1:])):
        score += 2
    if str(candidate.get("file_role") or "source") == "test":
        score += 20
    return score


@router.get("/{project_id}/graph/nodes")
def project_graph_nodes(
    project_id: str,
    q: str = Query(min_length=1, max_length=240),
    kind: list[str] | None = Query(default=None),
    limit: int = 25,
) -> list[dict]:
    try:
        return find_nodes(project_id, q, kinds=kind, limit=limit)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except GraphQueryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{project_id}/graph/nodes/{node_id}/neighbors")
def project_graph_neighbors(
    project_id: str,
    node_id: str,
    edge_type: list[str] | None = Query(default=None),
    limit: int = 100,
) -> dict:
    try:
        return node_neighbors(project_id, node_id, edge_types=edge_type, limit=limit)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project or node not found") from exc
    except GraphQueryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{project_id}/graph/path")
def project_graph_path(
    project_id: str,
    source: str = Query(min_length=1, max_length=500),
    target: str = Query(min_length=1, max_length=500),
    max_depth: int = 4,
    max_nodes: int = 1000,
    max_edges: int = 2000,
    timeout_ms: int = 500,
    edge_type: list[str] | None = Query(default=None),
) -> dict:
    try:
        return shortest_path(
            project_id,
            source,
            target,
            max_depth=max_depth,
            max_nodes=max_nodes,
            max_edges=max_edges,
            timeout_ms=timeout_ms,
            edge_types=edge_type,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except GraphQueryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
