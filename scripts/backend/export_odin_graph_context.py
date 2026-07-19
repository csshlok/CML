from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a bounded model-facing Odin graph context.")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument("--budget", type=int, default=16_000)
    args = parser.parse_args()

    database = args.database.resolve(strict=True)
    with sqlite3.connect(database) as conn:
        row = conn.execute(
            "SELECT id FROM projects WHERE active_structure_snapshot_id IS NOT NULL "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    if row is None:
        raise RuntimeError(f"No active Odin structure snapshot in {database}")

    os.environ["CML_DATABASE_PATH"] = str(database)
    os.environ["CML_DATA_DIR"] = str(database.parent)
    from backend.app.core.config import get_settings
    from backend.app.core.project_graph import graph_view, graph_view_markdown

    get_settings.cache_clear()
    view = graph_view(
        str(row[0]),
        mode="graph",
        query=args.question,
        max_depth=2,
        max_nodes=120,
        direction="outbound",
    )
    output = graph_view_markdown(view)
    print(_bounded(output, max(1, args.budget)), end="")
    return 0


def _bounded(value: str, budget: int) -> str:
    lines: list[str] = []
    used = 0
    for line in value.splitlines():
        addition = len(line) + 1
        if lines and used + addition > budget:
            break
        lines.append(line)
        used += addition
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
