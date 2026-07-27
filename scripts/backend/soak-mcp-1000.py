"""Run 1,000 real stdio MCP calls against an isolated authenticated backend."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import psutil


def percentile(values: list[float], ratio: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * ratio) - 1)]


def request_json(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict | None = None,
    token: str = "",
) -> dict:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"accept": "application/json"}
    if body is not None:
        headers["content-type"] = "application/json"
    if token:
        headers["x-cml-api-token"] = token
    request = Request(f"{base_url}{path}", data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed ({exc.code}): {detail[:500]}") from exc


def wait_for_backend(base_url: str, process: subprocess.Popen, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Backend exited before readiness ({process.returncode}).")
        try:
            request_json(base_url, "/health")
            return
        except Exception:
            time.sleep(0.1)
    raise RuntimeError("Backend did not become healthy before the timeout.")


def send_mcp(process: subprocess.Popen, message: dict) -> dict:
    assert process.stdin is not None
    assert process.stdout is not None
    process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
    process.stdin.flush()
    line = process.stdout.readline()
    if not line:
        stderr = process.stderr.read(2000) if process.stderr else ""
        raise RuntimeError(f"MCP server closed stdout unexpectedly: {stderr}")
    response = json.loads(line)
    if "error" in response:
        raise RuntimeError(f"MCP call failed: {response['error']}")
    return response


def terminate(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--calls", type=int, default=1000)
    parser.add_argument("--port", type=int, default=7477)
    parser.add_argument("--report", default="tmp/mcp-soak-1000.json")
    parser.add_argument(
        "--runtime-root",
        default="",
        help="Root containing backend/app; defaults to the source checkout.",
    )
    parser.add_argument("--max-p95-ms", type=float, default=500.0)
    parser.add_argument("--max-rss-growth-mib", type=float, default=32.0)
    args = parser.parse_args()
    if args.calls < 1:
        raise SystemExit("--calls must be positive")

    repo_root = Path(__file__).resolve().parents[2]
    runtime_root = Path(args.runtime_root).resolve() if args.runtime_root else repo_root
    if not (runtime_root / "backend" / "app" / "bridge_mcp.py").is_file():
        raise SystemExit(f"Backend runtime not found under {runtime_root}")
    report_path = (repo_root / args.report).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    base_url = f"http://127.0.0.1:{args.port}"
    api_token = f"soak-{secrets.token_urlsafe(32)}"
    work = Path(tempfile.mkdtemp(prefix="cml-mcp-soak-"))
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(runtime_root),
            "PYTHONNOUSERSITE": "1",
            "CML_DATA_DIR": str(work / "data"),
            "CML_DATABASE_PATH": str(work / "data" / "cml.sqlite3"),
            "CML_API_TOKEN": api_token,
            "CML_BACKEND_MODE": "full_vault",
            "CML_ALLOW_HASH_EMBEDDINGS": "1",
            "CML_EMBEDDING_PROVIDER": "hash",
            "CML_DISABLE_MODEL_AUTO_DOWNLOAD": "1",
            "CML_STARTUP_STATUS_PATH": str(work / "startup-status.json"),
        }
    )
    backend_log = (work / "backend.log").open("w", encoding="utf-8")
    backend: subprocess.Popen | None = None
    mcp: subprocess.Popen | None = None
    try:
        backend = subprocess.Popen(
            [
                sys.executable,
                "-s",
                "-m",
                "uvicorn",
                "backend.app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(args.port),
            ],
            cwd=runtime_root,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=backend_log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        wait_for_backend(base_url, backend)
        vault = request_json(
            base_url,
            "/api/v1/vaults",
            method="POST",
            payload={"name": "MCP soak vault", "path": str(work / "vault")},
            token=api_token,
        )
        request_json(
            base_url,
            "/api/v1/bridge/settings",
            method="PATCH",
            payload={
                "enabled": True,
                "allowed_vault_ids": [vault["id"]],
                "rotate_token": True,
            },
            token=api_token,
        )
        approval = request_json(
            base_url,
            "/api/v1/bridge/approval-requests",
            method="POST",
            payload={
                "claimed_name": "MCP soak client",
                "requested_vault_ids": [vault["id"]],
                "capability_profile": "read_only",
            },
        )
        approved = request_json(
            base_url,
            f"/api/v1/bridge/approval-requests/{approval['request_id']}/approve",
            method="POST",
            payload={"detail": "Automated 1,000-call release soak"},
            token=api_token,
        )
        mcp_env = {
            key: env[key]
            for key in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC")
            if env.get(key)
        }
        mcp_env.update({
            "PYTHONPATH": str(runtime_root),
            "PYTHONNOUSERSITE": "1",
            "CML_BACKEND_URL": base_url,
            "CML_BRIDGE_TOKEN": approved["token"],
            "CML_MCP_CAPABILITY_PROFILE": "read_only",
        })
        mcp = subprocess.Popen(
            [sys.executable, "-s", "-m", "backend.app.bridge_mcp_stdio"],
            cwd=runtime_root,
            env=mcp_env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        started = time.perf_counter()
        send_mcp(
            mcp,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "release-soak", "version": "1"},
                },
            },
        )
        initialization_ms = (time.perf_counter() - started) * 1000
        tool_list_started = time.perf_counter()
        tools = send_mcp(mcp, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        tool_list_ms = (time.perf_counter() - tool_list_started) * 1000
        names = {tool["name"] for tool in tools["result"]["tools"]}
        if "list_clusters" not in names or "capture_external_artifact" in names:
            raise RuntimeError("Read-only MCP tool scan returned the wrong capability profile.")

        process_info = psutil.Process(mcp.pid)
        rss_before = process_info.memory_info().rss
        latencies: list[float] = []
        rate_bucket_resets = 0
        for index in range(args.calls):
            # Production rate limiting is covered separately. Reset only this
            # isolated fixture's buckets so the soak measures 1,000 successful
            # protocol/backend calls without waiting through five-minute windows.
            if index > 0 and index % 50 == 0:
                with sqlite3.connect(work / "data" / "cml.sqlite3", timeout=10) as connection:
                    connection.execute("DELETE FROM bridge_rate_limits WHERE bucket = 'bridge_runtime'")
                rate_bucket_resets += 1
            call_started = time.perf_counter()
            response = send_mcp(
                mcp,
                {
                    "jsonrpc": "2.0",
                    "id": index + 100,
                    "method": "tools/call",
                    "params": {
                        "name": "list_clusters",
                        "arguments": {"limit": 1},
                    },
                },
            )
            latencies.append((time.perf_counter() - call_started) * 1000)
            if response["result"].get("isError"):
                raise RuntimeError(f"Call {index + 1} returned an MCP tool error.")
        rss_after = process_info.memory_info().rss
        rss_growth_mib = max(0, rss_after - rss_before) / (1024 * 1024)
        p95_ms = percentile(latencies, 0.95)
        report = {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "calls": args.calls,
            "backend": "isolated_authenticated_loopback",
            "runtime_root": str(runtime_root),
            "python": sys.executable,
            "capability_profile": "read_only",
            "initialization_ms": round(initialization_ms, 3),
            "tool_list_ms": round(tool_list_ms, 3),
            "list_clusters_ms": {
                "min": round(min(latencies), 3),
                "median": round(percentile(latencies, 0.5), 3),
                "p95": round(p95_ms, 3),
                "max": round(max(latencies), 3),
            },
            "mcp_rss_growth_mib": round(rss_growth_mib, 3),
            "isolated_rate_bucket_resets": rate_bucket_resets,
            "limits": {
                "max_p95_ms": args.max_p95_ms,
                "max_rss_growth_mib": args.max_rss_growth_mib,
            },
            "pass": (
                initialization_ms < 1000
                and tool_list_ms < 1000
                and p95_ms <= args.max_p95_ms
                and rss_growth_mib <= args.max_rss_growth_mib
            ),
            "work_root": str(work),
        }
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 0 if report["pass"] else 1
    finally:
        terminate(mcp)
        terminate(backend)
        backend_log.close()


if __name__ == "__main__":
    raise SystemExit(main())
