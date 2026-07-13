import os
import tempfile
import unittest
from pathlib import Path


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

        first = register_project(vault_id="vault-odin", root_path=str(self.repo), name="Sample", sync=True)
        second = register_project(vault_id="vault-odin", root_path=str(self.repo), name="Different", sync=False)

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

    def test_sync_reconciles_modified_added_and_removed_files(self) -> None:
        from backend.app.core.database import connect
        from backend.app.core.projects import register_project, sync_project

        project = register_project(vault_id="vault-odin", root_path=str(self.repo), name="Sample", sync=True)
        (self.repo / "src" / "auth.ts").unlink()
        (self.repo / "src" / "main.ts").write_text("export const start = () => 'updated';\n", encoding="utf-8")
        (self.repo / "src" / "routes.ts").write_text("export const routes = [];\n", encoding="utf-8")

        result = sync_project(project["id"])

        self.assertEqual(result["run"]["status"], "succeeded")
        self.assertEqual(result["project"]["source_count"], 3)
        with connect() as conn:
            deleted = conn.execute(
                "SELECT deleted_at FROM sources WHERE original_path = ?",
                (str(self.repo / "src" / "auth.ts"),),
            ).fetchone()
        self.assertIsNotNone(deleted["deleted_at"])

    def test_remove_deletes_only_cml_records(self) -> None:
        from backend.app.core.database import connect
        from backend.app.core.projects import register_project, remove_project

        project = register_project(vault_id="vault-odin", root_path=str(self.repo), name="Sample", sync=True)
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

        project = register_project(vault_id="vault-odin", root_path=str(self.repo), name="Sample", sync=True)
        result = shortest_path(project["id"], "start", "authorize")

        self.assertEqual(result["status"], "found")
        self.assertEqual([node["display_label"] for node in result["path"]], ["start", "authorize"])
        self.assertEqual(result["edges"][0]["edge_type"], "calls")

    def test_project_chat_session_persists_project_scope(self) -> None:
        from backend.app.api.routes.chat import create_chat_session
        from backend.app.core.projects import register_project
        from backend.app.schemas import ChatSessionCreate

        project = register_project(vault_id="vault-odin", root_path=str(self.repo), name="Sample", sync=False)
        session = create_chat_session(
            ChatSessionCreate(vault_id="vault-odin", scope_project_id=project["id"])
        )

        self.assertEqual(session["scope_project_id"], project["id"])
        self.assertEqual(session["scope_cluster_id"], project["primary_cluster_id"])

    def test_graph_view_is_bounded_and_contains_evidence(self) -> None:
        from backend.app.core.project_graph import graph_view, graph_view_markdown
        from backend.app.core.projects import register_project

        project = register_project(vault_id="vault-odin", root_path=str(self.repo), name="Sample", sync=True)
        view = graph_view(project["id"], mode="graph", query="authorize", max_depth=2, max_nodes=20)

        self.assertLessEqual(len(view["nodes"]), 20)
        self.assertTrue(any(node["label"] == "authorize" for node in view["nodes"]))
        self.assertTrue(any(edge["type"] in {"calls", "contains", "exports"} for edge in view["edges"]))
        packet = graph_view_markdown(view)
        self.assertIn("# Odin Graph Context", packet)
        self.assertIn("authorize", packet)

    def test_tree_view_builds_hidden_project_file_symbol_hierarchy(self) -> None:
        from backend.app.core.project_graph import graph_view
        from backend.app.core.projects import register_project

        project = register_project(vault_id="vault-odin", root_path=str(self.repo), name="Sample", sync=True)
        view = graph_view(project["id"], mode="tree", root="src", max_nodes=30)

        kinds = {node["kind"] for node in view["nodes"]}
        self.assertIn("project", kinds)
        self.assertIn("directory", kinds)
        self.assertIn("file", kinds)
        self.assertTrue(all(edge["type"] == "contains" for edge in view["edges"]))


if __name__ == "__main__":
    unittest.main()
