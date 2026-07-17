from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import psutil


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run repeatable cold-output structural benchmarks for Odin and Graphify."
    )
    parser.add_argument(
        "--repository",
        action="append",
        required=True,
        metavar="NAME=PATH",
        help="Repository label and local checkout. Repeat for multiple repositories.",
    )
    parser.add_argument("--graphify", type=Path, required=True, help="Graphify CLI executable.")
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--graphify-workers", type=int, default=6)
    args = parser.parse_args()

    repositories = [_parse_repository(value) for value in args.repository]
    graphify = args.graphify.resolve(strict=True)
    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    if args.runs < 1:
        raise ValueError("--runs must be at least 1")

    payload: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "python": sys.version,
        "graphify_executable": str(graphify),
        "runs_per_tool": args.runs,
        "odin_discovery_scope": "code",
        "repositories": [],
    }
    for name, repository in repositories:
        repo_record: dict[str, Any] = {
            "name": name,
            "path": str(repository),
            "commit": _git_commit(repository),
            "tracked_files": _git_file_count(repository),
            "odin_runs": [],
            "graphify_runs": [],
        }
        for run_number in range(1, args.runs + 1):
            order = ("odin", "graphify") if run_number % 2 else ("graphify", "odin")
            for tool in order:
                run_root = output_root / name / f"run-{run_number}" / tool
                run_root.mkdir(parents=True, exist_ok=False)
                if tool == "odin":
                    result = _run_odin(repository, run_root)
                    repo_record["odin_runs"].append(result)
                else:
                    result = _run_graphify(
                        graphify,
                        repository,
                        run_root,
                        workers=args.graphify_workers,
                    )
                    repo_record["graphify_runs"].append(result)
        repo_record["summary"] = _summarize(repo_record)
        payload["repositories"].append(repo_record)

    args.result.parent.mkdir(parents=True, exist_ok=True)
    args.result.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, separators=(",", ":")))
    return 0


def _parse_repository(value: str) -> tuple[str, Path]:
    name, separator, raw_path = value.partition("=")
    if not separator or not name.strip() or not raw_path.strip():
        raise ValueError(f"Invalid repository value: {value!r}; expected NAME=PATH")
    return name.strip(), Path(raw_path.strip()).resolve(strict=True)


def _run_odin(repository: Path, output: Path) -> dict[str, Any]:
    command = [
        sys.executable,
        "-m",
        "scripts.backend.benchmark_odin_project",
        str(repository),
        str(output),
        "--scope",
        "code",
    ]
    completed, wall_seconds, peak_rss = _run_sampled(command)
    if completed.returncode != 0:
        raise RuntimeError(f"Odin failed for {repository}: {completed.stderr[-4000:]}")
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    result = json.loads(lines[-1])
    result["process_tree_peak_rss_bytes"] = peak_rss
    result["command_wall_seconds"] = round(wall_seconds, 3)
    return result


def _run_graphify(
    executable: Path,
    repository: Path,
    output: Path,
    *,
    workers: int,
) -> dict[str, Any]:
    command = [
        str(executable),
        "extract",
        str(repository),
        "--code-only",
        "--out",
        str(output),
        "--timing",
        "--max-workers",
        str(workers),
    ]
    completed, wall_seconds, peak_rss = _run_sampled(command)
    if completed.returncode != 0:
        raise RuntimeError(f"Graphify failed for {repository}: {completed.stderr[-4000:]}")
    graph_path = output / "graphify-out" / "graph.json"
    manifest_path = output / "graphify-out" / "manifest.json"
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    links = list(graph.get("links") or graph.get("edges") or [])
    relation_counts: dict[str, int] = {}
    for link in links:
        relation = str(link.get("relation") or link.get("type") or "unknown")
        relation_counts[relation] = relation_counts.get(relation, 0) + 1
    return {
        "tool": "graphify",
        "wall_seconds": round(wall_seconds, 3),
        "process_tree_peak_rss_bytes": peak_rss,
        "indexed_files": len(manifest),
        "nodes": len(graph.get("nodes") or []),
        "edges": len(links),
        "edge_type_counts": dict(sorted(relation_counts.items())),
        "graph_bytes": graph_path.stat().st_size,
        "output_bytes": sum(path.stat().st_size for path in output.rglob("*") if path.is_file()),
        "timing_log": completed.stderr[-8000:],
    }


def _run_sampled(command: list[str]) -> tuple[subprocess.CompletedProcess[str], float, int]:
    started = time.perf_counter()
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    peak_rss = 0
    sampling = True

    def sample() -> None:
        nonlocal peak_rss
        root = psutil.Process(process.pid)
        while sampling:
            total = 0
            try:
                processes = [root, *root.children(recursive=True)]
                for item in processes:
                    try:
                        total += item.memory_info().rss
                    except (psutil.AccessDenied, psutil.NoSuchProcess):
                        continue
                peak_rss = max(peak_rss, total)
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                return
            time.sleep(0.01)

    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    stdout, stderr = process.communicate()
    sampling = False
    sampler.join(timeout=1)
    wall_seconds = time.perf_counter() - started
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr), wall_seconds, peak_rss


def _summarize(record: dict[str, Any]) -> dict[str, Any]:
    odin_runs = record["odin_runs"]
    graphify_runs = record["graphify_runs"]
    return {
        "odin": {
            "median_wall_seconds": round(
                statistics.median(item["structure_wall_seconds"] for item in odin_runs), 3
            ),
            "median_process_tree_peak_rss_bytes": int(
                statistics.median(item["process_tree_peak_rss_bytes"] for item in odin_runs)
            ),
            "eligible_files": odin_runs[-1]["eligible_files"],
            "nodes": odin_runs[-1]["nodes"],
            "edges": odin_runs[-1]["edges"],
            "edge_type_counts": odin_runs[-1]["edge_type_counts"],
            "parser_status_counts": odin_runs[-1]["parser_status_counts"],
        },
        "graphify": {
            "median_wall_seconds": round(
                statistics.median(item["wall_seconds"] for item in graphify_runs), 3
            ),
            "median_process_tree_peak_rss_bytes": int(
                statistics.median(item["process_tree_peak_rss_bytes"] for item in graphify_runs)
            ),
            "indexed_files": graphify_runs[-1]["indexed_files"],
            "nodes": graphify_runs[-1]["nodes"],
            "edges": graphify_runs[-1]["edges"],
            "edge_type_counts": graphify_runs[-1]["edge_type_counts"],
        },
    }


def _git_commit(repository: Path) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repository), "rev-parse", "HEAD"], text=True
    ).strip()


def _git_file_count(repository: Path) -> int:
    output = subprocess.check_output(
        ["git", "-C", str(repository), "ls-files", "-z"]
    )
    return len([item for item in output.split(b"\0") if item])


if __name__ == "__main__":
    raise SystemExit(main())
