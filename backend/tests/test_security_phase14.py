import unittest
from pathlib import Path


class SecurityPhase14ScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[2]

    def test_package_hardening_assets_are_wired_into_build(self) -> None:
        package_windows = (self.repo_root / "scripts" / "packaging" / "package-windows.ps1").read_text(encoding="utf-8")
        clean_machine = (self.repo_root / "scripts" / "packaging" / "validate-clean-machine-package.ps1").read_text(encoding="utf-8")

        self.assertIn("generate-helper-manifest.cjs", package_windows)
        self.assertIn("audit-package-layout.cjs", package_windows)
        self.assertIn("helper_manifest_exists", clean_machine)
        self.assertIn("package_layout_audit_exists", clean_machine)
        self.assertIn('"from": "packaging/helper-manifest.json"', package_windows)
        self.assertIn('"to": "helper-manifest.json"', package_windows)

    def test_phase14_security_runner_covers_required_smokes(self) -> None:
        runner = (self.repo_root / "scripts" / "security" / "run-security-e2e.ps1").read_text(encoding="utf-8")

        for required in (
            "npm run security:renderer",
            "audit-package-layout.cjs",
            "security-smoke-clean-vault.ps1",
            "security-smoke-large-vault.ps1",
            "security-drill-interrupted-flows.ps1",
            "inspect-offline-vault-at-rest.ps1",
        ):
            self.assertIn(required, runner)

    def test_phase14_smokes_record_scale_and_bridge_paths(self) -> None:
        clean_smoke = (self.repo_root / "scripts" / "security" / "security-smoke-clean-vault.ps1").read_text(encoding="utf-8")
        large_smoke = (self.repo_root / "scripts" / "security" / "security-smoke-large-vault.ps1").read_text(encoding="utf-8")
        offline_smoke = (self.repo_root / "scripts" / "security" / "inspect-offline-vault-at-rest.ps1").read_text(encoding="utf-8")

        self.assertIn("/api/v1/bridge/approval-requests", clean_smoke)
        self.assertIn("/api/v1/bridge/context", clean_smoke)
        self.assertIn("Sources = 2000", large_smoke)
        self.assertIn("/api/v1/integrations/imports/", large_smoke)
        self.assertIn("OFFLINE_VAULT_SECRET_MARKER", offline_smoke)
