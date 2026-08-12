from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


class ProjectFlowScaleTests(unittest.TestCase):
    """A CI-sized proxy for the separate 50k/150k release benchmark."""

    NODE_COUNT = max(1_000, int(os.getenv("CML_FLOW_SCALE_NODES", "10000")))
    EDGES_PER_NODE = 3

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        data_dir = Path(self.tmp.name) / "data"
        os.environ["CML_DATABASE_PATH"] = str(data_dir / "flow-scale.sqlite3")
        os.environ["CML_DATA_DIR"] = str(data_dir)
        os.environ["CML_EMBEDDING_PROVIDER"] = "hash"
        os.environ["CML_ALLOW_HASH_EMBEDDINGS"] = "1"
        from backend.app.core.config import get_settings
        get_settings.cache_clear()
        from backend.app.core.database import connect, init_db, utc_now
        from backend.app.core.migrations import run_migrations
        init_db()
        run_migrations()
        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-flow-scale", "Scale", str(data_dir), now, now),
            )
            conn.execute(
                """INSERT INTO clusters (id, vault_id, name, description, created_at, updated_at)
                   VALUES (?, ?, ?, '', ?, ?)""",
                ("cluster-flow-scale", "vault-flow-scale", "Scale", now, now),
            )
            conn.execute(
                """
                INSERT INTO projects (
                    id, vault_id, name, root_path, root_fingerprint, primary_cluster_id,
                    status, structure_status, retrieval_status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'ready', 'ready', 'ready', ?, ?)
                """,
                (
                    "project-flow-scale", "vault-flow-scale", "Scale", str(data_dir),
                    "scale-root", "cluster-flow-scale", now, now,
                ),
            )
            conn.execute(
                """
                INSERT INTO project_snapshots (
                    id, project_id, source_manifest_hash, extractor_version,
                    structure_status, retrieval_status, activated_at, created_at
                ) VALUES (?, ?, ?, ?, 'ready', 'ready', ?, ?)
                """,
                ("snapshot-flow-scale", "project-flow-scale", "scale", "test-v1", now, now),
            )
            conn.execute(
                """
                UPDATE projects SET active_snapshot_id = ?, active_manifest_snapshot_id = ?,
                    active_structure_snapshot_id = ?, active_retrieval_snapshot_id = ? WHERE id = ?
                """,
                ("snapshot-flow-scale", "snapshot-flow-scale", "snapshot-flow-scale", "snapshot-flow-scale", "project-flow-scale"),
            )
            nodes = []
            for index in range(self.NODE_COUNT):
                label = "flowEntry" if index == 0 else f"worker{index}"
                nodes.append((
                    f"node-{index}", "project-flow-scale", "snapshot-flow-scale", None,
                    f"scale:{label}", "function", "Python", label, f"src/worker_{index // 100}.py",
                    index + 1, 0, index + 1, 20, f"{label}()", "scale-test", "scale-v1",
                    f"hash-{index}", now,
                ))
            conn.executemany(
                """
                INSERT INTO code_nodes (
                    id, project_id, snapshot_id, source_id, qualified_id, kind, language,
                    display_label, relative_path, start_line, start_column, end_line, end_column,
                    signature, extraction_method, extractor_version, content_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                nodes,
            )
            edges = []
            for index in range(self.NODE_COUNT - 1):
                for offset in (1, 7, 31):
                    target = min(index + offset, self.NODE_COUNT - 1)
                    edges.append((
                        f"edge-{index}-{offset}", "project-flow-scale", "snapshot-flow-scale",
                        f"node-{index}", f"node-{target}", "calls", None, index + offset,
                        "scale-test", "extracted", now,
                    ))
            conn.executemany(
                """
                INSERT OR IGNORE INTO code_edges (
                    id, project_id, snapshot_id, source_node_id, target_node_id, edge_type,
                    evidence_source_id, source_line, extraction_method, confidence_class, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                edges,
            )

    def tearDown(self) -> None:
        from backend.app.core.config import get_settings
        get_settings.cache_clear()
        for key in ("CML_DATABASE_PATH", "CML_DATA_DIR", "CML_EMBEDDING_PROVIDER", "CML_ALLOW_HASH_EMBEDDINGS"):
            os.environ.pop(key, None)
        self.tmp.cleanup()

    def test_flow_projection_remains_bounded_on_a_large_graph(self) -> None:
        from backend.app.core.database import connect
        from backend.app.core.project_flow import project_flow_view

        started = time.perf_counter()
        with patch("backend.app.core.project_flow.build_cluster_bundle_context", return_value={"evidence": []}):
            view = project_flow_view("project-flow-scale", query="Trace flowEntry")
        elapsed_ms = (time.perf_counter() - started) * 1000

        self.assertEqual(view["status"], "found")
        self.assertLessEqual(len(view["primary_flow"]["steps"]), 8)
        self.assertLessEqual(view["diagnostics"]["examined_edges"], 800)
        self.assertLessEqual(view["diagnostics"]["candidate_nodes"], 160)
        self.assertLess(elapsed_ms, 1_500)
        with connect() as conn:
            plan = " ".join(
                row["detail"]
                for row in conn.execute(
                    """EXPLAIN QUERY PLAN SELECT * FROM code_edges
                       WHERE project_id=? AND snapshot_id=? AND source_node_id=? AND edge_type='calls'""",
                    ("project-flow-scale", "snapshot-flow-scale", "node-0"),
                ).fetchall()
            )
            indexes = {row["name"] for row in conn.execute("PRAGMA index_list(code_nodes)").fetchall()}
            label_plan = " ".join(
                row["detail"]
                for row in conn.execute(
                    """EXPLAIN QUERY PLAN SELECT * FROM code_nodes
                       WHERE project_id=? AND snapshot_id=?
                         AND display_label COLLATE NOCASE IN (?)""",
                    ("project-flow-scale", "snapshot-flow-scale", "flowentry"),
                ).fetchall()
            )
        self.assertIn("idx_code_edges_source", plan)
        self.assertIn("idx_code_nodes_source_range", indexes)
        self.assertIn("idx_code_nodes_label_search", indexes)
        self.assertIn("idx_code_nodes_label_search", label_plan)

    def test_broad_question_keeps_candidate_search_inside_its_own_budget(self) -> None:
        from backend.app.core.project_flow import project_flow_view

        started = time.perf_counter()
        with patch("backend.app.core.project_flow.build_cluster_bundle_context", return_value={"evidence": []}):
            view = project_flow_view(
                "project-flow-scale",
                query="Show how workers process and dispatch background work",
                timeout_ms=500,
            )
        elapsed_ms = (time.perf_counter() - started) * 1000

        self.assertLessEqual(view["diagnostics"]["candidate_ms"], 500)
        self.assertLessEqual(view["diagnostics"]["examined_edges"], 800)
        self.assertLess(elapsed_ms, 1_750)


if __name__ == "__main__":
    unittest.main()
