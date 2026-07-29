import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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

    def test_ambiguous_new_source_stays_unclustered(self) -> None:
        from backend.app.api.routes.sources import create_source
        from backend.app.schemas import SourceCreate

        self.seed_clusters()
        source = create_source(
            SourceCreate(
                vault_id="vault-1",
                title="Quarterly planning notes",
                source_type="note",
                raw_text="A mixed set of planning notes without a clear relationship to Alpha or Beta.",
            )
        )

        self.assertIsNone(source["cluster_id"])

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

    def test_suggestion_review_batch_does_not_regenerate_after_each_decision(self) -> None:
        from backend.app.api.routes.clusters import (
            decide_cluster_suggestion,
            list_cluster_suggestions,
        )
        from backend.app.schemas import ClusterSuggestionDecision

        self.seed_clusters()
        source = self.create_clustered_source()
        computed = [
            {
                "source_id": source["id"],
                "source_title": source["title"],
                "current_cluster_id": "cluster-a",
                "suggested_cluster_id": "cluster-b",
                "suggested_cluster_name": "Beta",
                "confidence": 0.82,
                "reason": "Closer to Beta.",
            }
        ]
        with patch(
            "backend.app.core.cluster_suggestions.suggest_source_cluster_moves",
            return_value=computed,
        ) as compute:
            first = list_cluster_suggestions("vault-1")
            repeated = list_cluster_suggestions("vault-1")
            decide_cluster_suggestion(
                ClusterSuggestionDecision(
                    source_id=source["id"],
                    suggested_cluster_id="cluster-b",
                    action="accepted",
                )
            )
            completed = list_cluster_suggestions("vault-1")

        self.assertEqual(first, computed)
        self.assertEqual(repeated, computed)
        self.assertEqual(completed, [])
        compute.assert_called_once()

    def test_accepting_last_source_prunes_only_an_auto_created_cluster(self) -> None:
        from backend.app.api.routes.clusters import decide_cluster_suggestion
        from backend.app.core.database import connect
        from backend.app.schemas import ClusterSuggestionDecision

        self.seed_clusters()
        source = self.create_clustered_source()
        with connect() as conn:
            conn.execute("UPDATE clusters SET name_origin = 'auto' WHERE id = 'cluster-a'")

        decide_cluster_suggestion(
            ClusterSuggestionDecision(
                source_id=source["id"],
                suggested_cluster_id="cluster-b",
                action="accepted",
            )
        )

        with connect() as conn:
            old_cluster = conn.execute(
                "SELECT id FROM clusters WHERE id = 'cluster-a'"
            ).fetchone()
            user_cluster = conn.execute(
                "SELECT id FROM clusters WHERE id = 'cluster-b'"
            ).fetchone()
        self.assertIsNone(old_cluster)
        self.assertIsNotNone(user_cluster)

    def test_stable_batch_migration_cleans_abandoned_auto_clusters_and_stale_decisions(self) -> None:
        from backend.app.core.database import connect, utc_now
        from backend.app.core.migrations import _migration_014_stable_cluster_suggestion_batches

        self.seed_clusters()
        source = self.create_clustered_source()
        now = utc_now()
        with connect() as conn:
            conn.execute("UPDATE clusters SET name_origin = 'auto' WHERE id = 'cluster-b'")
            conn.execute(
                """
                INSERT INTO cluster_suggestion_decisions (
                    source_id, vault_id, suggested_cluster_id, action,
                    source_updated_at, created_at, updated_at
                )
                VALUES (?, 'vault-1', 'cluster-missing', 'dismissed', ?, ?, ?)
                """,
                (source["id"], source["updated_at"], now, now),
            )
            _migration_014_stable_cluster_suggestion_batches(conn)
            auto_cluster = conn.execute(
                "SELECT id FROM clusters WHERE id = 'cluster-b'"
            ).fetchone()
            stale_decision = conn.execute(
                "SELECT source_id FROM cluster_suggestion_decisions WHERE source_id = ?",
                (source["id"],),
            ).fetchone()

        self.assertIsNone(auto_cluster)
        self.assertIsNone(stale_decision)

    def test_source_metadata_job_persists_description_and_refreshes_cluster(self) -> None:
        from backend.app.core.background_jobs import _run_source_metadata_enrichment
        from backend.app.core.database import connect

        self.seed_clusters()
        source = self.create_clustered_source()
        with patch(
            "backend.app.core.background_jobs.enrich_source_metadata",
            return_value={
                "summary": "A note explaining how a source move preserves its saved content.",
                "keywords": ["source organization", "saved content"],
            },
        ):
            _run_source_metadata_enrichment(
                {
                    "source_id": source["id"],
                    "source_updated_at": source["updated_at"],
                }
            )

        with connect() as conn:
            updated = conn.execute(
                "SELECT summary, tags, metadata_version FROM sources WHERE id = ?",
                (source["id"],),
            ).fetchone()
            refresh = conn.execute(
                """
                SELECT id FROM app_jobs
                WHERE job_type = 'refresh_cluster_profile' AND scope_id = 'cluster-a'
                LIMIT 1
                """
            ).fetchone()
        self.assertIn("source move", updated["summary"])
        self.assertIn("source organization", updated["tags"])
        self.assertEqual(updated["metadata_version"], 3)
        self.assertIsNotNone(refresh)

    def test_reconciliation_groups_related_analyzed_sources_after_model_recovery(self) -> None:
        from backend.app.api.routes.sources import create_source
        from backend.app.core.background_jobs import _run_source_cluster_reconciliation
        from backend.app.core.database import connect
        from backend.app.schemas import SourceCreate

        self.seed_clusters()
        sources = [
            create_source(
                SourceCreate(
                    vault_id="vault-1",
                    cluster_id="cluster-a",
                    title=title,
                    source_type="note",
                    raw_text=text,
                )
            )
            for title, text in (
                (
                    "Neural network training plan",
                    "Neural network training uses gradient descent, model evaluation, and validation data.",
                ),
                (
                    "Neural network evaluation notes",
                    "Neural network evaluation compares validation data, model accuracy, and training results.",
                ),
            )
        ]
        with connect() as conn:
            conn.executemany(
                """
                UPDATE sources
                SET cluster_id = NULL, metadata_version = 3, summary = ?, tags = ?, updated_at = updated_at
                WHERE id = ?
                """,
                [
                    (
                        "Neural network training, validation data, and model evaluation.",
                        '["neural networks","model training","validation data"]',
                        sources[0]["id"],
                    ),
                    (
                        "Neural network evaluation using validation data and training results.",
                        '["neural networks","model evaluation","validation data"]',
                        sources[1]["id"],
                    ),
                ],
            )

        _run_source_cluster_reconciliation({"vault_id": "vault-1"})

        with connect() as conn:
            memberships = conn.execute(
                "SELECT id, cluster_id FROM sources WHERE id IN (?, ?) ORDER BY id",
                (sources[0]["id"], sources[1]["id"]),
            ).fetchall()
            cluster = conn.execute(
                "SELECT name_origin FROM clusters WHERE id = ?",
                (memberships[0]["cluster_id"],),
            ).fetchone()
        self.assertIsNotNone(memberships[0]["cluster_id"])
        self.assertEqual(memberships[0]["cluster_id"], memberships[1]["cluster_id"])
        self.assertEqual(cluster["name_origin"], "auto")

    def test_startup_metadata_repair_is_bounded_and_deduplicated(self) -> None:
        from backend.app.core.background_jobs import enqueue_startup_metadata_jobs
        from backend.app.core.database import connect

        self.seed_clusters()
        source = self.create_clustered_source()
        enqueue_startup_metadata_jobs(limit=1)
        enqueue_startup_metadata_jobs(limit=1)

        with connect() as conn:
            jobs = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM app_jobs
                WHERE job_type = 'source_metadata_enrichment'
                  AND scope_id = ?
                """,
                (source["id"],),
            ).fetchone()
        self.assertEqual(jobs["count"], 1)

    def test_stale_metadata_job_queues_the_current_source_revision(self) -> None:
        from backend.app.core.background_jobs import _run_source_metadata_enrichment
        from backend.app.core.database import connect

        self.seed_clusters()
        source = self.create_clustered_source()
        with connect() as conn:
            conn.execute(
                "UPDATE sources SET updated_at = '2099-01-01T00:00:00+00:00' WHERE id = ?",
                (source["id"],),
            )

        _run_source_metadata_enrichment(
            {
                "source_id": source["id"],
                "source_updated_at": source["updated_at"],
            }
        )

        with connect() as conn:
            replacement = conn.execute(
                """
                SELECT payload FROM app_jobs
                WHERE job_type = 'source_metadata_enrichment'
                  AND scope_id = ?
                  AND dedupe_key LIKE '%2099-01-01T00:00:00+00:00'
                LIMIT 1
                """,
                (source["id"],),
            ).fetchone()
        self.assertIsNotNone(replacement)

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

    def test_dismissed_move_recomputes_only_after_source_evidence_changes(self) -> None:
        from backend.app.api.routes.clusters import decide_cluster_suggestion
        from backend.app.core.cluster_suggestions import suggest_source_cluster_moves
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import ClusterSuggestionDecision

        self.seed_clusters()
        source = self.create_clustered_source()
        with connect() as conn:
            conn.execute(
                "UPDATE sources SET checksum = 'stable-source-evidence' WHERE id = ?",
                (source["id"],),
            )
        decide_cluster_suggestion(
            ClusterSuggestionDecision(
                source_id=source["id"],
                suggested_cluster_id="cluster-b",
                action="dismissed",
            )
        )
        observed: list[int] = []

        def source_vectors(_conn, _vault_id, source_ids):
            observed.append(len(source_ids))
            return {}

        with connect() as conn, patch(
            "backend.app.core.cluster_suggestions._source_vectors",
            side_effect=source_vectors,
        ):
            suggest_source_cluster_moves(conn, "vault-1")
            conn.execute(
                "UPDATE sources SET metadata_version = metadata_version + 1, updated_at = ? WHERE id = ?",
                (utc_now(), source["id"]),
            )
            suggest_source_cluster_moves(conn, "vault-1")
            conn.execute(
                "UPDATE sources SET checksum = 'new-source-evidence', updated_at = ? WHERE id = ?",
                (utc_now(), source["id"]),
            )
            suggest_source_cluster_moves(conn, "vault-1")

        self.assertEqual(observed, [1])


if __name__ == "__main__":
    unittest.main()
