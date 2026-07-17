from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import uuid4

from backend.app.core.code_structure import build_structure_graph
from backend.app.core.database import connect, dict_from_row, utc_now
from backend.app.core.embeddings import reindex_source_chunks
from backend.app.core.encrypted_storage import source_from_encrypted_row, store_source_content_fields
from backend.app.core.memory_card import summarize_text
from backend.app.core.source_records import source_type_for_suffix


class ProjectIndexCancelled(RuntimeError):
    pass


def discover_candidate(*, project_id: str, run_id: str, snapshot_id: str, job_id: str) -> dict:
    from backend.app.core.projects import (
        EXTRACTOR_VERSION, _git_metadata, discover_project, get_project, normalize_root_path,
    )

    _require_running(run_id, phase="discovery")
    project = get_project(project_id)
    root = normalize_root_path(project["root_path"])
    discovery = discover_project(
        root,
        discovery_scope=project["discovery_scope"],
        progress_callback=lambda count: _discovery_checkpoint(run_id, count),
    )
    repository_kind, branch, commit, remote_fingerprint, dirty, changed_count = _git_metadata(root)
    now = utc_now()
    manifest = {
        "version": 2,
        "discovery_scope": discovery.discovery_scope,
        "root_fingerprint": project["root_fingerprint"],
        "files": [{"path": item.relative_path, "hash": item.content_hash} for item in discovery.files],
        "excluded": {"ignored": discovery.ignored_count, "generated": discovery.generated_count, "failed": discovery.failed_count},
    }
    with connect() as conn:
        _require_running_in_conn(conn, run_id)
        existing_snapshot = conn.execute("SELECT id FROM project_snapshots WHERE id = ?", (snapshot_id,)).fetchone()
        if existing_snapshot is not None:
            return {"snapshot_id": snapshot_id, "files": len(discovery.files), "idempotent": True}
        active_rows = conn.execute(
            "SELECT relative_path, source_id, content_hash, file_role FROM project_sources WHERE project_id = ?",
            (project_id,),
        ).fetchall()
        active = {str(row["relative_path"]): row for row in active_rows}
        conn.execute(
            """
            INSERT INTO project_snapshots (
                id, project_id, discovery_scope, source_manifest_hash, git_commit, branch, dirty_working_tree,
                extractor_version, eligible_count, ignored_count, generated_count, parsed_count,
                failed_count, structure_status, retrieval_status, interpretation_status,
                manifest_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, 'waiting', 'waiting', 'unavailable', ?, ?)
            """,
            (snapshot_id, project_id, discovery.discovery_scope, discovery.manifest_hash, commit, branch, int(dirty), EXTRACTOR_VERSION,
             len(discovery.files), discovery.ignored_count, discovery.generated_count, discovery.failed_count,
             json.dumps(manifest, separators=(",", ":")), now),
        )
        seen: set[str] = set()
        for index, item in enumerate(discovery.files, start=1):
            previous = active.get(item.relative_path)
            action = "add" if previous is None else "replace" if previous["content_hash"] != item.content_hash else "unchanged"
            source_id = str(previous["source_id"]) if action == "unchanged" else _insert_candidate_source(
                conn, project, snapshot_id, item, now
            )
            conn.execute(
                """
                INSERT INTO project_snapshot_sources (
                    snapshot_id, project_id, source_id, prior_source_id, relative_path, file_role,
                    language, byte_size, content_hash, resolved_path_hash, exclusion_decision,
                    intended_action, stage_status, parser_status, retrieval_status, error_category,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'included', ?, 'discovered', 'waiting', 'waiting', '', ?, ?)
                """,
                (snapshot_id, project_id, source_id, previous["source_id"] if previous else None,
                 item.relative_path, item.file_role, item.language, len(item.text.encode("utf-8")),
                 item.content_hash, _path_proof(root, item.absolute_path), action, now, now),
            )
            seen.add(item.relative_path)
            if index % 100 == 0:
                _heartbeat(conn, run_id, "discovery", index, len(discovery.files))
        for relative_path, previous in active.items():
            if relative_path in seen:
                continue
            conn.execute(
                """
                INSERT INTO project_snapshot_sources (
                    snapshot_id, project_id, source_id, prior_source_id, relative_path, file_role,
                    content_hash, resolved_path_hash, exclusion_decision, intended_action,
                    stage_status, parser_status, retrieval_status, created_at, updated_at
                ) VALUES (?, ?, NULL, ?, ?, ?, ?, '', 'included', 'remove', 'discovered', 'not_applicable', 'not_applicable', ?, ?)
                """,
                (snapshot_id, project_id, previous["source_id"], relative_path, previous["file_role"],
                 previous["content_hash"], now, now),
            )
        conn.execute(
            """
            UPDATE projects SET candidate_snapshot_id = ?, repository_kind = ?, git_remote_fingerprint = ?,
                default_branch = ?, working_tree_dirty = ?, changed_file_count = ?, updated_at = ? WHERE id = ?
            """,
            (snapshot_id, repository_kind, remote_fingerprint, branch, int(dirty), changed_count, now, project_id),
        )
        conn.execute(
            """
            UPDATE project_index_runs SET snapshot_id = ?, phase = 'discovery_complete', eligible_total = ?,
                completed_count = ?, phase_completed_count = ?, phase_total_count = ?, heartbeat_at = ?,
                detail_json = ?, updated_at = ? WHERE id = ?
            """,
            (snapshot_id, len(discovery.files), len(discovery.files), len(discovery.files), len(discovery.files),
             now, json.dumps({"manifest_hash": discovery.manifest_hash}, separators=(",", ":")), now, run_id),
        )
    return {"snapshot_id": snapshot_id, "files": len(discovery.files)}


def index_candidate_structure(*, project_id: str, run_id: str, snapshot_id: str, job_id: str) -> dict:
    from backend.app.core.projects import EXTRACTOR_VERSION, ManifestFile, _build_brief, get_project

    _require_running(run_id, phase="structure")
    project = get_project(project_id)
    now = utc_now()
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT pss.*, s.* FROM project_snapshot_sources pss
            JOIN sources s ON s.id = pss.source_id
            WHERE pss.snapshot_id = ? AND pss.intended_action != 'remove'
            ORDER BY pss.relative_path
            """, (snapshot_id,),
        ).fetchall()
        files = []
        source_by_path = {}
        for row in rows:
            source = source_from_encrypted_row(conn, row)
            relative_path = str(row["relative_path"])
            files.append(ManifestFile(Path(source["original_path"]), relative_path, row["content_hash"],
                                      source["extracted_text"], row["language"], row["file_role"]))
            source_by_path[relative_path] = str(row["source_id"])
        result = build_structure_graph(conn, project=project, snapshot_id=snapshot_id, files=files,
                                       now=now, source_by_path=source_by_path)
        status = "partial" if result["parse_failure_count"] else "ready" if files else "unavailable"
        snapshot = conn.execute("SELECT * FROM project_snapshots WHERE id = ?", (snapshot_id,)).fetchone()
        discovery = _discovery_facade(snapshot, files)
        brief = _build_brief(project["name"], project["repository_kind"], discovery, result)
        for file_result in result.get("file_results", []):
            conn.execute(
                "UPDATE project_snapshot_sources SET parser_status = ?, stage_status = 'structured', error_category = ?, updated_at = ? WHERE snapshot_id = ? AND relative_path = ?",
                (file_result["status"], file_result.get("error_category") or "", now, snapshot_id, file_result["path"]),
            )
        conn.execute("UPDATE project_snapshots SET structure_status = ?, parsed_count = ?, failed_count = ?, structure_activated_at = ? WHERE id = ?",
                     (status, len(files), result["parse_failure_count"], now, snapshot_id))
        conn.execute(
            """
            UPDATE projects SET active_snapshot_id = ?, active_manifest_snapshot_id = ?,
                active_structure_snapshot_id = ?, structure_status = ?, brief = ?, languages_json = ?,
                workspace_count = ?, entrypoints_json = ?, indexed_commit = ?, updated_at = ? WHERE id = ?
            """, (
                snapshot_id, snapshot_id, snapshot_id, status, brief, json.dumps(discovery.languages),
                discovery.workspace_count, json.dumps(discovery.entrypoints), snapshot["git_commit"], now, project_id,
            ),
        )
        _heartbeat(conn, run_id, "structure_complete", len(files), len(files))
    return result


def stage_candidate_retrieval(*, project_id: str, run_id: str, snapshot_id: str, job_id: str) -> dict:
    _require_running(run_id, phase="retrieval")
    now = utc_now()
    staged = 0
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT pss.*, s.* FROM project_snapshot_sources pss
            JOIN sources s ON s.id = pss.source_id
            WHERE pss.snapshot_id = ? AND pss.intended_action IN ('add', 'replace')
            ORDER BY pss.relative_path
            """, (snapshot_id,),
        ).fetchall()
        for index, row in enumerate(rows, start=1):
            _require_running_in_conn(conn, run_id)
            source = source_from_encrypted_row(conn, row)
            reindex_source_chunks(conn, source)
            conn.execute("UPDATE source_chunks SET project_id = ?, project_snapshot_id = ?, activation_state = 'candidate' WHERE source_id = ?",
                         (project_id, snapshot_id, row["source_id"]))
            conn.execute("UPDATE project_snapshot_sources SET retrieval_status = 'ready', stage_status = 'retrieval_staged', updated_at = ? WHERE snapshot_id = ? AND relative_path = ?",
                         (now, snapshot_id, row["relative_path"]))
            staged += 1
            _heartbeat(conn, run_id, "retrieval", index, len(rows))
        conn.execute("UPDATE project_snapshot_sources SET retrieval_status = 'ready', stage_status = 'retrieval_staged', updated_at = ? WHERE snapshot_id = ? AND intended_action = 'unchanged'",
                     (now, snapshot_id))
        conn.execute("UPDATE project_snapshots SET retrieval_status = 'ready' WHERE id = ?", (snapshot_id,))
    return {"staged_sources": staged}


def activate_candidate(*, project_id: str, run_id: str, snapshot_id: str, job_id: str) -> dict:
    from backend.app.core.projects import _project_from_row

    _require_running(run_id, phase="activation")
    now = utc_now()
    with connect() as conn:
        _require_running_in_conn(conn, run_id)
        project = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if project is None or project["candidate_snapshot_id"] != snapshot_id:
            raise RuntimeError("Candidate snapshot no longer belongs to this project run.")
        rows = conn.execute("SELECT * FROM project_snapshot_sources WHERE snapshot_id = ? ORDER BY relative_path", (snapshot_id,)).fetchall()
        for row in rows:
            action = row["intended_action"]
            if action in {"replace", "remove"} and row["prior_source_id"]:
                conn.execute("DELETE FROM project_sources WHERE project_id = ? AND source_id = ?", (project_id, row["prior_source_id"]))
                if action == "replace":
                    conn.execute("UPDATE sources SET activation_state = 'superseded', deleted_at = ?, updated_at = ? WHERE id = ?", (now, now, row["prior_source_id"]))
                else:
                    conn.execute("UPDATE sources SET activation_state = 'removed', deleted_at = ?, updated_at = ? WHERE id = ?", (now, now, row["prior_source_id"]))
            if action in {"add", "replace"}:
                conn.execute("INSERT INTO project_sources (project_id, source_id, relative_path, file_role, content_hash, discovered_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                             (project_id, row["source_id"], row["relative_path"], row["file_role"], row["content_hash"], now, now))
                conn.execute("UPDATE sources SET cluster_id = ?, state = 'indexed', activation_state = 'active', project_snapshot_id = ?, updated_at = ? WHERE id = ?",
                             (project["primary_cluster_id"], snapshot_id, now, row["source_id"]))
                conn.execute("UPDATE source_chunks SET activation_state = 'active' WHERE source_id = ? AND project_snapshot_id = ?", (row["source_id"], snapshot_id))
            elif action == "unchanged" and row["source_id"]:
                conn.execute("UPDATE sources SET project_snapshot_id = ?, activation_state = 'active', updated_at = ? WHERE id = ?", (snapshot_id, now, row["source_id"]))
        count = conn.execute("SELECT COUNT(*) AS total FROM project_sources WHERE project_id = ?", (project_id,)).fetchone()["total"]
        conn.execute("UPDATE project_snapshot_sources SET stage_status = 'active', updated_at = ? WHERE snapshot_id = ?", (now, snapshot_id))
        conn.execute("UPDATE project_snapshots SET retrieval_status = 'ready', activated_at = ?, manifest_activated_at = COALESCE(manifest_activated_at, ?), retrieval_activated_at = ? WHERE id = ?",
                     (now, now, now, snapshot_id))
        conn.execute(
            """
            UPDATE projects SET active_snapshot_id = ?, active_manifest_snapshot_id = ?,
                active_retrieval_snapshot_id = ?, candidate_snapshot_id = NULL, active_run_id = NULL,
                status = CASE WHEN structure_status = 'partial' THEN 'partial' ELSE 'ready' END,
                retrieval_status = 'ready', updated_at = ? WHERE id = ?
            """, (snapshot_id, snapshot_id, snapshot_id, now, project_id),
        )
        conn.execute("UPDATE clusters SET indexed_source_count = ?, index_status = ?, profile_status = 'needs_update', updated_at = ? WHERE id = ?",
                     (count, "ready" if count else "empty", now, project["primary_cluster_id"]))
        conn.execute(
            """
            UPDATE project_index_runs SET status = 'succeeded', phase = 'activated', activation_outcome = 'activated',
                completed_count = eligible_total, phase_completed_count = phase_total_count,
                heartbeat_at = ?, finished_at = ?, updated_at = ? WHERE id = ?
            """, (now, now, now, run_id),
        )
        updated = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return _project_from_row(conn, updated)


def cleanup_candidate(*, project_id: str, run_id: str, snapshot_id: str, job_id: str) -> dict:
    now = utc_now()
    with connect() as conn:
        project = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if project is None:
            return {"cleaned": False}
        active_ids = {project["active_snapshot_id"], project["active_manifest_snapshot_id"], project["active_structure_snapshot_id"], project["active_retrieval_snapshot_id"]}
        if snapshot_id in active_ids:
            return {"cleaned": False, "reason": "snapshot_active"}
        candidates = conn.execute("SELECT source_id FROM project_snapshot_sources WHERE snapshot_id = ? AND intended_action IN ('add', 'replace')", (snapshot_id,)).fetchall()
        for row in candidates:
            if row["source_id"]:
                conn.execute("DELETE FROM sources WHERE id = ? AND activation_state = 'candidate'", (row["source_id"],))
        conn.execute("DELETE FROM project_snapshots WHERE id = ?", (snapshot_id,))
        conn.execute("UPDATE projects SET candidate_snapshot_id = NULL, active_run_id = NULL, updated_at = ? WHERE id = ? AND candidate_snapshot_id = ?", (now, project_id, snapshot_id))
        return {"cleaned": True}


def _insert_candidate_source(conn, project: dict, snapshot_id: str, item, now: str) -> str:
    source_id = f"source-{uuid4()}"
    source = {
        "id": source_id, "vault_id": project["vault_id"], "cluster_id": None,
        "title": Path(item.relative_path).name, "source_type": source_type_for_suffix(item.absolute_path.suffix.lower()),
        "state": "staging", "original_path": str(item.absolute_path), "url": None,
        "checksum": item.content_hash, "provenance": "project_import", "trust_tier": "trusted_local",
        "security_labels": "[]", "parser_security_json": json.dumps({"odin": {"relative_path": item.relative_path}}),
        "raw_text": item.text, "extracted_text": item.text, "summary": summarize_text(item.text),
        "tags": json.dumps(["project", item.language.lower()]), "cover_image_url": None,
        "created_at": now, "updated_at": now,
    }
    stored = store_source_content_fields(conn, source, now=now)
    conn.execute(
        """
        INSERT INTO sources (
            id, vault_id, cluster_id, title, source_type, state, original_path, url, checksum,
            provenance, trust_tier, security_labels, parser_security_json, raw_text, extracted_text,
            summary, tags, cover_image_url, project_id, project_snapshot_id, activation_state,
            created_at, updated_at
        ) VALUES (
            :id, :vault_id, :cluster_id, :title, :source_type, :state, :original_path, :url, :checksum,
            :provenance, :trust_tier, :security_labels, :parser_security_json, :raw_text, :extracted_text,
            :summary, :tags, :cover_image_url, :project_id, :project_snapshot_id, 'candidate',
            :created_at, :updated_at
        )
        """, {**stored, "project_id": project["id"], "project_snapshot_id": snapshot_id},
    )
    return source_id


def _path_proof(root: Path, absolute_path: Path) -> str:
    resolved_root = root.resolve()
    resolved = absolute_path.resolve()
    resolved.relative_to(resolved_root)
    return hashlib.sha256(str(resolved).casefold().encode("utf-8")).hexdigest()


def _require_running(run_id: str, *, phase: str) -> None:
    with connect() as conn:
        _require_running_in_conn(conn, run_id)
        _heartbeat(conn, run_id, phase, 0, 0)


def _discovery_checkpoint(run_id: str, completed: int) -> None:
    with connect() as conn:
        _require_running_in_conn(conn, run_id)
        _heartbeat(conn, run_id, "discovery", completed, max(completed, 1))


def _require_running_in_conn(conn, run_id: str) -> None:
    run = conn.execute("SELECT status, cancellation_requested FROM project_index_runs WHERE id = ?", (run_id,)).fetchone()
    if run is None or run["status"] == "cancelled" or run["cancellation_requested"]:
        raise ProjectIndexCancelled("Project indexing was cancelled; the previous active snapshot is unchanged.")


def _heartbeat(conn, run_id: str, phase: str, completed: int, total: int) -> None:
    now = utc_now()
    conn.execute(
        """
        UPDATE project_index_runs SET status = 'running', phase = ?,
            phase_completed_count = CASE WHEN ? > 0 THEN ? ELSE phase_completed_count END,
            phase_total_count = CASE WHEN ? > 0 THEN ? ELSE phase_total_count END,
            heartbeat_at = ?, updated_at = ? WHERE id = ? AND status != 'cancelled'
        """,
        (phase, total, completed, total, total, now, now, run_id),
    )


class _DiscoveryFacade:
    pass


def _discovery_facade(snapshot, files):
    value = _DiscoveryFacade()
    value.files = files
    value.failed_count = int(snapshot["failed_count"] or 0)
    value.languages = {}
    for item in files:
        value.languages[item.language] = value.languages.get(item.language, 0) + 1
    value.workspace_count = sum(1 for item in files if item.file_role == "workspace_manifest" and "/" in item.relative_path)
    value.entrypoints = [item.relative_path for item in files if Path(item.relative_path).name.lower() in {"main.py", "main.ts", "index.ts", "index.tsx"}][:8]
    return value
