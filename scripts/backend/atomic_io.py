from __future__ import annotations

import os
import time
from pathlib import Path


def atomic_write_text(
    path: Path,
    text: str,
    *,
    encoding: str = "utf-8",
    attempts: int = 8,
    initial_delay_seconds: float = 0.025,
) -> None:
    """Atomically replace *path*, retrying transient Windows sharing violations."""
    if attempts < 1:
        raise ValueError("attempts must be positive")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp"
    )
    try:
        temporary.write_text(text, encoding=encoding)
        for attempt in range(attempts):
            try:
                os.replace(temporary, path)
                return
            except OSError:
                if attempt + 1 == attempts:
                    raise
                time.sleep(
                    min(initial_delay_seconds * (2**attempt), 0.5)
                )
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
