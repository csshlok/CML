import os
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


def _register_project(**kwargs):
    from backend.app.core.background_jobs import run_due_jobs_once
    from backend.app.core.projects import get_project, register_project

    project = register_project(**kwargs)
    if kwargs.get("sync", True):
        run_due_jobs_once(limit=20)
        project = get_project(project["id"])
    return project


class OdinProjectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.tmp.name)
        self.data_dir = self.root / "data"
        self.repo = self.root / "sample-project"
        (self.repo / "src").mkdir(parents=True)
        (self.repo / "node_modules" / "ignored").mkdir(parents=True)
        (self.repo / "src" / "main.ts").write_text(
            "import { authorize } from './auth';\nexport const start = () => authorize();\n",
            encoding="utf-8",
        )
        (self.repo / "src" / "auth.ts").write_text("export function authorize() { return true; }\n", encoding="utf-8")
        (self.repo / "package.json").write_text('{"name":"sample"}', encoding="utf-8")
        (self.repo / ".env").write_text("SECRET=must-not-be-indexed", encoding="utf-8")
        (self.repo / "node_modules" / "ignored" / "index.js").write_text("ignored", encoding="utf-8")
        os.environ["CML_DATABASE_PATH"] = str(self.data_dir / "test.sqlite3")
        os.environ["CML_DATA_DIR"] = str(self.data_dir)
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
                ("vault-odin", "Odin Test", str(self.data_dir), now, now),
            )

    def tearDown(self) -> None:
        from backend.app.core.config import get_settings

        get_settings.cache_clear()
        for key in ("CML_DATABASE_PATH", "CML_DATA_DIR", "CML_EMBEDDING_PROVIDER", "CML_ALLOW_HASH_EMBEDDINGS"):
            os.environ.pop(key, None)
        self.tmp.cleanup()

    def test_registration_is_idempotent_and_excludes_secrets_and_dependencies(self) -> None:
        from backend.app.core.database import connect
        from backend.app.core.projects import register_project

        first = _register_project(vault_id="vault-odin", root_path=str(self.repo), name="Sample", sync=True)
        second = _register_project(vault_id="vault-odin", root_path=str(self.repo), name="Different", sync=False)

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["source_count"], 3)
        self.assertEqual(first["structure_status"], "ready")
        self.assertIn("TypeScript", first["languages"])
        with connect() as conn:
            paths = {
                row["relative_path"]
                for row in conn.execute(
                    "SELECT relative_path FROM project_sources WHERE project_id = ?",
                    (first["id"],),
                ).fetchall()
            }
            node_count = conn.execute(
                "SELECT COUNT(*) AS total FROM code_nodes WHERE project_id = ? AND snapshot_id = ?",
                (first["id"], first["active_snapshot_id"]),
            ).fetchone()["total"]
        self.assertEqual(paths, {"package.json", "src/auth.ts", "src/main.ts"})
        self.assertGreaterEqual(node_count, 6)

    def test_project_brief_uses_readme_purpose_and_refreshes_after_sync(self) -> None:
        from backend.app.core.background_jobs import run_due_jobs_once
        from backend.app.core.projects import get_project, probe_project_changes

        readme = self.repo / "README.md"
        readme.write_text(
            "# Sample\n\nSample coordinates access decisions across local application services.\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "config", "user.email", "odin-test@example.invalid"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.repo), "config", "user.name", "Odin Test"],
            check=True,
        )
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "-q", "-m", "baseline"],
            check=True,
        )
        project = _register_project(
            vault_id="vault-odin",
            root_path=str(self.repo),
            name="Sample",
            sync=True,
        )

        self.assertIn(
            "Sample coordinates access decisions across local application services.",
            project["brief"],
        )
        self.assertIn("Indexed as a", project["brief"])
        self.assertNotIn("model-written project brief", project["brief"])

        readme.write_text(
            "# Sample\n\nSample now coordinates authorization and audit workflows for local services.\n",
            encoding="utf-8",
        )
        report = probe_project_changes(project["id"])
        self.assertEqual(report["sync_kind"], "git_delta")
        run_due_jobs_once(limit=20)
        refreshed = get_project(project["id"])

        self.assertIn(
            "Sample now coordinates authorization and audit workflows for local services.",
            refreshed["brief"],
        )
        self.assertNotIn("coordinates access decisions", refreshed["brief"])

    def test_delta_probe_detects_a_new_untracked_file_and_queues_sync(self) -> None:
        from backend.app.core.projects import get_project, probe_project_changes

        project = _register_project(
            vault_id="vault-odin",
            root_path=str(self.repo),
            name="Sample",
            sync=True,
        )
        self.assertTrue(project["change_fingerprint"])
        (self.repo / "src" / "new-file.ts").write_text(
            "export const newlyAdded = true;\n",
            encoding="utf-8",
        )

        result = probe_project_changes(project["id"])
        current = get_project(project["id"])

        self.assertTrue(result["changed"])
        self.assertTrue(result["sync_queued"])
        self.assertEqual(current["status"], "indexing")

    def test_notify_sync_mode_reports_typed_changes_without_queuing_work(self) -> None:
        from backend.app.core.projects import (
            inspect_project_changes,
            probe_project_changes,
            update_project,
        )

        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "config", "user.email", "odin-test@example.invalid"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.repo), "config", "user.name", "Odin Test"],
            check=True,
        )
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "-q", "-m", "baseline"],
            check=True,
        )
        project = _register_project(
            vault_id="vault-odin",
            root_path=str(self.repo),
            name="Notify project",
            sync=True,
        )
        update_project(project["id"], sync_mode="notify")
        (self.repo / "src" / "auth.ts").rename(self.repo / "src" / "permissions.ts")
        (self.repo / "src" / "new.ts").write_text(
            "export const created = true;\n",
            encoding="utf-8",
        )

        inspected = inspect_project_changes(project["id"])
        probed = probe_project_changes(project["id"])

        self.assertTrue(inspected["changed"])
        self.assertEqual(inspected["sync_mode"], "notify")
        self.assertIn("added", {item["kind"] for item in inspected["change_items"]})
        self.assertIn("renamed", {item["kind"] for item in inspected["change_items"]})
        self.assertFalse(probed["sync_queued"])
        self.assertEqual(probed["next_action"], "sync_changes")

    def test_dirty_worktree_matching_active_snapshot_is_not_pending_for_odin(self) -> None:
        from backend.app.core.projects import inspect_project_changes

        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "config", "user.email", "odin-test@example.invalid"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.repo), "config", "user.name", "Odin Test"],
            check=True,
        )
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "-q", "-m", "baseline"],
            check=True,
        )
        (self.repo / "src" / "auth.ts").write_text(
            "export function authorize() { return 'indexed-dirty-version'; }\n",
            encoding="utf-8",
        )
        project = _register_project(
            vault_id="vault-odin",
            root_path=str(self.repo),
            name="Dirty snapshot project",
            sync=True,
        )

        indexed = inspect_project_changes(project["id"])

        self.assertFalse(indexed["changed"])
        self.assertEqual(indexed["changed_path_count"], 0)
        self.assertTrue(indexed["working_tree_dirty"])
        self.assertIn("src/auth.ts", indexed["repository_changed_paths"])

        (self.repo / "src" / "auth.ts").write_text(
            "export function authorize() { return 'newer-than-snapshot'; }\n",
            encoding="utf-8",
        )
        pending = inspect_project_changes(project["id"])

        self.assertTrue(pending["changed"])
        self.assertEqual(pending["changed_paths"], ["src/auth.ts"])
        self.assertEqual(pending["change_items"][0]["kind"], "modified")

    def test_targeted_sync_accepts_snapshot_filtered_git_delta(self) -> None:
        from backend.app.api.routes.projects import project_sync_targeted
        from backend.app.schemas import ProjectTargetedSyncRequest

        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "config", "user.email", "odin-test@example.invalid"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.repo), "config", "user.name", "Odin Test"],
            check=True,
        )
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "-q", "-m", "baseline"],
            check=True,
        )
        project = _register_project(
            vault_id="vault-odin",
            root_path=str(self.repo),
            name="Targeted route project",
            sync=True,
        )
        (self.repo / "src" / "auth.ts").write_text(
            "export function authorize() { return 'targeted-change'; }\n",
            encoding="utf-8",
        )

        queued = project_sync_targeted(
            project["id"],
            ProjectTargetedSyncRequest(paths=["src/auth.ts"]),
        )

        self.assertEqual(queued["targeted_paths"], ["src/auth.ts"])
        self.assertTrue(queued["freshness_token"])

    def test_snapshot_delta_scales_across_many_already_indexed_untracked_files(self) -> None:
        from backend.app.core.database import connect, utc_now
        from backend.app.core.projects import (
            inspect_project_changes,
            project_discovery_policy_hash,
            register_project,
        )

        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "config", "user.email", "odin-test@example.invalid"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.repo), "config", "user.name", "Odin Test"],
            check=True,
        )
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "-q", "-m", "baseline"],
            check=True,
        )
        generated = self.repo / "src" / "scale"
        generated.mkdir()
        for index in range(750):
            (generated / f"module-{index:04d}.ts").write_text(
                f"export const value{index} = {index};\n",
                encoding="utf-8",
            )
        project = register_project(
            vault_id="vault-odin",
            root_path=str(self.repo),
            name="Scale snapshot project",
            sync=False,
        )
        manifest_files = []
        for path in sorted(self.repo.rglob("*")):
            if not path.is_file() or ".git" in path.parts or path.name == ".env":
                continue
            raw = path.read_bytes()
            manifest_files.append(
                {
                    "path": path.relative_to(self.repo).as_posix(),
                    "hash": hashlib.sha256(raw).hexdigest(),
                }
            )
        snapshot_id = "snapshot-scale-active"
        now = utc_now()
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO project_snapshots (
                    id, project_id, discovery_scope, source_manifest_hash, git_commit,
                    branch, dirty_working_tree, extractor_version, eligible_count,
                    ignored_count, generated_count, parsed_count, failed_count,
                    structure_status, retrieval_status, interpretation_status,
                    manifest_json, created_at
                ) VALUES (?, ?, 'context', '', '', '', 1, 'scale-test', ?, 0, 0, ?, 0,
                          'ready', 'ready', 'unavailable', ?, ?)
                """,
                (
                    snapshot_id,
                    project["id"],
                    len(manifest_files),
                    len(manifest_files),
                    json.dumps(
                        {
                            "version": 2,
                            "policy_hash": project_discovery_policy_hash(self.repo),
                            "files": manifest_files,
                        }
                    ),
                    now,
                ),
            )
            conn.execute(
                """
                UPDATE projects
                SET active_snapshot_id = ?, active_manifest_snapshot_id = ?,
                    active_retrieval_snapshot_id = ?, status = 'ready'
                WHERE id = ?
                """,
                (snapshot_id, snapshot_id, snapshot_id, project["id"]),
            )

        report = inspect_project_changes(project["id"], max_paths=1000)

        self.assertGreaterEqual(report["repository_changed_path_count"], 750)
        self.assertEqual(report["changed_path_count"], 0)
        self.assertFalse(report["changed"])
        self.assertFalse(report["truncated"])

    def test_repeated_targeted_delta_reuses_versioned_freshness_token(self) -> None:
        from backend.app.core.projects import sync_project_delta

        project = _register_project(
            vault_id="vault-odin",
            root_path=str(self.repo),
            name="Targeted project",
            sync=False,
        )
        first = sync_project_delta(
            project["id"],
            changed_paths=["src/auth.ts"],
            trigger_source="question_targeted",
        )
        repeated = sync_project_delta(
            project["id"],
            changed_paths=["src/auth.ts"],
            trigger_source="question_targeted",
        )

        self.assertTrue(first["snapshot_id"])
        self.assertEqual(repeated["sync_kind"], "existing")
        self.assertEqual(repeated["snapshot_id"], first["snapshot_id"])

    def test_project_auto_sync_setting_persists_on_create_and_update(self) -> None:
        from backend.app.core.projects import register_project, update_project

        project = register_project(
            vault_id="vault-odin",
            root_path=str(self.repo),
            name="Manual project",
            auto_sync_enabled=False,
            sync=False,
        )
        self.assertFalse(project["auto_sync_enabled"])
        self.assertEqual(project["sync_mode"], "manual")

        updated = update_project(project["id"], auto_sync_enabled=True)
        self.assertTrue(updated["auto_sync_enabled"])
        self.assertEqual(updated["sync_mode"], "automatic")

    def test_git_auto_sync_indexes_only_changed_paths_and_marks_structure_stale(self) -> None:
        from backend.app.core.background_jobs import run_due_jobs_once
        from backend.app.core.database import connect
        from backend.app.core.projects import get_project, probe_project_changes

        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "config", "user.email", "odin-test@example.invalid"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.repo), "config", "user.name", "Odin Test"],
            check=True,
        )
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "-q", "-m", "baseline"],
            check=True,
        )
        project = _register_project(
            vault_id="vault-odin",
            root_path=str(self.repo),
            name="Git project",
            sync=True,
        )
        structure_snapshot = project["active_structure_snapshot_id"]
        with connect() as conn:
            original_sources = {
                row["relative_path"]: row["source_id"]
                for row in conn.execute(
                    "SELECT relative_path, source_id FROM project_sources WHERE project_id = ?",
                    (project["id"],),
                ).fetchall()
            }
            unchanged_chunk_ids = {
                row["id"]
                for row in conn.execute(
                    "SELECT id FROM source_chunks WHERE source_id = ?",
                    (original_sources["package.json"],),
                ).fetchall()
            }

        (self.repo / "src" / "main.ts").write_text(
            "export const start = () => 'changed';\n",
            encoding="utf-8",
        )
        (self.repo / "src" / "new-file.ts").write_text(
            "export const newlyAdded = true;\n",
            encoding="utf-8",
        )
        (self.repo / "src" / "auth.ts").unlink()

        report = probe_project_changes(project["id"])
        self.assertEqual(report["sync_kind"], "git_delta")
        self.assertEqual(
            set(report["changed_paths"]),
            {"src/auth.ts", "src/main.ts", "src/new-file.ts"},
        )
        run_due_jobs_once(limit=20)
        current = get_project(project["id"])

        self.assertEqual(current["status"], "ready")
        self.assertEqual(current["retrieval_status"], "ready")
        self.assertEqual(current["structure_status"], "stale")
        self.assertEqual(current["active_structure_snapshot_id"], structure_snapshot)
        self.assertNotEqual(current["active_retrieval_snapshot_id"], structure_snapshot)
        with connect() as conn:
            current_sources = {
                row["relative_path"]: row["source_id"]
                for row in conn.execute(
                    "SELECT relative_path, source_id FROM project_sources WHERE project_id = ?",
                    (project["id"],),
                ).fetchall()
            }
            current_chunk_ids = {
                row["id"]
                for row in conn.execute(
                    "SELECT id FROM source_chunks WHERE source_id = ?",
                    (current_sources["package.json"],),
                ).fetchall()
            }
            delta_job = conn.execute(
                """
                SELECT status FROM app_jobs
                WHERE job_type = 'project_delta_apply' AND scope_id = ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (project["id"],),
            ).fetchone()
        self.assertEqual(
            set(current_sources),
            {"package.json", "src/main.ts", "src/new-file.ts"},
        )
        self.assertEqual(current_sources["package.json"], original_sources["package.json"])
        self.assertEqual(current_chunk_ids, unchanged_chunk_ids)
        self.assertEqual(delta_job["status"], "succeeded")

    def test_phased_activation_is_the_only_project_snapshot_writer(self) -> None:
        project_source = (
            Path(__file__).parents[1] / "app" / "core" / "projects.py"
        ).read_text(encoding="utf-8")
        indexing_source = (
            Path(__file__).parents[1] / "app" / "core" / "project_indexing.py"
        ).read_text(encoding="utf-8")
        jobs_source = (
            Path(__file__).parents[1] / "app" / "core" / "background_jobs.py"
        ).read_text(encoding="utf-8")

        self.assertNotIn("def run_project_index_job", project_source)
        self.assertNotIn("def _activate_discovery", project_source)
        self.assertNotIn('"project_index": JobPolicy', jobs_source)
        self.assertEqual(indexing_source.count("def activate_candidate("), 1)

    def test_legacy_monolithic_job_is_terminated_and_requeued_as_phases(self) -> None:
        import json

        from backend.app.core.background_jobs import migrate_legacy_project_index_jobs
        from backend.app.core.database import connect, utc_now
        from backend.app.core.projects import register_project

        project = register_project(
            vault_id="vault-odin",
            root_path=str(self.repo),
            name="Legacy",
            sync=False,
        )
        now = utc_now()
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO project_index_runs (
                    id, project_id, trigger_source, status, phase, started_at, created_at, updated_at
                )
                VALUES ('legacy-run', ?, 'startup', 'queued', 'queued', ?, ?, ?)
                """,
                (project["id"], now, now, now),
            )
            conn.execute(
                """
                UPDATE projects SET active_run_id = 'legacy-run', status = 'indexing'
                WHERE id = ?
                """,
                (project["id"],),
            )
            conn.execute(
                """
                INSERT INTO app_jobs (id, job_type, status, payload, created_at, updated_at)
                VALUES ('legacy-job', 'project_index', 'queued', ?, ?, ?)
                """,
                (
                    json.dumps({"project_id": project["id"], "run_id": "legacy-run"}),
                    now,
                    now,
                ),
            )

        self.assertEqual(migrate_legacy_project_index_jobs(), 1)

        with connect() as conn:
            legacy_job = conn.execute(
                "SELECT status, last_error FROM app_jobs WHERE id = 'legacy-job'"
            ).fetchone()
            legacy_run = conn.execute(
                "SELECT status, failure_category FROM project_index_runs WHERE id = 'legacy-run'"
            ).fetchone()
            phase_types = {
                row["job_type"]
                for row in conn.execute(
                    "SELECT job_type FROM app_jobs WHERE scope_id = ?",
                    (project["id"],),
                ).fetchall()
            }
        self.assertEqual(legacy_job["status"], "failed")
        self.assertEqual(legacy_job["last_error"], "legacy_project_index_removed")
        self.assertEqual(legacy_run["status"], "failed")
        self.assertTrue(
            {"project_discover", "project_structure_index", "project_retrieval_stage", "project_snapshot_activate"}
            <= phase_types
        )

    def test_project_list_filters_linked_projects_in_one_query(self) -> None:
        from backend.app.core.projects import link_project, list_projects

        first = _register_project(
            vault_id="vault-odin",
            root_path=str(self.repo),
            name="Primary",
            sync=False,
        )
        second_repo = self.root / "second-project"
        second_repo.mkdir()
        (second_repo / "main.py").write_text("print('second')\n", encoding="utf-8")
        second = _register_project(
            vault_id="vault-odin",
            root_path=str(second_repo),
            name="Linked",
            sync=False,
        )
        link_project(second["id"], first["primary_cluster_id"])

        matching = list_projects(
            vault_id="vault-odin",
            cluster_id=first["primary_cluster_id"],
            limit=200,
        )

        self.assertEqual({project["id"] for project in matching}, {first["id"], second["id"]})
        self.assertEqual(
            list_projects(
                vault_id="vault-odin",
                cluster_id=second["primary_cluster_id"],
                limit=200,
            )[0]["id"],
            second["id"],
        )

    def test_discovery_scope_filters_context_files_but_keeps_source_like_json(self) -> None:
        from backend.app.core.projects import discover_project

        (self.repo / "README.md").write_text("# Sample project\n", encoding="utf-8")
        (self.repo / "settings.yaml").write_text("feature: true\n", encoding="utf-8")
        (self.repo / "src" / "worker.mts").write_text("export const worker = true;\n", encoding="utf-8")
        (self.repo / "src" / "compat.cjs").write_text("module.exports = {};\n", encoding="utf-8")
        (self.repo / "src" / "contracts.pyi").write_text("def authorize(token: str) -> bool: ...\n", encoding="utf-8")

        context = discover_project(self.repo, discovery_scope="context")
        code = discover_project(self.repo, discovery_scope="code")

        self.assertEqual(context.discovery_scope, "context")
        self.assertEqual(code.discovery_scope, "code")
        self.assertEqual(
            {item.relative_path for item in code.files},
            {
                "package.json", "src/auth.ts", "src/compat.cjs", "src/contracts.pyi",
                "src/main.ts", "src/worker.mts",
            },
        )
        self.assertTrue({"README.md", "settings.yaml"} <= {item.relative_path for item in context.files})
        self.assertNotEqual(context.manifest_hash, code.manifest_hash)

    def test_discovery_normalizes_a_relative_project_root(self) -> None:
        from backend.app.core.projects import discover_project

        previous = Path.cwd()
        try:
            os.chdir(self.root)
            result = discover_project(Path("sample-project"), discovery_scope="code")
        finally:
            os.chdir(previous)

        self.assertEqual(
            {item.relative_path for item in result.files},
            {"package.json", "src/auth.ts", "src/main.ts"},
        )

    def test_scope_change_persists_and_activates_through_a_candidate_snapshot(self) -> None:
        from backend.app.core.background_jobs import run_due_jobs_once
        from backend.app.core.projects import get_project, register_project, sync_project

        (self.repo / "README.md").write_text("# Sample project\n", encoding="utf-8")
        project = _register_project(
            vault_id="vault-odin",
            root_path=str(self.repo),
            name="Sample",
            discovery_scope="context",
            sync=True,
        )
        prior_snapshot = project["active_snapshot_id"]
        self.assertEqual(project["source_count"], 4)
        self.assertEqual(project["active_snapshot"]["discovery_scope"], "context")

        from backend.app.schemas import ProjectRead

        serialized = ProjectRead.model_validate(project).model_dump()
        self.assertEqual(serialized["active_snapshot"]["discovery_scope"], "context")

        queued = sync_project(project["id"], discovery_scope="code")
        pending = get_project(project["id"])
        self.assertEqual(queued["project"]["discovery_scope"], "code")
        self.assertEqual(pending["active_snapshot_id"], prior_snapshot)
        self.assertEqual(pending["active_snapshot"]["discovery_scope"], "context")

        run_due_jobs_once(limit=20)
        activated = get_project(project["id"])
        self.assertEqual(activated["discovery_scope"], "code")
        self.assertEqual(activated["active_snapshot"]["discovery_scope"], "code")
        self.assertEqual(activated["source_count"], 3)
        self.assertNotEqual(activated["active_snapshot_id"], prior_snapshot)

    def test_sync_reconciles_modified_added_and_removed_files(self) -> None:
        from backend.app.core.database import connect
        from backend.app.core.projects import register_project, sync_project

        project = _register_project(vault_id="vault-odin", root_path=str(self.repo), name="Sample", sync=True)
        with connect() as conn:
            removed_source = conn.execute(
                """
                SELECT s.id
                FROM project_sources ps
                JOIN sources s ON s.id = ps.source_id
                WHERE ps.project_id = ? AND ps.relative_path = ?
                """,
                (project["id"], "src/auth.ts"),
            ).fetchone()
        self.assertIsNotNone(removed_source)
        (self.repo / "src" / "auth.ts").unlink()
        (self.repo / "src" / "main.ts").write_text("export const start = () => 'updated';\n", encoding="utf-8")
        (self.repo / "src" / "routes.ts").write_text("export const routes = [];\n", encoding="utf-8")

        queued = sync_project(project["id"])
        from backend.app.core.background_jobs import run_due_jobs_once
        from backend.app.core.projects import get_project, get_project_run

        run_due_jobs_once(limit=20)
        result = {"run": get_project_run(queued["run"]["id"]), "project": get_project(project["id"])}

        self.assertEqual(result["run"]["status"], "succeeded")
        self.assertEqual(result["project"]["source_count"], 3)
        with connect() as conn:
            deleted = conn.execute(
                "SELECT deleted_at FROM sources WHERE id = ?",
                (removed_source["id"],),
            ).fetchone()
            active_membership = conn.execute(
                """
                SELECT 1
                FROM project_sources
                WHERE project_id = ? AND source_id = ?
                """,
                (project["id"], removed_source["id"]),
            ).fetchone()
        # Cleanup may retain the tombstone for audit or physically purge it once
        # no active snapshot references it. Both outcomes preserve the contract.
        self.assertTrue(deleted is None or deleted["deleted_at"] is not None)
        self.assertIsNone(active_membership)

    def test_sync_populates_release_snapshot_and_run_contracts(self) -> None:
        from backend.app.core.database import connect
        from backend.app.core.projects import register_project

        project = _register_project(vault_id="vault-odin", root_path=str(self.repo), name="Sample", sync=True)

        self.assertEqual(project["active_manifest_snapshot_id"], project["active_snapshot_id"])
        self.assertEqual(project["active_structure_snapshot_id"], project["active_snapshot_id"])
        self.assertEqual(project["active_retrieval_snapshot_id"], project["active_snapshot_id"])
        self.assertIsNone(project["candidate_snapshot_id"])
        self.assertIsNone(project["active_run_id"])
        self.assertEqual(project["active_snapshot"]["manifest_activated_at"], project["active_snapshot"]["activated_at"])
        self.assertLessEqual(project["active_snapshot"]["structure_activated_at"], project["active_snapshot"]["activated_at"])
        with connect() as conn:
            memberships = conn.execute(
                """
                SELECT pss.relative_path, pss.stage_status, s.project_snapshot_id, s.activation_state
                FROM project_snapshot_sources pss
                JOIN sources s ON s.id = pss.source_id
                WHERE pss.snapshot_id = ?
                ORDER BY pss.relative_path
                """,
                (project["active_snapshot_id"],),
            ).fetchall()
            run = conn.execute(
                "SELECT * FROM project_index_runs WHERE project_id = ? ORDER BY created_at DESC LIMIT 1",
                (project["id"],),
            ).fetchone()
            chunk_scopes = conn.execute(
                """
                SELECT DISTINCT chunks.cluster_id
                FROM source_chunks chunks
                JOIN project_snapshot_sources membership
                  ON membership.source_id = chunks.source_id
                 AND membership.snapshot_id = chunks.project_snapshot_id
                WHERE membership.snapshot_id = ?
                  AND chunks.activation_state = 'active'
                """,
                (project["active_snapshot_id"],),
            ).fetchall()
        self.assertEqual([row["relative_path"] for row in memberships], ["package.json", "src/auth.ts", "src/main.ts"])
        self.assertTrue(all(row["stage_status"] == "active" for row in memberships))
        self.assertTrue(all(row["project_snapshot_id"] == project["active_snapshot_id"] for row in memberships))
        self.assertTrue(all(row["activation_state"] == "active" for row in memberships))
        self.assertEqual(
            {row["cluster_id"] for row in chunk_scopes},
            {project["primary_cluster_id"]},
        )
        self.assertEqual(run["activation_outcome"], "activated")
        self.assertEqual(run["phase_completed_count"], 3)
        self.assertEqual(run["phase_total_count"], 3)
        self.assertIsNotNone(run["heartbeat_at"])

    def test_sync_is_queued_deduplicated_and_cancellable_without_replacing_active_snapshot(self) -> None:
        from backend.app.core.projects import cancel_project_run, sync_project

        project = _register_project(vault_id="vault-odin", root_path=str(self.repo), name="Sample", sync=True)
        original_snapshot = project["active_snapshot_id"]

        first = sync_project(project["id"])
        second = sync_project(project["id"])

        self.assertTrue(first["queued"])
        self.assertEqual(first["job_id"], second["job_id"])
        self.assertEqual(first["run"]["id"], second["run"]["id"])
        cancelled = cancel_project_run(project["id"])
        self.assertEqual(cancelled["status"], "cancelled")
        current = __import__("backend.app.core.projects", fromlist=["get_project"]).get_project(project["id"])
        self.assertEqual(current["active_snapshot_id"], original_snapshot)
        self.assertIsNone(current["candidate_snapshot_id"])

    def test_reconnect_moves_registration_without_touching_repository_files(self) -> None:
        from backend.app.core.projects import update_project

        project = _register_project(vault_id="vault-odin", root_path=str(self.repo), name="Sample", sync=True)
        replacement = self.root / "moved-project"
        replacement.mkdir()
        marker = replacement / "README.md"
        marker.write_text("replacement root", encoding="utf-8")

        updated = update_project(project["id"], root_path=str(replacement))

        self.assertEqual(Path(updated["root_path"]), replacement.resolve())
        self.assertEqual(updated["status"], "stale")
        self.assertEqual(marker.read_text(encoding="utf-8"), "replacement root")
        self.assertEqual(updated["active_snapshot_id"], project["active_snapshot_id"])

    def test_failed_candidate_keeps_the_previous_snapshot_readable(self) -> None:
        from unittest.mock import patch

        from backend.app.core.background_jobs import run_due_jobs_once
        from backend.app.core.projects import get_project, get_project_run, sync_project

        project = _register_project(vault_id="vault-odin", root_path=str(self.repo), name="Sample", sync=True)
        original_snapshot = project["active_snapshot_id"]
        queued = sync_project(project["id"])
        with patch("backend.app.core.projects.discover_project", side_effect=RuntimeError("forced candidate failure")):
            run_due_jobs_once(limit=20)

        current = get_project(project["id"])
        run = get_project_run(queued["run"]["id"])
        self.assertEqual(run["status"], "failed")
        self.assertEqual(current["active_snapshot_id"], original_snapshot)
        self.assertIsNone(current["candidate_snapshot_id"])

    def test_phased_indexing_isolates_candidate_sources_until_atomic_retrieval_activation(self) -> None:
        from backend.app.core.background_jobs import run_due_jobs_once
        from backend.app.core.database import connect
        from backend.app.core.projects import get_project, get_project_run, sync_project

        project = _register_project(vault_id="vault-odin", root_path=str(self.repo), name="Sample", sync=True)
        old_manifest = project["active_manifest_snapshot_id"]
        old_structure = project["active_structure_snapshot_id"]
        old_retrieval = project["active_retrieval_snapshot_id"]
        (self.repo / "src" / "main.ts").write_text("export const start = () => 'candidate';\n", encoding="utf-8")
        queued = sync_project(project["id"])

        self.assertEqual(run_due_jobs_once(limit=1), 1)  # discovery
        discovered = get_project(project["id"])
        candidate = discovered["candidate_snapshot_id"]
        self.assertEqual(discovered["active_manifest_snapshot_id"], old_manifest)
        self.assertEqual(discovered["active_structure_snapshot_id"], old_structure)
        self.assertEqual(discovered["active_retrieval_snapshot_id"], old_retrieval)
        with connect() as conn:
            candidate_source = conn.execute(
                """
                SELECT s.cluster_id, s.state, s.activation_state, pss.intended_action
                FROM project_snapshot_sources pss JOIN sources s ON s.id = pss.source_id
                WHERE pss.snapshot_id = ? AND pss.relative_path = 'src/main.ts'
                """, (candidate,),
            ).fetchone()
            active_membership = conn.execute(
                "SELECT content_hash FROM project_sources WHERE project_id = ? AND relative_path = 'src/main.ts'",
                (project["id"],),
            ).fetchone()
        self.assertEqual(candidate_source["intended_action"], "replace")
        self.assertIsNone(candidate_source["cluster_id"])
        self.assertEqual(candidate_source["state"], "staging")
        self.assertEqual(candidate_source["activation_state"], "candidate")
        self.assertNotEqual(active_membership["content_hash"], __import__("hashlib").sha256(b"export const start = () => 'candidate';\n").hexdigest())
        from backend.app.api.routes.sources import count_sources, list_sources

        visible_sources = list_sources(vault_id="vault-odin")
        self.assertEqual(count_sources(vault_id="vault-odin")["total"], 3)
        self.assertEqual(len(visible_sources), 3)
        self.assertNotIn(candidate_source["activation_state"], {item.get("activation_state") for item in visible_sources})

        self.assertEqual(run_due_jobs_once(limit=1), 1)  # structure
        structured = get_project(project["id"])
        self.assertEqual(structured["active_manifest_snapshot_id"], candidate)
        self.assertEqual(structured["active_structure_snapshot_id"], candidate)
        self.assertEqual(structured["active_retrieval_snapshot_id"], old_retrieval)

        self.assertEqual(run_due_jobs_once(limit=1), 1)  # retrieval staging
        staged = get_project(project["id"])
        self.assertEqual(staged["active_retrieval_snapshot_id"], old_retrieval)
        with connect() as conn:
            still_old = conn.execute(
                "SELECT source_id FROM project_sources WHERE project_id = ? AND relative_path = 'src/main.ts'",
                (project["id"],),
            ).fetchone()["source_id"]
            candidate_id = conn.execute(
                "SELECT source_id FROM project_snapshot_sources WHERE snapshot_id = ? AND relative_path = 'src/main.ts'",
                (candidate,),
            ).fetchone()["source_id"]
        self.assertNotEqual(still_old, candidate_id)

        self.assertEqual(run_due_jobs_once(limit=1), 1)  # activation
        activated = get_project(project["id"])
        self.assertEqual(activated["active_retrieval_snapshot_id"], candidate)
        self.assertIsNone(activated["candidate_snapshot_id"])
        self.assertEqual(get_project_run(queued["run"]["id"])["status"], "succeeded")
        with connect() as conn:
            active_id = conn.execute(
                "SELECT source_id FROM project_sources WHERE project_id = ? AND relative_path = 'src/main.ts'",
                (project["id"],),
            ).fetchone()["source_id"]
        self.assertEqual(active_id, candidate_id)

    def test_large_project_sources_can_be_browsed_as_one_folder(self) -> None:
        from backend.app.api.routes.sources import count_sources, list_sources_page

        for index in range(20):
            (self.repo / "src" / f"module-{index:02d}.ts").write_text(
                f"export const module{index} = {index};\n",
                encoding="utf-8",
            )
        project = _register_project(
            vault_id="vault-odin",
            root_path=str(self.repo),
            name="Large project",
            sync=True,
        )

        root_page = list_sources_page(
            vault_id="vault-odin",
            exclude_grouped_projects=True,
            limit=100,
        )
        folder_page = list_sources_page(
            vault_id="vault-odin",
            project_id=project["id"],
            limit=100,
        )

        self.assertEqual(project["source_count"], 23)
        self.assertEqual(root_page["items"], [])
        self.assertEqual(count_sources(vault_id="vault-odin", exclude_grouped_projects=True)["total"], 0)
        self.assertEqual(len(folder_page["items"]), 23)

    def test_project_job_recovery_requeues_staging_and_verifies_committed_activation(self) -> None:
        from backend.app.core.background_jobs import recover_interrupted_jobs, run_due_jobs_once
        from backend.app.core.database import connect
        from backend.app.core.projects import register_project, sync_project

        project = register_project(vault_id="vault-odin", root_path=str(self.repo), name="Sample", sync=False)
        queued = sync_project(project["id"])
        with connect() as conn:
            conn.execute("UPDATE app_jobs SET status = 'running' WHERE id = ?", (queued["job_id"],))
        recovered = recover_interrupted_jobs()
        self.assertEqual(recovered["queued"], 1)
        with connect() as conn:
            self.assertEqual(conn.execute("SELECT status FROM app_jobs WHERE id = ?", (queued["job_id"],)).fetchone()["status"], "queued")

        run_due_jobs_once(limit=20)
        with connect() as conn:
            activation = conn.execute(
                "SELECT id FROM app_jobs WHERE job_type = 'project_snapshot_activate' AND payload LIKE ?",
                (f'%"run_id":"{queued["run"]["id"]}"%',),
            ).fetchone()
            conn.execute("UPDATE app_jobs SET status = 'running', completed_at = NULL WHERE id = ?", (activation["id"],))
        recover_interrupted_jobs()
        with connect() as conn:
            recovered_activation = conn.execute("SELECT status, status_detail FROM app_jobs WHERE id = ?", (activation["id"],)).fetchone()
        self.assertEqual(recovered_activation["status"], "succeeded")
        self.assertIn("verified", recovered_activation["status_detail"].lower())

    def test_remove_deletes_only_cml_records(self) -> None:
        from backend.app.core.database import connect
        from backend.app.core.projects import register_project, remove_project

        project = _register_project(vault_id="vault-odin", root_path=str(self.repo), name="Sample", sync=True)
        remove_project(project["id"], confirmation_name="Sample")

        self.assertTrue((self.repo / "src" / "main.ts").exists())
        with connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 0)

    def test_cli_global_options_work_after_subcommands(self) -> None:
        from backend.app.odin_cli import _normalize_global_args

        normalized = _normalize_global_args(["project", "list", "--json", "--backend", "http://127.0.0.1:7343"])
        self.assertEqual(normalized[:3], ["--json", "--backend", "http://127.0.0.1:7343"])

    def test_bounded_graph_path_uses_proven_import_relationships(self) -> None:
        from backend.app.core.project_graph import shortest_path
        from backend.app.core.projects import register_project

        project = _register_project(vault_id="vault-odin", root_path=str(self.repo), name="Sample", sync=True)
        result = shortest_path(project["id"], "start", "authorize")

        self.assertEqual(result["status"], "found")
        self.assertEqual([node["display_label"] for node in result["path"]], ["start", "authorize"])
        self.assertEqual(result["edges"][0]["edge_type"], "calls")

    def test_project_context_retrieves_activated_project_sources(self) -> None:
        from backend.app.api.routes.projects import ProjectContextRequest, project_context

        project = _register_project(
            vault_id="vault-odin",
            root_path=str(self.repo),
            name="Sample",
            sync=True,
        )
        response = project_context(
            project["id"],
            ProjectContextRequest(query="What does this project do?", limit=8, mode="context"),
        )

        self.assertEqual(response["project_id"], project["id"])
        self.assertTrue(response["citations"])
        self.assertTrue(response["source_snippets"])
        self.assertGreater(response["evidence_summary"]["implementation_files"], 0)
        self.assertEqual(
            response["freshness"]["retrieval_snapshot_id"],
            project["active_retrieval_snapshot_id"],
        )
        citation_source_ids = {item["source_id"] for item in response["citations"]}
        from backend.app.core.database import connect
        with connect() as conn:
            citation_clusters = {
                row["cluster_id"]
                for row in conn.execute(
                    f"SELECT cluster_id FROM sources WHERE id IN ({','.join('?' for _ in citation_source_ids)})",
                    list(citation_source_ids),
                ).fetchall()
            }
        self.assertEqual(citation_clusters, {project["primary_cluster_id"]})

    def test_project_context_withholds_authority_when_local_changes_are_unindexed(self) -> None:
        from backend.app.api.routes.projects import ProjectContextRequest, project_context
        from backend.app.core.database import connect

        project = _register_project(
            vault_id="vault-odin",
            root_path=str(self.repo),
            name="Sample",
            sync=True,
        )
        with connect() as conn:
            conn.execute(
                "UPDATE projects SET changed_file_count = 2 WHERE id = ?",
                (project["id"],),
            )

        response = project_context(
            project["id"],
            ProjectContextRequest(query="What does this project do?", limit=8, mode="context"),
        )

        self.assertFalse(response["retrieval_authority"])
        self.assertEqual(response["freshness"]["changed_file_count"], 2)
        self.assertIn(
            "Local project changes are not included in this snapshot.",
            response["limitations"],
        )

    def test_project_chat_retrieves_the_same_project_evidence(self) -> None:
        from backend.app.api.routes.chat import _build_retrieval_context, _resolve_project_chat_scope
        from backend.app.schemas import ChatContextRequest

        project = _register_project(
            vault_id="vault-odin",
            root_path=str(self.repo),
            name="Sample",
            sync=True,
        )
        payload = _resolve_project_chat_scope(
            ChatContextRequest(
                vault_id="vault-odin",
                project_id=project["id"],
                prompt="What does this project do?",
                persist=False,
            )
        )
        response = _build_retrieval_context(payload, synthesize=False)

        self.assertEqual(payload.cluster_id, project["primary_cluster_id"])
        self.assertTrue(response["citations"])
        self.assertNotEqual(
            response["coverage_ledger"]["partial_failure_mode"],
            "no_citations",
        )

    def test_graph_view_explains_key_areas_and_observed_flows(self) -> None:
        from backend.app.core.project_graph import graph_view, graph_view_markdown

        project = _register_project(
            vault_id="vault-odin",
            root_path=str(self.repo),
            name="Sample",
            sync=True,
        )
        view = graph_view(project["id"], query="Show the architecture graph for this project.")

        self.assertTrue(view["nodes"])
        self.assertIn("traceable relationships", view["insights"]["summary"])
        self.assertTrue(view["insights"]["key_areas"])
        markdown = graph_view_markdown(view)
        self.assertIn("## Overview", markdown)
        self.assertIn("## Key areas", markdown)
        self.assertIn("## Flows", markdown)

    def test_node_insertion_is_idempotent_within_a_snapshot(self) -> None:
        from backend.app.core.code_structure import _insert_node, _path_key
        from backend.app.core.database import connect, utc_now

        project = _register_project(vault_id="vault-odin", root_path=str(self.repo), name="Sample", sync=True)
        values = {
            "project_id": project["id"],
            "snapshot_id": project["active_structure_snapshot_id"],
            "qualified_id": "test:idempotent-node",
            "kind": "function",
            "language": "Python",
            "label": "idempotent",
            "relative_path": "src/idempotent.py",
            "source_id": None,
            "signature": "idempotent()",
            "content_hash": "hash",
            "now": utc_now(),
        }
        with connect() as conn:
            first = _insert_node(conn, **values)
            second = _insert_node(conn, **values)
            upper = _insert_node(
                conn, **{**values, "qualified_id": f"file:{_path_key('src/Thing.ts')}", "relative_path": "src/Thing.ts"},
            )
            lower = _insert_node(
                conn, **{**values, "qualified_id": f"file:{_path_key('src/thing.ts')}", "relative_path": "src/thing.ts"},
            )
            count = conn.execute(
                "SELECT COUNT(*) AS total FROM code_nodes WHERE snapshot_id = ? AND qualified_id = ?",
                (values["snapshot_id"], values["qualified_id"]),
            ).fetchone()["total"]

        self.assertEqual(first, second)
        self.assertEqual(count, 1)
        self.assertNotEqual(upper, lower)

    def test_import_resolution_is_language_aware_and_rejects_root_escape(self) -> None:
        from backend.app.core.code_structure import _module_file_index, _resolve_import

        index = _module_file_index({
            "lib/utils.ts": "node-utils",
            "some.module.js": "node-dotted-js",
            "django/db/utils.py": "node-python-relative",
            "flask/helpers.py": "node-python-absolute",
            "types/client.py": "node-python-runtime",
            "types/client.pyi": "node-python-stub",
        })

        self.assertEqual(_resolve_import("src/components/Button.tsx", "../../lib/utils", index), "lib/utils.ts")
        self.assertIsNone(_resolve_import("src/components/Button.tsx", "../../../outside", index))
        self.assertEqual(_resolve_import("src/main.js", "some.module.js", index), "some.module.js")
        self.assertEqual(_resolve_import("django/db/models/base.py", "..utils", index), "django/db/utils.py")
        self.assertEqual(_resolve_import("app.py", "flask.helpers", index), "flask/helpers.py")
        self.assertEqual(_resolve_import("app.py", "types.client", index), "types/client.pyi")

    def test_file_roles_and_context_terms_are_project_agnostic(self) -> None:
        from backend.app.api.routes.projects import _context_candidate_score, _context_query_terms
        from backend.app.core.projects import _file_role

        self.assertEqual(_file_role("pkg/test_auth.py", "test_auth.py"), "test")
        self.assertEqual(_file_role("pkg/auth_test.py", "auth_test.py"), "test")
        self.assertEqual(_file_role("src/__tests__/auth.ts", "auth.ts"), "test")
        self.assertEqual(_file_role("src/auth.spec.ts", "auth.spec.ts"), "test")
        self.assertEqual(_file_role("src/Button.stories.tsx", "button.stories.tsx"), "test")
        self.assertEqual(_file_role("types/api.pyi", "api.pyi"), "stub")
        self.assertEqual(_file_role("src/contest.py", "contest.py"), "source")
        self.assertEqual(_context_query_terms("How does useState work in the project?"), ["useState"])

        source = {"display_label": "useState", "qualified_id": "tsx:hooks:useState", "relative_path": "src/hooks.ts", "file_role": "source"}
        test = {**source, "relative_path": "src/__tests__/hooks.test.ts", "file_role": "test"}
        self.assertLess(_context_candidate_score(source, "useState"), _context_candidate_score(test, "useState"))

    def test_graph_search_exposes_snapshot_file_roles_for_context_ranking(self) -> None:
        from backend.app.api.routes.projects import _context_candidate_score
        from backend.app.core.project_graph import find_nodes

        (self.repo / "src" / "auth.test.ts").write_text(
            "export function authorize() { return false; }\n",
            encoding="utf-8",
        )
        project = _register_project(vault_id="vault-odin", root_path=str(self.repo), name="Sample", sync=True)
        matches = find_nodes(project["id"], "authorize", limit=10)
        roles = {match["file_role"] for match in matches if match["display_label"] == "authorize"}
        ranked = sorted(matches, key=lambda match: _context_candidate_score(match, "authorize"))

        self.assertEqual(roles, {"source", "test"})
        self.assertEqual(ranked[0]["file_role"], "source")

    def test_named_imports_and_barrel_exports_disambiguate_call_targets(self) -> None:
        from backend.app.core.database import connect

        (self.repo / "src" / "utils.ts").write_text(
            "export function target() { return 1; }\n",
            encoding="utf-8",
        )
        (self.repo / "src" / "other.ts").write_text(
            "export function target() { return 2; }\n",
            encoding="utf-8",
        )
        (self.repo / "src" / "index.ts").write_text(
            "export { target } from './utils';\n",
            encoding="utf-8",
        )
        (self.repo / "src" / "consumer.ts").write_text(
            "import { target as chosen } from './index';\nexport function invokeImported() { return chosen(); }\n",
            encoding="utf-8",
        )
        project = _register_project(vault_id="vault-odin", root_path=str(self.repo), name="Sample", sync=True)

        with connect() as conn:
            calls = conn.execute(
                """
                SELECT source.display_label AS source_label, target.display_label AS target_label,
                       target.relative_path AS target_path
                FROM code_edges edge
                JOIN code_nodes source ON source.id = edge.source_node_id
                JOIN code_nodes target ON target.id = edge.target_node_id
                WHERE edge.project_id = ? AND edge.snapshot_id = ? AND edge.edge_type = 'calls'
                  AND source.display_label = 'invokeImported'
                """,
                (project["id"], project["active_structure_snapshot_id"]),
            ).fetchall()

        self.assertEqual(
            [(row["source_label"], row["target_label"], row["target_path"]) for row in calls],
            [("invokeImported", "target", "src/utils.ts")],
        )

    def test_shortest_path_enforces_node_and_edge_budgets_without_overshoot(self) -> None:
        from backend.app.core.code_structure import _insert_edge, _insert_node
        from backend.app.core.database import connect, utc_now
        from backend.app.core.project_graph import shortest_path

        project = _register_project(vault_id="vault-odin", root_path=str(self.repo), name="Sample", sync=True)
        snapshot_id = project["active_structure_snapshot_id"]
        now = utc_now()
        with connect() as conn:
            source = _insert_node(
                conn, project_id=project["id"], snapshot_id=snapshot_id,
                qualified_id="budget:source", kind="function", language="Python",
                label="budgetSource", relative_path="budget.py", source_id=None,
                signature="budgetSource()", content_hash="source", now=now,
            )
            _insert_node(
                conn, project_id=project["id"], snapshot_id=snapshot_id,
                qualified_id="budget:target", kind="function", language="Python",
                label="budgetTarget", relative_path="budget.py", source_id=None,
                signature="budgetTarget()", content_hash="target", now=now,
            )
            for index in range(12):
                leaf = _insert_node(
                    conn, project_id=project["id"], snapshot_id=snapshot_id,
                    qualified_id=f"budget:leaf:{index}", kind="function", language="Python",
                    label=f"budgetLeaf{index}", relative_path="budget.py", source_id=None,
                    signature=f"budgetLeaf{index}()", content_hash=str(index), now=now,
                )
                _insert_edge(
                    conn, project["id"], snapshot_id, source, leaf, "calls", None, index + 1, now,
                )

        node_limited = shortest_path(
            project["id"], "budgetSource", "budgetTarget", max_nodes=10, max_edges=100,
        )
        edge_limited = shortest_path(
            project["id"], "budgetSource", "budgetTarget", max_nodes=100, max_edges=10,
        )

        self.assertEqual(node_limited["status"], "node_budget_exceeded")
        self.assertLessEqual(node_limited["visited_nodes"], 10)
        self.assertEqual(edge_limited["status"], "edge_budget_exceeded")
        self.assertLessEqual(edge_limited["examined_edges"], 10)

    def test_project_chat_session_persists_project_scope(self) -> None:
        from backend.app.api.routes.chat import create_chat_session
        from backend.app.core.projects import register_project
        from backend.app.schemas import ChatSessionCreate

        project = _register_project(vault_id="vault-odin", root_path=str(self.repo), name="Sample", sync=False)
        session = create_chat_session(
            ChatSessionCreate(vault_id="vault-odin", scope_project_id=project["id"])
        )

        self.assertEqual(session["scope_project_id"], project["id"])
        self.assertEqual(session["scope_cluster_id"], project["primary_cluster_id"])

    def test_graph_view_is_bounded_and_contains_evidence(self) -> None:
        from backend.app.core.project_graph import graph_view, graph_view_markdown
        from backend.app.core.projects import register_project

        project = _register_project(vault_id="vault-odin", root_path=str(self.repo), name="Sample", sync=True)
        view = graph_view(project["id"], mode="graph", query="authorize", max_depth=2, max_nodes=20)

        self.assertLessEqual(len(view["nodes"]), 20)
        self.assertTrue(any(node["label"] == "authorize" for node in view["nodes"]))
        self.assertTrue(any(edge["type"] in {"calls", "contains", "exports"} for edge in view["edges"]))
        self.assertEqual(view["direction"], "outbound")
        packet = graph_view_markdown(view)
        self.assertIn("# Odin Graph Context", packet)
        self.assertIn("authorize", packet)

    def test_graph_view_direction_prioritizes_the_requested_edge_orientation(self) -> None:
        from backend.app.core.code_structure import _insert_edge, _insert_node
        from backend.app.core.database import connect, utc_now
        from backend.app.core.project_graph import graph_view
        from backend.app.core.projects import register_project

        project = _register_project(vault_id="vault-odin", root_path=str(self.repo), name="Sample", sync=True)
        snapshot_id = project["active_snapshot_id"]
        now = utc_now()
        with connect() as conn:
            root = _insert_node(
                conn, project_id=project["id"], snapshot_id=snapshot_id,
                qualified_id="direction:root", kind="function", language="TypeScript",
                label="directionRoot", relative_path="src/direction.ts", source_id=None,
                signature="directionRoot()", content_hash="root", now=now,
            )
            for index in range(12):
                inbound = _insert_node(
                    conn, project_id=project["id"], snapshot_id=snapshot_id,
                    qualified_id=f"orientation:inbound:{index}", kind="function", language="TypeScript",
                    label=f"inboundCaller{index}", relative_path="src/inbound.ts", source_id=None,
                    signature=f"inboundCaller{index}()", content_hash=f"inbound-{index}", now=now,
                )
                outbound = _insert_node(
                    conn, project_id=project["id"], snapshot_id=snapshot_id,
                    qualified_id=f"orientation:outbound:{index}", kind="function", language="TypeScript",
                    label=f"outboundCallee{index}", relative_path="src/outbound.ts", source_id=None,
                    signature=f"outboundCallee{index}()", content_hash=f"outbound-{index}", now=now,
                )
                # Insert inbound first so insertion order cannot mask direction ordering.
                _insert_edge(conn, project["id"], snapshot_id, inbound, root, "calls", None, index + 1, now)
                _insert_edge(conn, project["id"], snapshot_id, root, outbound, "calls", None, index + 1, now)

        outbound_view = graph_view(
            project["id"], mode="graph", query="directionRoot", max_depth=1,
            max_nodes=10, direction="outbound",
        )
        inbound_view = graph_view(
            project["id"], mode="graph", query="directionRoot", max_depth=1,
            max_nodes=10, direction="inbound",
        )

        outbound_labels = {node["label"] for node in outbound_view["nodes"]}
        inbound_labels = {node["label"] for node in inbound_view["nodes"]}
        self.assertIn("directionRoot", outbound_labels)
        self.assertTrue(any(label.startswith("outboundCallee") for label in outbound_labels))
        self.assertFalse(any(label.startswith("inboundCaller") for label in outbound_labels))
        self.assertIn("directionRoot", inbound_labels)
        self.assertTrue(any(label.startswith("inboundCaller") for label in inbound_labels))
        self.assertFalse(any(label.startswith("outboundCallee") for label in inbound_labels))

    def test_tree_view_builds_hidden_project_file_symbol_hierarchy(self) -> None:
        from backend.app.core.project_graph import graph_view
        from backend.app.core.projects import register_project

        project = _register_project(vault_id="vault-odin", root_path=str(self.repo), name="Sample", sync=True)
        view = graph_view(project["id"], mode="tree", root="src", max_nodes=30)

        kinds = {node["kind"] for node in view["nodes"]}
        self.assertIn("project", kinds)
        self.assertIn("directory", kinds)
        self.assertIn("file", kinds)
        self.assertTrue(all(edge["type"] == "contains" for edge in view["edges"]))


if __name__ == "__main__":
    unittest.main()
