from __future__ import annotations

import atexit
import json
import os
from pathlib import Path
import socket
import subprocess
import threading
import time
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from backend.app.core.config import get_settings
from backend.app.core.database import utc_now


class ManagedRuntimeError(RuntimeError):
    pass


_LOCK = threading.RLock()
_PROCESS: subprocess.Popen[bytes] | None = None
_STATE: dict[str, Any] = {}
_STATE_PATH: Path | None = None


def managed_runtime_state_path() -> Path:
    return get_settings().data_dir / "managed-model-runtime.json"


def managed_runtime_status() -> dict[str, Any]:
    with _LOCK:
        state = dict(_load_state_locked())
        process = _PROCESS
        if process is not None and process.poll() is not None:
            state.update(
                {
                    "state": "failed",
                    "available": False,
                    "pid": None,
                    "error": f"The local model process exited with code {process.returncode}.",
                    "detail": "The selected model stopped unexpectedly.",
                    "updated_at": utc_now(),
                }
            )
            _persist_state_locked(state)
        elif process is not None:
            state["pid"] = process.pid
        return state


def effective_runtime_config() -> dict[str, str] | None:
    state = managed_runtime_status()
    if state.get("state") not in {"ready", "busy"} or not state.get("available"):
        return None
    base_url = str(state.get("base_url") or "")
    model_id = str(state.get("model_id") or "")
    if not base_url or not model_id:
        return None
    return {
        "provider": "managed-llama.cpp",
        "base_url": base_url,
        "model": model_id,
    }


def activate_managed_model(model_id: str, model_path: str) -> dict[str, Any]:
    candidate = Path(model_path).resolve()
    if not candidate.is_file() or candidate.suffix.casefold() != ".gguf":
        raise ManagedRuntimeError("The selected model does not contain an executable GGUF file.")

    runtime_binary = _runtime_binary()
    if runtime_binary is None:
        raise ManagedRuntimeError(
            "The local model engine is missing. Reinstall Vault or repair the packaged runtime."
        )

    with _LOCK:
        previous = dict(_load_state_locked())
        previous_model_id = str(previous.get("model_id") or "")
        previous_model_path = str(previous.get("model_path") or "")
        _stop_locked(mark_stopped=False)
        try:
            return _start_locked(
                model_id=model_id,
                model_path=str(candidate),
                runtime_binary=runtime_binary,
            )
        except Exception as exc:
            failure = {
                **previous,
                "state": "failed",
                "available": False,
                "pid": None,
                "attempted_model_id": model_id,
                "error": str(exc),
                "detail": f"Vault could not start {model_id}.",
                "updated_at": utc_now(),
            }
            _persist_state_locked(failure)
            if previous_model_id and previous_model_path and Path(previous_model_path).is_file():
                try:
                    _start_locked(
                        model_id=previous_model_id,
                        model_path=previous_model_path,
                        runtime_binary=runtime_binary,
                    )
                except Exception as rollback_exc:
                    failure["rollback_error"] = str(rollback_exc)
                    _persist_state_locked(failure)
            raise ManagedRuntimeError(str(exc)) from exc


def restore_selected_model(model_id: str, model_path: str) -> None:
    def worker() -> None:
        try:
            activate_managed_model(model_id, model_path)
        except ManagedRuntimeError:
            return

    thread = threading.Thread(target=worker, name="managed-model-runtime-restore", daemon=True)
    thread.start()


def stop_managed_runtime() -> None:
    with _LOCK:
        _stop_locked(mark_stopped=True)


def _start_locked(*, model_id: str, model_path: str, runtime_binary: str) -> dict[str, Any]:
    global _PROCESS
    port = _find_open_port()
    base_url = f"http://127.0.0.1:{port}/v1"
    stdout_path = get_settings().data_dir / "model-runtime-stdout.log"
    stderr_path = get_settings().data_dir / "model-runtime-stderr.log"
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    command = _runtime_command(runtime_binary, model_path, model_id, port)
    starting = {
        "schema_version": 1,
        "state": "starting",
        "available": False,
        "provider": "managed-llama.cpp",
        "base_url": base_url,
        "model_id": model_id,
        "model_path": model_path,
        "pid": None,
        "error": None,
        "detail": f"Starting {model_id}.",
        "stdout_log": str(stdout_path),
        "stderr_log": str(stderr_path),
        "started_at": utc_now(),
        "updated_at": utc_now(),
    }
    _persist_state_locked(starting)
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    with stdout_path.open("ab") as stdout, stderr_path.open("ab") as stderr:
        _PROCESS = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            cwd=str(Path(runtime_binary).resolve().parent),
            creationflags=creationflags,
        )
    starting["pid"] = _PROCESS.pid
    _persist_state_locked(starting)
    try:
        _wait_for_models(base_url, _PROCESS)
        _probe_generation(base_url, model_id, _PROCESS)
    except Exception:
        _terminate_process(_PROCESS)
        _PROCESS = None
        raise
    ready = {
        **starting,
        "state": "ready",
        "available": True,
        "pid": _PROCESS.pid,
        "detail": f"{model_id} is ready for local chat.",
        "ready_at": utc_now(),
        "updated_at": utc_now(),
    }
    _persist_state_locked(ready)
    return dict(ready)


def _stop_locked(*, mark_stopped: bool) -> None:
    global _PROCESS
    if _PROCESS is not None:
        _terminate_process(_PROCESS)
        _PROCESS = None
    if mark_stopped:
        state = dict(_load_state_locked())
        state.update(
            {
                "state": "stopped",
                "available": False,
                "pid": None,
                "detail": "The managed local model is stopped.",
                "updated_at": utc_now(),
            }
        )
        _persist_state_locked(state)


def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _runtime_binary() -> str | None:
    configured = str(os.environ.get("CML_LLM_RUNTIME_BINARY") or "").strip()
    if configured and Path(configured).is_file():
        return str(Path(configured).resolve())
    return None


def _runtime_command(runtime_binary: str, model_path: str, model_id: str, port: int) -> list[str]:
    template = str(os.environ.get("CML_LLM_RUNTIME_COMMAND_JSON") or "").strip()
    if template:
        try:
            values = json.loads(template)
        except json.JSONDecodeError as exc:
            raise ManagedRuntimeError("The managed runtime command is malformed.") from exc
        if not isinstance(values, list) or not values:
            raise ManagedRuntimeError("The managed runtime command is malformed.")
        replacements = {
            "{runtime_binary}": runtime_binary,
            "{model_path}": model_path,
            "{model_id}": model_id,
            "{port}": str(port),
        }
        return [
            replacements.get(str(value), str(value)
                .replace("{runtime_binary}", runtime_binary)
                .replace("{model_path}", model_path)
                .replace("{model_id}", model_id)
                .replace("{port}", str(port)))
            for value in values
        ]
    return [
        runtime_binary,
        "--model",
        model_path,
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--alias",
        model_id,
        "--ctx-size",
        "4096",
        "--no-webui",
    ]


def _wait_for_models(base_url: str, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + max(
        5.0,
        float(os.environ.get("CML_LLM_RUNTIME_START_TIMEOUT_SECONDS") or 120),
    )
    last_error = "The local model engine did not become ready."
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise ManagedRuntimeError(
                f"The local model engine exited during startup with code {process.returncode}."
            )
        try:
            _json_request(f"{base_url}/models", timeout=2)
            return
        except ManagedRuntimeError as exc:
            last_error = str(exc)
            time.sleep(0.25)
    raise ManagedRuntimeError(last_error)


def _probe_generation(
    base_url: str,
    model_id: str,
    process: subprocess.Popen[bytes],
) -> None:
    if process.poll() is not None:
        raise ManagedRuntimeError("The local model engine stopped before its generation check.")
    response = _json_request(
        f"{base_url}/chat/completions",
        payload={
            "model": model_id,
            "messages": [
                {
                    "role": "user",
                    "content": "/no_think\nReply with exactly OK.",
                }
            ],
            "temperature": 0,
            "max_tokens": 32,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
        },
        timeout=max(
            5.0,
            float(os.environ.get("CML_LLM_RUNTIME_PROBE_TIMEOUT_SECONDS") or 60),
        ),
    )
    try:
        content = str(response["choices"][0]["message"]["content"]).strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise ManagedRuntimeError("The local model engine failed its generation check.") from exc
    if not content:
        raise ManagedRuntimeError("The local model engine returned an empty generation check.")


def _json_request(
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout: float,
) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        url,
        data=data,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="POST" if payload is not None else "GET",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ManagedRuntimeError(f"The local model engine is not reachable at {url}.") from exc
    if not isinstance(result, dict):
        raise ManagedRuntimeError("The local model engine returned an invalid response.")
    return result


def _find_open_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        return int(server.getsockname()[1])


def _load_state_locked() -> dict[str, Any]:
    global _STATE_PATH
    path = managed_runtime_state_path()
    if _STATE_PATH == path and _STATE:
        return _STATE
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    if payload.get("state") in {"starting", "ready", "busy"}:
        payload.update(
            {
                "state": "stopped",
                "available": False,
                "pid": None,
                "detail": "The selected model will restart with the vault service.",
                "updated_at": utc_now(),
            }
        )
    _STATE.clear()
    _STATE.update(payload)
    _STATE_PATH = path
    return _STATE


def _persist_state_locked(state: dict[str, Any]) -> None:
    global _STATE_PATH
    path = managed_runtime_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(state, indent=2), encoding="utf-8")
    temporary.replace(path)
    _STATE.clear()
    _STATE.update(state)
    _STATE_PATH = path


atexit.register(stop_managed_runtime)
