from __future__ import annotations

import argparse
import json
import os
import threading
import time
from pathlib import Path

import psutil


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark Odin's local project indexing pipeline.")
    parser.add_argument("project_root", type=Path)
    parser.add_argument("data_dir", type=Path)
    parser.add_argument(
        "--retrieval",
        action="store_true",
        help="Continue through retrieval staging and atomic activation after structural indexing.",
    )
    args = parser.parse_args()

    root = args.project_root.resolve(strict=True)
    data_dir = args.data_dir.resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ.update(
        {
            "CML_DATABASE_PATH": str(data_dir / "odin-benchmark.sqlite3"),
            "CML_DATA_DIR": str(data_dir),
            "CML_EMBEDDING_PROVIDER": "hash",
            "CML_ALLOW_HASH_EMBEDDINGS": "1",
        }
    )

    from backend.app.core.config import get_settings

    get_settings.cache_clear()
    from backend.app.core.background_jobs import run_due_jobs_once
    from backend.app.core.database import connect, init_db, utc_now
    from backend.app.core.migrations import run_migrations
    from backend.app.core.projects import get_project, register_project

    process = psutil.Process()
    peak_rss = 0
    sampling = True

    def sample_memory() -> None:
        nonlocal peak_rss
        while sampling:
            try:
                peak_rss = max(peak_rss, process.memory_info().rss)
            except psutil.Error:
                return
            time.sleep(0.01)

    sampler = threading.Thread(target=sample_memory, daemon=True)
    sampler.start()
    started_wall = time.perf_counter()
    started_cpu = time.process_time()
    init_db()
    run_migrations()
    now = utc_now()
    with connect() as conn:
        conn.execute(
            "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("vault-odin-benchmark", "Odin benchmark", str(data_dir), now, now),
        )
    project = register_project(
        vault_id="vault-odin-benchmark",
        root_path=str(root),
        name=f"{root.name} benchmark",
        sync=True,
    )
    structure_jobs = 0
    while not project.get("active_structure_snapshot_id"):
        processed = run_due_jobs_once(limit=1)
        structure_jobs += processed
        if processed == 0:
            raise RuntimeError("Odin structural indexing stopped before activating a structure snapshot.")
        project = get_project(project["id"])
    structure_wall_seconds = time.perf_counter() - started_wall

    retrieval_jobs = 0
    if args.retrieval:
        while True:
            processed = run_due_jobs_once(limit=1)
            retrieval_jobs += processed
            if processed == 0:
                break
        project = get_project(project["id"])
    cpu_seconds = time.process_time() - started_cpu
    wall_seconds = time.perf_counter() - started_wall
    sampling = False
    sampler.join(timeout=1)

    with connect() as conn:
        snapshot_id = project["active_structure_snapshot_id"]
        eligible_files = conn.execute(
            "SELECT COUNT(*) FROM project_snapshot_sources WHERE snapshot_id = ? AND intended_action != 'remove'",
            (snapshot_id,),
        ).fetchone()[0]
        node_count = conn.execute(
            "SELECT COUNT(*) FROM code_nodes WHERE project_id = ? AND snapshot_id = ?",
            (project["id"], snapshot_id),
        ).fetchone()[0]
        edge_count = conn.execute(
            "SELECT COUNT(*) FROM code_edges WHERE project_id = ? AND snapshot_id = ?",
            (project["id"], snapshot_id),
        ).fetchone()[0]
        node_kind_counts = {
            str(row["kind"]): int(row["total"])
            for row in conn.execute(
                "SELECT kind, COUNT(*) AS total FROM code_nodes WHERE project_id = ? AND snapshot_id = ? GROUP BY kind ORDER BY kind",
                (project["id"], snapshot_id),
            ).fetchall()
        }
        edge_type_counts = {
            str(row["edge_type"]): int(row["total"])
            for row in conn.execute(
                "SELECT edge_type, COUNT(*) AS total FROM code_edges WHERE project_id = ? AND snapshot_id = ? GROUP BY edge_type ORDER BY edge_type",
                (project["id"], snapshot_id),
            ).fetchall()
        }
        parser_status_counts = {
            str(row["parser_status"]): int(row["total"])
            for row in conn.execute(
                "SELECT parser_status, COUNT(*) AS total FROM project_snapshot_sources WHERE snapshot_id = ? GROUP BY parser_status ORDER BY parser_status",
                (snapshot_id,),
            ).fetchall()
        }
        chunk_count = conn.execute(
            """
            SELECT COUNT(*) FROM source_chunks sc
            JOIN project_sources ps ON ps.source_id = sc.source_id
            WHERE ps.project_id = ?
            """,
            (project["id"],),
        ).fetchone()[0]
        db_size = Path(os.environ["CML_DATABASE_PATH"]).stat().st_size
    print(
        json.dumps(
            {
                "tool": "odin",
                "structure_wall_seconds": round(structure_wall_seconds, 3),
                "full_wall_seconds": round(wall_seconds, 3),
                "cpu_seconds": round(cpu_seconds, 3),
                "peak_rss_bytes": peak_rss,
                "eligible_files": eligible_files,
                "nodes": node_count,
                "edges": edge_count,
                "node_kind_counts": node_kind_counts,
                "edge_type_counts": edge_type_counts,
                "parser_status_counts": parser_status_counts,
                "retrieval_chunks": chunk_count,
                "retrieval_jobs_processed": retrieval_jobs,
                "structure_jobs_processed": structure_jobs,
                "database_bytes": db_size,
                "status": project["status"],
                "structure_status": project["structure_status"],
                "retrieval_status": project["retrieval_status"],
                "indexed_commit": project["indexed_commit"],
                "working_tree_dirty": project["working_tree_dirty"],
                "changed_file_count": project["changed_file_count"],
            },
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
