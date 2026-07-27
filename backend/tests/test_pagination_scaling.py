import os
import tempfile
import time
import unittest
from pathlib import Path


class PaginationScalingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        data_dir = Path(self.tmp.name) / "data"
        os.environ["CML_DATABASE_PATH"] = str(data_dir / "test.sqlite3")
        os.environ["CML_DATA_DIR"] = str(data_dir)
        from backend.app.core.config import get_settings

        get_settings.cache_clear()
        from backend.app.core.database import connect, init_db, utc_now

        init_db()
        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-scale", "Scale", str(data_dir), now, now),
            )

    def tearDown(self) -> None:
        from backend.app.core.config import get_settings

        get_settings.cache_clear()
        os.environ.pop("CML_DATABASE_PATH", None)
        os.environ.pop("CML_DATA_DIR", None)
        self.tmp.cleanup()

    def test_ten_thousand_clusters_page_to_completion_without_duplicates(self) -> None:
        from backend.app.api.routes.clusters import list_clusters_page
        from backend.app.core.database import connect, utc_now

        now = utc_now()
        with connect() as conn:
            conn.executemany(
                """
                INSERT INTO clusters (id, vault_id, name, description, color, created_at, updated_at)
                VALUES (?, 'vault-scale', ?, '', 'sage', ?, ?)
                """,
                [
                    (f"cluster-{index:05d}", f"Cluster {index}", now, f"2026-01-01T00:{index // 60:03d}:{index % 60:02d}+00:00")
                    for index in range(10_000)
                ],
            )

        started = time.perf_counter()
        first = list_clusters_page(vault_id="vault-scale", limit=200)
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO clusters (id, vault_id, name, description, color, created_at, updated_at)
                VALUES ('cluster-newer', 'vault-scale', 'Newer', '', 'sage', ?, '2099-01-01T00:00:00+00:00')
                """,
                (now,),
            )
        ids = [item["id"] for item in first["items"]]
        cursor = first["next_cursor"]
        while cursor:
            page = list_clusters_page(vault_id="vault-scale", limit=200, cursor=cursor)
            ids.extend(item["id"] for item in page["items"])
            cursor = page["next_cursor"]
        elapsed = time.perf_counter() - started

        self.assertEqual(len(ids), 10_000)
        self.assertEqual(len(set(ids)), 10_000)
        self.assertNotIn("cluster-newer", ids)
        self.assertLess(elapsed, 5.0)

    def test_project_list_hydration_uses_constant_query_count(self) -> None:
        from backend.app.core.database import connect, utc_now
        from backend.app.core.projects import list_projects_page

        now = utc_now()
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO clusters (id, vault_id, name, description, color, created_at, updated_at)
                VALUES ('project-cluster', 'vault-scale', 'Projects', '', 'sage', ?, ?)
                """,
                (now, now),
            )
            conn.executemany(
                """
                INSERT INTO projects (
                    id, vault_id, name, root_path, root_fingerprint, primary_cluster_id,
                    created_at, updated_at
                )
                VALUES (?, 'vault-scale', ?, ?, ?, 'project-cluster', ?, ?)
                """,
                [
                    (
                        f"project-{index:03d}",
                        f"Project {index}",
                        str(Path(self.tmp.name) / f"project-{index}"),
                        f"fingerprint-{index}",
                        now,
                        f"2026-01-01T00:00:{index:02d}+00:00",
                    )
                    for index in range(20)
                ],
            )
            statements: list[str] = []
            conn.set_trace_callback(statements.append)
            # Exercise the same batch hydrator with this traced connection by
            # patching the module's connection factory for the call.
            from unittest.mock import patch
            from contextlib import nullcontext

            with patch("backend.app.core.projects.connect", return_value=nullcontext(conn)):
                page = list_projects_page(vault_id="vault-scale", limit=20)
            conn.set_trace_callback(None)

        selects = [statement for statement in statements if statement.lstrip().upper().startswith("SELECT")]
        self.assertEqual(len(page["items"]), 20)
        self.assertLessEqual(len(selects), 3)
