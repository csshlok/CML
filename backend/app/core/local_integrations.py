from pathlib import Path

SUPPORTED_SOURCE_EXTENSIONS = {
    ".aac", ".asc", ".bat", ".bmp", ".c", ".cpp", ".cs", ".csv", ".css", ".docx",
    ".flac", ".gif", ".go", ".htm", ".html", ".java", ".jpeg", ".jpg", ".js",
    ".json", ".jsonl", ".jsx", ".kt", ".log", ".lua", ".m4a", ".markdown", ".md",
    ".mov", ".mp3", ".mp4", ".ogg", ".pdf", ".php", ".png", ".ps1", ".py", ".rb",
    ".rs", ".rtf", ".sh", ".sql", ".swift", ".text", ".tif", ".tiff", ".toml",
    ".ts", ".tsv", ".tsx", ".txt", ".wav", ".webm", ".webp", ".xml", ".yaml", ".yml",
}

SKIPPED_FOLDER_NAMES = {".git", "node_modules", ".venv", "dist", "build"}


def scan_local_folder(path: str, max_files: int = 500) -> dict:
    root = Path(path).expanduser()
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"Folder does not exist: {root}")
    supported: list[str] = []
    skipped = 0
    truncated = False

    for candidate in _walk(root):
        if len(supported) >= max_files:
            truncated = True
            break
        if candidate.suffix.lower() in SUPPORTED_SOURCE_EXTENSIONS:
            supported.append(str(candidate))
        else:
            skipped += 1

    return {
        "path": str(root),
        "integration_type": _integration_type(root),
        "supported_files": supported,
        "supported_count": len(supported),
        "skipped_count": skipped,
        "truncated": truncated,
    }


def _walk(root: Path):
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except OSError:
            continue
        for entry in sorted(entries, key=lambda value: value.name.lower(), reverse=True):
            if entry.is_symlink():
                continue
            if entry.is_dir():
                if entry.name in SKIPPED_FOLDER_NAMES:
                    continue
                stack.append(entry)
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
