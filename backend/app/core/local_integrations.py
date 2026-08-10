from pathlib import Path

SUPPORTED_SOURCE_EXTENSIONS = {
    ".aac", ".asc", ".bat", ".bmp", ".c", ".cpp", ".cs", ".csv", ".css", ".docx",
    ".flac", ".gif", ".go", ".htm", ".html", ".java", ".jpeg", ".jpg", ".js",
    ".json", ".jsonl", ".jsx", ".kt", ".log", ".lua", ".m4a", ".markdown", ".md",
    ".mov", ".mp3", ".mp4", ".ogg", ".pdf", ".php", ".png", ".ps1", ".py", ".rb",
    ".rs", ".rtf", ".sh", ".sql", ".swift", ".text", ".tif", ".tiff", ".toml",
    ".ts", ".tsv", ".tsx", ".txt", ".wav", ".webm", ".webp", ".xml", ".yaml", ".yml",
}

SKIPPED_FOLDER_NAMES = {".git", ".tmp", "node_modules", ".venv", "dist", "build"}
DEFAULT_SCAN_LIMIT = 500
MAX_SCAN_LIMIT = 5000
WATCHED_FOLDER_SCAN_LIMIT = 1000
WATCHED_FOLDER_BACKPRESSURE_THRESHOLD = 1000


def scan_local_folder(path: str, max_files: int = DEFAULT_SCAN_LIMIT, *, cursor: str = "") -> dict:
    root = Path(path).expanduser()
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"Folder does not exist: {root}")
    max_files = max(1, min(int(max_files), MAX_SCAN_LIMIT))
    supported: list[str] = []
    skipped = 0
    truncated = False

    normalized_cursor = str(cursor or "").replace("\\", "/")
    last_relative_path = normalized_cursor
    for candidate in _walk(root):
        relative_path = candidate.relative_to(root).as_posix()
        if normalized_cursor and relative_path <= normalized_cursor:
            continue
        if len(supported) >= max_files:
            truncated = True
            break
        if candidate.suffix.lower() in SUPPORTED_SOURCE_EXTENSIONS:
            supported.append(str(candidate))
            last_relative_path = relative_path
        else:
            skipped += 1

    return {
        "path": str(root),
        "integration_type": _integration_type(root),
        "supported_files": supported,
        "supported_count": len(supported),
        "skipped_count": skipped,
        "truncated": truncated,
        "backpressure_required": truncated or len(supported) >= WATCHED_FOLDER_BACKPRESSURE_THRESHOLD,
        "scan_limit": max_files,
        "scan_cursor": last_relative_path if truncated else "",
        "scan_complete": not truncated,
    }


def watched_folder_limits() -> dict:
    return {
        "default_scan_limit": DEFAULT_SCAN_LIMIT,
        "max_scan_limit": MAX_SCAN_LIMIT,
        "watched_folder_scan_limit": WATCHED_FOLDER_SCAN_LIMIT,
        "backpressure_threshold": WATCHED_FOLDER_BACKPRESSURE_THRESHOLD,
        "skipped_folder_names": sorted(SKIPPED_FOLDER_NAMES),
        "policy": "Watched refreshes cap each pass and mark backpressure when a folder reaches the watched-folder threshold.",
    }


def _walk(root: Path):
    try:
        entries = sorted(root.iterdir(), key=lambda value: (value.name.casefold(), value.name))
    except OSError:
        return
    for entry in entries:
        if entry.is_symlink():
            continue
        if entry.is_dir():
            if entry.name in SKIPPED_FOLDER_NAMES:
                continue
            yield from _walk(entry)
        elif entry.is_file():
            yield entry


def _integration_type(root: Path) -> str:
    parts = {part.lower() for part in root.parts}
    joined = str(root).lower()
    if ".obsidian" in parts or (root / ".obsidian").exists():
        return "obsidian"
    if "google drive" in joined or "googledrive" in joined:
        return "google_drive_synced_folder"
    if "dropbox" in parts:
        return "dropbox_synced_folder"
    if "onedrive" in joined:
        return "onedrive_synced_folder"
    if "icloud drive" in joined or "iclouddrive" in joined:
        return "icloud_drive_synced_folder"
    return "local_folder"
