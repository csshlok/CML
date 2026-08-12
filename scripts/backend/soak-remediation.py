#!/usr/bin/env python3
"""Restartable mixed-workload soak for Vault stability qualification.

The default duration is 72 hours. All state is isolated under --state-dir; this
runner never points at a user's Vault database or library. A short accelerated
run is useful for validating the harness, but is not equivalent to the 72-hour
release gate.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import subprocess
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import psutil


REPO_ROOT = Path(__file__).resolve().parents[2]
API_PREFIX = "/api/v1"
TEST_PASSPHRASE = "Vault-soak-only-passphrase-2026"
ACTIVE_JOB_STATES = (
    "queued",
    "running",
    "paused",
    "blocked_by_dependency",
    "blocked_setup_required",
    "deferred",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    duration = parser.add_mutually_exclusive_group()
    duration.add_argument("--duration-hours", type=float, default=72.0)
    duration.add_argument("--duration-seconds", type=float)
    parser.add_argument("--cycle-seconds", type=float, default=10.0)
    parser.add_argument("--restart-every-cycles", type=int, default=180)
    parser.add_argument("--lock-every-cycles", type=int, default=60)
    parser.add_argument("--state-dir", default=".tmp/remediation-soak")
    parser.add_argument("--report", default=".tmp/remediation-soak-report.json")
    parser.add_argument("--port", type=int, default=18463)
    parser.add_argument("--max-sources", type=int, default=5_000)
    parser.add_argument("--max-chats", type=int, default=2_000)
    parser.add_argument("--max-rss-mib", type=float, default=4_096)
    parser.add_argument("--max-rss-growth-mib", type=float, default=768)
    parser.add_argument("--max-db-mib", type=float, default=4_096)
    parser.add_argument("--request-timeout", type=float, default=30.0)
    parser.add_argument("--continue-on-operation-error", action="store_true")
    return parser.parse_args()


def atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * ratio) - 1))
    return float(ordered[index])


def matching_file_bytes(directory: Path, pattern: str) -> int:
    """Return a best-effort size for files that may appear and disappear.

    SQLite creates and removes WAL/SHM sidecars while connections open and
    close.  A sidecar can therefore vanish between ``glob`` and ``stat``;
    resource telemetry must not be able to terminate the workload it observes.
    """
    total = 0
    for path in directory.glob(pattern):
        try:
            if path.is_file():
                total += path.stat().st_size
        except (FileNotFoundError, PermissionError):
            continue
    return total


def free_port(preferred: int) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            probe.bind(("127.0.0.1", 0))
            return int(probe.getsockname()[1])


class SoakRunner:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.state_dir = (REPO_ROOT / args.state_dir).resolve()
        self.report_path = (REPO_ROOT / args.report).resolve()
        self.data_dir = self.state_dir / "backend-data"
        self.database_path = self.data_dir / "cml.sqlite3"
        self.library_dir = self.state_dir / "library"
        self.watch_dir = self.state_dir / "watched"
        self.project_dir = self.state_dir / "project"
        self.state_path = self.state_dir / "state.json"
        self.live_status_path = self.state_dir / "live-status.json"
        self.stdout_path = self.state_dir / "backend.stdout.log"
        self.stderr_path = self.state_dir / "backend.stderr.log"
        self.port = free_port(args.port)
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.process: subprocess.Popen[bytes] | None = None
        self.api_token = "remediation-soak-" + secrets.token_urlsafe(24)
        self.state: dict[str, Any] = {
            "schema_version": 1,
            "cycle": 0,
            "source_count": 0,
            "chat_count": 0,
            "restart_count": 0,
            "lock_cycle_count": 0,
            "vault_id": "",
            "watch_import_id": "",
            "project_id": "",
            "bridge_client_id": "",
            "bridge_token": "",
            "search_source_id": "",
            "search_cluster_id": "",
            "started_at": time.time(),
        }
        if self.state_path.exists():
            loaded = json.loads(self.state_path.read_text(encoding="utf-8"))
            if int(loaded.get("schema_version", 0)) != 1:
                raise RuntimeError("Unsupported soak checkpoint schema")
            self.state.update(loaded)
        self.state["last_run_started_at"] = time.time()
        self.latencies: dict[str, list[float]] = {}
        self.operation_counts: dict[str, int] = {}
        self.operation_errors: list[dict[str, Any]] = []
        self.samples: list[dict[str, Any]] = []
        self.invariant_failures: list[dict[str, Any]] = []
        self.expected_disconnects = 0

    def start_backend(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.library_dir.mkdir(parents=True, exist_ok=True)
        environment = os.environ.copy()
        environment.update(
            {
                "PYTHONPATH": str(REPO_ROOT),
                "PYTHONNOUSERSITE": "1",
                "CML_BACKEND_MODE": "full_vault",
                "CML_DATA_DIR": str(self.data_dir),
                "CML_DATABASE_PATH": str(self.database_path),
                "CML_API_TOKEN": self.api_token,
                "CML_ALLOW_HASH_EMBEDDINGS": "1",
                "CML_EMBEDDING_PROVIDER": "hash",
                "CML_ENABLE_DYNAMIC_WEB_INGESTION": "0",
            }
        )
        stdout = self.stdout_path.open("ab", buffering=0)
        stderr = self.stderr_path.open("ab", buffering=0)
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "backend.app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
            ],
            cwd=REPO_ROOT,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            creationflags=creationflags,
        )
        stdout.close()
        stderr.close()
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(f"Backend exited during startup with {self.process.returncode}")
            try:
                health = self.request("health", "GET", "/health", authenticated=False)
                if health.get("status") == "ok":
                    self.ensure_unlocked_after_restart()
                    return
            except (RuntimeError, URLError):
                time.sleep(0.25)
        raise RuntimeError("Backend did not become healthy within 45 seconds")

    def stop_backend(self) -> None:
        process = self.process
        self.process = None
        if process is None or process.poll() is not None:
            return
        try:
            root = psutil.Process(process.pid)
            children = root.children(recursive=True)
            for item in reversed(children):
                item.terminate()
            root.terminate()
            _gone, alive = psutil.wait_procs([*children, root], timeout=8)
            for item in alive:
                item.kill()
        except psutil.Error:
            process.kill()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()

    def restart_backend(self) -> None:
        self.stop_backend()
        try:
            self.request("expected_disconnect", "GET", "/health", authenticated=False, timeout=0.5)
            raise RuntimeError("Backend health unexpectedly succeeded after process stop")
        except (RuntimeError, URLError):
            self.expected_disconnects += 1
        self.start_backend()
        self.state["restart_count"] = int(self.state["restart_count"]) + 1

    def request(
        self,
        operation: str,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        authenticated: bool = True,
        bridge_token: str = "",
        timeout: float | None = None,
        expected_statuses: tuple[int, ...] = (200, 201, 202),
    ) -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if authenticated:
            headers["x-cml-api-token"] = self.api_token
        if bridge_token:
            headers["x-cml-bridge-token"] = bridge_token
        request = Request(self.base_url + path, data=body, headers=headers, method=method)
        started = time.perf_counter()
        status = 0
        try:
            with urlopen(request, timeout=timeout or self.args.request_timeout) as response:
                status = int(response.status)
                raw = response.read(4 * 1024 * 1024 + 1)
                if len(raw) > 4 * 1024 * 1024:
                    raise RuntimeError(f"{operation} response exceeded 4 MiB")
                result = json.loads(raw.decode("utf-8")) if raw else {}
        except HTTPError as exc:
            status = int(exc.code)
            raw = exc.read(64 * 1024)
            detail = raw.decode("utf-8", errors="replace")
            if status not in expected_statuses:
                raise RuntimeError(f"{operation} returned HTTP {status}: {detail[:500]}") from exc
            result = json.loads(detail) if detail else {}
        finally:
            elapsed = (time.perf_counter() - started) * 1000
            self.latencies.setdefault(operation, []).append(elapsed)
            if len(self.latencies[operation]) > 20_000:
                self.latencies[operation] = self.latencies[operation][-20_000:]
        if status not in expected_statuses:
            raise RuntimeError(f"{operation} returned unexpected HTTP {status}")
        self.operation_counts[operation] = self.operation_counts.get(operation, 0) + 1
        return result if isinstance(result, dict) else {"items": result}

    def ensure_fixture(self) -> None:
        if not self.state["vault_id"]:
            vault = self.request(
                "create_vault",
                "POST",
                f"{API_PREFIX}/vaults",
                {"name": "Remediation soak vault", "path": str(self.library_dir)},
            )
            self.state["vault_id"] = vault["id"]
            self.request(
                "initialize_security",
                "POST",
                f"{API_PREFIX}/system/unlock/initialize",
                {
                    "vault_id": vault["id"],
                    "passphrase": TEST_PASSPHRASE,
                    "unlock_mode": "strict",
                },
            )
        self.ensure_unlocked_after_restart()
        self.watch_dir.mkdir(parents=True, exist_ok=True)
        if not self.state["watch_import_id"]:
            (self.watch_dir / "seed.md").write_text("soak watched seed", encoding="utf-8")
            scanned = self.request(
                "watch_register",
                "POST",
                f"{API_PREFIX}/integrations/local-folder/scan",
                {"path": str(self.watch_dir), "vault_id": self.state["vault_id"], "max_files": 25},
            )
            self.state["watch_import_id"] = scanned["import_id"]
        self.project_dir.mkdir(parents=True, exist_ok=True)
        project_file = self.project_dir / "soak_module.py"
        if not project_file.exists():
            project_file.write_text("VALUE = 1\n", encoding="utf-8")
        if not self.state["project_id"]:
            project = self.request(
                "project_register",
                "POST",
                f"{API_PREFIX}/projects",
                {
                    "vault_id": self.state["vault_id"],
                    "root_path": str(self.project_dir),
                    "name": "Remediation soak project",
                    "discovery_scope": "code",
                    "sync": True,
                },
            )
            self.state["project_id"] = project["id"]
        if not self.state["bridge_token"]:
            self.request(
                "bridge_enable",
                "PATCH",
                f"{API_PREFIX}/bridge/settings",
                {"enabled": True, "allowed_vault_ids": [self.state["vault_id"]]},
            )
            client = self.request(
                "bridge_client_create",
                "POST",
                f"{API_PREFIX}/bridge/clients",
                {
                    "name": "Remediation soak",
                    "capability_profile": "read_only",
                    "allowed_vault_ids": [self.state["vault_id"]],
                },
            )
            self.state["bridge_client_id"] = client["id"]
            self.state["bridge_token"] = client["token"]
        self.save_state()

    def ensure_unlocked_after_restart(self) -> None:
        if not self.state.get("vault_id"):
            return
        status = self.request("unlock_status", "GET", f"{API_PREFIX}/system/unlock/status")
        if not status.get("ready"):
            self.request(
                "unlock_passphrase",
                "POST",
                f"{API_PREFIX}/system/unlock/passphrase",
                {"vault_id": self.state["vault_id"], "passphrase": TEST_PASSPHRASE},
            )

    def run_cycle(self) -> None:
        cycle = int(self.state["cycle"]) + 1
        vault_id = self.state["vault_id"]
        self.request("health", "GET", "/health", authenticated=False)
        if int(self.state["source_count"]) < self.args.max_sources:
            source = self.request(
                "source_create",
                "POST",
                f"{API_PREFIX}/sources/from-text",
                {
                    "vault_id": vault_id,
                    "title": f"Soak source {cycle}",
                    "text": (
                        ("soakneedle " * 20)
                        + (f"remediation soak cycle {cycle} stability security restart retrieval evidence " * 8)
                    ),
                },
            )
            if not source.get("id"):
                raise RuntimeError("Source creation returned no id")
            self.state["search_source_id"] = source["id"]
            if source.get("cluster_id"):
                self.state["search_cluster_id"] = source["cluster_id"]
            self.state["source_count"] = int(self.state["source_count"]) + 1
        search_payload = {
            "vault_id": vault_id,
            "query": "soakneedle",
            "limit": 5,
        }
        if self.state.get("search_cluster_id"):
            search_payload["cluster_id"] = self.state["search_cluster_id"]
        search = self.request(
            "semantic_search", "POST", f"{API_PREFIX}/search/semantic", search_payload
        )
        if int(self.state["source_count"]) > 0 and not search.get("results"):
            # Text ingestion is durable before its reindex worker publishes chunks.
            # Give that asynchronous boundary a bounded chance to finish rather
            # than treating expected first-cycle queueing as lost data.
            self.request("jobs_wake", "POST", f"{API_PREFIX}/jobs/run-once", {})
            search_deadline = time.monotonic() + min(15.0, self.args.request_timeout)
            while time.monotonic() < search_deadline and not search.get("results"):
                time.sleep(0.25)
                if self.state.get("search_source_id") and not self.state.get("search_cluster_id"):
                    published_source = self.request(
                        "source_publication_status",
                        "GET",
                        f"{API_PREFIX}/sources/{self.state['search_source_id']}",
                    )
                    if published_source.get("cluster_id"):
                        self.state["search_cluster_id"] = published_source["cluster_id"]
                        search_payload["cluster_id"] = published_source["cluster_id"]
                search = self.request(
                    "semantic_search_retry",
                    "POST",
                    f"{API_PREFIX}/search/semantic",
                    search_payload,
                )
            if not search.get("results"):
                raise RuntimeError("Semantic search did not observe durable source publication")
        if int(self.state["chat_count"]) < self.args.max_chats and cycle % 3 == 0:
            chat = self.request(
                "chat_create",
                "POST",
                f"{API_PREFIX}/chat/sessions",
                {"vault_id": vault_id, "title": f"Soak chat {cycle}"},
            )
            if not chat.get("id"):
                raise RuntimeError("Chat creation returned no id")
            self.state["chat_count"] = int(self.state["chat_count"]) + 1
        self.request(
            "chat_list",
            "GET",
            f"{API_PREFIX}/chat/sessions/page?{urlencode({'vault_id': vault_id, 'limit': 25})}",
        )
        if cycle % 4 == 0:
            watched = self.watch_dir / f"watched-{cycle % 100:03d}.md"
            watched.write_text(f"watched cycle {cycle}", encoding="utf-8")
            self.request(
                "watch_refresh",
                "POST",
                f"{API_PREFIX}/integrations/imports/{self.state['watch_import_id']}/refresh"
                "?import_files=false&tombstone_missing=false&trigger_source=watch_refresh&scan_limit=25",
            )
        if cycle % 6 == 0:
            self.request(
                "bridge_context",
                "POST",
                f"{API_PREFIX}/bridge/context",
                {"vault_id": vault_id, "query": "stability restart evidence", "limit": 3},
                bridge_token=self.state["bridge_token"],
            )
        if cycle % 10 == 0:
            (self.project_dir / "soak_module.py").write_text(f"VALUE = {cycle}\n", encoding="utf-8")
            self.request(
                "project_sync",
                "POST",
                f"{API_PREFIX}/projects/{self.state['project_id']}/sync",
                {},
            )
        self.request("jobs_wake", "POST", f"{API_PREFIX}/jobs/run-once", {})
        self.request("jobs_status", "GET", f"{API_PREFIX}/jobs/status")
        if self.args.lock_every_cycles > 0 and cycle % self.args.lock_every_cycles == 0:
            self.request(
                "vault_lock",
                "POST",
                f"{API_PREFIX}/system/unlock/lock?{urlencode({'vault_id': vault_id})}",
                {},
            )
            self.request(
                "locked_search",
                "POST",
                f"{API_PREFIX}/search/semantic",
                {"vault_id": vault_id, "query": "must be locked", "limit": 1},
                expected_statuses=(423,),
            )
            self.ensure_unlocked_after_restart()
            self.state["lock_cycle_count"] = int(self.state["lock_cycle_count"]) + 1
        self.state["cycle"] = cycle
        self.sample_resources()
        self.check_invariants()
        self.save_state()

    def sample_resources(self) -> None:
        rss = 0
        handles = 0
        threads = 0
        if self.process and self.process.poll() is None:
            try:
                processes = [psutil.Process(self.process.pid)]
                processes.extend(processes[0].children(recursive=True))
                for process in processes:
                    with process.oneshot():
                        rss += process.memory_info().rss
                        threads += process.num_threads()
                        if hasattr(process, "num_handles"):
                            handles += process.num_handles()
            except psutil.Error:
                pass
        db_bytes = matching_file_bytes(self.data_dir, "cml.sqlite3*")
        self.samples.append(
            {
                "at": time.time(),
                "cycle": int(self.state["cycle"]),
                "rss_bytes": rss,
                "handles": handles,
                "threads": threads,
                "database_bytes": db_bytes,
            }
        )
        if len(self.samples) > 100_000:
            self.samples = self.samples[-100_000:]

    def check_invariants(self) -> None:
        if not self.database_path.exists():
            return
        try:
            with sqlite3.connect(f"file:{self.database_path}?mode=ro", uri=True, timeout=5) as conn:
                integrity = conn.execute("PRAGMA quick_check").fetchone()[0]
                duplicate_generations = conn.execute(
                    """
                    SELECT COUNT(*) FROM (
                        SELECT session_id FROM chat_generations
                        WHERE state IN ('queued', 'in_flight', 'retriable')
                        GROUP BY session_id HAVING COUNT(*) > 1
                    )
                    """
                ).fetchone()[0]
                stale_running = conn.execute(
                    """
                    SELECT COUNT(*) FROM app_jobs
                    WHERE status = 'running' AND deadline_at IS NOT NULL
                      AND deadline_at < datetime('now', '-30 seconds')
                    """
                ).fetchone()[0]
                active_jobs = conn.execute(
                    f"SELECT COUNT(*) FROM app_jobs WHERE status IN ({','.join('?' for _ in ACTIVE_JOB_STATES)})",
                    ACTIVE_JOB_STATES,
                ).fetchone()[0]
        except sqlite3.Error as exc:
            self.record_invariant("database_read", str(exc))
            return
        if integrity != "ok":
            self.record_invariant("sqlite_quick_check", str(integrity))
        if duplicate_generations:
            self.record_invariant("duplicate_active_generations", int(duplicate_generations))
        if stale_running:
            self.record_invariant("expired_running_jobs", int(stale_running))
        if active_jobs > 5_000:
            self.record_invariant("active_job_budget", int(active_jobs))

    def record_invariant(self, name: str, detail: Any) -> None:
        self.invariant_failures.append(
            {"at": time.time(), "cycle": int(self.state["cycle"]), "name": name, "detail": detail}
        )

    def save_state(self) -> None:
        atomic_json_write(self.state_path, self.state)
        latest_sample = self.samples[-1] if self.samples else {}
        atomic_json_write(
            self.live_status_path,
            {
                "schema_version": 1,
                "updated_at": time.time(),
                "runner_pid": os.getpid(),
                "backend_pid": self.process.pid if self.process is not None and self.process.poll() is None else None,
                "backend_alive": self.process is not None and self.process.poll() is None,
                "requested_duration_seconds": self.duration_seconds,
                "run_elapsed_seconds": round(time.time() - float(self.state["last_run_started_at"]), 3),
                "cycle": int(self.state["cycle"]),
                "source_count": int(self.state["source_count"]),
                "chat_count": int(self.state["chat_count"]),
                "restart_count": int(self.state["restart_count"]),
                "lock_cycle_count": int(self.state["lock_cycle_count"]),
                "operation_error_count": len(self.operation_errors),
                "invariant_failure_count": len(self.invariant_failures),
                "latest_resource_sample": latest_sample,
                "final_report": str(self.report_path),
            },
        )

    def build_report(self, *, elapsed: float, completed: bool) -> dict[str, Any]:
        latency_summary = {
            name: {
                "count": len(values),
                "p50_ms": round(percentile(values, 0.50), 3),
                "p95_ms": round(percentile(values, 0.95), 3),
                "p99_ms": round(percentile(values, 0.99), 3),
                "max_ms": round(max(values, default=0), 3),
            }
            for name, values in sorted(self.latencies.items())
        }
        rss_values = [int(item["rss_bytes"]) for item in self.samples if item["rss_bytes"]]
        db_values = [int(item["database_bytes"]) for item in self.samples]
        baseline_rss = percentile(rss_values[: min(30, len(rss_values))], 0.50)
        ending_rss = percentile(rss_values[-min(30, len(rss_values)) :], 0.95)
        rss_growth = max(0.0, ending_rss - baseline_rss)
        limits = {
            "max_rss_bytes": int(self.args.max_rss_mib * 1024 * 1024),
            "max_rss_growth_bytes": int(self.args.max_rss_growth_mib * 1024 * 1024),
            "max_database_bytes": int(self.args.max_db_mib * 1024 * 1024),
        }
        failures = list(self.operation_errors) + list(self.invariant_failures)
        if rss_values and max(rss_values) > limits["max_rss_bytes"]:
            failures.append({"name": "rss_ceiling", "detail": max(rss_values)})
        if rss_growth > limits["max_rss_growth_bytes"]:
            failures.append({"name": "rss_growth", "detail": rss_growth})
        if db_values and max(db_values) > limits["max_database_bytes"]:
            failures.append({"name": "database_ceiling", "detail": max(db_values)})
        return {
            "schema_version": 1,
            "generated_at": time.time(),
            "requested_duration_seconds": self.duration_seconds,
            "elapsed_seconds": round(elapsed, 3),
            "completed_requested_duration": completed,
            "accelerated_run": self.duration_seconds < 72 * 60 * 60,
            "state_dir": str(self.state_dir),
            "database_path": str(self.database_path),
            "state": self.state,
            "operation_counts": self.operation_counts,
            "latencies": latency_summary,
            "resource_summary": {
                "sample_count": len(self.samples),
                "peak_rss_bytes": max(rss_values, default=0),
                "baseline_rss_bytes": baseline_rss,
                "ending_rss_p95_bytes": ending_rss,
                "rss_growth_bytes": rss_growth,
                "peak_handles": max((int(item["handles"]) for item in self.samples), default=0),
                "peak_threads": max((int(item["threads"]) for item in self.samples), default=0),
                "peak_database_bytes": max(db_values, default=0),
            },
            "limits": limits,
            "expected_disconnects": self.expected_disconnects,
            "operation_errors": self.operation_errors,
            "invariant_failures": self.invariant_failures,
            "failures": failures,
            "pass": completed and not failures,
            "qualification_note": (
                "Only a completed 72-hour run on the intended Windows qualification host satisfies "
                "the elapsed-time soak gate. Shorter runs validate the harness and workload only."
            ),
        }

    @property
    def duration_seconds(self) -> float:
        if self.args.duration_seconds is not None:
            return max(1.0, float(self.args.duration_seconds))
        return max(1.0, float(self.args.duration_hours) * 60 * 60)

    def run(self) -> int:
        started = time.monotonic()
        deadline = started + self.duration_seconds
        completed = False
        try:
            self.start_backend()
            self.ensure_fixture()
            while time.monotonic() < deadline:
                cycle_started = time.monotonic()
                try:
                    self.run_cycle()
                    if (
                        self.args.restart_every_cycles > 0
                        and int(self.state["cycle"]) % self.args.restart_every_cycles == 0
                    ):
                        self.restart_backend()
                        self.save_state()
                except Exception as exc:
                    error = {
                        "at": time.time(),
                        "cycle": int(self.state["cycle"]),
                        "error": f"{exc.__class__.__name__}: {exc}",
                    }
                    self.operation_errors.append(error)
                    if not self.args.continue_on_operation_error:
                        raise
                remaining = self.args.cycle_seconds - (time.monotonic() - cycle_started)
                if remaining > 0:
                    time.sleep(min(remaining, max(0, deadline - time.monotonic())))
            completed = True
        finally:
            elapsed = time.monotonic() - started
            self.stop_backend()
            self.save_state()
            report = self.build_report(elapsed=elapsed, completed=completed)
            atomic_json_write(self.report_path, report)
            print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["pass"] else 1


def main() -> int:
    args = parse_args()
    runner = SoakRunner(args)
    return runner.run()


if __name__ == "__main__":
    raise SystemExit(main())
