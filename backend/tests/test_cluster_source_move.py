import os
import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException


class ClusterSourceMoveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.sqlite3"
        os.environ["CML_DATABASE_PATH"] = str(self.db_path)
        os.environ["CML_DATA_DIR"] = self.tmp.name
        os.environ["CML_EMBEDDING_PROVIDER"] = "hash"
        os.environ["CML_ALLOW_HASH_EMBEDDINGS"] = "1"

        from backend.app.core.config import get_settings
        from backend.app.core.database import init_db

        get_settings.cache_clear()
        init_db()

    def tearDown(self) -> None:
        from backend.app.core.config import get_settings

        get_settings.cache_clear()
        os.environ.pop("CML_DATABASE_PATH", None)
        os.environ.pop("CML_DATA_DIR", None)
        os.environ.pop("CML_EMBEDDING_PROVIDER", None)
        os.environ.pop("CML_ALLOW_HASH_EMBEDDINGS", None)
        self.tmp.cleanup()

    def seed_clusters(self) -> None:
        from backend.app.core.database import connect, utc_now

        now = utc_now()
        with connect() as conn:
            conn.executemany(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                [
                    ("vault-1", "Main", self.tmp.name, now, now),
                    ("vault-2", "Other", self.tmp.name, now, now),
                ],
            )
            conn.executemany(
                "INSERT INTO clusters (id, vault_id, name, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                [
                    ("cluster-a", "vault-1", "Alpha", now, now),
                    ("cluster-b", "vault-1", "Beta", now, now),
                    ("cluster-other", "vault-2", "Other", now, now),
                ],
            )

    def create_clustered_source(self) -> dict:
        from backend.app.api.routes.sources import create_source
        from backend.app.schemas import SourceCreate

        return create_source(
            SourceCreate(
                vault_id="vault-1",
                cluster_id="cluster-a",
                title="Move me",
                source_type="note",
                raw_text="A source that should move without changing its saved content.",
            )
        )

    def test_one_source_moves_between_clusters_and_refreshes_membership(self) -> None:
        from backend.app.api.routes.sources import update_source
        from backend.app.core.database import connect
        from backend.app.schemas import SourceUpdate

        self.seed_clusters()
        source = self.create_clustered_source()

        moved = update_source(source["id"], SourceUpdate(cluster_id="cluster-b"))

        with connect() as conn:
            membership = conn.execute(
                "SELECT cluster_id, raw_text FROM sources WHERE id = ?",
                (source["id"],),
            ).fetchone()
            counts = {
                row["cluster_id"]: row["count"]
                for row in conn.execute(
                    """
                    SELECT cluster_id, COUNT(*) AS count
                    FROM sources
                    WHERE vault_id = ? AND deleted_at IS NULL
                    GROUP BY cluster_id
                    """,
                    ("vault-1",),
                ).fetchall()
            }
            profile_scopes = {
                row["scope_id"]
                for row in conn.execute(
                    "SELECT scope_id FROM app_jobs WHERE job_type = 'refresh_cluster_profile'",
                ).fetchall()
            }

        self.assertEqual(moved["cluster_id"], "cluster-b")
        self.assertEqual(membership["cluster_id"], "cluster-b")
        self.assertIn("should move", moved["raw_text"])
        self.assertEqual(membership["raw_text"], source["raw_text"])
        self.assertEqual(counts.get("cluster-a", 0), 0)
        self.assertEqual(counts["cluster-b"], 1)
        self.assertTrue({"cluster-a", "cluster-b"}.issubset(profile_scopes))

    def test_source_cannot_move_to_a_cluster_in_another_vault(self) -> None:
        from backend.app.api.routes.sources import update_source
        from backend.app.core.database import connect
        from backend.app.schemas import SourceUpdate

        self.seed_clusters()
        source = self.create_clustered_source()

        with self.assertRaises(HTTPException) as raised:
            update_source(source["id"], SourceUpdate(cluster_id="cluster-other"))

        with connect() as conn:
            membership = conn.execute(
                "SELECT cluster_id FROM sources WHERE id = ?",
                (source["id"],),
            ).fetchone()

        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(membership["cluster_id"], "cluster-a")

    def test_accepting_a_suggested_move_updates_membership_and_records_the_decision(self) -> None:
        from backend.app.api.routes.clusters import decide_cluster_suggestion
        from backend.app.core.database import connect
        from backend.app.schemas import ClusterSuggestionDecision

        self.seed_clusters()
        source = self.create_clustered_source()

        result = decide_cluster_suggestion(
            ClusterSuggestionDecision(
                source_id=source["id"],
                suggested_cluster_id="cluster-b",
                action="accepted",
            )
        )

        with connect() as conn:
            membership = conn.execute(
                "SELECT cluster_id, updated_at FROM sources WHERE id = ?",
                (source["id"],),
            ).fetchone()
            decision = conn.execute(
                """
                SELECT action, suggested_cluster_id, source_updated_at
                FROM cluster_suggestion_decisions
                WHERE source_id = ?
                """,
                (source["id"],),
            ).fetchone()

        self.assertEqual(result["action"], "accepted")
        self.assertEqual(membership["cluster_id"], "cluster-b")
        self.assertEqual(decision["action"], "accepted")
        self.assertEqual(decision["suggested_cluster_id"], "cluster-b")
        self.assertEqual(decision["source_updated_at"], membership["updated_at"])

    def test_dismissing_a_suggested_move_keeps_membership_and_records_the_decision(self) -> None:
        from backend.app.api.routes.clusters import decide_cluster_suggestion
        from backend.app.core.database import connect
        from backend.app.schemas import ClusterSuggestionDecision

        self.seed_clusters()
        source = self.create_clustered_source()

        decide_cluster_suggestion(
            ClusterSuggestionDecision(
                source_id=source["id"],
                suggested_cluster_id="cluster-b",
                action="dismissed",
            )
        )

        with connect() as conn:
            membership = conn.execute(
                "SELECT cluster_id, updated_at FROM sources WHERE id = ?",
                (source["id"],),
            ).fetchone()
            decision = conn.execute(
                "SELECT action, source_updated_at FROM cluster_suggestion_decisions WHERE source_id = ?",
                (source["id"],),
            ).fetchone()

        self.assertEqual(membership["cluster_id"], "cluster-a")
        self.assertEqual(decision["action"], "dismissed")
        self.assertEqual(decision["source_updated_at"], membership["updated_at"])


if __name__ == "__main__":
    unittest.main()
