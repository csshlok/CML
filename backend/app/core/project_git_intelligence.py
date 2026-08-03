from __future__ import annotations

from collections import Counter, defaultdict
from itertools import combinations
import json
from pathlib import Path
import re
import subprocess

from backend.app.core.database import connect, dict_from_row, utc_now


GIT_INTELLIGENCE_VERSION = "odin-git-intelligence-v1"
_FIX_WORDS = re.compile(r"\b(fix(?:e[ds])?|bug|regression|hotfix|repair)\b", re.IGNORECASE)


def refresh_git_intelligence(
    project_id: str, *, max_commits: int = 1000, max_pairs: int = 5000
) -> dict:
    """Capture bounded repository history and the current worktree without executing repository code."""
    limit = max(1, min(int(max_commits), 5000))
    now = utc_now()
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM projects WHERE id = ? AND deleted_at IS NULL", (project_id,)
        ).fetchone()
        if row is None:
            raise KeyError(project_id)
        project = dict_from_row(row)
        root = Path(str(project["root_path"])).resolve()
        owning_snapshot = project.get("active_manifest_snapshot_id") or project.get(
            "active_snapshot_id"
        )
        indexed_paths = {
            _normal_path(str(item["relative_path"]))
            for item in conn.execute(
                "SELECT relative_path FROM project_sources WHERE project_id = ?", (project_id,)
            )
        }

    repository = _git(root, "rev-parse", "--is-inside-work-tree")
    if repository.returncode != 0 or repository.stdout.strip() != "true":
        return _store_git_snapshot(
            project,
            owning_snapshot,
            now,
            indexed_paths=indexed_paths,
            error_detail="The project folder is not a Git worktree.",
        )

    head = _git_text(root, "rev-parse", "HEAD")
    branch = _git_text(root, "branch", "--show-current") or "detached"
    shallow = _git_text(root, "rev-parse", "--is-shallow-repository") == "true"
    total_text = _git_text(root, "rev-list", "--count", "HEAD")
    total_commits = int(total_text) if total_text.isdigit() else 0
    history_truncated = total_commits > limit
    log = _git(
        root,
        "log",
        "--no-merges",
        f"-n{limit}",
        "--date=iso-strict",
        "--format=%x1e%H%x1f%an%x1f%aI%x1f%s",
        "--numstat",
    )
    commits = _parse_log(log.stdout) if log.returncode == 0 else []
    file_signals: dict[str, dict] = {}
    authors: dict[str, Counter] = defaultdict(Counter)
    pair_counts: Counter = Counter()
    for commit in commits:
        paths = sorted({item[0] for item in commit["files"]})
        if len(paths) <= 50:
            pair_counts.update(combinations(paths, 2))
        for path, additions, deletions in commit["files"]:
            signal = file_signals.setdefault(
                path,
                {
                    "additions": 0,
                    "deletions": 0,
                    "commit_count": 0,
                    "bugfix_commit_count": 0,
                    "last_commit_id": commit["id"],
                    "last_commit_at": commit["at"],
                    "last_commit_subject": commit["subject"],
                },
            )
            signal["additions"] += additions
            signal["deletions"] += deletions
            signal["commit_count"] += 1
            signal["bugfix_commit_count"] += int(bool(_FIX_WORDS.search(commit["subject"])))
            authors[path][commit["author"]] += 1
    for path, signal in file_signals.items():
        total = max(1, signal["commit_count"])
        signal["ownership"] = [
            {"author": author, "commits": count, "share": round(count / total, 4)}
            for author, count in sorted(
                authors[path].items(), key=lambda item: (-item[1], item[0].casefold())
            )
        ]

    live_state = _live_state(root, indexed_paths)
    live_state.update(
        {
            "head_commit": head or None,
            "branch": branch,
            "indexed_commit": project.get("indexed_commit"),
            "indexed_relation": _commit_relation(root, project.get("indexed_commit"), head),
        }
    )
    recent = [
        {key: commit[key] for key in ("id", "author", "at", "subject")} for commit in commits[:20]
    ]
    return _store_git_snapshot(
        project,
        owning_snapshot,
        now,
        indexed_paths=indexed_paths,
        head=head,
        branch=branch,
        shallow=shallow,
        history_truncated=history_truncated,
        total_commits=total_commits,
        live_state=live_state,
        recent_commits=recent,
        file_signals=file_signals,
        pair_counts=pair_counts.most_common(max(1, min(int(max_pairs), 20_000))),
        error_detail="" if log.returncode == 0 else _safe_error(log.stderr),
    )


def get_project_repository_state(project_id: str) -> dict:
    with connect() as conn:
        project = conn.execute(
            "SELECT id, root_path, indexed_commit FROM projects WHERE id = ? AND deleted_at IS NULL",
            (project_id,),
        ).fetchone()
        if project is None:
            raise KeyError(project_id)
        indexed_paths = {
            _normal_path(str(value["relative_path"]))
            for value in conn.execute(
                "SELECT relative_path FROM project_sources WHERE project_id = ?", (project_id,)
            )
        }
        row = conn.execute(
            "SELECT * FROM project_git_snapshots WHERE project_id = ? ORDER BY generated_at DESC LIMIT 1",
            (project_id,),
        ).fetchone()
        if row is None:
            return {
                "status": "unavailable",
                "unknown_reason": "Git intelligence has not been refreshed.",
            }
        item = dict_from_row(row)
        signals = [
            dict_from_row(value)
            for value in conn.execute(
                "SELECT * FROM project_git_file_signals WHERE git_snapshot_id = ? ORDER BY commit_count DESC, relative_path LIMIT 200",
                (item["id"],),
            )
        ]
        cochange = [
            dict_from_row(value)
            for value in conn.execute(
                "SELECT * FROM project_cochange_edges WHERE git_snapshot_id = ? ORDER BY touch_count DESC, source_path, target_path LIMIT 200",
                (item["id"],),
            )
        ]
    for signal in signals:
        signal["ownership"] = _loads(signal.pop("ownership_json"), [])
    item["live_state"] = _loads(item.pop("live_state_json"), {})
    root = Path(str(project["root_path"])).resolve()
    if _git(root, "rev-parse", "--is-inside-work-tree").returncode == 0:
        head = _git_text(root, "rev-parse", "HEAD")
        live_state = _live_state(root, indexed_paths)
        live_state.update(
            {
                "head_commit": head or None,
                "branch": _git_text(root, "branch", "--show-current") or "detached",
                "indexed_commit": project["indexed_commit"],
                "indexed_relation": _commit_relation(root, project["indexed_commit"], head),
            }
        )
        item["live_state"] = live_state
    item["recent_commits"] = _loads(item.pop("recent_commits_json"), [])
    item["history_available"] = bool(item["history_available"])
    item["history_truncated"] = bool(item["history_truncated"])
    item["shallow_history"] = bool(item["shallow_history"])
    item["file_signals"] = signals
    item["cochange"] = cochange
    item["status"] = "ready" if item["history_available"] else "unavailable"
    return item


def _store_git_snapshot(
    project: dict,
    owning_snapshot: str | None,
    now: str,
    *,
    indexed_paths: set[str],
    head: str = "",
    branch: str = "",
    shallow: bool = False,
    history_truncated: bool = False,
    total_commits: int = 0,
    live_state: dict | None = None,
    recent_commits: list | None = None,
    file_signals: dict | None = None,
    pair_counts: list | None = None,
    error_detail: str = "",
) -> dict:
    snapshot_key = owning_snapshot or "unindexed"
    snapshot_id = f"git-intelligence-{project['id']}-{snapshot_key}"
    file_signals = file_signals or {}
    live_state = live_state or {
        "files": [],
        "counts": {},
        "represented_file_count": len(indexed_paths),
    }
    with connect() as conn:
        conn.execute("DELETE FROM project_git_snapshots WHERE id = ?", (snapshot_id,))
        conn.execute(
            """INSERT INTO project_git_snapshots
            (id, project_id, owning_snapshot_id, indexed_commit, head_commit, branch, history_available,
             history_truncated, shallow_history, commit_count, live_state_json, recent_commits_json,
             error_detail, generated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                snapshot_id,
                project["id"],
                owning_snapshot,
                project.get("indexed_commit"),
                head or None,
                branch,
                int(bool(head)),
                int(history_truncated),
                int(shallow),
                total_commits,
                _json(live_state),
                _json(recent_commits or []),
                error_detail,
                now,
            ),
        )
        for path, signal in sorted(file_signals.items()):
            conn.execute(
                """INSERT INTO project_git_file_signals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    project["id"],
                    snapshot_id,
                    path,
                    signal["additions"],
                    signal["deletions"],
                    signal["commit_count"],
                    signal["bugfix_commit_count"],
                    signal["last_commit_id"],
                    signal["last_commit_at"],
                    signal["last_commit_subject"],
                    _json(signal["ownership"]),
                    int(history_truncated),
                ),
            )
        for (source, target), count in pair_counts or []:
            conn.execute(
                "INSERT INTO project_cochange_edges VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    project["id"],
                    snapshot_id,
                    source,
                    target,
                    count,
                    "heuristic",
                    "historical_cochange_not_dependency",
                ),
            )
        summary = {
            "status": "ready" if head else "unavailable",
            "head_commit": head or None,
            "branch": branch or None,
            "indexed_relation": live_state.get("indexed_relation", "unknown"),
            "history_available": bool(head),
            "history_truncated": history_truncated,
            "shallow_history": shallow,
            "commit_count": total_commits,
            "changed_file_count": len(live_state.get("files", [])),
            "error_detail": error_detail,
        }
        intelligence = conn.execute(
            "SELECT id, layer_states_json, freshness_json FROM project_intelligence_snapshots WHERE project_id = ? AND owning_snapshot_id = ?",
            (project["id"], owning_snapshot),
        ).fetchone()
        if intelligence:
            layers = _loads(intelligence["layer_states_json"], {})
            layers["repository_signals"] = {
                "status": "ready" if head else "unavailable",
                "version": GIT_INTELLIGENCE_VERSION,
                "generated_at": now,
                "truncated": history_truncated,
                "unknown_reason": None if head else {"code": "not_git", "detail": error_detail},
            }
            freshness = _loads(intelligence["freshness_json"], {})
            freshness["live_head_commit"] = head or None
            conn.execute(
                "UPDATE project_intelligence_snapshots SET repository_signals_json = ?, layer_states_json = ?, freshness_json = ? WHERE id = ?",
                (_json(summary), _json(layers), _json(freshness), intelligence["id"]),
            )
    return get_project_repository_state(str(project["id"]))


def _parse_log(text: str) -> list[dict]:
    commits: list[dict] = []
    for block in text.split("\x1e"):
        block = block.strip("\r\n")
        if not block:
            continue
        lines = block.splitlines()
        header = lines[0].split("\x1f", 3)
        if len(header) != 4:
            continue
        files = []
        for line in lines[1:]:
            fields = line.split("\t", 2)
            if len(fields) != 3:
                continue
            additions = int(fields[0]) if fields[0].isdigit() else 0
            deletions = int(fields[1]) if fields[1].isdigit() else 0
            files.append((_normal_path(_flatten_rename(fields[2])), additions, deletions))
        commits.append(
            {
                "id": header[0],
                "author": header[1],
                "at": header[2],
                "subject": header[3][:500],
                "files": files,
            }
        )
    return commits


def _live_state(root: Path, indexed_paths: set[str]) -> dict:
    result = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    entries = result.stdout.split("\0") if result.returncode == 0 else []
    files, counts = [], Counter()
    index = 0
    while index < len(entries):
        raw = entries[index]
        index += 1
        if not raw or len(raw) < 4:
            continue
        xy, path = raw[:2], _normal_path(raw[3:])
        if xy[0] in "RC" and index < len(entries):
            path = _normal_path(entries[index])
            index += 1
        states = []
        if xy == "??":
            states = ["untracked"]
        else:
            if xy[0] not in " ?":
                states.append("staged")
            if xy[1] not in " ?":
                states.append("unstaged")
            if "R" in xy:
                states.append("renamed")
            if "D" in xy:
                states.append("deleted")
        for state in states:
            counts[state] += 1
        files.append(
            {
                "relative_path": path,
                "status": states,
                "represented_in_index": path in indexed_paths,
                "active_content_current": False,
            }
        )
    return {
        "files": files,
        "counts": dict(sorted(counts.items())),
        "represented_file_count": len(indexed_paths),
        "truncated": False,
    }


def _commit_relation(root: Path, indexed: object, head: str) -> str:
    indexed_value = str(indexed or "")
    if not indexed_value or not head:
        return "unknown"
    if indexed_value == head:
        return "equal"
    if _git(root, "merge-base", "--is-ancestor", indexed_value, head).returncode == 0:
        return "behind"
    if _git(root, "merge-base", "--is-ancestor", head, indexed_value).returncode == 0:
        return "ahead"
    return "diverged"


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(args, 1, "", str(exc))


def _git_text(root: Path, *args: str) -> str:
    result = _git(root, *args)
    return result.stdout.strip() if result.returncode == 0 else ""


def _flatten_rename(path: str) -> str:
    # Git may abbreviate renames as src/{old => new}/file.py.
    match = re.search(r"\{[^{}]* => ([^{}]*)\}", path)
    if match:
        path = path[: match.start()] + match.group(1) + path[match.end() :]
    elif " => " in path:
        path = path.rsplit(" => ", 1)[1]
    return path


def _normal_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def _safe_error(value: str) -> str:
    return re.sub(r"[\r\n]+", " ", value).strip()[:500]


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _loads(value: object, fallback: object):
    try:
        return json.loads(str(value))
    except (TypeError, ValueError):
        return fallback
