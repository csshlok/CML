from __future__ import annotations

import os
from functools import lru_cache

from backend.app.core.config import ROOT_DIR

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None


DEFAULT_APP_VERSION = "0.0.0"


@lru_cache(maxsize=1)
def app_version() -> str:
    override = str(os.getenv("CML_APP_VERSION") or "").strip()
    if override:
        return override
    if tomllib is None:
        return DEFAULT_APP_VERSION
    pyproject_path = ROOT_DIR / "backend" / "pyproject.toml"
    try:
        payload = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except OSError:
        return DEFAULT_APP_VERSION
    project = payload.get("project") if isinstance(payload, dict) else None
    version = project.get("version") if isinstance(project, dict) else None
    if isinstance(version, str) and version.strip():
        return version.strip()
    return DEFAULT_APP_VERSION
