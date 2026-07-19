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

from backend.app.core.projects import (
    ProjectError,
    cancel_project_run,
    get_project,
    get_project_run,
    link_project,
    list_project_links,
    list_project_runs,
    list_projects,
    register_project,
    reindex_project,
    remove_project,
    sync_project,
    unlink_project,
    update_project,
)
from backend.app.schemas import (
    ProjectCreate,
    ProjectIndexRunRead,
    ProjectLinkCreate,
    ProjectLinkRead,
    ProjectRead,
    ProjectReindexRequest,
    ProjectRemoveRequest,
    ProjectSyncResponse,
    ProjectSyncRequest,
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


class ProjectContextRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    limit: int = Field(default=6, ge=1, le=12)
    mode: str = "context"


@router.get("", response_model=list[ProjectRead])
def project_list(request: Request, vault_id: str | None = None, limit: int = 200, offset: int = 0) -> list[dict]:
    context = getattr(request.state, "cli_auth", None)
    if vault_id:
        _enforce_cli_vault(request, vault_id)
    rows = list_projects(vault_id=vault_id, limit=limit, offset=offset)
    if context and not vault_id:
        rows = [row for row in rows if row["vault_id"] in context["allowed_vault_ids"]]
    return rows


@router.post("", response_model=ProjectRead)
def project_create(payload: ProjectCreate, request: Request) -> dict:
    _enforce_cli_vault(request, payload.vault_id)
    try:
        return register_project(
            vault_id=payload.vault_id,
            root_path=payload.root_path,
            name=payload.name,
            discovery_scope=payload.discovery_scope,
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


@router.patch("/{project_id}", response_model=ProjectRead)
def project_update(project_id: str, payload: ProjectUpdate) -> dict:
    try:
        return update_project(
            project_id,
            name=payload.name,
            root_path=payload.root_path,
            discovery_scope=payload.discovery_scope,
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
    return {
        "project_id": project_id,
        "project_name": project["name"],
        "snapshot_id": project["active_snapshot_id"],
        "indexed_commit": project["indexed_commit"],
        "query": payload.query,
        "citations": bundle.get("citations") or [],
        "source_snippets": bundle.get("source_snippets") or [],
        "structural_hits": structural_hits,
        "warnings": bundle.get("warnings") or [],
        "retrieval_authority": bool(bundle.get("retrieval_authority", True)),
        "token_estimate": bundle.get("token_estimate") or {},
        "bundle_status": bundle.get("bundle_status") or {},
    }


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
