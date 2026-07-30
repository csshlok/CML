from __future__ import annotations

from pathlib import Path

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[2]
TURBOVEC_PIN = "turbovec==0.8.0"


def test_turbovec_is_pinned_across_backend_and_windows_packaging() -> None:
    assert TURBOVEC_PIN in (REPO_ROOT / "backend" / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    assert TURBOVEC_PIN in (
        REPO_ROOT / "requirements" / "contributors-backend.txt"
    ).read_text(encoding="utf-8")
    packaging = (
        REPO_ROOT / "scripts" / "packaging" / "package-windows.ps1"
    ).read_text(encoding="utf-8")
    assert TURBOVEC_PIN in packaging
    assert "from turbovec import IdMapIndex" in packaging
    assert "Lib\\site-packages\\turbovec" in packaging

    preflight = (
        REPO_ROOT / "scripts" / "packaging" / "check-windows-dev-build.ps1"
    ).read_text(encoding="utf-8")
    assert "'turbovec'" in preflight

    layout_audit = (
        REPO_ROOT / "scripts" / "packaging" / "audit-package-layout.cjs"
    ).read_text(encoding="utf-8")
    assert '"turbovec"' in layout_audit
    assert "runtime_dependencies_ok" in layout_audit

    packaged_smoke = (
        REPO_ROOT / "scripts" / "packaging" / "smoke-packaged-runtime.ps1"
    ).read_text(encoding="utf-8")
    assert "from turbovec import IdMapIndex" in packaged_smoke
    assert "turbovec_runtime_available" in packaged_smoke

    clean_machine = (
        REPO_ROOT / "scripts" / "packaging" / "validate-clean-machine-package.ps1"
    ).read_text(encoding="utf-8")
    assert "turbovec_runtime_exists" in clean_machine


def test_default_vector_policy_is_auto() -> None:
    from backend.app.core.config import Settings

    assert Settings(_env_file=None).vector_search_backend == "auto"


def test_real_turbovec_id_map_round_trip(tmp_path: Path) -> None:
    from turbovec import IdMapIndex

    vectors = np.ascontiguousarray(
        np.array(
            [
                [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            ],
            dtype=np.float32,
        )
    )
    ids = np.ascontiguousarray(np.array([101, 202], dtype=np.uint64))
    index = IdMapIndex(dim=8, bit_width=4)
    index.add_with_ids(vectors, ids)
    index.prepare()
    index_path = tmp_path / "contract.tvim"
    index.write(str(index_path))

    loaded = IdMapIndex.load(str(index_path))
    scores, result_ids = loaded.search(vectors[0:1], k=1)

    assert scores.shape == (1, 1)
    assert result_ids.tolist() == [[101]]
