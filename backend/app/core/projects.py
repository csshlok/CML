from __future__ import annotations

import fnmatch
import hashlib
import html
import json
import os
import re
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from backend.app.core.background_jobs import cancel_jobs_for_scope, enqueue_job
from backend.app.core.code_structure import STRUCTURE_EXTRACTOR_VERSION
from backend.app.core.database import connect, dict_from_row, utc_now
from backend.app.core.extractor_registry import extractor_fingerprint
from backend.app.core.pagination import cursor_page, decode_cursor


EXTRACTOR_VERSION = (
    f"odin-manifest-v2+{STRUCTURE_EXTRACTOR_VERSION}+{extractor_fingerprint()}"
)
MAX_FILE_BYTES = 1_000_000
MAX_IGNORE_FILE_BYTES = 1_000_000


def _read_bounded_bytes(path: Path, max_bytes: int = MAX_FILE_BYTES) -> bytes:
    """Read at most the admitted project-file budget, including growth races."""
    with path.open("rb") as handle:
        payload = handle.read(max_bytes + 1)
    if len(payload) > max_bytes:
        raise ValueError("Project file exceeds the indexing size limit")
    return payload


def _safe_git_run(command: list[str], **kwargs):
    """Run Git without user/system command-bearing configuration."""
    if not command or Path(command[0]).name.casefold() not in {"git", "git.exe"}:
        raise ValueError("safe Git runner only accepts Git commands")
    command_tail = list(command[1:])
    if "diff" in command_tail:
        diff_index = command_tail.index("diff") + 1
        command_tail[diff_index:diff_index] = ["--no-ext-diff", "--no-textconv"]
    hardened = [
        command[0],
        "-c", "core.fsmonitor=false",
        "-c", f"core.hooksPath={os.devnull}",
        "-c", "diff.external=",
        "-c", "core.pager=cat",
        *command_tail,
    ]
    env = os.environ.copy()
    env.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_ATTR_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_PAGER": "cat",
            "GIT_EXTERNAL_DIFF": "",
        }
    )
    kwargs["env"] = env
    return subprocess.run(hardened, **kwargs)
DEFAULT_IGNORED_DIRECTORIES = {
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".tmp",
    ".venv",
    "__pycache__",
    "bin",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "obj",
    "target",
    "vendor",
    "venv",
}
SECRET_SUFFIXES = {".key", ".pem", ".p12", ".pfx", ".jks", ".keystore"}
SECRET_NAMES = {
    ".env",
    "credentials",
    "credentials.json",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "id_rsa",
    "secrets.json",
}
SUPPORTED_EXTENSIONS = {
    ".c",
    ".cc",
    ".cfg",
    ".clj",
    ".cljs",
    ".cmake",
    ".conf",
    ".cpp",
    ".cs",
    ".css",
    ".csv",
    ".dart",
    ".ex",
    ".exs",
    ".go",
    ".graphql",
    ".gql",
    ".h",
    ".hpp",
    ".html",
    ".ini",
    ".java",
    ".js",
    ".cjs",
    ".json",
    ".jsx",
    ".kt",
    ".kts",
    ".lua",
    ".md",
    ".mdx",
    ".mjs",
    ".mts",
    ".php",
    ".prisma",
    ".properties",
    ".proto",
    ".ps1",
    ".py",
    ".pyi",
    ".rb",
    ".rs",
    ".scala",
    ".scss",
    ".sh",
    ".sql",
    ".svelte",
    ".swift",
    ".toml",
    ".ts",
    ".cts",
    ".tsx",
    ".txt",
    ".vue",
    ".xml",
    ".yaml",
    ".yml",
}
SUPPORTED_FILENAMES = {
    "dockerfile",
    "gemfile",
    "makefile",
    "procfile",
    "rakefile",
}
DISCOVERY_SCOPES = frozenset({"context", "code"})
CODE_EXTENSIONS = {
    ".c", ".cc", ".clj", ".cljs", ".cpp", ".cs", ".dart", ".ex", ".exs",
    ".go", ".graphql", ".gql", ".h", ".hpp", ".java", ".js", ".cjs", ".json", ".jsx",
    ".kt", ".kts", ".lua", ".php", ".prisma", ".proto", ".ps1", ".py", ".pyi", ".rb",
    ".rs", ".scala", ".sh", ".sql", ".svelte", ".swift", ".mjs", ".mts",
    ".ts", ".cts", ".tsx", ".vue",
}
GENERATED_FILENAMES = {
    "bun.lock",
    "composer.lock",
    "package-lock.json",
    "pnpm-lock.yaml",
    "poetry.lock",
    "uv.lock",
    "yarn.lock",
}
LANGUAGE_BY_EXTENSION = {
    ".c": "C",
    ".cc": "C++",
    ".cpp": "C++",
    ".cs": "C#",
    ".css": "CSS",
    ".dart": "Dart",
    ".ex": "Elixir",
    ".exs": "Elixir",
    ".go": "Go",
    ".h": "C/C++",
    ".hpp": "C++",
    ".html": "HTML",
    ".java": "Java",
    ".js": "JavaScript",
    ".cjs": "JavaScript",
    ".jsx": "JavaScript",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".lua": "Lua",
    ".md": "Markdown",
    ".mdx": "Markdown",
    ".mjs": "JavaScript",
    ".mts": "TypeScript",
    ".php": "PHP",
    ".ps1": "PowerShell",
    ".py": "Python",
    ".pyi": "Python",
    ".rb": "Ruby",
    ".rs": "Rust",
    ".scala": "Scala",
    ".scss": "SCSS",
    ".sh": "Shell",
    ".sql": "SQL",
    ".svelte": "Svelte",
    ".swift": "Swift",
    ".ts": "TypeScript",
    ".cts": "TypeScript",
    ".tsx": "TypeScript",
    ".vue": "Vue",
}
ENTRYPOINT_NAMES = {
    "app.py",
    "main.go",
    "main.py",
    "main.rs",
    "main.ts",
    "main.tsx",
    "server.js",
    "server.py",
    "server.ts",
}


class ProjectError(ValueError):
    pass


@dataclass(frozen=True)
class ManifestFile:
    absolute_path: Path
    relative_path: str
    content_hash: str
    text: str
    language: str
    file_role: str


@dataclass(frozen=True)
class DiscoveryResult:
    files: list[ManifestFile]
    ignored_count: int
    generated_count: int
    failed_count: int
    languages: dict[str, int]
    entrypoints: list[str]
    workspace_count: int
    manifest_hash: str
    discovery_scope: str = "context"


def normalize_root_path(value: str) -> Path:
    root = Path(value).expanduser()
    if not root.exists():
        raise ProjectError("Project path does not exist.")
    if not root.is_dir():
        raise ProjectError("Project path must be a directory.")
    try:
        return root.resolve(strict=True)
    except OSError as exc:
        raise ProjectError("Project path could not be resolved safely.") from exc


def root_fingerprint(root: Path) -> str:
    normalized = os.path.normcase(os.path.normpath(str(root)))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def project_discovery_policy_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for filename in (".cmlignore", ".gitignore"):
        path = root / filename
        digest.update(f"{filename}\0".encode("utf-8"))
        try:
            digest.update(_read_bounded_bytes(path, MAX_IGNORE_FILE_BYTES))
        except FileNotFoundError:
            digest.update(b"<missing>")
        except OSError:
            digest.update(b"<unreadable>")
        digest.update(b"\0")
    return digest.hexdigest()


def project_change_fingerprint(root: Path) -> str:
    """Detect working-tree deltas without parsing or indexing project content."""

    if (root / ".git").exists():
        try:
            status = _safe_git_run(
                ["git", "-C", str(root), "status", "--porcelain=v1", "--untracked-files=all"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=8,
                check=False,
            )
            head = _safe_git_run(
                ["git", "-C", str(root), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                encoding="ascii",
                errors="replace",
                timeout=5,
                check=False,
            )
            if status.returncode == 0:
                return hashlib.sha256(
                    f"{head.stdout.strip()}\n{status.stdout}".encode("utf-8")
                ).hexdigest()
        except (OSError, subprocess.SubprocessError):
            pass

    digest = hashlib.sha256()
    for current_root, directory_names, file_names in os.walk(root):
        directory_names[:] = sorted(
            name
            for name in directory_names
            if name.casefold() not in DEFAULT_IGNORED_DIRECTORIES
        )
        current = Path(current_root)
        for file_name in sorted(file_names):
            path = current / file_name
            try:
                relative = path.relative_to(root).as_posix()
                stat = path.stat()
            except OSError:
                continue
            digest.update(relative.casefold().encode("utf-8", errors="replace"))
            digest.update(f":{stat.st_size}:{stat.st_mtime_ns}\n".encode("ascii"))
    return digest.hexdigest()


def inspect_project_changes(project_id: str, *, max_paths: int = 5000) -> dict:
    project = get_project(project_id)
    root = normalize_root_path(project["root_path"])
    bounded_max_paths = max(1, min(int(max_paths), 20_000))
    fingerprint = project_change_fingerprint(root)
    repository_paths, repository_detection_mode, repository_truncated = _project_changed_paths(
        root,
        max_paths=bounded_max_paths,
        baseline_commit=str(project.get("indexed_commit") or "") or None,
    )
    previous = str(project.get("change_fingerprint") or "")
    repository_items = _project_change_items(
        root,
        baseline_commit=str(project.get("indexed_commit") or "") or None,
        max_paths=bounded_max_paths,
    )
    snapshot_delta = _project_snapshot_delta(
        project=project,
        root=root,
        repository_paths=repository_paths,
        repository_items=repository_items,
        repository_detection_mode=repository_detection_mode,
        repository_truncated=repository_truncated,
        max_paths=bounded_max_paths,
    )
    return {
        "project_id": project_id,
        "changed": bool(snapshot_delta["changed_path_count"]),
        "change_fingerprint": fingerprint,
        "previous_fingerprint": previous,
        "fingerprint_changed": bool(previous and previous != fingerprint),
        "detection_mode": snapshot_delta["detection_mode"],
        "changed_paths": snapshot_delta["changed_paths"],
        "change_items": snapshot_delta["change_items"],
        "changed_path_count": snapshot_delta["changed_path_count"],
        "truncated": snapshot_delta["truncated"],
        "requires_full_scan": snapshot_delta["requires_full_scan"],
        "repository_detection_mode": repository_detection_mode,
        "repository_changed_paths": repository_paths,
        "repository_change_items": repository_items,
        "repository_changed_path_count": len(repository_paths),
        "repository_truncated": repository_truncated,
        "working_tree_dirty": bool(repository_paths),
        "last_checked_at": project.get("last_change_checked_at"),
        "auto_sync_enabled": bool(project.get("auto_sync_enabled", True)),
        "sync_mode": str(project.get("sync_mode") or "automatic"),
    }


def _project_changed_paths(
    root: Path,
    *,
    max_paths: int,
    baseline_commit: str | None = None,
) -> tuple[list[str], str, bool]:
    if (root / ".git").exists():
        try:
            commands = [
                ["git", "-C", str(root), "diff", "--no-renames", "--name-only", "-z", "HEAD"],
            ]
            if baseline_commit:
                commands.append(
                    [
                        "git", "-C", str(root), "diff", "--no-renames",
                        "--name-only", "-z", f"{baseline_commit}..HEAD",
                    ]
                )
            changed_results = [
                _safe_git_run(command, capture_output=True, timeout=8, check=False)
                for command in commands
            ]
            untracked = _safe_git_run(
                [
                    "git",
                    "-C",
                    str(root),
                    "ls-files",
                    "--others",
                    "--exclude-standard",
                    "-z",
                ],
                capture_output=True,
                timeout=8,
                check=False,
            )
            if all(result.returncode == 0 for result in changed_results) and untracked.returncode == 0:
                values = [
                    item.decode("utf-8", errors="replace").replace("\\", "/")
                    for item in [
                        *[
                            value
                            for result in changed_results
                            for value in result.stdout.split(b"\0")
                        ],
                        *untracked.stdout.split(b"\0"),
                    ]
                    if item
                ]
                unique = sorted(dict.fromkeys(values), key=str.casefold)
                return unique[:max_paths], "git_delta", len(unique) > max_paths
        except (OSError, subprocess.SubprocessError):
            pass
    return [], "metadata_fingerprint", False


def _project_change_items(
    root: Path,
    *,
    baseline_commit: str | None,
    max_paths: int,
) -> list[dict]:
    if not (root / ".git").exists():
        return []
    commands: list[list[str]] = [
        [
            "git",
            "-C",
            str(root),
            "diff",
            "--name-status",
            "-z",
            "--find-renames",
            "HEAD",
        ]
    ]
    if baseline_commit:
        commands.append(
            [
                "git",
                "-C",
                str(root),
                "diff",
                "--name-status",
                "-z",
                "--find-renames",
                f"{baseline_commit}..HEAD",
            ]
        )
    items: dict[tuple[str, str], dict] = {}
    try:
        for command in commands:
            result = _safe_git_run(command, capture_output=True, timeout=8, check=False)
            if result.returncode != 0:
                continue
            for item in _parse_git_name_status(result.stdout):
                key = (str(item["kind"]), str(item["path"]).casefold())
                items[key] = item
        untracked = _safe_git_run(
            [
                "git",
                "-C",
                str(root),
                "ls-files",
                "--others",
                "--exclude-standard",
                "-z",
            ],
            capture_output=True,
            timeout=8,
            check=False,
        )
        if untracked.returncode == 0:
            for raw_path in untracked.stdout.split(b"\0"):
                if not raw_path:
                    continue
                path = raw_path.decode("utf-8", errors="replace").replace("\\", "/")
                items[("added", path.casefold())] = {
                    "kind": "added",
                    "path": path,
                    "previous_path": None,
                }
    except (OSError, subprocess.SubprocessError):
        return []
    _coalesce_unstaged_renames(root, items)
    return sorted(
        items.values(),
        key=lambda item: (str(item["path"]).casefold(), str(item["kind"])),
    )[:max_paths]


def _coalesce_unstaged_renames(
    root: Path,
    items: dict[tuple[str, str], dict],
) -> None:
    """Recognize exact renames whose destination is still untracked.

    ``git diff`` cannot pair a tracked deletion with an untracked destination.
    Comparing Git object IDs gives us a conservative rename signal without
    staging files or mutating the user's repository.
    """

    deleted_items = [
        (key, item)
        for key, item in items.items()
        if item.get("kind") == "deleted" and str(item.get("path") or "")
    ]
    added_items = [
        (key, item)
        for key, item in items.items()
        if item.get("kind") == "added" and str(item.get("path") or "")
    ]
    if not deleted_items or not added_items:
        return

    deleted_by_oid: dict[str, list[tuple[tuple[str, str], dict]]] = {}
    added_by_oid: dict[str, list[tuple[tuple[str, str], dict]]] = {}
    try:
        tree = _safe_git_run(
            ["git", "-C", str(root), "ls-tree", "-r", "-z", "HEAD"],
            capture_output=True,
            timeout=8,
            check=False,
        )
        if tree.returncode != 0:
            return
        head_oids: dict[str, str] = {}
        for raw_entry in tree.stdout.split(b"\0"):
            if not raw_entry or b"\t" not in raw_entry:
                continue
            metadata, raw_path = raw_entry.split(b"\t", 1)
            parts = metadata.split()
            if len(parts) < 3:
                continue
            path = raw_path.decode("utf-8", errors="replace").replace("\\", "/")
            head_oids[path.casefold()] = parts[2].decode("ascii", errors="ignore")
        for key, item in deleted_items:
            oid = head_oids.get(str(item["path"]).casefold(), "")
            if len(oid) >= 20:
                deleted_by_oid.setdefault(oid, []).append((key, item))

        oid_length = max((len(value) for value in head_oids.values()), default=40)
        algorithm = "sha256" if oid_length == 64 else "sha1"
        resolved_root = root.resolve()
        for key, item in added_items:
            candidate = (root / str(item["path"])).resolve()
            try:
                candidate.relative_to(resolved_root)
                if candidate.is_symlink() or not candidate.is_file() or candidate.stat().st_size > MAX_FILE_BYTES:
                    continue
                data = _read_bounded_bytes(candidate)
            except (OSError, ValueError):
                continue
            variants = {data, data.replace(b"\r\n", b"\n")}
            for variant in variants:
                header = f"blob {len(variant)}\0".encode("ascii")
                oid = hashlib.new(algorithm, header + variant).hexdigest()
                added_by_oid.setdefault(oid, []).append((key, item))
    except (OSError, subprocess.SubprocessError):
        return

    for oid in deleted_by_oid.keys() & added_by_oid.keys():
        deleted = deleted_by_oid[oid]
        added = added_by_oid[oid]
        if len(deleted) != 1 or len(added) != 1:
            continue
        deleted_key, deleted_item = deleted[0]
        added_key, added_item = added[0]
        items.pop(deleted_key, None)
        items.pop(added_key, None)
        destination = str(added_item["path"])
        items[("renamed", destination.casefold())] = {
            "kind": "renamed",
            "path": destination,
            "previous_path": deleted_item["path"],
        }


def _parse_git_name_status(raw: bytes) -> list[dict]:
    tokens = [token for token in raw.split(b"\0") if token]
    items: list[dict] = []
    index = 0
    while index < len(tokens):
        status = tokens[index].decode("ascii", errors="replace")
        index += 1
        if index >= len(tokens):
            break
        first_path = tokens[index].decode("utf-8", errors="replace").replace("\\", "/")
        index += 1
        code = status[:1]
        if code in {"R", "C"} and index < len(tokens):
            next_path = tokens[index].decode("utf-8", errors="replace").replace("\\", "/")
            index += 1
            items.append(
                {
                    "kind": "renamed" if code == "R" else "copied",
                    "path": next_path,
                    "previous_path": first_path,
                }
            )
            continue
        kind = {
            "A": "added",
            "D": "deleted",
            "M": "modified",
            "T": "modified",
            "U": "modified",
        }.get(code, "modified")
        items.append({"kind": kind, "path": first_path, "previous_path": None})
    return items


def _project_snapshot_delta(
    *,
    project: dict,
    root: Path,
    repository_paths: list[str],
    repository_items: list[dict],
    repository_detection_mode: str,
    repository_truncated: bool,
    max_paths: int,
) -> dict:
    """Compare the current eligible content with Odin's active manifest.

    Git is only a candidate-path accelerator. A dirty Git path is not pending
    when its current bytes already match the active Odin snapshot.
    """

    manifest = _active_project_manifest(project)
    if manifest is None:
        return {
            "changed_paths": repository_paths,
            "change_items": repository_items,
            "changed_path_count": len(repository_paths),
            "truncated": repository_truncated,
            "detection_mode": repository_detection_mode,
            "requires_full_scan": repository_detection_mode != "git_delta",
        }

    manifest_by_key = {
        str(item.get("path") or "").replace("\\", "/").casefold(): {
            "path": str(item.get("path") or "").replace("\\", "/"),
            "hash": str(item.get("hash") or ""),
        }
        for item in manifest.get("files") or []
        if isinstance(item, dict) and str(item.get("path") or "").strip()
    }
    indexed_policy_hash = str(manifest.get("policy_hash") or "")
    policy_changed = (
        not indexed_policy_hash
        or indexed_policy_hash != project_discovery_policy_hash(root)
    )
    use_targeted_scan = (
        repository_detection_mode == "git_delta"
        and not repository_truncated
        and not policy_changed
    )

    if use_targeted_scan:
        candidate_paths = list(repository_paths)
        # Git cannot report deletion of a file that was untracked when Odin
        # indexed it. Existence checks are cheap and close that correctness gap.
        for item in manifest_by_key.values():
            path = root / Path(item["path"])
            if not path.exists():
                candidate_paths.append(item["path"])
        files, removed, skipped = discover_project_paths(
            root,
            candidate_paths,
            discovery_scope=str(project.get("discovery_scope") or "context"),
        )
        current_by_key = {
            item.relative_path.casefold(): item
            for item in files
        }
        removed_keys = {
            str(path).replace("\\", "/").casefold()
            for path in [*removed, *skipped]
        }
        candidate_keys = {
            str(path).replace("\\", "/").casefold()
            for path in candidate_paths
        }
        pending = _compare_snapshot_entries(
            manifest_by_key=manifest_by_key,
            current_by_key=current_by_key,
            candidate_keys=candidate_keys,
            removed_keys=removed_keys,
        )
        detection_mode = "snapshot_git_delta"
        requires_full_scan = False
    else:
        discovery = discover_project(
            root,
            discovery_scope=str(project.get("discovery_scope") or "context"),
        )
        current_by_key = {
            item.relative_path.casefold(): item
            for item in discovery.files
        }
        pending = _compare_snapshot_entries(
            manifest_by_key=manifest_by_key,
            current_by_key=current_by_key,
            candidate_keys=set(manifest_by_key) | set(current_by_key),
            removed_keys=set(manifest_by_key) - set(current_by_key),
        )
        detection_mode = "snapshot_full_scan"
        requires_full_scan = True

    pending_items = _pending_snapshot_change_items(
        pending,
        repository_items=repository_items,
    )
    pending_paths = sorted(
        {
            str(item["path"])
            for item in pending_items
        }
        | {
            str(item["previous_path"])
            for item in pending_items
            if item.get("previous_path")
        },
        key=str.casefold,
    )
    total = len(pending_paths)
    return {
        "changed_paths": pending_paths[:max_paths],
        "change_items": pending_items[:max_paths],
        "changed_path_count": total,
        "truncated": total > max_paths,
        "detection_mode": detection_mode,
        "requires_full_scan": requires_full_scan,
    }


def _active_project_manifest(project: dict) -> dict | None:
    snapshot_id = (
        project.get("active_manifest_snapshot_id")
        or project.get("active_snapshot_id")
    )
    if not snapshot_id:
        return None
    with connect() as conn:
        row = conn.execute(
            "SELECT manifest_json FROM project_snapshots WHERE id = ? AND project_id = ?",
            (snapshot_id, project["id"]),
        ).fetchone()
    if row is None:
        return None
    try:
        manifest = json.loads(row["manifest_json"] or "{}")
    except (TypeError, ValueError):
        return None
    return manifest if isinstance(manifest, dict) else None


def _compare_snapshot_entries(
    *,
    manifest_by_key: dict[str, dict],
    current_by_key: dict[str, ManifestFile],
    candidate_keys: set[str],
    removed_keys: set[str],
) -> dict[str, dict]:
    pending: dict[str, dict] = {}
    for key in candidate_keys:
        previous = manifest_by_key.get(key)
        current = current_by_key.get(key)
        if current is None:
            if previous is not None and key in removed_keys:
                pending[key] = {
                    "kind": "deleted",
                    "path": previous["path"],
                    "previous_path": None,
                    "hash": previous["hash"],
                }
            continue
        if previous is None:
            pending[key] = {
                "kind": "added",
                "path": current.relative_path,
                "previous_path": None,
                "hash": current.content_hash,
            }
        elif previous["hash"] != current.content_hash:
            pending[key] = {
                "kind": "modified",
                "path": current.relative_path,
                "previous_path": None,
                "hash": current.content_hash,
            }
    return pending


def _pending_snapshot_change_items(
    pending: dict[str, dict],
    *,
    repository_items: list[dict],
) -> list[dict]:
    remaining = dict(pending)
    items: list[dict] = []
    for repository_item in repository_items:
        kind = str(repository_item.get("kind") or "")
        path = str(repository_item.get("path") or "").replace("\\", "/")
        previous_path = str(repository_item.get("previous_path") or "").replace("\\", "/")
        path_key = path.casefold()
        previous_key = previous_path.casefold()
        if kind == "renamed" and path_key in remaining and previous_key in remaining:
            if (
                remaining[path_key]["kind"] == "added"
                and remaining[previous_key]["kind"] == "deleted"
            ):
                items.append(
                    {
                        "kind": "renamed",
                        "path": path,
                        "previous_path": previous_path,
                    }
                )
                remaining.pop(path_key, None)
                remaining.pop(previous_key, None)
        elif kind == "copied" and path_key in remaining:
            items.append(
                {
                    "kind": "copied",
                    "path": path,
                    "previous_path": previous_path or None,
                }
            )
            remaining.pop(path_key, None)
    items.extend(
        {
            "kind": str(item["kind"]),
            "path": str(item["path"]),
            "previous_path": item.get("previous_path"),
        }
        for _, item in sorted(
            remaining.items(),
            key=lambda pair: str(pair[1]["path"]).casefold(),
        )
    )
    return items


def probe_project_changes(project_id: str, *, force_sync: bool = False) -> dict:
    report = inspect_project_changes(project_id)
    fingerprint = str(report["change_fingerprint"])
    changed = bool(report["changed"])
    now = utc_now()
    with connect() as conn:
        conn.execute(
            """
            UPDATE projects
            SET change_fingerprint = CASE WHEN change_fingerprint = '' THEN ? ELSE change_fingerprint END,
                last_change_checked_at = ?,
                changed_file_count = ?,
                status = CASE WHEN ? THEN 'stale' ELSE status END,
                updated_at = CASE WHEN ? THEN ? ELSE updated_at END
            WHERE id = ?
            """,
            (
                fingerprint,
                now,
                int(report["changed_path_count"] or 0),
                int(changed),
                int(changed),
                now,
                project_id,
            ),
        )
    project = get_project(project_id)
    sync_mode = str(project.get("sync_mode") or "automatic")
    source_count = int(project.get("source_count") or 0)
    path_count = int(report["changed_path_count"] or 0)
    complete_git_delta = (
        report["detection_mode"] == "snapshot_git_delta"
        and not bool(report["truncated"])
        and bool(project.get("active_manifest_snapshot_id"))
        and path_count > 0
        and path_count <= 500
        and (source_count < 100 or path_count <= max(25, source_count // 5))
    )
    should_sync = bool(force_sync or sync_mode == "automatic")
    if not changed or not should_sync:
        sync = None
        sync_kind = None
    elif complete_git_delta:
        sync = sync_project_delta(
            project_id,
            changed_paths=list(report["changed_paths"]),
            trigger_source="auto_delta",
        )
        sync_kind = "git_delta"
    else:
        sync = sync_project(project_id, trigger_source="auto_full_refresh")
        sync_kind = "full"
    return {
        "project_id": project_id,
        "changed": changed,
        "change_fingerprint": fingerprint,
        "sync_queued": bool(sync),
        "job_id": sync.get("job_id") if sync else None,
        "detection_mode": report["detection_mode"],
        "changed_paths": report["changed_paths"],
        "change_items": report["change_items"],
        "changed_path_count": report["changed_path_count"],
        "requires_full_scan": report["requires_full_scan"],
        "sync_kind": sync_kind,
        "sync_mode": sync_mode,
        "next_action": (
            "wait_for_sync"
            if sync
            else "sync_changes"
            if changed
            else "none"
        ),
    }


def normalize_discovery_scope(value: str | None) -> str:
    scope = str(value or "context").strip().casefold()
    if scope not in DISCOVERY_SCOPES:
        raise ProjectError("Project discovery scope must be 'context' or 'code'.")
    return scope


def normalize_project_sync_mode(
    value: str | None,
    *,
    auto_sync_enabled: bool | None = None,
) -> str:
    if value is None:
        return "automatic" if auto_sync_enabled is not False else "manual"
    normalized = str(value).strip().casefold().replace("-", "_")
    aliases = {
        "auto": "automatic",
        "automatic": "automatic",
        "notify": "notify",
        "notify_only": "notify",
        "manual": "manual",
    }
    if normalized not in aliases:
        raise ProjectError("Project sync mode must be automatic, notify, or manual.")
    return aliases[normalized]


def register_project(
    *, vault_id: str, root_path: str, name: str | None,
    discovery_scope: str = "context", auto_sync_enabled: bool | None = None,
    sync_mode: str | None = None,
    sync: bool = True,
) -> dict:
    root = normalize_root_path(root_path)
    normalized_scope = normalize_discovery_scope(discovery_scope)
    normalized_sync_mode = normalize_project_sync_mode(
        sync_mode,
        auto_sync_enabled=auto_sync_enabled,
    )
    fingerprint = root_fingerprint(root)
    project_name = (name or root.name).strip()
    if not project_name:
        raise ProjectError("Project name is required.")
    if len(project_name) > 120:
        raise ProjectError("Project name must be 120 characters or fewer.")

    with connect() as conn:
        vault = conn.execute("SELECT id FROM vaults WHERE id = ?", (vault_id,)).fetchone()
        if vault is None:
            raise ProjectError("Vault not found.")
        existing = conn.execute(
            "SELECT id FROM projects WHERE vault_id = ? AND root_fingerprint = ? AND deleted_at IS NULL",
            (vault_id, fingerprint),
        ).fetchone()
        if existing is not None:
            project_id = str(existing["id"])
        else:
            collision = conn.execute(
                "SELECT id FROM projects WHERE vault_id = ? AND lower(name) = lower(?) AND deleted_at IS NULL",
                (vault_id, project_name),
            ).fetchone()
            if collision is not None:
                raise ProjectError("A project with this name already exists in the vault.")
            cluster = conn.execute(
                "SELECT id FROM clusters WHERE vault_id = ? AND lower(name) = lower(?) ORDER BY created_at LIMIT 1",
                (vault_id, project_name),
            ).fetchone()
            now = utc_now()
            cluster_id = str(cluster["id"]) if cluster is not None else f"cluster-{uuid4()}"
            if cluster is None:
                conn.execute(
                    """
                    INSERT INTO clusters (
                        id, vault_id, name, description, color, index_status, profile_status,
                        cluster_summary, cluster_glossary, indexed_source_count, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'sky', 'empty', 'missing', '', '[]', 0, ?, ?)
                    """,
                    (
                        cluster_id,
                        vault_id,
                        project_name,
                        "Files and context from this project folder.",
                        now,
                        now,
                    ),
                )
            repository_kind, branch, commit, remote_fingerprint, dirty, changed_file_count = _git_metadata(root)
            project_id = f"project-{uuid4()}"
            conn.execute(
                """
                INSERT INTO projects (
                    id, vault_id, name, root_path, root_fingerprint, primary_cluster_id,
                    discovery_scope,
                    repository_kind, git_remote_fingerprint, default_branch, indexed_commit,
                    working_tree_dirty, changed_file_count, status,
                    structure_status, retrieval_status, interpretation_status,
                    auto_sync_enabled, sync_mode, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'registered', 'waiting', 'waiting',
                          'unavailable', ?, ?, ?, ?)
                """,
                (
                    project_id,
                    vault_id,
                    project_name,
                    str(root),
                    fingerprint,
                    cluster_id,
                    normalized_scope,
                    repository_kind,
                    remote_fingerprint,
                    branch,
                    commit,
                    int(dirty),
                    changed_file_count,
                    int(normalized_sync_mode == "automatic"),
                    normalized_sync_mode,
                    now,
                    now,
                ),
            )
            conn.execute(
                "INSERT INTO project_cluster_links (project_id, cluster_id, role, created_at) VALUES (?, ?, 'primary', ?)",
                (project_id, cluster_id, now),
            )
    if sync:
        sync_project(project_id, trigger_source="project_add")
    return get_project(project_id)


def list_projects(
    *,
    vault_id: str | None = None,
    cluster_id: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[dict]:
    safe_limit = max(1, min(int(limit), 1000))
    safe_offset = max(0, int(offset))
    with connect() as conn:
        if cluster_id:
            clauses = ["p.deleted_at IS NULL", "pcl.cluster_id = ?"]
            params: list[object] = [cluster_id]
            if vault_id:
                clauses.append("p.vault_id = ?")
                params.append(vault_id)
            params.extend([safe_limit, safe_offset])
            rows = conn.execute(
                f"""
                SELECT DISTINCT p.*
                FROM projects p
                JOIN project_cluster_links pcl ON pcl.project_id = p.id
                WHERE {" AND ".join(clauses)}
                ORDER BY p.updated_at DESC, p.id DESC
                LIMIT ? OFFSET ?
                """,
                tuple(params),
            ).fetchall()
        elif vault_id:
            rows = conn.execute(
                """
                SELECT * FROM projects
                WHERE vault_id = ? AND deleted_at IS NULL
                ORDER BY updated_at DESC, id DESC LIMIT ? OFFSET ?
                """,
                (vault_id, safe_limit, safe_offset),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM projects WHERE deleted_at IS NULL ORDER BY updated_at DESC, id DESC LIMIT ? OFFSET ?",
                (safe_limit, safe_offset),
            ).fetchall()
        return _projects_from_rows(conn, rows)


def list_projects_page(
    *,
    vault_id: str | None = None,
    cluster_id: str | None = None,
    limit: int = 100,
    cursor: str | None = None,
) -> dict:
    safe_limit = max(1, min(int(limit), 200))
    decoded = decode_cursor(cursor)
    cursor_clause = ""
    cursor_params: list[object] = []
    if decoded:
        updated_at, item_id = decoded
        cursor_clause = "AND (p.updated_at < ? OR (p.updated_at = ? AND p.id < ?))"
        cursor_params = [updated_at, updated_at, item_id]
    with connect() as conn:
        if cluster_id:
            clauses = ["p.deleted_at IS NULL", "pcl.cluster_id = ?"]
            params: list[object] = [cluster_id]
            if vault_id:
                clauses.append("p.vault_id = ?")
                params.append(vault_id)
            rows = conn.execute(
                f"""
                SELECT DISTINCT p.*
                FROM projects p
                JOIN project_cluster_links pcl ON pcl.project_id = p.id
                WHERE {' AND '.join(clauses)} {cursor_clause}
                ORDER BY p.updated_at DESC, p.id DESC
                LIMIT ?
                """,
                [*params, *cursor_params, safe_limit + 1],
            ).fetchall()
        else:
            clauses = ["p.deleted_at IS NULL"]
            params = []
            if vault_id:
                clauses.append("p.vault_id = ?")
                params.append(vault_id)
            rows = conn.execute(
                f"""
                SELECT p.* FROM projects p
                WHERE {' AND '.join(clauses)} {cursor_clause}
                ORDER BY p.updated_at DESC, p.id DESC
                LIMIT ?
                """,
                [*params, *cursor_params, safe_limit + 1],
            ).fetchall()
        items = _projects_from_rows(conn, rows)
    return cursor_page(items, requested_limit=safe_limit, sort_field="updated_at")


def get_project(project_id: str) -> dict:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM projects WHERE id = ? AND deleted_at IS NULL",
            (project_id,),
        ).fetchone()
        if row is None:
            raise KeyError(project_id)
        return _project_from_row(conn, row)


def update_project(
    project_id: str, *, name: str | None = None, root_path: str | None = None,
    discovery_scope: str | None = None, auto_sync_enabled: bool | None = None,
    sync_mode: str | None = None,
) -> dict:
    if (
        name is None
        and root_path is None
        and discovery_scope is None
        and auto_sync_enabled is None
        and sync_mode is None
    ):
        raise ProjectError("Provide a project setting to update.")
    normalized = name.strip() if name is not None else None
    if normalized is not None and (not normalized or len(normalized) > 120):
        raise ProjectError("Project name must be between 1 and 120 characters.")
    replacement_root = normalize_root_path(root_path) if root_path is not None else None
    replacement_fingerprint = root_fingerprint(replacement_root) if replacement_root is not None else None
    normalized_scope = normalize_discovery_scope(discovery_scope) if discovery_scope is not None else None
    normalized_sync_mode = (
        normalize_project_sync_mode(sync_mode, auto_sync_enabled=auto_sync_enabled)
        if sync_mode is not None or auto_sync_enabled is not None
        else None
    )
    with connect() as conn:
        row = conn.execute(
            "SELECT vault_id, primary_cluster_id, name, active_run_id, discovery_scope FROM projects WHERE id = ? AND deleted_at IS NULL",
            (project_id,),
        ).fetchone()
        if row is None:
            raise KeyError(project_id)
        if row["active_run_id"] and (replacement_root is not None or normalized_scope is not None):
            raise ProjectError("Cancel the active synchronization before changing this project's folder or scope.")
        if normalized is not None:
            collision = conn.execute(
                """
                SELECT id FROM projects
                WHERE vault_id = ? AND lower(name) = lower(?) AND id != ? AND deleted_at IS NULL
                """,
                (row["vault_id"], normalized, project_id),
            ).fetchone()
            if collision is not None:
                raise ProjectError("A project with this name already exists in the vault.")
        if replacement_fingerprint is not None:
            collision = conn.execute(
                "SELECT id FROM projects WHERE vault_id = ? AND root_fingerprint = ? AND id != ? AND deleted_at IS NULL",
                (row["vault_id"], replacement_fingerprint, project_id),
            ).fetchone()
            if collision is not None:
                raise ProjectError("That folder is already registered as another project.")
        now = utc_now()
        if normalized is not None:
            conn.execute("UPDATE projects SET name = ?, updated_at = ? WHERE id = ?", (normalized, now, project_id))
            conn.execute(
                "UPDATE clusters SET name = ?, updated_at = ? WHERE id = ?",
                (normalized, now, row["primary_cluster_id"]),
            )
        if replacement_root is not None:
            repository_kind, branch, _commit, remote_fingerprint, dirty, changed_count = _git_metadata(replacement_root)
            conn.execute(
                """
                UPDATE projects SET root_path = ?, root_fingerprint = ?, repository_kind = ?,
                    git_remote_fingerprint = ?, default_branch = ?, working_tree_dirty = ?,
                    changed_file_count = ?, status = CASE WHEN active_snapshot_id IS NULL THEN 'registered' ELSE 'stale' END,
                    updated_at = ? WHERE id = ?
                """,
                (str(replacement_root), replacement_fingerprint, repository_kind, remote_fingerprint,
                 branch, int(dirty), changed_count, now, project_id),
            )
        if normalized_scope is not None and normalized_scope != row["discovery_scope"]:
            conn.execute(
                """
                UPDATE projects SET discovery_scope = ?,
                    status = CASE WHEN active_snapshot_id IS NULL THEN 'registered' ELSE 'stale' END,
                    updated_at = ? WHERE id = ?
                """,
                (normalized_scope, now, project_id),
            )
        if normalized_sync_mode is not None:
            conn.execute(
                """
                UPDATE projects
                SET auto_sync_enabled = ?, sync_mode = ?,
                    last_change_checked_at = NULL, updated_at = ?
                WHERE id = ?
                """,
                (
                    int(normalized_sync_mode == "automatic"),
                    normalized_sync_mode,
                    now,
                    project_id,
                ),
            )
    return get_project(project_id)


def sync_project(
    project_id: str, *, trigger_source: str = "manual", discovery_scope: str | None = None,
) -> dict:
    if discovery_scope is not None:
        requested_scope = normalize_discovery_scope(discovery_scope)
        current = get_project(project_id)
        if requested_scope != current["discovery_scope"]:
            update_project(project_id, discovery_scope=requested_scope)
    project = get_project(project_id)
    run_id = f"project-run-{uuid4()}"
    candidate_snapshot_id = f"project-snapshot-{uuid4()}"
    now = utc_now()
    with connect() as conn:
        active = conn.execute(
            """
            SELECT * FROM project_index_runs
            WHERE project_id = ? AND status IN ('queued', 'running')
            ORDER BY created_at DESC LIMIT 1
            """,
            (project_id,),
        ).fetchone()
        if active is not None:
            active_run = _project_run_from_row(active)
            return {
                "project": project,
                "run": active_run,
                "snapshot_id": None,
                "job_id": active_run.get("job_id"),
                "queued": True,
            }
        conn.execute(
            """
            INSERT INTO project_index_runs (
                id, project_id, trigger_source, status, phase, queued_at, heartbeat_at,
                started_at, created_at, updated_at
            ) VALUES (?, ?, ?, 'queued', 'queued', ?, ?, ?, ?, ?)
            """,
            (run_id, project_id, trigger_source, now, now, now, now, now),
        )
        payload = {
            "project_id": project_id,
            "run_id": run_id,
            "candidate_snapshot_id": candidate_snapshot_id,
        }
        discover_job = enqueue_job(
            conn,
            job_type="project_discover",
            payload=payload,
            dedupe_key=f"project-index:{project_id}",
            scope_id=project_id,
            user_initiated=True,
        )
        structure_job = enqueue_job(
            conn, job_type="project_structure_index", payload=payload,
            dedupe_key=f"project-structure:{candidate_snapshot_id}", depends_on_job_id=discover_job["id"],
            scope_id=project_id, user_initiated=True,
        )
        retrieval_job = enqueue_job(
            conn, job_type="project_retrieval_stage", payload=payload,
            dedupe_key=f"project-retrieval:{candidate_snapshot_id}", depends_on_job_id=structure_job["id"],
            scope_id=project_id, user_initiated=True,
        )
        activate_job = enqueue_job(
            conn, job_type="project_snapshot_activate", payload=payload,
            dedupe_key=f"project-activate:{candidate_snapshot_id}", depends_on_job_id=retrieval_job["id"],
            scope_id=project_id, user_initiated=True,
        )
        conn.execute(
            "UPDATE project_index_runs SET job_id = ?, detail_json = ? WHERE id = ?",
            (
                discover_job["id"],
                json.dumps({"candidate_snapshot_id": candidate_snapshot_id, "phase_job_ids": [discover_job["id"], structure_job["id"], retrieval_job["id"], activate_job["id"]]}, separators=(",", ":")),
                run_id,
            ),
        )
        conn.execute(
            """
            UPDATE projects SET status = 'indexing',
                active_run_id = ?, updated_at = ? WHERE id = ?
            """,
            (run_id, now, project_id),
        )
    return {
        "project": get_project(project_id),
        "run": get_project_run(run_id),
        "snapshot_id": None,
        "job_id": discover_job["id"],
        "queued": True,
    }


def sync_project_delta(
    project_id: str,
    *,
    changed_paths: list[str],
    trigger_source: str = "auto_delta",
) -> dict:
    normalized_paths = sorted(
        dict.fromkeys(
            str(path or "").replace("\\", "/").lstrip("/")
            for path in changed_paths
            if str(path or "").strip()
        ),
        key=str.casefold,
    )
    if not normalized_paths:
        raise ProjectError("No changed project files were supplied.")
    run_id = f"project-run-{uuid4()}"
    candidate_snapshot_id = f"project-snapshot-{uuid4()}"
    now = utc_now()
    with connect() as conn:
        active = conn.execute(
            """
            SELECT * FROM project_index_runs
            WHERE project_id = ? AND status IN ('queued', 'running')
            ORDER BY created_at DESC LIMIT 1
            """,
            (project_id,),
        ).fetchone()
        if active is not None:
            active_run = _project_run_from_row(active)
            current_project = get_project(project_id)
            return {
                "project": current_project,
                "run": active_run,
                "snapshot_id": current_project.get("candidate_snapshot_id"),
                "job_id": active_run.get("job_id"),
                "queued": True,
                "sync_kind": "existing",
            }
        conn.execute(
            """
            INSERT INTO project_index_runs (
                id, project_id, trigger_source, status, phase, queued_at, heartbeat_at,
                started_at, created_at, updated_at
            ) VALUES (?, ?, ?, 'queued', 'delta_queued', ?, ?, ?, ?, ?)
            """,
            (run_id, project_id, trigger_source, now, now, now, now, now),
        )
        payload = {
            "project_id": project_id,
            "run_id": run_id,
            "candidate_snapshot_id": candidate_snapshot_id,
            "changed_paths": normalized_paths,
        }
        job = enqueue_job(
            conn,
            job_type="project_delta_apply",
            payload=payload,
            dedupe_key=f"project-delta-apply:{project_id}",
            scope_id=project_id,
            user_initiated=False,
        )
        conn.execute(
            "UPDATE project_index_runs SET job_id = ?, detail_json = ? WHERE id = ?",
            (
                job["id"],
                json.dumps(
                    {
                        "candidate_snapshot_id": candidate_snapshot_id,
                        "sync_kind": "git_delta",
                        "changed_path_count": len(normalized_paths),
                    },
                    separators=(",", ":"),
                ),
                run_id,
            ),
        )
        conn.execute(
            """
            UPDATE projects
            SET status = 'indexing', active_run_id = ?, candidate_snapshot_id = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (run_id, candidate_snapshot_id, now, project_id),
        )
    return {
        "project": get_project(project_id),
        "run": get_project_run(run_id),
        "snapshot_id": candidate_snapshot_id,
        "job_id": job["id"],
        "queued": True,
        "sync_kind": "git_delta",
    }


def reindex_project(project_id: str, *, layer: str) -> dict:
    normalized = layer.strip().lower()
    if normalized in {"structure", "retrieval", "full"}:
        return sync_project(project_id, trigger_source=f"reindex_{normalized}")
    if normalized != "interpretation":
        raise ProjectError("Layer must be structure, retrieval, interpretation, or full.")
    if normalized == "interpretation":
        from backend.app.core.project_operations import enqueue_project_intelligence_layers

        queued = enqueue_project_intelligence_layers(
            project_id,
            layers=["overview"],
            user_initiated=True,
        )
        return {
            "project": get_project(project_id),
            "queued_jobs": len(queued["jobs"]),
            "jobs": queued["jobs"],
            "layer": normalized,
        }
    raise AssertionError("unreachable")


def list_project_links(project_id: str) -> list[dict]:
    with connect() as conn:
        project = conn.execute("SELECT id FROM projects WHERE id = ? AND deleted_at IS NULL", (project_id,)).fetchone()
        if project is None:
            raise KeyError(project_id)
        rows = conn.execute(
            """
            SELECT pcl.project_id, pcl.cluster_id, pcl.role, pcl.created_at,
                   c.name AS cluster_name
            FROM project_cluster_links pcl
            JOIN clusters c ON c.id = pcl.cluster_id
            WHERE pcl.project_id = ?
            ORDER BY CASE pcl.role WHEN 'primary' THEN 0 ELSE 1 END, lower(c.name)
            """,
            (project_id,),
        ).fetchall()
        return [_project_run_from_row(row) for row in rows]


def link_project(project_id: str, cluster_id: str) -> dict:
    with connect() as conn:
        project = conn.execute(
            "SELECT vault_id FROM projects WHERE id = ? AND deleted_at IS NULL",
            (project_id,),
        ).fetchone()
        if project is None:
            raise KeyError(project_id)
        cluster = conn.execute(
            "SELECT id FROM clusters WHERE id = ? AND vault_id = ?",
            (cluster_id, project["vault_id"]),
        ).fetchone()
        if cluster is None:
            raise ProjectError("Cluster not found in this vault.")
        conn.execute(
            "INSERT OR IGNORE INTO project_cluster_links (project_id, cluster_id, role, created_at) VALUES (?, ?, 'linked', ?)",
            (project_id, cluster_id, utc_now()),
        )
    return next(item for item in list_project_links(project_id) if item["cluster_id"] == cluster_id)


def unlink_project(project_id: str, cluster_id: str) -> None:
    with connect() as conn:
        link = conn.execute(
            "SELECT role FROM project_cluster_links WHERE project_id = ? AND cluster_id = ?",
            (project_id, cluster_id),
        ).fetchone()
        if link is None:
            raise KeyError(cluster_id)
        if link["role"] == "primary":
            raise ProjectError("The primary project cluster cannot be unlinked.")
        conn.execute(
            "DELETE FROM project_cluster_links WHERE project_id = ? AND cluster_id = ?",
            (project_id, cluster_id),
        )


def list_project_runs(project_id: str, *, limit: int = 50, offset: int = 0) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM project_index_runs WHERE project_id = ?
            ORDER BY created_at DESC LIMIT ? OFFSET ?
            """,
            (project_id, max(1, min(limit, 200)), max(0, offset)),
        ).fetchall()
        return [dict_from_row(row) for row in rows]


def get_project_run(run_id: str) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM project_index_runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return _project_run_from_row(row)


def cancel_project_run(project_id: str) -> dict:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM project_index_runs
            WHERE project_id = ? AND status IN ('queued', 'running')
            ORDER BY created_at DESC LIMIT 1
            """,
            (project_id,),
        ).fetchone()
        if row is None:
            raise ProjectError("This project has no active indexing run.")
        now = utc_now()
        conn.execute(
            """
            UPDATE project_index_runs
            SET cancellation_requested = 1, cancellation_requested_at = ?, status = 'cancelled',
                finished_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (now, now, now, row["id"]),
        )
        phase_jobs = conn.execute(
            "SELECT id, payload FROM app_jobs WHERE status IN ('queued', 'running', 'blocked_by_dependency')"
        ).fetchall()
        for phase_job in phase_jobs:
            try:
                phase_payload = json.loads(phase_job["payload"] or "{}")
            except ValueError:
                continue
            if phase_payload.get("run_id") != row["id"]:
                continue
            conn.execute(
                "UPDATE app_jobs SET status = 'cancelled', completed_at = ?, updated_at = ?, status_detail = 'Cancelled by the user.' WHERE id = ?",
                (now, now, phase_job["id"]),
            )
        candidate_snapshot_id = row["snapshot_id"]
        if not candidate_snapshot_id:
            try:
                candidate_snapshot_id = json.loads(row["detail_json"] or "{}").get("candidate_snapshot_id")
            except ValueError:
                candidate_snapshot_id = None
        if candidate_snapshot_id:
            enqueue_job(
                conn, job_type="project_candidate_cleanup",
                payload={"project_id": project_id, "run_id": row["id"], "candidate_snapshot_id": candidate_snapshot_id},
                dedupe_key=f"project-cleanup:{candidate_snapshot_id}", scope_id=project_id,
            )
        conn.execute(
            """
            UPDATE projects SET active_run_id = NULL, candidate_snapshot_id = NULL,
                status = CASE WHEN active_snapshot_id IS NULL THEN 'registered' ELSE status END,
                updated_at = ? WHERE id = ?
            """,
            (now, project_id),
        )
        updated = conn.execute("SELECT * FROM project_index_runs WHERE id = ?", (row["id"],)).fetchone()
        return _project_run_from_row(updated)


def remove_project(project_id: str, *, confirmation_name: str) -> None:
    with connect() as conn:
        project = conn.execute(
            "SELECT name, primary_cluster_id FROM projects WHERE id = ? AND deleted_at IS NULL",
            (project_id,),
        ).fetchone()
        if project is None:
            raise KeyError(project_id)
        if confirmation_name.strip() != project["name"]:
            raise ProjectError("Confirmation name does not match the project name.")
        cancel_jobs_for_scope(
            conn,
            write_scope="project",
            scope_id=project_id,
            detail="Project was deleted.",
        )
        source_rows = conn.execute(
            "SELECT source_id FROM project_sources WHERE project_id = ?",
            (project_id,),
        ).fetchall()
        source_ids = [str(row["source_id"]) for row in source_rows]
        for source_id in source_ids:
            cancel_jobs_for_scope(
                conn,
                write_scope="source",
                scope_id=source_id,
                detail="Project source was deleted.",
            )
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        for source_id in source_ids:
            conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
        count_row = conn.execute(
            "SELECT COUNT(*) AS total FROM sources WHERE cluster_id = ? AND deleted_at IS NULL",
            (project["primary_cluster_id"],),
        ).fetchone()
        conn.execute(
            """
            UPDATE clusters SET indexed_source_count = ?, index_status = CASE WHEN ? = 0 THEN 'empty' ELSE index_status END,
                updated_at = ? WHERE id = ?
            """,
            (count_row["total"], count_row["total"], utc_now(), project["primary_cluster_id"]),
        )


def discover_project(
    root: Path, *, discovery_scope: str = "context", progress_callback=None,
) -> DiscoveryResult:
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"Project root is not a directory: {root}")
    normalized_scope = normalize_discovery_scope(discovery_scope)
    ignore_patterns = _load_ignore_patterns(root)
    files: list[ManifestFile] = []
    ignored_count = 0
    generated_count = 0
    failed_count = 0
    language_counts: Counter[str] = Counter()
    entrypoints: list[str] = []
    workspaces = 0
    scanned_directories = 0

    for current_root, directories, filenames in os.walk(root, topdown=True, followlinks=False):
        scanned_directories += 1
        current = Path(current_root)
        kept_directories: list[str] = []
        for directory in directories:
            candidate = current / directory
            relative = candidate.relative_to(root).as_posix()
            if directory.lower() in DEFAULT_IGNORED_DIRECTORIES or _matches_ignore(relative + "/", ignore_patterns):
                ignored_count += 1
                continue
            if _is_link_or_junction(candidate) or not _inside_root(root, candidate):
                ignored_count += 1
                continue
            kept_directories.append(directory)
        directories[:] = kept_directories

        for filename in filenames:
            path = current / filename
            relative = path.relative_to(root).as_posix()
            lower_name = filename.lower()
            suffix = path.suffix.lower()
            if _is_secret_name(lower_name, suffix) or _matches_ignore(relative, ignore_patterns):
                ignored_count += 1
                continue
            if _is_link_or_junction(path) or not _inside_root(root, path):
                ignored_count += 1
                continue
            if lower_name in GENERATED_FILENAMES:
                generated_count += 1
                continue
            if lower_name.endswith((".min.js", ".min.css", ".map", ".generated.ts", ".g.cs")):
                generated_count += 1
                continue
            if suffix not in SUPPORTED_EXTENSIONS and lower_name not in SUPPORTED_FILENAMES:
                ignored_count += 1
                continue
            if normalized_scope == "code" and suffix not in CODE_EXTENSIONS:
                ignored_count += 1
                continue
            try:
                size = path.stat().st_size
                if size > MAX_FILE_BYTES:
                    ignored_count += 1
                    continue
                raw = _read_bounded_bytes(path)
                if b"\x00" in raw[:8192]:
                    ignored_count += 1
                    continue
                text = raw.decode("utf-8-sig")
            except (OSError, UnicodeDecodeError, ValueError):
                failed_count += 1
                continue
            digest = hashlib.sha256(raw).hexdigest()
            language = LANGUAGE_BY_EXTENSION.get(suffix, "Configuration")
            language_counts[language] += 1
            role = _file_role(relative, lower_name)
            if role == "workspace_manifest" and "/" in relative:
                workspaces += 1
            if lower_name in ENTRYPOINT_NAMES or relative.lower() in {
                "src/index.ts",
                "src/index.tsx",
                "src/main.ts",
                "src/main.tsx",
            }:
                entrypoints.append(relative)
            files.append(ManifestFile(path, relative, digest, text, language, role))
            if progress_callback is not None and len(files) % 100 == 0:
                progress_callback(len(files))

        if progress_callback is not None and scanned_directories % 25 == 0:
            progress_callback(len(files))

    files.sort(key=lambda item: item.relative_path.casefold())
    manifest_digest = hashlib.sha256()
    manifest_digest.update(normalized_scope.encode("ascii"))
    manifest_digest.update(b"\n")
    for item in files:
        manifest_digest.update(item.relative_path.casefold().encode("utf-8"))
        manifest_digest.update(b"\0")
        manifest_digest.update(item.content_hash.encode("ascii"))
        manifest_digest.update(b"\n")
    return DiscoveryResult(
        files=files,
        ignored_count=ignored_count,
        generated_count=generated_count,
        failed_count=failed_count,
        languages=dict(language_counts.most_common()),
        entrypoints=entrypoints[:8],
        workspace_count=workspaces,
        manifest_hash=manifest_digest.hexdigest(),
        discovery_scope=normalized_scope,
    )


def discover_project_paths(
    root: Path,
    relative_paths: list[str],
    *,
    discovery_scope: str = "context",
) -> tuple[list[ManifestFile], list[str], list[str]]:
    """Read only a known delta set. Missing paths represent removals."""

    root = root.resolve(strict=True)
    normalized_scope = normalize_discovery_scope(discovery_scope)
    ignore_patterns = _load_ignore_patterns(root)
    files: list[ManifestFile] = []
    removed: list[str] = []
    skipped: list[str] = []
    for raw_relative in sorted(dict.fromkeys(relative_paths), key=str.casefold):
        relative = str(raw_relative or "").replace("\\", "/").lstrip("/")
        if not relative or relative.startswith("../") or "/../" in relative:
            skipped.append(relative or raw_relative)
            continue
        path = (root / Path(relative)).resolve(strict=False)
        if not _inside_root(root, path):
            skipped.append(relative)
            continue
        if not path.exists():
            removed.append(relative)
            continue
        if not path.is_file():
            skipped.append(relative)
            continue
        filename = path.name
        lower_name = filename.casefold()
        suffix = path.suffix.casefold()
        if (
            _is_secret_name(lower_name, suffix)
            or _matches_ignore(relative, ignore_patterns)
            or any(part.casefold() in DEFAULT_IGNORED_DIRECTORIES for part in Path(relative).parts[:-1])
            or lower_name in GENERATED_FILENAMES
            or lower_name.endswith((".min.js", ".min.css", ".map", ".generated.ts", ".g.cs"))
            or (suffix not in SUPPORTED_EXTENSIONS and lower_name not in SUPPORTED_FILENAMES)
            or (normalized_scope == "code" and suffix not in CODE_EXTENSIONS)
            or _is_link_or_junction(path)
        ):
            skipped.append(relative)
            continue
        try:
            raw = _read_bounded_bytes(path)
            if b"\x00" in raw[:8192]:
                skipped.append(relative)
                continue
            text = raw.decode("utf-8-sig")
        except (OSError, UnicodeDecodeError, ValueError):
            skipped.append(relative)
            continue
        language = LANGUAGE_BY_EXTENSION.get(suffix, "Configuration")
        files.append(
            ManifestFile(
                absolute_path=path,
                relative_path=relative,
                content_hash=hashlib.sha256(raw).hexdigest(),
                text=text,
                language=language,
                file_role=_file_role(relative, lower_name),
            )
        )
    return files, removed, skipped


def _project_from_row(conn, row) -> dict:
    result = dict_from_row(row)
    result["working_tree_dirty"] = bool(result.get("working_tree_dirty"))
    result["sync_mode"] = str(
        result.get("sync_mode")
        or ("automatic" if bool(result.get("auto_sync_enabled", True)) else "manual")
    )
    result["auto_sync_enabled"] = result["sync_mode"] == "automatic"
    compatibility_snapshot_id = result.get("active_snapshot_id")
    result["active_manifest_snapshot_id"] = result.get("active_manifest_snapshot_id") or compatibility_snapshot_id
    result["active_structure_snapshot_id"] = result.get("active_structure_snapshot_id") or compatibility_snapshot_id
    result["active_retrieval_snapshot_id"] = result.get("active_retrieval_snapshot_id") or compatibility_snapshot_id
    owning_snapshot_id = result.get("active_manifest_snapshot_id") or compatibility_snapshot_id
    if owning_snapshot_id:
        intelligence = conn.execute(
            """
            SELECT layer_states_json
            FROM project_intelligence_snapshots
            WHERE project_id = ? AND owning_snapshot_id = ?
            """,
            (result["id"], owning_snapshot_id),
        ).fetchone()
        if intelligence is not None:
            try:
                layers = json.loads(intelligence["layer_states_json"] or "{}")
            except (TypeError, ValueError):
                layers = {}
            interpretation = layers.get("interpretation") or {}
            interpretation_status = str(interpretation.get("status") or "").strip()
            if interpretation_status:
                result["interpretation_status"] = interpretation_status
    result["languages"] = json.loads(result.pop("languages_json") or "{}")
    result["entrypoints"] = json.loads(result.pop("entrypoints_json") or "[]")
    count = conn.execute(
        "SELECT COUNT(*) AS total FROM project_sources WHERE project_id = ?",
        (row["id"],),
    ).fetchone()
    result["source_count"] = int(count["total"] or 0)
    snapshot = None
    manifest_snapshot_id = result.get("active_manifest_snapshot_id")
    if manifest_snapshot_id:
        snapshot_row = conn.execute(
            "SELECT * FROM project_snapshots WHERE id = ?",
            (manifest_snapshot_id,),
        ).fetchone()
        if snapshot_row is not None:
            snapshot = dict_from_row(snapshot_row)
            snapshot["dirty_working_tree"] = bool(snapshot["dirty_working_tree"])
            snapshot.pop("manifest_json", None)
    result["active_snapshot"] = snapshot
    return result


def _projects_from_rows(conn, rows) -> list[dict]:
    row_list = list(rows)
    if not row_list:
        return []
    project_ids = [str(row["id"]) for row in row_list]
    placeholders = ",".join("?" for _ in project_ids)
    count_rows = conn.execute(
        f"""
        SELECT project_id, COUNT(*) AS total
        FROM project_sources
        WHERE project_id IN ({placeholders})
        GROUP BY project_id
        """,
        project_ids,
    ).fetchall()
    source_counts = {str(row["project_id"]): int(row["total"] or 0) for row in count_rows}
    snapshot_ids = list(
        dict.fromkeys(
            str(row["active_manifest_snapshot_id"] or row["active_snapshot_id"])
            for row in row_list
            if row["active_manifest_snapshot_id"] or row["active_snapshot_id"]
        )
    )
    snapshots: dict[str, dict] = {}
    if snapshot_ids:
        snapshot_placeholders = ",".join("?" for _ in snapshot_ids)
        snapshot_rows = conn.execute(
            f"SELECT * FROM project_snapshots WHERE id IN ({snapshot_placeholders})",
            snapshot_ids,
        ).fetchall()
        for snapshot_row in snapshot_rows:
            snapshot = dict_from_row(snapshot_row)
            snapshot["dirty_working_tree"] = bool(snapshot["dirty_working_tree"])
            snapshot.pop("manifest_json", None)
            snapshots[str(snapshot["id"])] = snapshot
    results: list[dict] = []
    for row in row_list:
        result = dict_from_row(row)
        result["working_tree_dirty"] = bool(result.get("working_tree_dirty"))
        result["sync_mode"] = str(
            result.get("sync_mode")
            or ("automatic" if bool(result.get("auto_sync_enabled", True)) else "manual")
        )
        result["auto_sync_enabled"] = result["sync_mode"] == "automatic"
        compatibility_snapshot_id = result.get("active_snapshot_id")
        result["active_manifest_snapshot_id"] = result.get("active_manifest_snapshot_id") or compatibility_snapshot_id
        result["active_structure_snapshot_id"] = result.get("active_structure_snapshot_id") or compatibility_snapshot_id
        result["active_retrieval_snapshot_id"] = result.get("active_retrieval_snapshot_id") or compatibility_snapshot_id
        result["languages"] = json.loads(result.pop("languages_json") or "{}")
        result["entrypoints"] = json.loads(result.pop("entrypoints_json") or "[]")
        result["source_count"] = source_counts.get(str(result["id"]), 0)
        result["active_snapshot"] = snapshots.get(str(result.get("active_manifest_snapshot_id") or ""))
        results.append(result)
    return results


def _project_run_from_row(row) -> dict:
    result = dict_from_row(row)
    result["cancellation_requested"] = bool(result.get("cancellation_requested"))
    return result


def _load_ignore_patterns(root: Path) -> list[str]:
    patterns: list[str] = []
    for filename in (".cmlignore", ".gitignore"):
        path = root / filename
        if not path.is_file():
            continue
        try:
            lines = _read_bounded_bytes(path, MAX_IGNORE_FILE_BYTES).decode("utf-8-sig").splitlines()
        except (OSError, UnicodeDecodeError, ValueError):
            continue
        for line in lines:
            pattern = line.strip()
            if pattern and not pattern.startswith("#") and not pattern.startswith("!"):
                patterns.append(pattern.lstrip("/"))
    return patterns


def _matches_ignore(relative: str, patterns: list[str]) -> bool:
    normalized = relative.replace("\\", "/")
    for pattern in patterns:
        candidate = pattern.rstrip("/")
        if not candidate:
            continue
        if fnmatch.fnmatch(normalized, candidate) or fnmatch.fnmatch(normalized, f"**/{candidate}"):
            return True
        if "/" not in candidate and any(fnmatch.fnmatch(part, candidate) for part in normalized.split("/")):
            return True
        if normalized == candidate or normalized.startswith(candidate + "/"):
            return True
    return False


def _is_secret_name(name: str, suffix: str) -> bool:
    return name in SECRET_NAMES or name.startswith(".env.") or suffix in SECRET_SUFFIXES


def _is_link_or_junction(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction and is_junction())


def _inside_root(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve(strict=False).relative_to(root)
        return True
    except (OSError, ValueError):
        return False


def _file_role(relative: str, lower_name: str) -> str:
    if lower_name in {"package.json", "pyproject.toml", "cargo.toml", "go.mod", "pom.xml"}:
        return "workspace_manifest"
    if lower_name.endswith(".pyi"):
        return "stub"
    normalized = relative.replace("\\", "/").casefold()
    directories = set(normalized.split("/")[:-1])
    test_directories = {"test", "tests", "__tests__", "spec", "specs", "fixture", "fixtures", "__fixtures__"}
    test_filename = (
        lower_name.startswith("test_")
        or lower_name.endswith(("_test.py", "_test.go", "_test.rs"))
        or ".test." in lower_name
        or ".spec." in lower_name
        or lower_name.endswith((".stories.ts", ".stories.tsx", ".stories.js", ".stories.jsx"))
    )
    if directories & test_directories or test_filename:
        return "test"
    if lower_name in ENTRYPOINT_NAMES:
        return "entrypoint"
    if lower_name.endswith((".json", ".yaml", ".yml", ".toml", ".ini", ".cfg")):
        return "configuration"
    return "source"


def _git_metadata(root: Path) -> tuple[str, str | None, str | None, str | None, bool, int]:
    git_path = root / ".git"
    if not git_path.exists():
        return "folder", None, None, None, False, 0
    git_dir = git_path
    if git_path.is_file():
        try:
            marker = git_path.read_text(encoding="utf-8").strip()
            if marker.lower().startswith("gitdir:"):
                git_dir = (root / marker.split(":", 1)[1].strip()).resolve()
        except (OSError, UnicodeDecodeError):
            return "git", None, None, None, False, 0
    try:
        head = (git_dir / "HEAD").read_text(encoding="ascii").strip()
    except OSError:
        return "git", None, None, None, False, 0
    if head.startswith("ref:"):
        reference = head.split(":", 1)[1].strip()
        branch = reference.rsplit("/", 1)[-1]
        try:
            commit = (git_dir / reference).read_text(encoding="ascii").strip() or None
        except OSError:
            commit = _packed_ref(git_dir, reference)
        return _git_worktree_metadata(root, branch, commit)
    return _git_worktree_metadata(root, None, head or None)


def _git_worktree_metadata(
    root: Path,
    branch: str | None,
    commit: str | None,
) -> tuple[str, str | None, str | None, str | None, bool, int]:
    remote_fingerprint = None
    changed_count = 0
    try:
        status = _safe_git_run(
            ["git", "-C", str(root), "status", "--porcelain=v1", "--untracked-files=normal"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
        if status.returncode == 0:
            changed_count = sum(1 for line in status.stdout.splitlines() if line.strip())
        remote = _safe_git_run(
            ["git", "-C", str(root), "config", "--get", "remote.origin.url"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
        if remote.returncode == 0 and remote.stdout.strip():
            remote_fingerprint = hashlib.sha256(remote.stdout.strip().encode("utf-8")).hexdigest()
    except (OSError, subprocess.SubprocessError):
        pass
    return "git", branch, commit, remote_fingerprint, changed_count > 0, changed_count


def _packed_ref(git_dir: Path, reference: str) -> str | None:
    try:
        for line in (git_dir / "packed-refs").read_text(encoding="ascii").splitlines():
            if line.startswith("#") or line.startswith("^"):
                continue
            commit, _, name = line.partition(" ")
            if name.strip() == reference:
                return commit.strip() or None
    except OSError:
        return None
    return None


def _build_brief(
    name: str,
    repository_kind: str,
    discovery: DiscoveryResult,
    structure: dict | None = None,
    *,
    indexed_file_count: int | None = None,
) -> str:
    purpose = _project_purpose_from_files(name, discovery.files)
    file_count = len(discovery.files) if indexed_file_count is None else indexed_file_count
    language_names = list(discovery.languages)[:3]
    language_text = ", ".join(language_names) if language_names else "text"
    kind = "Git repository" if repository_kind == "git" else "code folder"
    identity_text = (
        f"Indexed as a {kind} with {file_count} files, primarily {language_text}."
        if purpose
        else f"{name} is a {kind} with {file_count} indexed files, primarily {language_text}."
    )
    workspace_text = (
        (
            " It contains 1 detected package or workspace manifest."
            if discovery.workspace_count == 1
            else f" It contains {discovery.workspace_count} detected package or workspace manifests."
        )
        if discovery.workspace_count
        else ""
    )
    entrypoint_text = (
        f" Detected entry points include {', '.join(discovery.entrypoints[:3])}."
        if discovery.entrypoints
        else ""
    )
    structure_text = ""
    if structure:
        structure_text = (
            f" Odin extracted {structure['symbol_count']} symbols, {structure['edge_count']} evidence-backed relationships, "
            f"and {structure['route_count']} routes."
        )
    return f"{purpose + ' ' if purpose else ''}{identity_text}{workspace_text}{entrypoint_text}{structure_text}"


def _project_purpose_from_files(name: str, files: list[ManifestFile]) -> str:
    """Extract a concise, author-written purpose without invoking a model."""
    by_path = {item.relative_path.casefold(): item for item in files}
    readme = next(
        (
            by_path[path]
            for path in ("readme.md", "readme.mdx", "readme.txt", "readme")
            if path in by_path
        ),
        None,
    )
    if readme is not None:
        purpose = _first_readme_description(readme.text, name)
        if purpose:
            return purpose

    for path in ("package.json", "pyproject.toml"):
        manifest = by_path.get(path)
        if manifest is None:
            continue
        purpose = _manifest_description(manifest.text, path)
        if purpose:
            return purpose
    return ""


def _first_readme_description(text: str, name: str) -> str:
    cleaned = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    cleaned = re.sub(r"!\[[^\]]*]\([^)]*\)", "", cleaned)
    cleaned = re.sub(r"\[([^\]]+)]\([^)]*\)", r"\1", cleaned)
    cleaned = re.sub(r"<img\b[^>]*>", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    cleaned = html.unescape(cleaned).replace("\r\n", "\n")
    normalized_name = re.sub(r"\W+", "", name).casefold()
    for paragraph in re.split(r"\n\s*\n", cleaned):
        value = " ".join(
            line.strip().lstrip("#>*- ").strip()
            for line in paragraph.splitlines()
            if line.strip()
        )
        value = re.sub(r"\s+", " ", value).strip()
        normalized_value = re.sub(r"\W+", "", value).casefold()
        if len(value) < 40 or len(value) > 600:
            continue
        if normalized_value == normalized_name:
            continue
        if value.count("|") >= 2 or re.search(r"\b(installation|quick start|license|status badge)\b", value, re.I):
            continue
        return value
    return ""


def _manifest_description(text: str, path: str) -> str:
    if path == "package.json":
        try:
            value = json.loads(text).get("description")
        except (json.JSONDecodeError, AttributeError):
            return ""
        return str(value).strip()[:600] if value else ""
    match = re.search(r'(?m)^\s*description\s*=\s*["\'](.+?)["\']\s*$', text)
    return match.group(1).strip()[:600] if match else ""
