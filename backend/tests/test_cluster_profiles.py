import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class ClusterCandidateProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.sqlite3"
        os.environ["CML_DATABASE_PATH"] = str(self.db_path)
        os.environ["CML_DATA_DIR"] = self.tmp.name
        from backend.app.core.config import get_settings
        from backend.app.core.database import init_db

        get_settings.cache_clear()
        init_db()

    def tearDown(self) -> None:
        from backend.app.core.config import get_settings

        get_settings.cache_clear()
        os.environ.pop("CML_DATABASE_PATH", None)
        os.environ.pop("CML_DATA_DIR", None)
        self.tmp.cleanup()

    def test_candidate_lookup_is_bounded_and_not_recency_based(self) -> None:
        from backend.app.core.cluster_profiles import shortlist_cluster_candidates
        from backend.app.core.database import connect, utc_now

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", self.tmp.name, now, now),
            )
            for index in range(1000):
                cluster_id = f"cluster-{index:03d}"
                conn.execute(
                    """
                    INSERT INTO clusters (id, vault_id, name, name_origin, created_at, updated_at)
                    VALUES (?, 'vault-1', ?, 'auto', ?, ?)
                    """,
                    (cluster_id, f"Architecture {index}", now, now),
                )
                conn.execute(
                    """
                    INSERT INTO cluster_candidate_profiles (
                        cluster_id, vault_id, profile_version, source_hash, lexical_terms,
                        source_type_distribution, representative_source_ids, cohesion,
                        status, created_at, updated_at
                    )
                    VALUES (?, 'vault-1', 1, ?, '{"architecture":1}', '{}', '[]', 0.8, 'ready', ?, ?)
                    """,
                    (cluster_id, f"hash-{index}", now, now),
                )
                conn.execute(
                    """
                    INSERT INTO cluster_candidate_terms (cluster_id, vault_id, term, weight)
                    VALUES (?, 'vault-1', 'architecture', ?)
                    """,
                    (cluster_id, 2.0 if index == 0 else 1.0),
                )

            candidates = shortlist_cluster_candidates(
                conn,
                vault_id="vault-1",
                text="Explain the architecture",
            )

        self.assertEqual(len(candidates), 32)
        self.assertEqual(candidates[0]["cluster_id"], "cluster-000")

    def test_suggestion_review_bounds_source_work_in_a_ten_thousand_source_vault(self) -> None:
        from unittest.mock import patch

        from backend.app.core.cluster_suggestions import (
            MAX_SOURCES_PER_REVIEW,
            suggest_source_cluster_moves,
        )
        from backend.app.core.database import connect, utc_now

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-scale", "Scale", self.tmp.name, now, now),
            )
            conn.executemany(
                """
                INSERT INTO sources (
                    id, vault_id, title, source_type, state, checksum,
                    summary, tags, created_at, updated_at
                )
                VALUES (?, 'vault-scale', ?, 'note', 'indexed', ?, '', '[]', ?, ?)
                """,
                [
                    (
                        f"source-{index:05d}",
                        f"Source {index}",
                        f"hash-{index}",
                        now,
                        f"2026-01-{1 + index % 28:02d}T00:00:00+00:00",
                    )
                    for index in range(10_000)
                ],
            )
            observed: list[int] = []

            def source_vectors(_conn, _vault_id, source_ids):
                observed.append(len(source_ids))
                return {}

            with patch(
                "backend.app.core.cluster_suggestions._source_vectors",
                side_effect=source_vectors,
            ):
                suggestions = suggest_source_cluster_moves(conn, "vault-scale")

        self.assertEqual(suggestions, [])
        self.assertEqual(observed, [MAX_SOURCES_PER_REVIEW])

    def test_project_clusters_are_not_general_candidates(self) -> None:
        from backend.app.core.cluster_profiles import shortlist_cluster_candidates
        from backend.app.core.database import connect, utc_now

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-1", "Vault", self.tmp.name, now, now),
            )
            conn.execute(
                """
                INSERT INTO clusters (id, vault_id, name, name_origin, created_at, updated_at)
                VALUES ('cluster-project', 'vault-1', 'Project', 'auto', ?, ?)
                """,
                (now, now),
            )
            conn.execute(
                """
                INSERT INTO projects (
                    id, vault_id, name, root_path, root_fingerprint, primary_cluster_id,
                    created_at, updated_at
                )
                VALUES ('project-1', 'vault-1', 'Project', ?, 'fingerprint', 'cluster-project', ?, ?)
                """,
                (self.tmp.name, now, now),
            )
            conn.execute(
                """
                INSERT INTO project_cluster_links (project_id, cluster_id, role, created_at)
                VALUES ('project-1', 'cluster-project', 'primary', ?)
                """,
                (now,),
            )
            conn.execute(
                """
                INSERT INTO cluster_candidate_profiles (
                    cluster_id, vault_id, profile_version, source_hash, lexical_terms,
                    source_type_distribution, representative_source_ids, cohesion,
                    status, created_at, updated_at
                )
                VALUES (
                    'cluster-project', 'vault-1', 1, 'hash', '{"architecture":1}',
                    '{}', '[]', 0.8, 'ready', ?, ?
                )
                """,
                (now, now),
            )
            conn.execute(
                """
                INSERT INTO cluster_candidate_terms (cluster_id, vault_id, term, weight)
                VALUES ('cluster-project', 'vault-1', 'architecture', 1)
                """
            )

            candidates = shortlist_cluster_candidates(
                conn,
                vault_id="vault-1",
                text="Project architecture",
            )

        self.assertEqual(candidates, [])

    def test_profile_backfill_uses_durable_pause_resume_controls(self) -> None:
        from backend.app.api.routes.jobs import backfill_cluster_profiles
        from backend.app.core.background_jobs import pause_job, resume_job
        from backend.app.core.database import connect, utc_now

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-backfill", "Backfill", self.tmp.name, now, now),
            )

        job = backfill_cluster_profiles("vault-backfill")
        paused = pause_job(job["id"])
        resumed = resume_job(job["id"])

        self.assertEqual(job["job_type"], "cluster_profile_backfill")
        self.assertEqual(job["preemptable"], 1)
        self.assertEqual(paused["status"], "paused")
        self.assertEqual(resumed["status"], "queued")

    def test_profile_backfill_queues_unclustered_source_reconciliation(self) -> None:
        from backend.app.api.routes.jobs import backfill_cluster_profiles
        from backend.app.core.database import connect, utc_now

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-organize", "Organize", self.tmp.name, now, now),
            )

        profile_job = backfill_cluster_profiles("vault-organize")

        with connect() as conn:
            reconciliation = conn.execute(
                """
                SELECT job_type, status, depends_on_job_id, scope_id
                FROM app_jobs
                WHERE job_type = 'source_cluster_reconciliation'
                  AND scope_id = ?
                """,
                ("vault-organize",),
            ).fetchone()

        self.assertIsNotNone(reconciliation)
        self.assertEqual(reconciliation["status"], "blocked_by_dependency")
        self.assertEqual(reconciliation["depends_on_job_id"], profile_job["id"])

    def test_profile_backfill_prunes_abandoned_automatic_clusters(self) -> None:
        from backend.app.api.routes.jobs import backfill_cluster_profiles
        from backend.app.core.background_jobs import _run_cluster_profile_backfill
        from backend.app.core.database import connect, utc_now

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-cleanup", "Cleanup", self.tmp.name, now, now),
            )
            conn.execute(
                """
                INSERT INTO clusters (
                    id, vault_id, name, name_origin, created_at, updated_at
                )
                VALUES ('cluster-empty', 'vault-cleanup', 'Old suggestion', 'auto', ?, ?)
                """,
                (now, now),
            )
        job = backfill_cluster_profiles("vault-cleanup")
        with connect() as conn:
            conn.execute(
                "UPDATE app_jobs SET status = 'running' WHERE id = ?",
                (job["id"],),
            )

        _run_cluster_profile_backfill({"vault_id": "vault-cleanup"}, job["id"])

        with connect() as conn:
            cluster = conn.execute(
                "SELECT id FROM clusters WHERE id = 'cluster-empty'"
            ).fetchone()
        self.assertIsNone(cluster)

    def test_profile_backfill_skips_transcript_only_cluster(self) -> None:
        from backend.app.api.routes.jobs import backfill_cluster_profiles
        from backend.app.core.background_jobs import _run_cluster_profile_backfill
        from backend.app.core.database import connect, utc_now

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-chat", "Chat only", self.tmp.name, now, now),
            )
            conn.execute(
                """
                INSERT INTO clusters (
                    id, vault_id, name, name_origin, profile_status, created_at, updated_at
                )
                VALUES ('cluster-chat', 'vault-chat', 'Chats', 'user', 'missing', ?, ?)
                """,
                (now, now),
            )
            conn.execute(
                """
                INSERT INTO sources (
                    id, vault_id, cluster_id, title, source_type, state, provenance, trust_tier,
                    security_labels, parser_security_json, raw_text, extracted_text, summary, tags,
                    created_at, updated_at
                )
                VALUES (
                    'source-chat', 'vault-chat', 'cluster-chat', 'Conversation', 'chat_transcript',
                    'indexed', 'chat_transcript', 'trusted_local', '[]', '{}', 'hello', 'hello',
                    'Conversation transcript', '[]', ?, ?
                )
                """,
                (now, now),
            )
        job = backfill_cluster_profiles("vault-chat")
        with connect() as conn:
            conn.execute("UPDATE app_jobs SET status = 'running' WHERE id = ?", (job["id"],))

        _run_cluster_profile_backfill({"vault_id": "vault-chat"}, job["id"])

        with connect() as conn:
            result = conn.execute(
                "SELECT result_json, status_detail FROM app_jobs WHERE id = ?",
                (job["id"],),
            ).fetchone()
        payload = json.loads(result["result_json"])
        self.assertEqual(payload["processed"], 0)
        self.assertEqual(payload["failures"], [])
        self.assertEqual(result["status_detail"], "Refreshed 0 unique clusters.")

    def test_profile_backfill_stops_when_refresh_makes_no_progress(self) -> None:
        from backend.app.api.routes.jobs import backfill_cluster_profiles
        from backend.app.core.background_jobs import _run_cluster_profile_backfill
        from backend.app.core.database import connect, utc_now

        now = utc_now()
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("vault-stalled", "Stalled", self.tmp.name, now, now),
            )
            conn.execute(
                """
                INSERT INTO clusters (
                    id, vault_id, name, name_origin, profile_status, created_at, updated_at
                )
                VALUES ('cluster-stalled', 'vault-stalled', 'Documents', 'user', 'missing', ?, ?)
                """,
                (now, now),
            )
            conn.execute(
                """
                INSERT INTO sources (
                    id, vault_id, cluster_id, title, source_type, state, provenance, trust_tier,
                    security_labels, parser_security_json, raw_text, extracted_text, summary, tags,
                    created_at, updated_at
                )
                VALUES (
                    'source-stalled', 'vault-stalled', 'cluster-stalled', 'Document', 'note',
                    'indexed', 'local_import', 'trusted_local', '[]', '{}', 'text', 'text',
                    'Document text', '[]', ?, ?
                )
                """,
                (now, now),
            )
        job = backfill_cluster_profiles("vault-stalled")
        with connect() as conn:
            conn.execute("UPDATE app_jobs SET status = 'running' WHERE id = ?", (job["id"],))

        with patch("backend.app.core.background_jobs.refresh_cluster_profile") as refresh:
            _run_cluster_profile_backfill({"vault_id": "vault-stalled"}, job["id"])

        with connect() as conn:
            result = conn.execute(
                "SELECT result_json, status_detail FROM app_jobs WHERE id = ?",
                (job["id"],),
            ).fetchone()
        payload = json.loads(result["result_json"])
        refresh.assert_called_once()
        self.assertEqual(payload["processed"], 1)
        self.assertEqual(payload["failures"][0]["reason"], "profile_remained_eligible")
        self.assertIn("1 unique clusters", result["status_detail"])


if __name__ == "__main__":
    unittest.main()
