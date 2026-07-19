from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from backend.app.core.background_jobs import enqueue_job
from backend.app.core.code_structure import STRUCTURE_EXTRACTOR_VERSION, build_structure_graph
from backend.app.core.extractor_registry import extractor_fingerprint
from backend.app.core.database import connect, dict_from_row, utc_now
from backend.app.core.encrypted_storage import store_source_content_fields, update_source_content_fields
from backend.app.core.memory_card import summarize_text
from backend.app.core.source_records import source_type_for_suffix


EXTRACTOR_VERSION = f"odin-manifest-v2+{STRUCTURE_EXTRACTOR_VERSION}+{extractor_fingerprint()}"
MAX_FILE_BYTES = 1_000_000
DEFAULT_IGNORED_DIRECTORIES = {
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".tmp",
    ".venv",
    "__pycache__",
    "bin",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "obj",
    "target",
    "vendor",
    "venv",
}
SECRET_SUFFIXES = {".key", ".pem", ".p12", ".pfx", ".jks", ".keystore"}
SECRET_NAMES = {
    ".env",
    "credentials",
    "credentials.json",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "id_rsa",
    "secrets.json",
}
SUPPORTED_EXTENSIONS = {
    ".c",
    ".cc",
    ".cfg",
    ".clj",
    ".cljs",
    ".cmake",
    ".conf",
    ".cpp",
    ".cs",
    ".css",
    ".csv",
    ".dart",
    ".ex",
    ".exs",
    ".go",
    ".graphql",
    ".gql",
    ".h",
    ".hpp",
    ".html",
    ".ini",
    ".java",
    ".js",
    ".cjs",
    ".json",
    ".jsx",
    ".kt",
    ".kts",
    ".lua",
    ".md",
    ".mdx",
    ".mjs",
    ".mts",
    ".php",
    ".prisma",
    ".properties",
    ".proto",
    ".ps1",
    ".py",
    ".pyi",
    ".rb",
    ".rs",
    ".scala",
    ".scss",
    ".sh",
    ".sql",
    ".svelte",
    ".swift",
    ".toml",
    ".ts",
    ".cts",
    ".tsx",
    ".txt",
    ".vue",
    ".xml",
    ".yaml",
    ".yml",
}
SUPPORTED_FILENAMES = {
    "dockerfile",
    "gemfile",
    "makefile",
    "procfile",
    "rakefile",
}
DISCOVERY_SCOPES = frozenset({"context", "code"})
CODE_EXTENSIONS = {
    ".c", ".cc", ".clj", ".cljs", ".cpp", ".cs", ".dart", ".ex", ".exs",
    ".go", ".graphql", ".gql", ".h", ".hpp", ".java", ".js", ".cjs", ".json", ".jsx",
    ".kt", ".kts", ".lua", ".php", ".prisma", ".proto", ".ps1", ".py", ".pyi", ".rb",
    ".rs", ".scala", ".sh", ".sql", ".svelte", ".swift", ".mjs", ".mts",
    ".ts", ".cts", ".tsx", ".vue",
}
GENERATED_FILENAMES = {
    "bun.lock",
    "composer.lock",
    "package-lock.json",
    "pnpm-lock.yaml",
    "poetry.lock",
    "uv.lock",
    "yarn.lock",
}
LANGUAGE_BY_EXTENSION = {
    ".c": "C",
    ".cc": "C++",
    ".cpp": "C++",
    ".cs": "C#",
    ".css": "CSS",
    ".dart": "Dart",
    ".ex": "Elixir",
    ".exs": "Elixir",
    ".go": "Go",
    ".h": "C/C++",
    ".hpp": "C++",
    ".html": "HTML",
    ".java": "Java",
    ".js": "JavaScript",
    ".cjs": "JavaScript",
    ".jsx": "JavaScript",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".lua": "Lua",
    ".md": "Markdown",
    ".mdx": "Markdown",
    ".mjs": "JavaScript",
    ".mts": "TypeScript",
    ".php": "PHP",
    ".ps1": "PowerShell",
    ".py": "Python",
    ".pyi": "Python",
    ".rb": "Ruby",
    ".rs": "Rust",
    ".scala": "Scala",
    ".scss": "SCSS",
    ".sh": "Shell",
    ".sql": "SQL",
    ".svelte": "Svelte",
    ".swift": "Swift",
    ".ts": "TypeScript",
    ".cts": "TypeScript",
    ".tsx": "TypeScript",
    ".vue": "Vue",
}
ENTRYPOINT_NAMES = {
    "app.py",
    "main.go",
    "main.py",
    "main.rs",
    "main.ts",
    "main.tsx",
    "server.js",
    "server.py",
    "server.ts",
}


class ProjectError(ValueError):
    pass


@dataclass(frozen=True)
class ManifestFile:
    absolute_path: Path
    relative_path: str
    content_hash: str
    text: str
    language: str
    file_role: str


@dataclass(frozen=True)
class DiscoveryResult:
    files: list[ManifestFile]
    ignored_count: int
    generated_count: int
    failed_count: int
    languages: dict[str, int]
    entrypoints: list[str]
    workspace_count: int
    manifest_hash: str
    discovery_scope: str = "context"


def normalize_root_path(value: str) -> Path:
    root = Path(value).expanduser()
    if not root.exists():
        raise ProjectError("Project path does not exist.")
    if not root.is_dir():
        raise ProjectError("Project path must be a directory.")
    try:
        return root.resolve(strict=True)
    except OSError as exc:
        raise ProjectError("Project path could not be resolved safely.") from exc


def root_fingerprint(root: Path) -> str:
    normalized = os.path.normcase(os.path.normpath(str(root)))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def normalize_discovery_scope(value: str | None) -> str:
    scope = str(value or "context").strip().casefold()
    if scope not in DISCOVERY_SCOPES:
        raise ProjectError("Project discovery scope must be 'context' or 'code'.")
    return scope


def register_project(
    *, vault_id: str, root_path: str, name: str | None,
    discovery_scope: str = "context", sync: bool = True,
) -> dict:
    root = normalize_root_path(root_path)
    normalized_scope = normalize_discovery_scope(discovery_scope)
    fingerprint = root_fingerprint(root)
    project_name = (name or root.name).strip()
    if not project_name:
        raise ProjectError("Project name is required.")
    if len(project_name) > 120:
        raise ProjectError("Project name must be 120 characters or fewer.")

    with connect() as conn:
        vault = conn.execute("SELECT id FROM vaults WHERE id = ?", (vault_id,)).fetchone()
        if vault is None:
            raise ProjectError("Vault not found.")
        existing = conn.execute(
            "SELECT id FROM projects WHERE vault_id = ? AND root_fingerprint = ? AND deleted_at IS NULL",
            (vault_id, fingerprint),
        ).fetchone()
        if existing is not None:
            project_id = str(existing["id"])
        else:
            collision = conn.execute(
                "SELECT id FROM projects WHERE vault_id = ? AND lower(name) = lower(?) AND deleted_at IS NULL",
                (vault_id, project_name),
            ).fetchone()
            if collision is not None:
                raise ProjectError("A project with this name already exists in the vault.")
            cluster = conn.execute(
                "SELECT id FROM clusters WHERE vault_id = ? AND lower(name) = lower(?) ORDER BY created_at LIMIT 1",
                (vault_id, project_name),
            ).fetchone()
            now = utc_now()
            cluster_id = str(cluster["id"]) if cluster is not None else f"cluster-{uuid4()}"
            if cluster is None:
                conn.execute(
                    """
                    INSERT INTO clusters (
                        id, vault_id, name, description, color, index_status, profile_status,
                        cluster_summary, cluster_glossary, indexed_source_count, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'sky', 'empty', 'missing', '', '[]', 0, ?, ?)
                    """,
                    (
                        cluster_id,
                        vault_id,
                        project_name,
                        "Code project registered through Odin.",
                        now,
                        now,
                    ),
                )
            repository_kind, branch, commit, remote_fingerprint, dirty, changed_file_count = _git_metadata(root)
            project_id = f"project-{uuid4()}"
            conn.execute(
                """
                INSERT INTO projects (
                    id, vault_id, name, root_path, root_fingerprint, primary_cluster_id,
                    discovery_scope,
                    repository_kind, git_remote_fingerprint, default_branch, indexed_commit,
                    working_tree_dirty, changed_file_count, status,
                    structure_status, retrieval_status, interpretation_status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'registered', 'waiting', 'waiting',
                          'unavailable', ?, ?)
                """,
                (
                    project_id,
                    vault_id,
                    project_name,
                    str(root),
                    fingerprint,
                    cluster_id,
                    normalized_scope,
                    repository_kind,
                    remote_fingerprint,
                    branch,
                    commit,
                    int(dirty),
                    changed_file_count,
                    now,
                    now,
                ),
            )
            conn.execute(
                "INSERT INTO project_cluster_links (project_id, cluster_id, role, created_at) VALUES (?, ?, 'primary', ?)",
                (project_id, cluster_id, now),
            )
    if sync:
        sync_project(project_id, trigger_source="odin_add")
    return get_project(project_id)


def list_projects(*, vault_id: str | None = None, limit: int = 200, offset: int = 0) -> list[dict]:
    safe_limit = max(1, min(int(limit), 1000))
    safe_offset = max(0, int(offset))
    with connect() as conn:
        if vault_id:
            rows = conn.execute(
                """
                SELECT * FROM projects
                WHERE vault_id = ? AND deleted_at IS NULL
                ORDER BY updated_at DESC LIMIT ? OFFSET ?
                """,
                (vault_id, safe_limit, safe_offset),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM projects WHERE deleted_at IS NULL ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (safe_limit, safe_offset),
            ).fetchall()
        return [_project_from_row(conn, row) for row in rows]


def get_project(project_id: str) -> dict:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM projects WHERE id = ? AND deleted_at IS NULL",
            (project_id,),
        ).fetchone()
        if row is None:
            raise KeyError(project_id)
        return _project_from_row(conn, row)


def update_project(
    project_id: str, *, name: str | None = None, root_path: str | None = None,
    discovery_scope: str | None = None,
) -> dict:
    if name is None and root_path is None and discovery_scope is None:
        raise ProjectError("Provide a project name, replacement folder, or discovery scope.")
    normalized = name.strip() if name is not None else None
    if normalized is not None and (not normalized or len(normalized) > 120):
        raise ProjectError("Project name must be between 1 and 120 characters.")
    replacement_root = normalize_root_path(root_path) if root_path is not None else None
    replacement_fingerprint = root_fingerprint(replacement_root) if replacement_root is not None else None
    normalized_scope = normalize_discovery_scope(discovery_scope) if discovery_scope is not None else None
    with connect() as conn:
        row = conn.execute(
            "SELECT vault_id, primary_cluster_id, name, active_run_id, discovery_scope FROM projects WHERE id = ? AND deleted_at IS NULL",
            (project_id,),
        ).fetchone()
        if row is None:
            raise KeyError(project_id)
        if row["active_run_id"] and (replacement_root is not None or normalized_scope is not None):
            raise ProjectError("Cancel the active synchronization before changing this project's folder or scope.")
        if normalized is not None:
            collision = conn.execute(
                """
                SELECT id FROM projects
                WHERE vault_id = ? AND lower(name) = lower(?) AND id != ? AND deleted_at IS NULL
                """,
                (row["vault_id"], normalized, project_id),
            ).fetchone()
            if collision is not None:
                raise ProjectError("A project with this name already exists in the vault.")
        if replacement_fingerprint is not None:
            collision = conn.execute(
                "SELECT id FROM projects WHERE vault_id = ? AND root_fingerprint = ? AND id != ? AND deleted_at IS NULL",
                (row["vault_id"], replacement_fingerprint, project_id),
            ).fetchone()
            if collision is not None:
                raise ProjectError("That folder is already registered as another project.")
        now = utc_now()
        if normalized is not None:
            conn.execute("UPDATE projects SET name = ?, updated_at = ? WHERE id = ?", (normalized, now, project_id))
            conn.execute(
                "UPDATE clusters SET name = ?, updated_at = ? WHERE id = ?",
                (normalized, now, row["primary_cluster_id"]),
            )
        if replacement_root is not None:
            repository_kind, branch, _commit, remote_fingerprint, dirty, changed_count = _git_metadata(replacement_root)
            conn.execute(
                """
                UPDATE projects SET root_path = ?, root_fingerprint = ?, repository_kind = ?,
                    git_remote_fingerprint = ?, default_branch = ?, working_tree_dirty = ?,
                    changed_file_count = ?, status = CASE WHEN active_snapshot_id IS NULL THEN 'registered' ELSE 'stale' END,
                    updated_at = ? WHERE id = ?
                """,
                (str(replacement_root), replacement_fingerprint, repository_kind, remote_fingerprint,
                 branch, int(dirty), changed_count, now, project_id),
            )
        if normalized_scope is not None and normalized_scope != row["discovery_scope"]:
            conn.execute(
                """
                UPDATE projects SET discovery_scope = ?,
                    status = CASE WHEN active_snapshot_id IS NULL THEN 'registered' ELSE 'stale' END,
                    updated_at = ? WHERE id = ?
                """,
                (normalized_scope, now, project_id),
            )
    return get_project(project_id)


def sync_project(
    project_id: str, *, trigger_source: str = "manual", discovery_scope: str | None = None,
) -> dict:
    if discovery_scope is not None:
        requested_scope = normalize_discovery_scope(discovery_scope)
        current = get_project(project_id)
        if requested_scope != current["discovery_scope"]:
            update_project(project_id, discovery_scope=requested_scope)
    project = get_project(project_id)
    run_id = f"project-run-{uuid4()}"
    candidate_snapshot_id = f"project-snapshot-{uuid4()}"
    now = utc_now()
    with connect() as conn:
        active = conn.execute(
            """
            SELECT * FROM project_index_runs
            WHERE project_id = ? AND status IN ('queued', 'running')
            ORDER BY created_at DESC LIMIT 1
            """,
            (project_id,),
        ).fetchone()
        if active is not None:
            active_run = _project_run_from_row(active)
            return {
                "project": project,
                "run": active_run,
                "snapshot_id": None,
                "job_id": active_run.get("job_id"),
                "queued": True,
            }
        conn.execute(
            """
            INSERT INTO project_index_runs (
                id, project_id, trigger_source, status, phase, queued_at, heartbeat_at,
                started_at, created_at, updated_at
            ) VALUES (?, ?, ?, 'queued', 'queued', ?, ?, ?, ?, ?)
            """,
            (run_id, project_id, trigger_source, now, now, now, now, now),
        )
        payload = {
            "project_id": project_id,
            "run_id": run_id,
            "candidate_snapshot_id": candidate_snapshot_id,
        }
        discover_job = enqueue_job(
            conn,
            job_type="project_discover",
            payload=payload,
            dedupe_key=f"project-index:{project_id}",
            scope_id=project_id,
            user_initiated=True,
        )
        structure_job = enqueue_job(
            conn, job_type="project_structure_index", payload=payload,
            dedupe_key=f"project-structure:{candidate_snapshot_id}", depends_on_job_id=discover_job["id"],
            scope_id=project_id, user_initiated=True,
        )
        retrieval_job = enqueue_job(
            conn, job_type="project_retrieval_stage", payload=payload,
            dedupe_key=f"project-retrieval:{candidate_snapshot_id}", depends_on_job_id=structure_job["id"],
            scope_id=project_id, user_initiated=True,
        )
        activate_job = enqueue_job(
            conn, job_type="project_snapshot_activate", payload=payload,
            dedupe_key=f"project-activate:{candidate_snapshot_id}", depends_on_job_id=retrieval_job["id"],
            scope_id=project_id, user_initiated=True,
        )
        conn.execute(
            "UPDATE project_index_runs SET job_id = ?, detail_json = ? WHERE id = ?",
            (
                discover_job["id"],
                json.dumps({"candidate_snapshot_id": candidate_snapshot_id, "phase_job_ids": [discover_job["id"], structure_job["id"], retrieval_job["id"], activate_job["id"]]}, separators=(",", ":")),
                run_id,
            ),
        )
        conn.execute(
            """
            UPDATE projects SET status = 'indexing',
                active_run_id = ?, updated_at = ? WHERE id = ?
            """,
            (run_id, now, project_id),
        )
    return {
        "project": get_project(project_id),
        "run": get_project_run(run_id),
        "snapshot_id": None,
        "job_id": discover_job["id"],
        "queued": True,
    }


def run_project_index_job(*, project_id: str, run_id: str, job_id: str) -> dict:
    project = get_project(project_id)
    root = normalize_root_path(project["root_path"])
    now = utc_now()
    with connect() as conn:
        run = conn.execute("SELECT * FROM project_index_runs WHERE id = ?", (run_id,)).fetchone()
        if run is None:
            raise ProjectError("Project indexing run was not found.")
        if run["status"] == "cancelled" or run["cancellation_requested"]:
            return {"status": "cancelled", "run_id": run_id}
        conn.execute(
            """
            UPDATE project_index_runs SET status = 'running', phase = 'discovery', job_id = ?,
                started_at = COALESCE(started_at, ?), heartbeat_at = ?, updated_at = ? WHERE id = ?
            """,
            (job_id, now, now, now, run_id),
        )
    try:
        discovery = discover_project(root, discovery_scope=project["discovery_scope"])
        with connect() as conn:
            run = conn.execute(
                "SELECT cancellation_requested, status FROM project_index_runs WHERE id = ?", (run_id,)
            ).fetchone()
            if run is None or run["status"] == "cancelled" or run["cancellation_requested"]:
                return {"status": "cancelled", "run_id": run_id}
            conn.execute(
                """
                UPDATE project_index_runs SET phase = 'candidate_build', eligible_total = ?,
                    phase_total_count = ?, heartbeat_at = ?, updated_at = ? WHERE id = ?
                """,
                (len(discovery.files), len(discovery.files), utc_now(), utc_now(), run_id),
            )
        snapshot_id = _activate_discovery(project, discovery, run_id)
    except Exception as exc:
        with connect() as conn:
            conn.execute(
                """
                UPDATE project_index_runs
                SET status = 'failed', failure_category = ?, finished_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (exc.__class__.__name__, utc_now(), utc_now(), run_id),
            )
            current = conn.execute("SELECT active_snapshot_id FROM projects WHERE id = ?", (project_id,)).fetchone()
            if current and current["active_snapshot_id"]:
                conn.execute(
                    "UPDATE projects SET status = 'ready', active_run_id = NULL, candidate_snapshot_id = NULL, updated_at = ? WHERE id = ?",
                    (utc_now(), project_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE projects SET status = 'issue', structure_status = 'issue',
                        active_run_id = NULL, candidate_snapshot_id = NULL, updated_at = ? WHERE id = ?
                    """,
                    (utc_now(), project_id),
                )
        raise
    return {
        "project": get_project(project_id),
        "run": get_project_run(run_id),
        "snapshot_id": snapshot_id,
        "job_id": job_id,
        "queued": False,
    }


def reindex_project(project_id: str, *, layer: str) -> dict:
    normalized = layer.strip().lower()
    if normalized in {"structure", "retrieval", "full"}:
        return sync_project(project_id, trigger_source=f"reindex_{normalized}")
    if normalized != "interpretation":
        raise ProjectError("Layer must be structure, retrieval, interpretation, or full.")
    if normalized == "interpretation":
        with connect() as conn:
            conn.execute(
                "UPDATE projects SET interpretation_status = 'unavailable', updated_at = ? WHERE id = ?",
                (utc_now(), project_id),
            )
        return {"project": get_project(project_id), "queued_jobs": 0, "layer": normalized}
    raise AssertionError("unreachable")


def list_project_links(project_id: str) -> list[dict]:
    with connect() as conn:
        project = conn.execute("SELECT id FROM projects WHERE id = ? AND deleted_at IS NULL", (project_id,)).fetchone()
        if project is None:
            raise KeyError(project_id)
        rows = conn.execute(
            """
            SELECT pcl.project_id, pcl.cluster_id, pcl.role, pcl.created_at,
                   c.name AS cluster_name
            FROM project_cluster_links pcl
            JOIN clusters c ON c.id = pcl.cluster_id
            WHERE pcl.project_id = ?
            ORDER BY CASE pcl.role WHEN 'primary' THEN 0 ELSE 1 END, lower(c.name)
            """,
            (project_id,),
        ).fetchall()
        return [_project_run_from_row(row) for row in rows]


def link_project(project_id: str, cluster_id: str) -> dict:
    with connect() as conn:
        project = conn.execute(
            "SELECT vault_id FROM projects WHERE id = ? AND deleted_at IS NULL",
            (project_id,),
        ).fetchone()
        if project is None:
            raise KeyError(project_id)
        cluster = conn.execute(
            "SELECT id FROM clusters WHERE id = ? AND vault_id = ?",
            (cluster_id, project["vault_id"]),
        ).fetchone()
        if cluster is None:
            raise ProjectError("Cluster not found in this vault.")
        conn.execute(
            "INSERT OR IGNORE INTO project_cluster_links (project_id, cluster_id, role, created_at) VALUES (?, ?, 'linked', ?)",
            (project_id, cluster_id, utc_now()),
        )
    return next(item for item in list_project_links(project_id) if item["cluster_id"] == cluster_id)


def unlink_project(project_id: str, cluster_id: str) -> None:
    with connect() as conn:
        link = conn.execute(
            "SELECT role FROM project_cluster_links WHERE project_id = ? AND cluster_id = ?",
            (project_id, cluster_id),
        ).fetchone()
        if link is None:
            raise KeyError(cluster_id)
        if link["role"] == "primary":
            raise ProjectError("The primary project cluster cannot be unlinked.")
        conn.execute(
            "DELETE FROM project_cluster_links WHERE project_id = ? AND cluster_id = ?",
            (project_id, cluster_id),
        )


def list_project_runs(project_id: str, *, limit: int = 50, offset: int = 0) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM project_index_runs WHERE project_id = ?
            ORDER BY created_at DESC LIMIT ? OFFSET ?
            """,
            (project_id, max(1, min(limit, 200)), max(0, offset)),
        ).fetchall()
        return [dict_from_row(row) for row in rows]


def get_project_run(run_id: str) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM project_index_runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return _project_run_from_row(row)


def cancel_project_run(project_id: str) -> dict:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM project_index_runs
            WHERE project_id = ? AND status IN ('queued', 'running')
            ORDER BY created_at DESC LIMIT 1
            """,
            (project_id,),
        ).fetchone()
        if row is None:
            raise ProjectError("This project has no active indexing run.")
        now = utc_now()
        conn.execute(
            """
            UPDATE project_index_runs
            SET cancellation_requested = 1, cancellation_requested_at = ?, status = 'cancelled',
                finished_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (now, now, now, row["id"]),
        )
        phase_jobs = conn.execute(
            "SELECT id, payload FROM app_jobs WHERE status IN ('queued', 'running', 'blocked_by_dependency')"
        ).fetchall()
        for phase_job in phase_jobs:
            try:
                phase_payload = json.loads(phase_job["payload"] or "{}")
            except ValueError:
                continue
            if phase_payload.get("run_id") != row["id"]:
                continue
            conn.execute(
                "UPDATE app_jobs SET status = 'cancelled', completed_at = ?, updated_at = ?, status_detail = 'Cancelled by the user.' WHERE id = ?",
                (now, now, phase_job["id"]),
            )
        candidate_snapshot_id = row["snapshot_id"]
        if not candidate_snapshot_id:
            try:
                candidate_snapshot_id = json.loads(row["detail_json"] or "{}").get("candidate_snapshot_id")
            except ValueError:
                candidate_snapshot_id = None
        if candidate_snapshot_id:
            enqueue_job(
                conn, job_type="project_candidate_cleanup",
                payload={"project_id": project_id, "run_id": row["id"], "candidate_snapshot_id": candidate_snapshot_id},
                dedupe_key=f"project-cleanup:{candidate_snapshot_id}", scope_id=project_id,
            )
        conn.execute(
            """
            UPDATE projects SET active_run_id = NULL, candidate_snapshot_id = NULL,
                status = CASE WHEN active_snapshot_id IS NULL THEN 'registered' ELSE status END,
                updated_at = ? WHERE id = ?
            """,
            (now, project_id),
        )
        updated = conn.execute("SELECT * FROM project_index_runs WHERE id = ?", (row["id"],)).fetchone()
        return _project_run_from_row(updated)


def remove_project(project_id: str, *, confirmation_name: str) -> None:
    with connect() as conn:
        project = conn.execute(
            "SELECT name, primary_cluster_id FROM projects WHERE id = ? AND deleted_at IS NULL",
            (project_id,),
        ).fetchone()
        if project is None:
            raise KeyError(project_id)
        if confirmation_name.strip() != project["name"]:
            raise ProjectError("Confirmation name does not match the project name.")
        source_rows = conn.execute(
            "SELECT source_id FROM project_sources WHERE project_id = ?",
            (project_id,),
        ).fetchall()
        source_ids = [str(row["source_id"]) for row in source_rows]
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        for source_id in source_ids:
            conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
        count_row = conn.execute(
            "SELECT COUNT(*) AS total FROM sources WHERE cluster_id = ? AND deleted_at IS NULL",
            (project["primary_cluster_id"],),
        ).fetchone()
        conn.execute(
            """
            UPDATE clusters SET indexed_source_count = ?, index_status = CASE WHEN ? = 0 THEN 'empty' ELSE index_status END,
                updated_at = ? WHERE id = ?
            """,
            (count_row["total"], count_row["total"], utc_now(), project["primary_cluster_id"]),
        )


def discover_project(
    root: Path, *, discovery_scope: str = "context", progress_callback=None,
) -> DiscoveryResult:
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"Project root is not a directory: {root}")
    normalized_scope = normalize_discovery_scope(discovery_scope)
    ignore_patterns = _load_ignore_patterns(root)
    files: list[ManifestFile] = []
    ignored_count = 0
    generated_count = 0
    failed_count = 0
    language_counts: Counter[str] = Counter()
    entrypoints: list[str] = []
    workspaces = 0
    scanned_directories = 0

    for current_root, directories, filenames in os.walk(root, topdown=True, followlinks=False):
        scanned_directories += 1
        current = Path(current_root)
        kept_directories: list[str] = []
        for directory in directories:
            candidate = current / directory
            relative = candidate.relative_to(root).as_posix()
            if directory.lower() in DEFAULT_IGNORED_DIRECTORIES or _matches_ignore(relative + "/", ignore_patterns):
                ignored_count += 1
                continue
            if _is_link_or_junction(candidate) or not _inside_root(root, candidate):
                ignored_count += 1
                continue
            kept_directories.append(directory)
        directories[:] = kept_directories

        for filename in filenames:
            path = current / filename
            relative = path.relative_to(root).as_posix()
            lower_name = filename.lower()
            suffix = path.suffix.lower()
            if _is_secret_name(lower_name, suffix) or _matches_ignore(relative, ignore_patterns):
                ignored_count += 1
                continue
            if _is_link_or_junction(path) or not _inside_root(root, path):
                ignored_count += 1
                continue
            if lower_name in GENERATED_FILENAMES:
                generated_count += 1
                continue
            if lower_name.endswith((".min.js", ".min.css", ".map", ".generated.ts", ".g.cs")):
                generated_count += 1
                continue
            if suffix not in SUPPORTED_EXTENSIONS and lower_name not in SUPPORTED_FILENAMES:
                ignored_count += 1
                continue
            if normalized_scope == "code" and suffix not in CODE_EXTENSIONS:
                ignored_count += 1
                continue
            try:
                size = path.stat().st_size
                if size > MAX_FILE_BYTES:
                    ignored_count += 1
                    continue
                raw = path.read_bytes()
                if b"\x00" in raw[:8192]:
                    ignored_count += 1
                    continue
                text = raw.decode("utf-8-sig")
            except (OSError, UnicodeDecodeError):
                failed_count += 1
                continue
            digest = hashlib.sha256(raw).hexdigest()
            language = LANGUAGE_BY_EXTENSION.get(suffix, "Configuration")
            language_counts[language] += 1
            role = _file_role(relative, lower_name)
            if role == "workspace_manifest" and "/" in relative:
                workspaces += 1
            if lower_name in ENTRYPOINT_NAMES or relative.lower() in {
                "src/index.ts",
                "src/index.tsx",
                "src/main.ts",
                "src/main.tsx",
            }:
                entrypoints.append(relative)
            files.append(ManifestFile(path, relative, digest, text, language, role))
            if progress_callback is not None and len(files) % 100 == 0:
                progress_callback(len(files))

        if progress_callback is not None and scanned_directories % 25 == 0:
            progress_callback(len(files))

    files.sort(key=lambda item: item.relative_path.casefold())
    manifest_digest = hashlib.sha256()
    manifest_digest.update(normalized_scope.encode("ascii"))
    manifest_digest.update(b"\n")
    for item in files:
        manifest_digest.update(item.relative_path.casefold().encode("utf-8"))
        manifest_digest.update(b"\0")
        manifest_digest.update(item.content_hash.encode("ascii"))
        manifest_digest.update(b"\n")
    return DiscoveryResult(
        files=files,
        ignored_count=ignored_count,
        generated_count=generated_count,
        failed_count=failed_count,
        languages=dict(language_counts.most_common()),
        entrypoints=entrypoints[:8],
        workspace_count=workspaces,
        manifest_hash=manifest_digest.hexdigest(),
        discovery_scope=normalized_scope,
    )


def _activate_discovery(project: dict, discovery: DiscoveryResult, run_id: str) -> str:
    now = utc_now()
    snapshot_id = f"project-snapshot-{uuid4()}"
    repository_kind, branch, commit, remote_fingerprint, dirty, changed_file_count = _git_metadata(Path(project["root_path"]))
    manifest_summary = {
        "version": 1,
        "discovery_scope": discovery.discovery_scope,
        "files": [{"path": item.relative_path, "hash": item.content_hash} for item in discovery.files],
        "excluded": {
            "ignored": discovery.ignored_count,
            "generated": discovery.generated_count,
            "failed": discovery.failed_count,
        },
    }
    changed_sources: list[str] = []
    with connect() as conn:
        existing_rows = conn.execute(
            """
            SELECT ps.relative_path, ps.source_id, ps.content_hash
            FROM project_sources ps WHERE ps.project_id = ?
            """,
            (project["id"],),
        ).fetchall()
        existing = {str(row["relative_path"]): row for row in existing_rows}
        current_paths: set[str] = set()
        for item in discovery.files:
            current_paths.add(item.relative_path)
            previous = existing.get(item.relative_path)
            if previous is None:
                source_id = f"source-{uuid4()}"
                source = {
                    "id": source_id,
                    "vault_id": project["vault_id"],
                    "cluster_id": project["primary_cluster_id"],
                    "title": Path(item.relative_path).name,
                    "source_type": source_type_for_suffix(item.absolute_path.suffix.lower()),
                    "state": "indexed",
                    "original_path": str(item.absolute_path),
                    "url": None,
                    "checksum": item.content_hash,
                    "provenance": "project_import",
                    "trust_tier": "trusted_local",
                    "security_labels": "[]",
                    "parser_security_json": json.dumps({"odin": {"relative_path": item.relative_path}}),
                    "raw_text": item.text,
                    "extracted_text": item.text,
                    "summary": summarize_text(item.text),
                    "tags": json.dumps(["project", item.language.lower()]),
                    "cover_image_url": None,
                    "created_at": now,
                    "updated_at": now,
                }
                stored = store_source_content_fields(conn, source, now=now)
                conn.execute(
                    """
                    INSERT INTO sources (
                        id, vault_id, cluster_id, title, source_type, state, original_path, url,
                        checksum, provenance, trust_tier, security_labels, parser_security_json,
                        raw_text, extracted_text, summary, tags, cover_image_url, created_at, updated_at
                    ) VALUES (
                        :id, :vault_id, :cluster_id, :title, :source_type, :state, :original_path, :url,
                        :checksum, :provenance, :trust_tier, :security_labels, :parser_security_json,
                        :raw_text, :extracted_text, :summary, :tags, :cover_image_url, :created_at, :updated_at
                    )
                    """,
                    stored,
                )
                conn.execute(
                    """
                    INSERT INTO project_sources (
                        project_id, source_id, relative_path, file_role, content_hash, discovered_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (project["id"], source_id, item.relative_path, item.file_role, item.content_hash, now, now),
                )
                changed_sources.append(source_id)
            else:
                source_id = str(previous["source_id"])
                if previous["content_hash"] != item.content_hash:
                    updates = update_source_content_fields(
                        conn,
                        vault_id=project["vault_id"],
                        source_id=source_id,
                        updates={
                            "raw_text": item.text,
                            "extracted_text": item.text,
                            "summary": summarize_text(item.text),
                        },
                        now=now,
                    )
                    conn.execute(
                        """
                        UPDATE sources SET title = ?, state = 'indexed', original_path = ?, checksum = ?,
                            raw_text = ?, extracted_text = ?, summary = ?, deleted_at = NULL, updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            Path(item.relative_path).name,
                            str(item.absolute_path),
                            item.content_hash,
                            updates["raw_text"],
                            updates["extracted_text"],
                            updates["summary"],
                            now,
                            source_id,
                        ),
                    )
                    changed_sources.append(source_id)
                conn.execute(
                    """
                    UPDATE project_sources SET file_role = ?, content_hash = ?, updated_at = ?
                    WHERE project_id = ? AND source_id = ?
                    """,
                    (item.file_role, item.content_hash, now, project["id"], source_id),
                )

        removed = [row for path, row in existing.items() if path not in current_paths]
        for row in removed:
            conn.execute("DELETE FROM project_sources WHERE project_id = ? AND source_id = ?", (project["id"], row["source_id"]))
            conn.execute(
                "UPDATE sources SET deleted_at = ?, updated_at = ? WHERE id = ?",
                (now, now, row["source_id"]),
            )

        structure_status = "processing" if discovery.files else "unavailable"
        retrieval_status = "partial" if discovery.files else "unavailable"
        conn.execute(
            """
            INSERT INTO project_snapshots (
                id, project_id, discovery_scope, source_manifest_hash, git_commit, branch, dirty_working_tree,
                extractor_version, eligible_count, ignored_count, generated_count, parsed_count,
                failed_count, structure_status, retrieval_status, interpretation_status,
                manifest_json, activated_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'unavailable', ?, ?, ?)
            """,
            (
                snapshot_id,
                project["id"],
                discovery.discovery_scope,
                discovery.manifest_hash,
                commit,
                branch,
                int(dirty),
                EXTRACTOR_VERSION,
                len(discovery.files),
                discovery.ignored_count,
                discovery.generated_count,
                len(discovery.files),
                discovery.failed_count,
                structure_status,
                retrieval_status,
                json.dumps(manifest_summary, separators=(",", ":")),
                now,
                now,
            ),
        )
        conn.execute(
            "UPDATE projects SET candidate_snapshot_id = ?, updated_at = ? WHERE id = ?",
            (snapshot_id, now, project["id"]),
        )
        active_sources = {
            row["relative_path"]: row
            for row in conn.execute(
                """
                SELECT source_id, relative_path, file_role, content_hash, discovered_at, updated_at
                FROM project_sources WHERE project_id = ?
                """,
                (project["id"],),
            ).fetchall()
        }
        for item in discovery.files:
            membership = active_sources[item.relative_path]
            previous = existing.get(item.relative_path)
            intended_action = "add" if previous is None else "modify" if previous["content_hash"] != item.content_hash else "unchanged"
            conn.execute(
                """
                INSERT INTO project_snapshot_sources (
                    snapshot_id, project_id, source_id, prior_source_id, relative_path,
                    file_role, language, byte_size, content_hash, intended_action,
                    stage_status, error_category, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'candidate', '', ?, ?)
                """,
                (
                    snapshot_id,
                    project["id"],
                    membership["source_id"],
                    membership["source_id"],
                    item.relative_path,
                    item.file_role,
                    item.language,
                    len(item.text.encode("utf-8")),
                    item.content_hash,
                    intended_action,
                    membership["discovered_at"],
                    membership["updated_at"],
                ),
            )
            conn.execute(
                """
                UPDATE sources SET project_id = ?, project_snapshot_id = ?, activation_state = 'active'
                WHERE id = ?
                """,
                (project["id"], snapshot_id, membership["source_id"]),
            )
        structure_result = build_structure_graph(
            conn,
            project=project,
            snapshot_id=snapshot_id,
            files=discovery.files,
            now=now,
        )
        structure_status = (
            "partial" if structure_result["parse_failure_count"] or discovery.failed_count else "ready"
        ) if discovery.files else "unavailable"
        conn.execute(
            """
            UPDATE project_snapshots
            SET structure_status = ?, failed_count = ?, extractor_version = ?,
                manifest_activated_at = ?, structure_activated_at = ?,
                retrieval_activated_at = COALESCE(retrieval_activated_at, ?)
            WHERE id = ?
            """,
            (
                structure_status,
                discovery.failed_count + structure_result["parse_failure_count"],
                EXTRACTOR_VERSION,
                now,
                now,
                now,
                snapshot_id,
            ),
        )
        brief = _build_brief(project["name"], repository_kind, discovery, structure_result)
        aggregate_status = "partial" if discovery.failed_count or structure_result["parse_failure_count"] else "ready"
        conn.execute(
            """
            UPDATE projects SET repository_kind = ?, git_remote_fingerprint = ?, default_branch = ?, indexed_commit = ?,
                working_tree_dirty = ?, changed_file_count = ?,
                status = ?, structure_status = ?, retrieval_status = ?, interpretation_status = 'unavailable',
                active_snapshot_id = ?, active_manifest_snapshot_id = ?,
                active_structure_snapshot_id = ?, active_retrieval_snapshot_id = ?,
                candidate_snapshot_id = NULL, active_run_id = NULL,
                brief = ?, languages_json = ?, workspace_count = ?, entrypoints_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                repository_kind,
                remote_fingerprint,
                branch,
                commit,
                int(dirty),
                changed_file_count,
                aggregate_status,
                structure_status,
                retrieval_status,
                snapshot_id,
                snapshot_id,
                snapshot_id,
                snapshot_id,
                brief,
                json.dumps(discovery.languages),
                discovery.workspace_count,
                json.dumps(discovery.entrypoints),
                now,
                project["id"],
            ),
        )
        conn.execute(
            "UPDATE project_snapshot_sources SET stage_status = 'active', updated_at = ? WHERE snapshot_id = ?",
            (now, snapshot_id),
        )
        conn.execute(
            """
            UPDATE project_index_runs SET snapshot_id = ?, status = 'succeeded', phase = 'activated',
                eligible_total = ?, completed_count = ?, skipped_count = ?, failed_count = ?,
                phase_completed_count = ?, phase_total_count = ?, activation_outcome = 'activated',
                heartbeat_at = ?, detail_json = ?, finished_at = ?, updated_at = ? WHERE id = ?
            """,
            (
                snapshot_id,
                len(discovery.files),
                len(discovery.files),
                discovery.ignored_count + discovery.generated_count,
                discovery.failed_count + structure_result["parse_failure_count"],
                len(discovery.files),
                len(discovery.files),
                now,
                json.dumps(
                    {
                        "changed_sources": len(changed_sources),
                        "removed_sources": len(removed),
                        "structure": structure_result,
                    },
                    separators=(",", ":"),
                ),
                now,
                now,
                run_id,
            ),
        )
        conn.execute(
            """
            UPDATE clusters SET index_status = ?, profile_status = 'needs_update',
                cluster_summary = ?, indexed_source_count = ?, updated_at = ? WHERE id = ?
            """,
            (
                "ready" if discovery.files else "empty",
                brief,
                len(discovery.files),
                now,
                project["primary_cluster_id"],
            ),
        )
        for source_id in changed_sources:
            enqueue_job(
                conn,
                job_type="reindex_source",
                payload={"source_id": source_id},
                dedupe_key=f"reindex-source:{source_id}",
            )
    return snapshot_id


def _project_from_row(conn, row) -> dict:
    result = dict_from_row(row)
    result["working_tree_dirty"] = bool(result.get("working_tree_dirty"))
    compatibility_snapshot_id = result.get("active_snapshot_id")
    result["active_manifest_snapshot_id"] = result.get("active_manifest_snapshot_id") or compatibility_snapshot_id
    result["active_structure_snapshot_id"] = result.get("active_structure_snapshot_id") or compatibility_snapshot_id
    result["active_retrieval_snapshot_id"] = result.get("active_retrieval_snapshot_id") or compatibility_snapshot_id
    result["languages"] = json.loads(result.pop("languages_json") or "{}")
    result["entrypoints"] = json.loads(result.pop("entrypoints_json") or "[]")
    count = conn.execute(
        "SELECT COUNT(*) AS total FROM project_sources WHERE project_id = ?",
        (row["id"],),
    ).fetchone()
    result["source_count"] = int(count["total"] or 0)
    snapshot = None
    manifest_snapshot_id = result.get("active_manifest_snapshot_id")
    if manifest_snapshot_id:
        snapshot_row = conn.execute(
            "SELECT * FROM project_snapshots WHERE id = ?",
            (manifest_snapshot_id,),
        ).fetchone()
        if snapshot_row is not None:
            snapshot = dict_from_row(snapshot_row)
            snapshot["dirty_working_tree"] = bool(snapshot["dirty_working_tree"])
            snapshot.pop("manifest_json", None)
    result["active_snapshot"] = snapshot
    return result


def _project_run_from_row(row) -> dict:
    result = dict_from_row(row)
    result["cancellation_requested"] = bool(result.get("cancellation_requested"))
    return result


def _load_ignore_patterns(root: Path) -> list[str]:
    patterns: list[str] = []
    for filename in (".cmlignore", ".gitignore"):
        path = root / filename
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8-sig").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for line in lines:
            pattern = line.strip()
            if pattern and not pattern.startswith("#") and not pattern.startswith("!"):
                patterns.append(pattern.lstrip("/"))
    return patterns


def _matches_ignore(relative: str, patterns: list[str]) -> bool:
    normalized = relative.replace("\\", "/")
    for pattern in patterns:
        candidate = pattern.rstrip("/")
        if not candidate:
            continue
        if fnmatch.fnmatch(normalized, candidate) or fnmatch.fnmatch(normalized, f"**/{candidate}"):
            return True
        if "/" not in candidate and any(fnmatch.fnmatch(part, candidate) for part in normalized.split("/")):
            return True
        if normalized == candidate or normalized.startswith(candidate + "/"):
            return True
    return False


def _is_secret_name(name: str, suffix: str) -> bool:
    return name in SECRET_NAMES or name.startswith(".env.") or suffix in SECRET_SUFFIXES


def _is_link_or_junction(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction and is_junction())


def _inside_root(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve(strict=False).relative_to(root)
        return True
    except (OSError, ValueError):
        return False


def _file_role(relative: str, lower_name: str) -> str:
    if lower_name in {"package.json", "pyproject.toml", "cargo.toml", "go.mod", "pom.xml"}:
        return "workspace_manifest"
    if lower_name.endswith(".pyi"):
        return "stub"
    normalized = relative.replace("\\", "/").casefold()
    directories = set(normalized.split("/")[:-1])
    test_directories = {"test", "tests", "__tests__", "spec", "specs", "fixture", "fixtures", "__fixtures__"}
    test_filename = (
        lower_name.startswith("test_")
        or lower_name.endswith(("_test.py", "_test.go", "_test.rs"))
        or ".test." in lower_name
        or ".spec." in lower_name
        or lower_name.endswith((".stories.ts", ".stories.tsx", ".stories.js", ".stories.jsx"))
    )
    if directories & test_directories or test_filename:
        return "test"
    if lower_name in ENTRYPOINT_NAMES:
        return "entrypoint"
    if lower_name.endswith((".json", ".yaml", ".yml", ".toml", ".ini", ".cfg")):
        return "configuration"
    return "source"


def _git_metadata(root: Path) -> tuple[str, str | None, str | None, str | None, bool, int]:
    git_path = root / ".git"
    if not git_path.exists():
        return "folder", None, None, None, False, 0
    git_dir = git_path
    if git_path.is_file():
        try:
            marker = git_path.read_text(encoding="utf-8").strip()
            if marker.lower().startswith("gitdir:"):
                git_dir = (root / marker.split(":", 1)[1].strip()).resolve()
        except (OSError, UnicodeDecodeError):
            return "git", None, None, None, False, 0
    try:
        head = (git_dir / "HEAD").read_text(encoding="ascii").strip()
    except OSError:
        return "git", None, None, None, False, 0
    if head.startswith("ref:"):
        reference = head.split(":", 1)[1].strip()
        branch = reference.rsplit("/", 1)[-1]
        try:
            commit = (git_dir / reference).read_text(encoding="ascii").strip() or None
        except OSError:
            commit = _packed_ref(git_dir, reference)
        return _git_worktree_metadata(root, branch, commit)
    return _git_worktree_metadata(root, None, head or None)


def _git_worktree_metadata(
    root: Path,
    branch: str | None,
    commit: str | None,
) -> tuple[str, str | None, str | None, str | None, bool, int]:
    remote_fingerprint = None
    changed_count = 0
    try:
        status = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain=v1", "--untracked-files=normal"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
        if status.returncode == 0:
            changed_count = sum(1 for line in status.stdout.splitlines() if line.strip())
        remote = subprocess.run(
            ["git", "-C", str(root), "config", "--get", "remote.origin.url"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
        if remote.returncode == 0 and remote.stdout.strip():
            remote_fingerprint = hashlib.sha256(remote.stdout.strip().encode("utf-8")).hexdigest()
    except (OSError, subprocess.SubprocessError):
        pass
    return "git", branch, commit, remote_fingerprint, changed_count > 0, changed_count


def _packed_ref(git_dir: Path, reference: str) -> str | None:
    try:
        for line in (git_dir / "packed-refs").read_text(encoding="ascii").splitlines():
            if line.startswith("#") or line.startswith("^"):
                continue
            commit, _, name = line.partition(" ")
            if name.strip() == reference:
                return commit.strip() or None
    except OSError:
        return None
    return None


def _build_brief(
    name: str,
    repository_kind: str,
    discovery: DiscoveryResult,
    structure: dict | None = None,
) -> str:
    language_names = list(discovery.languages)[:3]
    language_text = ", ".join(language_names) if language_names else "text"
    kind = "Git repository" if repository_kind == "git" else "code folder"
    workspace_text = (
        f" It contains {discovery.workspace_count} detected package or workspace manifests."
        if discovery.workspace_count
        else ""
    )
    entrypoint_text = (
        f" Detected entry points include {', '.join(discovery.entrypoints[:3])}."
        if discovery.entrypoints
        else ""
    )
    structure_text = ""
    if structure:
        structure_text = (
            f" Odin extracted {structure['symbol_count']} symbols, {structure['edge_count']} evidence-backed relationships, "
            f"and {structure['route_count']} routes."
        )
    return (
        f"{name} is a {kind} with {len(discovery.files)} indexed files, primarily {language_text}."
        f"{workspace_text}{entrypoint_text}{structure_text} Retrieval indexing is local and the optional "
        "model-written project brief remains a separate derived layer."
    )
