from __future__ import annotations

import argparse
import json
import subprocess
import time

import psutil


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure wall time, CPU time, and aggregate RSS for a command tree.")
    parser.add_argument("--label", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("a command is required after --")

    started = time.perf_counter()
    child = subprocess.Popen(command)
    root = psutil.Process(child.pid)
    peak_rss = 0
    cpu_seconds = 0.0
    while child.poll() is None:
        processes = [root]
        try:
            processes.extend(root.children(recursive=True))
        except psutil.Error:
            pass
        rss = 0
        cpu = 0.0
        for process in processes:
            try:
                rss += process.memory_info().rss
                times = process.cpu_times()
                cpu += times.user + times.system
            except psutil.Error:
                continue
        peak_rss = max(peak_rss, rss)
        cpu_seconds = max(cpu_seconds, cpu)
        time.sleep(0.02)
    wall_seconds = time.perf_counter() - started
    print(
        json.dumps(
            {
                "tool": args.label,
                "exit_code": child.returncode,
                "wall_seconds": round(wall_seconds, 3),
                "cpu_seconds_observed": round(cpu_seconds, 3),
                "peak_tree_rss_bytes": peak_rss,
            },
            separators=(",", ":"),
        )
    )
    return child.returncode


if __name__ == "__main__":
    raise SystemExit(main())
