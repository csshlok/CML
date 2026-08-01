from __future__ import annotations

import hashlib
import json
from pathlib import Path

from backend.app.core.database import connect, dict_from_row, utc_now


COVERAGE_FORMAT = "lcov"
COVERAGE_VERSION = "odin-lcov-v1"


def parse_lcov(text: str, *, root_path: str, indexed_paths: set[str] | None = None) -> dict:
    """Parse LCOV records, preserving per-test mappings when TN records are present."""
    root = Path(root_path).resolve()
    records, current = [], {"test_name": "", "source": "", "lines": {}}
    for raw in text.replace("\r\n", "\n").splitlines():
        if raw.startswith("TN:"):
            current["test_name"] = raw[3:].strip()
        elif raw.startswith("SF:"):
            if current["source"]: records.append(current)
            current = {"test_name": current["test_name"], "source": raw[3:].strip(), "lines": {}}
        elif raw.startswith("DA:") and current["source"]:
            fields = raw[3:].split(",")
            if len(fields) >= 2 and fields[0].isdigit() and fields[1].isdigit():
                current["lines"][int(fields[0])] = int(fields[1])
        elif raw == "end_of_record" and current["source"]:
            records.append(current)
            current = {"test_name": "", "source": "", "lines": {}}
    if current["source"]: records.append(current)
    files: dict[str, dict[str, set[int]]] = {}
    tests = []
    for record in records:
        path = _coverage_path(str(record["source"]), root, indexed_paths=indexed_paths)
        if path is None: continue
        covered = {line for line, hits in record["lines"].items() if hits > 0}
        missed = {line for line, hits in record["lines"].items() if hits == 0}
        merged = files.setdefault(path, {"covered": set(), "missed": set()})
        merged["covered"].update(covered)
        merged["missed"].update(missed)
        merged["missed"].difference_update(merged["covered"])
        if record["test_name"]:
            tests.append({"test_name": str(record["test_name"])[:500], "test_path": _test_path(str(record["test_name"])),
                          "source_path": path, "covered_lines": sorted(covered)})
    return {"files": {path: {"covered_lines": sorted(value["covered"]), "missed_lines": sorted(value["missed"])}
                      for path, value in sorted(files.items())},
            "tests": sorted(tests, key=lambda item: (item["test_name"], item["source_path"]))}


def import_project_coverage(project_id: str, artifact_path: str) -> dict:
    artifact = Path(artifact_path).resolve()
    with connect() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id=? AND deleted_at IS NULL", (project_id,)).fetchone()
        if row is None: raise KeyError(project_id)
        project = dict_from_row(row)
        indexed_paths = {_normal_path(item["relative_path"]) for item in conn.execute(
            "SELECT relative_path FROM project_sources WHERE project_id=?", (project_id,)
        )}
    if artifact.suffix.lower() not in {".info", ".lcov"}: raise ValueError("Coverage must be an LCOV .info or .lcov file.")
    try: text = artifact.read_text(encoding="utf-8", errors="replace")
    except OSError as exc: raise ValueError(f"Coverage artifact could not be read: {exc}") from exc
    parsed = parse_lcov(text, root_path=str(project["root_path"]), indexed_paths=indexed_paths)
    now = utc_now()
    owning = project.get("active_manifest_snapshot_id") or project.get("active_snapshot_id")
    digest = hashlib.sha256(text.encode()).hexdigest()
    coverage_id = f"coverage-{project_id}-{digest[:24]}"
    with connect() as conn:
        conn.execute("DELETE FROM project_coverage_snapshots WHERE id=?", (coverage_id,))
        conn.execute("""INSERT INTO project_coverage_snapshots VALUES (?, ?, ?, ?, ?, 'lcov', ?, ?, ?, ?, ?)""",
                     (coverage_id, project_id, owning, project.get("indexed_commit"), str(artifact),
                      "ready" if parsed["files"] else "empty", len(parsed["files"]),
                      len({item["test_name"] for item in parsed["tests"]}), now, now))
        for path, coverage in parsed["files"].items():
            conn.execute("INSERT INTO project_coverage_files VALUES (?, ?, ?, ?, ?)",
                         (coverage_id, project_id, path, _json(coverage["covered_lines"]), _json(coverage["missed_lines"])))
        for item in parsed["tests"]:
            conn.execute("INSERT OR REPLACE INTO project_coverage_test_map VALUES (?, ?, ?, ?, ?, ?)",
                         (coverage_id, project_id, item["test_name"], item["test_path"], item["source_path"],
                          _json(item["covered_lines"])))
    return get_project_coverage(project_id)


def get_project_coverage(project_id: str) -> dict:
    with connect() as conn:
        if conn.execute("SELECT id FROM projects WHERE id=? AND deleted_at IS NULL", (project_id,)).fetchone() is None:
            raise KeyError(project_id)
        row = conn.execute("SELECT * FROM project_coverage_snapshots WHERE project_id=? ORDER BY generated_at DESC LIMIT 1",
                           (project_id,)).fetchone()
        if row is None: return {"project_id": project_id, "status": "unknown", "unknown_reason": "No LCOV artifact has been imported."}
        result = dict_from_row(row)
        result["files"] = [{**dict_from_row(item), "covered_lines": _loads(item["covered_lines_json"]),
                            "missed_lines": _loads(item["missed_lines_json"])} for item in conn.execute(
            "SELECT * FROM project_coverage_files WHERE coverage_snapshot_id=? ORDER BY relative_path", (result["id"],))]
        for item in result["files"]: item.pop("covered_lines_json"); item.pop("missed_lines_json")
        result["has_per_test_mapping"] = bool(conn.execute(
            "SELECT 1 FROM project_coverage_test_map WHERE coverage_snapshot_id=? LIMIT 1", (result["id"],)).fetchone())
        return result


def calculate_test_impact(project_id: str, *, changed_paths: list[str], changed_lines: dict[str, list[int]] | None = None) -> dict:
    changed = sorted({_normal_path(path) for path in changed_paths})
    line_map = {_normal_path(path): set(lines) for path, lines in (changed_lines or {}).items()}
    with connect() as conn:
        snapshot = conn.execute("SELECT * FROM project_coverage_snapshots WHERE project_id=? ORDER BY generated_at DESC LIMIT 1",
                                (project_id,)).fetchone()
        if snapshot is None:
            return {"status": "unknown", "exact_tests": [], "guessed_tests": [],
                    "unknown_reason": "No coverage map is available; Odin will not present guesses as coverage."}
        rows = conn.execute("SELECT * FROM project_coverage_test_map WHERE coverage_snapshot_id=? ORDER BY test_path, test_name",
                            (snapshot["id"],)).fetchall()
    exact = {}
    for row in rows:
        source = _normal_path(row["source_path"])
        if source not in changed: continue
        mapped = set(_loads(row["covered_lines_json"]))
        if source in line_map and line_map[source] and not (mapped & line_map[source]): continue
        key = (row["test_path"], row["test_name"])
        exact.setdefault(key, set()).add(source)
    exact_tests = [{"test_path": key[0], "test_name": key[1], "matched_sources": sorted(paths),
                    "confidence_class": "coverage_exact"} for key, paths in sorted(exact.items())]
    guesses = _filename_guesses(changed) if not rows else []
    stale = snapshot["indexed_commit"] is not None and snapshot["indexed_commit"] != _project_commit(project_id)
    return {"status": "stale" if stale else "ready", "coverage_snapshot_id": snapshot["id"],
            "exact_tests": exact_tests, "guessed_tests": guesses,
            "known_empty": bool(rows) and not exact_tests, "has_per_test_mapping": bool(rows),
            "warning": "Coverage was produced for a different indexed commit." if stale else None}


def _filename_guesses(paths: list[str]) -> list[dict]:
    return [{"test_path": None, "source_path": path, "search_hint": Path(path).stem,
             "confidence_class": "filename_guess_not_coverage"} for path in paths[:50]]


def _project_commit(project_id: str) -> str | None:
    with connect() as conn:
        row = conn.execute("SELECT indexed_commit FROM projects WHERE id=?", (project_id,)).fetchone()
        return row["indexed_commit"] if row else None


def _coverage_path(value: str, root: Path, *, indexed_paths: set[str] | None = None) -> str | None:
    path = Path(value)
    try:
        absolute = path.resolve() if path.is_absolute() else (root / path).resolve()
        relative = absolute.relative_to(root).as_posix()
        if indexed_paths is not None and relative not in indexed_paths and "/" not in relative:
            matches = sorted(path for path in indexed_paths if Path(path).name == relative)
            return matches[0] if len(matches) == 1 else None
        return relative
    except ValueError: return None


def _test_path(name: str) -> str:
    candidate = name.split("::", 1)[0].replace("\\", "/")
    return candidate if "/" in candidate or candidate.endswith((".py", ".ts", ".tsx", ".js", ".jsx")) else ""
def _normal_path(path: str) -> str: return str(path).replace("\\", "/").lstrip("./")
def _json(value: object) -> str: return json.dumps(value, separators=(",", ":"))
def _loads(value: object):
    try: return json.loads(str(value))
    except (TypeError, ValueError): return []
