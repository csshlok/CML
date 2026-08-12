import os
import re
import json
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
        from backend.app.core.database import connect
        from backend.app.core.embeddings import reindex_source_chunks
        from backend.app.schemas import SourceCreate

        source = create_source(
            SourceCreate(
                vault_id="vault-1",
                cluster_id="cluster-a",
                title="Move me",
                source_type="note",
                raw_text="A source that should move without changing its saved content.",
            )
        )
        with connect() as conn:
            reindex_source_chunks(conn, source)
        return source

    def test_cluster_counts_are_exact_beyond_list_page_sizes(self) -> None:
        from backend.app.api.routes.clusters import get_cluster_counts
        from backend.app.core.database import connect, utc_now

        self.seed_clusters()
        now = utc_now()
        with connect() as conn:
            conn.executemany(
                """
                INSERT INTO sources (
                    id, vault_id, cluster_id, title, source_type, state, created_at, updated_at
                ) VALUES (?, 'vault-1', 'cluster-a', ?, 'note', ?, ?, ?)
                """,
                (
                    (f"source-{index}", f"Source {index}", "indexed" if index < 1001 else "waiting", now, now)
                    for index in range(1005)
                ),
            )
            conn.executemany(
                """
                INSERT INTO chat_sessions (id, vault_id, title, scope_cluster_id, created_at, updated_at)
                VALUES (?, 'vault-1', ?, 'cluster-a', ?, ?)
                """,
                ((f"chat-{index}", f"Chat {index}", now, now) for index in range(101)),
            )

        counts = get_cluster_counts("cluster-a")

        self.assertEqual(counts["source_count"], 1005)
        self.assertEqual(counts["indexed_source_count"], 1001)
        self.assertEqual(counts["chat_count"], 101)

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
            chunk_memberships = {
                row["cluster_id"]
                for row in conn.execute(
                    "SELECT cluster_id FROM source_chunks WHERE source_id = ? AND activation_state = 'active'",
                    (source["id"],),
                ).fetchall()
            }
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
        self.assertEqual(chunk_memberships, {"cluster-b"})
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

    def test_reconciliation_does_not_reassign_an_already_clustered_source(self) -> None:
        from backend.app.core.background_jobs import _run_source_cluster_reconciliation
        from backend.app.core.database import connect

        self.seed_clusters()
        source = self.create_clustered_source()
        with connect() as conn:
            conn.execute(
                "UPDATE sources SET metadata_version = 3 WHERE id = ?",
                (source["id"],),
            )

        _run_source_cluster_reconciliation(
            {"vault_id": "vault-1", "source_id": source["id"]}
        )

        with connect() as conn:
            membership = conn.execute(
                "SELECT cluster_id FROM sources WHERE id = ?",
                (source["id"],),
            ).fetchone()

        self.assertEqual(membership["cluster_id"], "cluster-a")

    def test_chat_only_cluster_does_not_block_first_document_cluster(self) -> None:
        from backend.app.api.routes.sources import create_source
        from backend.app.core.background_jobs import _run_source_cluster_reconciliation
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import SourceCreate

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-chat-first", "Chat first", self.tmp.name, now, now),
            )
            conn.execute(
                """
                INSERT INTO clusters (id, vault_id, name, name_origin, created_at, updated_at)
                VALUES (?, ?, ?, 'user', ?, ?)
                """,
                ("cluster-chats", "vault-chat-first", "Chats", now, now),
            )

        create_source(
            SourceCreate(
                vault_id="vault-chat-first",
                cluster_id="cluster-chats",
                title="Existing chat",
                source_type="chat_transcript",
                raw_text="A saved conversation.",
            )
        )
        document = create_source(
            SourceCreate(
                vault_id="vault-chat-first",
                title="Architecture notes",
                source_type="note",
                raw_text="Architecture boundaries, services, and deployment notes.",
            )
        )
        with connect() as conn:
            conn.execute(
                "UPDATE sources SET metadata_version = 3 WHERE id = ?",
                (document["id"],),
            )

        _run_source_cluster_reconciliation(
            {"vault_id": "vault-chat-first", "source_id": document["id"]}
        )

        with connect() as conn:
            moved = conn.execute(
                "SELECT cluster_id FROM sources WHERE id = ?",
                (document["id"],),
            ).fetchone()
            created_cluster = conn.execute(
                "SELECT name_origin FROM clusters WHERE id = ?",
                (moved["cluster_id"],),
            ).fetchone()

        self.assertIsNotNone(moved["cluster_id"])
        self.assertNotEqual(moved["cluster_id"], "cluster-chats")
        self.assertEqual(created_cluster["name_origin"], "auto")

    def test_first_auto_cluster_immediately_accepts_related_batch_documents(self) -> None:
        from backend.app.api.routes.sources import create_source
        from backend.app.core.background_jobs import _run_source_cluster_reconciliation
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import SourceCreate

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-batch", "Batch", self.tmp.name, now, now),
            )

        sources = [
            create_source(
                SourceCreate(
                    vault_id="vault-batch",
                    title=f"Quarterly revenue forecast {index}",
                    source_type="note",
                    raw_text=(
                        "Quarterly revenue forecast, customer pipeline, renewal targets, "
                        "and account growth planning."
                    ),
                )
            )
            for index in range(2)
        ]
        with connect() as conn:
            conn.executemany(
                "UPDATE sources SET metadata_version = 3 WHERE id = ?",
                [(source["id"],) for source in sources],
            )

        _run_source_cluster_reconciliation(
            {"vault_id": "vault-batch", "source_id": sources[0]["id"]}
        )
        _run_source_cluster_reconciliation(
            {"vault_id": "vault-batch", "source_id": sources[1]["id"]}
        )

        with connect() as conn:
            memberships = conn.execute(
                "SELECT id, cluster_id FROM sources WHERE id IN (?, ?) ORDER BY id",
                (sources[0]["id"], sources[1]["id"]),
            ).fetchall()
            candidate_profiles = conn.execute(
                "SELECT COUNT(*) AS total FROM cluster_candidate_profiles"
            ).fetchone()
        self.assertTrue(all(row["cluster_id"] for row in memberships))
        self.assertEqual(len({row["cluster_id"] for row in memberships}), 1)
        self.assertEqual(candidate_profiles["total"], 1)

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
            chunk_memberships = {
                row["cluster_id"]
                for row in conn.execute(
                    "SELECT cluster_id FROM source_chunks WHERE source_id = ? AND activation_state = 'active'",
                    (source["id"],),
                ).fetchall()
            }

        self.assertEqual(result["action"], "accepted")
        self.assertEqual(membership["cluster_id"], "cluster-b")
        self.assertEqual(decision["action"], "accepted")
        self.assertEqual(decision["suggested_cluster_id"], "cluster-b")
        self.assertEqual(decision["source_updated_at"], membership["updated_at"])
        self.assertEqual(chunk_memberships, {"cluster-b"})

    def test_cluster_merge_and_rollback_keep_chunks_aligned(self) -> None:
        from backend.app.api.routes.clusters import (
            merge_cluster,
            rollback_cluster_merge_artifact,
        )
        from backend.app.core.database import connect
        from backend.app.schemas import ClusterMergeRequest

        self.seed_clusters()
        source = self.create_clustered_source()

        merge_cluster("cluster-a", ClusterMergeRequest(target_cluster_id="cluster-b"))

        with connect() as conn:
            artifact = conn.execute(
                "SELECT id FROM cluster_merge_artifacts ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            moved_source = conn.execute(
                "SELECT cluster_id FROM sources WHERE id = ?",
                (source["id"],),
            ).fetchone()
            moved_chunks = {
                row["cluster_id"]
                for row in conn.execute(
                    "SELECT cluster_id FROM source_chunks WHERE source_id = ? AND activation_state = 'active'",
                    (source["id"],),
                ).fetchall()
            }
        self.assertEqual(moved_source["cluster_id"], "cluster-b")
        self.assertEqual(moved_chunks, {"cluster-b"})

        rollback_cluster_merge_artifact(str(artifact["id"]))

        with connect() as conn:
            restored_source = conn.execute(
                "SELECT cluster_id FROM sources WHERE id = ?",
                (source["id"],),
            ).fetchone()
            restored_chunks = {
                row["cluster_id"]
                for row in conn.execute(
                    "SELECT cluster_id FROM source_chunks WHERE source_id = ? AND activation_state = 'active'",
                    (source["id"],),
                ).fetchall()
            }
        self.assertEqual(restored_source["cluster_id"], "cluster-a")
        self.assertEqual(restored_chunks, {"cluster-a"})

    def test_cluster_merge_resumes_after_a_committed_batch(self) -> None:
        import backend.app.api.routes.clusters as clusters_route
        from backend.app.core.database import connect
        from backend.app.schemas import ClusterMergeRequest

        self.seed_clusters()
        sources = [self.create_clustered_source() for _ in range(3)]
        original_move = clusters_route.move_source_cluster_membership
        calls = 0

        def interrupt_third(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise RuntimeError("injected merge interruption")
            return original_move(*args, **kwargs)

        with patch.object(clusters_route, "CLUSTER_MERGE_BATCH_SIZE", 2), patch.object(
            clusters_route, "move_source_cluster_membership", side_effect=interrupt_third
        ):
            with self.assertRaisesRegex(RuntimeError, "injected merge interruption"):
                clusters_route.merge_cluster(
                    "cluster-a", ClusterMergeRequest(target_cluster_id="cluster-b")
                )

        with connect() as conn:
            interrupted = conn.execute(
                "SELECT source_cursor, status FROM cluster_merge_artifacts"
            ).fetchone()
        self.assertEqual(interrupted["source_cursor"], 2)
        self.assertEqual(interrupted["status"], "running")

        with patch.object(clusters_route, "CLUSTER_MERGE_BATCH_SIZE", 2):
            clusters_route.merge_cluster(
                "cluster-a", ClusterMergeRequest(target_cluster_id="cluster-b")
            )
        with connect() as conn:
            artifact = conn.execute("SELECT * FROM cluster_merge_artifacts").fetchone()
            memberships = conn.execute(
                "SELECT id, cluster_id FROM sources WHERE id IN (?, ?, ?)",
                tuple(source["id"] for source in sources),
            ).fetchall()
        self.assertEqual(artifact["status"], "completed")
        self.assertEqual(artifact["source_cursor"], 3)
        self.assertEqual(len(set(json.loads(artifact["moved_source_ids"]))), 3)
        self.assertEqual({row["cluster_id"] for row in memberships}, {"cluster-b"})

    def test_cluster_merge_rollback_does_not_overwrite_a_later_user_move(self) -> None:
        from backend.app.api.routes.clusters import merge_cluster, rollback_cluster_merge_artifact
        from backend.app.core.database import connect, utc_now
        from backend.app.schemas import ClusterMergeRequest

        self.seed_clusters()
        source = self.create_clustered_source()
        merge_cluster("cluster-a", ClusterMergeRequest(target_cluster_id="cluster-b"))
        with connect() as conn:
            now = utc_now()
            conn.execute(
                "INSERT INTO clusters (id, vault_id, name, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("cluster-c", "vault-1", "Gamma", now, now),
            )
            conn.execute("UPDATE sources SET cluster_id = 'cluster-c' WHERE id = ?", (source["id"],))
            conn.execute("UPDATE source_chunks SET cluster_id = 'cluster-c' WHERE source_id = ?", (source["id"],))
            artifact_id = conn.execute("SELECT id FROM cluster_merge_artifacts").fetchone()["id"]

        rollback_cluster_merge_artifact(str(artifact_id))
        with connect() as conn:
            membership = conn.execute(
                "SELECT cluster_id FROM sources WHERE id = ?", (source["id"],)
            ).fetchone()
            artifact = conn.execute(
                "SELECT reversible, conflict_count FROM cluster_merge_artifacts WHERE id = ?",
                (artifact_id,),
            ).fetchone()
        self.assertEqual(membership["cluster_id"], "cluster-c")
        self.assertEqual(artifact["reversible"], 0)
        self.assertGreaterEqual(artifact["conflict_count"], 1)

    def test_deleting_cluster_unclusters_sources_and_chunks_together(self) -> None:
        from backend.app.api.routes.clusters import delete_cluster
        from backend.app.core.database import connect

        self.seed_clusters()
        source = self.create_clustered_source()

        delete_cluster("cluster-a")

        with connect() as conn:
            membership = conn.execute(
                "SELECT cluster_id FROM sources WHERE id = ?",
                (source["id"],),
            ).fetchone()
            chunk_memberships = {
                row["cluster_id"]
                for row in conn.execute(
                    "SELECT cluster_id FROM source_chunks WHERE source_id = ? AND activation_state = 'active'",
                    (source["id"],),
                ).fetchall()
            }
        self.assertIsNone(membership["cluster_id"])
        self.assertEqual(chunk_memberships, {None})

    def test_membership_move_rolls_back_source_and_chunks_on_derived_state_failure(self) -> None:
        from backend.app.api.routes.sources import update_source
        from backend.app.core.database import connect
        from backend.app.schemas import SourceUpdate

        self.seed_clusters()
        source = self.create_clustered_source()
        with connect() as conn:
            initial_event_count = conn.execute(
                "SELECT COUNT(*) AS total FROM cluster_membership_events WHERE source_id = ?",
                (source["id"],),
            ).fetchone()["total"]

        with patch(
            "backend.app.core.cluster_membership.rebuild_source_memory",
            side_effect=RuntimeError("derived state failed"),
        ):
            with self.assertRaises(RuntimeError):
                update_source(source["id"], SourceUpdate(cluster_id="cluster-b"))

        with connect() as conn:
            membership = conn.execute(
                "SELECT cluster_id FROM sources WHERE id = ?",
                (source["id"],),
            ).fetchone()
            chunk_memberships = {
                row["cluster_id"]
                for row in conn.execute(
                    "SELECT cluster_id FROM source_chunks WHERE source_id = ? AND activation_state = 'active'",
                    (source["id"],),
                ).fetchall()
            }
            event_count = conn.execute(
                "SELECT COUNT(*) AS total FROM cluster_membership_events WHERE source_id = ?",
                (source["id"],),
            ).fetchone()
        self.assertEqual(membership["cluster_id"], "cluster-a")
        self.assertEqual(chunk_memberships, {"cluster-a"})
        self.assertEqual(event_count["total"], initial_event_count)

    def test_membership_repair_is_bounded_and_idempotent(self) -> None:
        from backend.app.core.cluster_membership import repair_cluster_membership_batch
        from backend.app.core.database import connect

        self.seed_clusters()
        source = self.create_clustered_source()
        with connect() as conn:
            conn.execute(
                "UPDATE source_chunks SET cluster_id = NULL WHERE source_id = ?",
                (source["id"],),
            )
            repaired = repair_cluster_membership_batch(
                conn,
                vault_id="vault-1",
                limit=1,
            )
        with connect() as conn:
            repeated = repair_cluster_membership_batch(
                conn,
                vault_id="vault-1",
                limit=1,
            )
            chunk_memberships = {
                row["cluster_id"]
                for row in conn.execute(
                    "SELECT cluster_id FROM source_chunks WHERE source_id = ? AND activation_state = 'active'",
                    (source["id"],),
                ).fetchall()
            }
        self.assertEqual(repaired["sources_repaired"], 1)
        self.assertGreater(repaired["chunks_repaired"], 0)
        self.assertEqual(repeated["sources_repaired"], 0)
        self.assertEqual(repeated["chunks_repaired"], 0)
        self.assertEqual(chunk_memberships, {"cluster-a"})

    def test_scoped_preflight_repairs_small_membership_mismatch(self) -> None:
        from backend.app.core.cluster_membership import preflight_scoped_cluster_membership
        from backend.app.core.database import connect

        self.seed_clusters()
        source = self.create_clustered_source()
        with connect() as conn:
            conn.execute(
                "UPDATE source_chunks SET cluster_id = NULL WHERE source_id = ?",
                (source["id"],),
            )
            result = preflight_scoped_cluster_membership(
                conn,
                vault_id="vault-1",
                cluster_id="cluster-a",
            )
            remaining = conn.execute(
                """
                SELECT COUNT(*) AS total
                FROM source_chunks
                WHERE source_id = ? AND activation_state = 'active'
                  AND NOT (cluster_id IS 'cluster-a')
                """,
                (source["id"],),
            ).fetchone()
        self.assertEqual(result["mismatched_source_count"], 1)
        self.assertEqual(result["sources_repaired"], 1)
        self.assertFalse(result["repair_pending"])
        self.assertEqual(remaining["total"], 0)

    def test_chat_transcripts_do_not_feed_cluster_profile_generation(self) -> None:
        from backend.app.api.routes.sources import create_source
        from backend.app.core.cluster_lifecycle import refresh_cluster_profile
        from backend.app.core.database import connect
        from backend.app.schemas import SourceCreate

        self.seed_clusters()
        self.create_clustered_source()
        create_source(
            SourceCreate(
                vault_id="vault-1",
                cluster_id="cluster-a",
                title="Generated conversation",
                source_type="chat_transcript",
                raw_text="Assistant generated text that must not name the document cluster.",
            )
        )
        observed_types: list[str] = []

        def enrich(sources, **_kwargs):
            observed_types.extend(str(source["source_type"]) for source in sources)
            return {
                "name": "Alpha documents",
                "description": "Documents in Alpha.",
                "summary": "Documents in Alpha.",
                "glossary": [],
            }

        with connect() as conn, patch(
            "backend.app.core.cluster_lifecycle.enrich_cluster_metadata",
            side_effect=enrich,
        ):
            refresh_cluster_profile(conn, "cluster-a")
        self.assertEqual(observed_types, ["note"])

    def test_runtime_cluster_membership_writes_are_centralized(self) -> None:
        root = Path(__file__).resolve().parents[1] / "app"
        pattern = re.compile(
            r"UPDATE\s+sources\s+SET[\s\S]{0,180}?cluster_id\s*=",
            re.IGNORECASE,
        )
        unauthorized: list[str] = []
        for path in root.rglob("*.py"):
            if path.name in {"cluster_membership.py", "database.py", "migrations.py"}:
                continue
            if pattern.search(path.read_text(encoding="utf-8")):
                unauthorized.append(str(path.relative_to(root)))
        self.assertEqual(unauthorized, [])

    def test_startup_reconciliation_queues_membership_repair_for_mismatched_vault(self) -> None:
        from backend.app.core.background_jobs import enqueue_startup_reconciliation_jobs
        from backend.app.core.database import connect

        self.seed_clusters()
        source = self.create_clustered_source()
        with connect() as conn:
            conn.execute(
                "UPDATE source_chunks SET cluster_id = NULL WHERE source_id = ?",
                (source["id"],),
            )

        enqueue_startup_reconciliation_jobs()

        with connect() as conn:
            job = conn.execute(
                """
                SELECT job_type, scope_id, payload
                FROM app_jobs
                WHERE job_type = 'cluster_membership_repair' AND scope_id = 'vault-1'
                """
            ).fetchone()
        self.assertIsNotNone(job)
        self.assertIn('"vault_id":"vault-1"', job["payload"])

    def test_membership_repair_job_persists_result_and_finishes_consistent(self) -> None:
        from backend.app.core.background_jobs import (
            _run_cluster_membership_repair,
            enqueue_job,
        )
        from backend.app.core.cluster_membership import summarize_cluster_membership
        from backend.app.core.database import connect

        self.seed_clusters()
        source = self.create_clustered_source()
        with connect() as conn:
            conn.execute(
                "UPDATE source_chunks SET cluster_id = NULL WHERE source_id = ?",
                (source["id"],),
            )
            job = enqueue_job(
                conn,
                job_type="cluster_membership_repair",
                payload={"vault_id": "vault-1", "batch_size": 1, "user_initiated": True},
                scope_id="vault-1",
                user_initiated=True,
            )

        _run_cluster_membership_repair(
            {"vault_id": "vault-1", "batch_size": 1, "user_initiated": True},
            job["id"],
        )

        with connect() as conn:
            repaired_job = conn.execute(
                "SELECT result_json, status_detail FROM app_jobs WHERE id = ?",
                (job["id"],),
            ).fetchone()
            audit = summarize_cluster_membership(conn, vault_id="vault-1")
        self.assertIn('"chunks_repaired":', repaired_job["result_json"])
        self.assertIn("repaired", repaired_job["status_detail"].casefold())
        self.assertTrue(audit["consistent"])

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
            semantic = conn.execute(
                """
                SELECT id FROM app_jobs
                WHERE job_type = 'source_semantic_enrichment' AND scope_id = ?
                LIMIT 1
                """,
                (source["id"],),
            ).fetchone()
        self.assertIn("source move", updated["summary"])
        self.assertIn("source organization", updated["tags"])
        self.assertEqual(updated["metadata_version"], 3)
        self.assertIsNotNone(refresh)
        self.assertIsNotNone(semantic)

    def test_semantic_source_metadata_improves_fallback_without_changing_content(self) -> None:
        from backend.app.core.background_jobs import _run_source_semantic_enrichment
        from backend.app.core.database import connect

        self.seed_clusters()
        source = self.create_clustered_source()
        with connect() as conn:
            before = conn.execute(
                "SELECT raw_text, extracted_text FROM sources WHERE id = ?",
                (source["id"],),
            ).fetchone()
        with patch(
            "backend.app.core.background_jobs.enrich_source_metadata",
            return_value={
                "summary": "Explains transactional source movement and retained retrieval context.",
                "keywords": ["cluster movement", "retrieval context"],
            },
        ):
            _run_source_semantic_enrichment({"source_id": source["id"]})

        with connect() as conn:
            updated = conn.execute(
                """
                SELECT raw_text, extracted_text, summary, tags, metadata_quality,
                       semantic_metadata_version, semantic_metadata_updated_at
                FROM sources WHERE id = ?
                """,
                (source["id"],),
            ).fetchone()
        self.assertEqual(updated["raw_text"], before["raw_text"])
        self.assertEqual(updated["extracted_text"], before["extracted_text"])
        self.assertIn("transactional source movement", updated["summary"])
        self.assertIn("cluster movement", updated["tags"])
        self.assertEqual(updated["metadata_quality"], "semantic")
        self.assertEqual(updated["semantic_metadata_version"], 1)
        self.assertIsNotNone(updated["semantic_metadata_updated_at"])

    def test_semantic_enrichment_wave_coalesces_cluster_profile_refresh_at_scale(self) -> None:
        from backend.app.core.background_jobs import (
            _finalize_source_semantic_wave,
            enqueue_job,
        )
        from backend.app.core.database import connect, utc_now

        self.seed_clusters()
        now = utc_now()
        source_count = 128
        with connect() as conn:
            conn.execute(
                "UPDATE clusters SET profile_status = 'stale' WHERE id = 'cluster-a'"
            )
            conn.executemany(
                """
                INSERT INTO sources (
                    id, vault_id, cluster_id, title, source_type, state,
                    provenance, trust_tier, security_labels, parser_security_json,
                    raw_text, extracted_text, summary, tags, created_at, updated_at
                )
                VALUES (?, 'vault-1', 'cluster-a', ?, 'note', 'indexed',
                        'local_import', 'trusted_local', '[]', '{}',
                        ?, ?, '', '[]', ?, ?)
                """,
                [
                    (
                        f"source-wave-{index}",
                        f"Wave source {index}",
                        f"Semantic content {index}",
                        f"Semantic content {index}",
                        now,
                        now,
                    )
                    for index in range(source_count)
                ],
            )
            jobs = [
                enqueue_job(
                    conn,
                    job_type="source_semantic_enrichment",
                    payload={"source_id": f"source-wave-{index}"},
                    dedupe_key=f"semantic-wave:{index}",
                    scope_id=f"source-wave-{index}",
                )
                for index in range(source_count)
            ]

        self.assertFalse(
            _finalize_source_semantic_wave({"source_id": "source-wave-0"})
        )
        with connect() as conn:
            conn.execute(
                "UPDATE app_jobs SET status = 'succeeded' WHERE job_type = 'source_semantic_enrichment'"
            )
        self.assertTrue(
            _finalize_source_semantic_wave(
                {"source_id": f"source-wave-{source_count - 1}"}
            )
        )
        for index in range(source_count):
            _finalize_source_semantic_wave({"source_id": f"source-wave-{index}"})

        with connect() as conn:
            refresh_count = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM app_jobs
                WHERE job_type = 'refresh_cluster_profile'
                  AND scope_id = 'cluster-a'
                  AND status = 'queued'
                """
            ).fetchone()["count"]
            semantic_count = conn.execute(
                "SELECT COUNT(*) AS count FROM app_jobs WHERE job_type = 'source_semantic_enrichment'"
            ).fetchone()["count"]
        self.assertEqual(semantic_count, len(jobs))
        self.assertEqual(refresh_count, 1)

    def test_semantic_job_refreshes_cluster_after_its_wave_finishes(self) -> None:
        from backend.app.core.background_jobs import _run_claimed_job, enqueue_job
        from backend.app.core.database import connect, dict_from_row, utc_now

        self.seed_clusters()
        source = self.create_clustered_source()
        with connect() as conn:
            conn.execute("DELETE FROM app_jobs")
            job = enqueue_job(
                conn,
                job_type="source_semantic_enrichment",
                payload={"source_id": source["id"]},
                dedupe_key=f"semantic-wave:{source['id']}",
                scope_id=source["id"],
            )
            conn.execute(
                """
                UPDATE app_jobs
                SET status = 'running', attempts = 1, started_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (utc_now(), utc_now(), job["id"]),
            )
            claimed = dict_from_row(
                conn.execute("SELECT * FROM app_jobs WHERE id = ?", (job["id"],)).fetchone()
            )

        with patch(
            "backend.app.core.background_jobs.enrich_source_metadata",
            return_value={
                "summary": "A semantic description produced once for this source.",
                "keywords": ["semantic", "coalesced"],
            },
        ):
            _run_claimed_job(claimed)

        with connect() as conn:
            completed = conn.execute(
                "SELECT status FROM app_jobs WHERE id = ?", (job["id"],)
            ).fetchone()
            refreshes = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM app_jobs
                WHERE job_type = 'refresh_cluster_profile'
                  AND scope_id = 'cluster-a'
                  AND status = 'queued'
                """
            ).fetchone()["count"]
            cluster = conn.execute(
                "SELECT profile_status FROM clusters WHERE id = 'cluster-a'"
            ).fetchone()
        self.assertEqual(completed["status"], "succeeded")
        self.assertEqual(cluster["profile_status"], "stale")
        self.assertEqual(refreshes, 1)

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
