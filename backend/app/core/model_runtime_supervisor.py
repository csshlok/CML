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
_SWAP_LOCK = threading.Lock()
_PROCESS: subprocess.Popen[bytes] | None = None
_STATE: dict[str, Any] = {}
_STATE_PATH: Path | None = None
_RUNTIME_LEASES: dict[str, int] = {}


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


def acquire_managed_runtime() -> dict[str, str] | None:
    """Atomically pin the currently published managed endpoint for one request."""
    with _LOCK:
        config = effective_runtime_config()
        if config is None:
            return None
        key = _runtime_key(config["base_url"])
        _RUNTIME_LEASES[key] = _RUNTIME_LEASES.get(key, 0) + 1
        return config


def release_managed_runtime(config: dict[str, str]) -> None:
    with _LOCK:
        key = _runtime_key(config.get("base_url", ""))
        remaining = max(0, _RUNTIME_LEASES.get(key, 0) - 1)
        if remaining:
            _RUNTIME_LEASES[key] = remaining
        else:
            _RUNTIME_LEASES.pop(key, None)


def activate_managed_model(model_id: str, model_path: str) -> dict[str, Any]:
    candidate = Path(model_path).resolve()
    if not candidate.is_file() or candidate.suffix.casefold() != ".gguf":
        raise ManagedRuntimeError("The selected model does not contain an executable GGUF file.")

    runtime_candidates = _runtime_candidates()
    if not runtime_candidates:
        raise ManagedRuntimeError(
            "The local model engine is missing. Reinstall Vault or repair the packaged runtime."
        )

    with _SWAP_LOCK:
        previous_process: subprocess.Popen[bytes] | None = None
        previous_base_url = ""
        with _LOCK:
            global _PROCESS
            previous = dict(_load_state_locked())
            previous_model_id = str(previous.get("model_id") or "")
            previous_model_path = str(previous.get("model_path") or "")
            previous_base_url = str(previous.get("base_url") or "")
            previous_process = _PROCESS
            keep_previous_running = (
                previous_process is not None
                and previous_process.poll() is None
                and _runtime_request_count(previous_base_url) > 0
            )
            if keep_previous_running:
                # _start_locked publishes the replacement through _PROCESS. Keep
                # the old handle locally until requests pinned to its URL drain.
                _PROCESS = None
            else:
                _stop_locked(mark_stopped=False)
                previous_process = None
            cleanup = _terminate_verified_orphans_locked(
                runtime_binaries={binary for _, binary in runtime_candidates},
                model_paths={
                    path
                    for path in (str(candidate), previous_model_path)
                    if path
                },
                exclude_pids=(
                    {int(previous_process.pid)} if previous_process is not None else set()
                ),
            )
            attempts: list[dict[str, str]] = []
            last_error: Exception | None = None
            activated: dict[str, Any] | None = None
            for runtime_backend, runtime_binary in runtime_candidates:
                try:
                    activated = _start_locked(
                        model_id=model_id,
                        model_path=str(candidate),
                        runtime_binary=runtime_binary,
                        runtime_backend=runtime_backend,
                        cleanup=cleanup,
                        attempts=attempts,
                    )
                    break
                except Exception as exc:
                    last_error = exc
                    attempts.append({"runtime_backend": runtime_backend, "error": str(exc)})

            if activated is None:
                final_error = str(last_error or "The local model engine could not start.")
                if previous_process is not None and previous_process.poll() is None:
                    _PROCESS = previous_process
                    previous.update(
                        {
                            "state": "ready",
                            "available": True,
                            "pid": previous_process.pid,
                            "attempted_model_id": model_id,
                            "error": final_error,
                            "detail": f"Vault kept {previous_model_id} active because {model_id} could not start.",
                            "runtime_attempts": attempts,
                            "updated_at": utc_now(),
                        }
                    )
                    _persist_state_locked(previous)
                else:
                    failure = {
                        **previous,
                        "state": "failed",
                        "available": False,
                        "pid": None,
                        "attempted_model_id": model_id,
                        "error": final_error,
                        "detail": f"Vault could not start {model_id}.",
                        "runtime_attempts": attempts,
                        "orphan_cleanup": cleanup,
                        "updated_at": utc_now(),
                    }
                    _persist_state_locked(failure)
                    if previous_model_id and previous_model_path and Path(previous_model_path).is_file():
                        for runtime_backend, runtime_binary in runtime_candidates:
                            try:
                                _start_locked(
                                    model_id=previous_model_id,
                                    model_path=previous_model_path,
                                    runtime_binary=runtime_binary,
                                    runtime_backend=runtime_backend,
                                    cleanup={"count": 0, "pids": []},
                                    attempts=[],
                                )
                                break
                            except Exception as rollback_exc:
                                failure["rollback_error"] = str(rollback_exc)
                                _persist_state_locked(failure)
                raise ManagedRuntimeError(final_error) from last_error

        if previous_process is not None:
            drained = _wait_for_runtime_drain(previous_base_url)
            _terminate_process(previous_process)
            with _LOCK:
                current = dict(_load_state_locked())
                current["previous_runtime_drained"] = drained
                current["previous_runtime_model_id"] = previous_model_id
                current["updated_at"] = utc_now()
                _persist_state_locked(current)
        return dict(activated)


def restore_selected_model(model_id: str, model_path: str) -> None:
    def worker() -> None:
        try:
            activate_managed_model(model_id, model_path)
        except ManagedRuntimeError:
            return

    thread = threading.Thread(target=worker, name="managed-model-runtime-restore", daemon=True)
    thread.start()


def stop_managed_runtime() -> None:
    with _SWAP_LOCK, _LOCK:
        previous = dict(_load_state_locked())
        _stop_locked(mark_stopped=False)
        runtime_binary = str(previous.get("runtime_binary") or "")
        model_path = str(previous.get("model_path") or "")
        cleanup = _terminate_verified_orphans_locked(
            runtime_binaries={runtime_binary} if runtime_binary else set(),
            model_paths={model_path} if model_path else set(),
        )
        previous.update(
            {
                "state": "stopped",
                "available": False,
                "pid": None,
                "detail": "The managed local model is stopped.",
                "orphan_cleanup": cleanup,
                "updated_at": utc_now(),
            }
        )
        _persist_state_locked(previous)


def _start_locked(
    *,
    model_id: str,
    model_path: str,
    runtime_binary: str,
    runtime_backend: str,
    cleanup: dict[str, Any],
    attempts: list[dict[str, str]],
) -> dict[str, Any]:
    global _PROCESS
    port = _find_open_port()
    base_url = f"http://127.0.0.1:{port}/v1"
    stdout_path = get_settings().data_dir / "model-runtime-stdout.log"
    stderr_path = get_settings().data_dir / "model-runtime-stderr.log"
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    command = _runtime_command(
        runtime_binary,
        model_path,
        model_id,
        port,
        runtime_backend=runtime_backend,
    )
    starting = {
        "schema_version": 1,
        "state": "starting",
        "available": False,
        "provider": "managed-llama.cpp",
        "runtime_backend": runtime_backend,
        "runtime_binary": runtime_binary,
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
        "runtime_attempts": list(attempts),
        "orphan_cleanup": cleanup,
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
    try:
        import psutil

        starting["process_create_time"] = float(psutil.Process(_PROCESS.pid).create_time())
    except Exception:
        starting["process_create_time"] = None
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
        "detail": (
            f"{model_id} is ready with GPU acceleration."
            if runtime_backend == "cuda"
            else (
                f"{model_id} is ready on CPU after GPU acceleration was unavailable."
                if attempts
                else f"{model_id} is ready for local chat."
            )
        ),
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


def _terminate_verified_orphans_locked(
    *,
    runtime_binaries: set[str],
    model_paths: set[str],
    exclude_pids: set[int] | None = None,
) -> dict[str, Any]:
    if not runtime_binaries or not model_paths:
        return {"count": 0, "pids": []}
    try:
        import psutil
    except Exception:
        return {"count": 0, "pids": []}

    expected_binaries = {_normalized_process_path(path) for path in runtime_binaries if path}
    expected_models = {_normalized_process_path(path) for path in model_paths if path}
    matched = []
    excluded = exclude_pids or set()
    for process in psutil.process_iter(["pid", "exe", "cmdline"]):
        try:
            if int(process.info.get("pid") or process.pid) in excluded:
                continue
            executable = _normalized_process_path(str(process.info.get("exe") or ""))
            command = [str(value) for value in (process.info.get("cmdline") or [])]
            model_path = _command_option(command, "--model")
            host = _command_option(command, "--host")
            if (
                executable in expected_binaries
                and _normalized_process_path(model_path) in expected_models
                and host in {"127.0.0.1", "localhost", "::1"}
            ):
                matched.append(process)
        except (psutil.AccessDenied, psutil.NoSuchProcess, OSError, ValueError):
            continue

    pids = sorted({int(process.pid) for process in matched})
    for process in matched:
        try:
            process.terminate()
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
    _, alive = psutil.wait_procs(matched, timeout=5)
    for process in alive:
        try:
            process.kill()
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
    if alive:
        _, alive = psutil.wait_procs(alive, timeout=5)
    if alive:
        survivor_ids = sorted({int(process.pid) for process in alive})
        raise ManagedRuntimeError(
            "Vault could not stop its previous local model process "
            f"({', '.join(str(pid) for pid in survivor_ids)})."
        )
    return {"count": len(pids), "pids": pids}


def _runtime_request_count(base_url: str) -> int:
    with _LOCK:
        return _RUNTIME_LEASES.get(_runtime_key(base_url), 0)


def _runtime_key(base_url: str) -> str:
    return str(base_url or "").rstrip("/").casefold()


def _wait_for_runtime_drain(base_url: str) -> bool:
    deadline = time.monotonic() + _bounded_int_env(
        "CML_LLM_RUNTIME_DRAIN_TIMEOUT_SECONDS",
        default=30,
        minimum=1,
        maximum=300,
    )
    while time.monotonic() < deadline:
        if _runtime_request_count(base_url) == 0:
            return True
        time.sleep(0.05)
    return _runtime_request_count(base_url) == 0


def _command_option(command: list[str], option: str) -> str:
    try:
        index = command.index(option)
    except ValueError:
        return ""
    if index + 1 >= len(command):
        return ""
    return str(command[index + 1])


def _normalized_process_path(value: str) -> str:
    if not value:
        return ""
    try:
        return os.path.normcase(os.path.abspath(value))
    except (OSError, ValueError):
        return ""


def _runtime_candidates() -> list[tuple[str, str]]:
    configured_cpu = str(os.environ.get("CML_LLM_RUNTIME_BINARY") or "").strip()
    configured_cuda = str(os.environ.get("CML_LLM_RUNTIME_CUDA_BINARY") or "").strip()
    cpu_binary = str(Path(configured_cpu).resolve()) if configured_cpu and Path(configured_cpu).is_file() else ""
    cuda_binary = (
        str(Path(configured_cuda).resolve())
        if configured_cuda and Path(configured_cuda).is_file()
        else ""
    )
    preference = str(os.environ.get("CML_LLM_RUNTIME_PREFERENCE") or "auto").strip().lower()
    if preference not in {"auto", "cpu", "cuda"}:
        preference = "auto"

    ordered: list[tuple[str, str]] = []
    if preference == "cpu":
        if cpu_binary:
            ordered.append(("cpu", cpu_binary))
    elif preference == "cuda":
        if cuda_binary:
            ordered.append(("cuda", cuda_binary))
        if cpu_binary:
            ordered.append(("cpu", cpu_binary))
    else:
        if cuda_binary and _nvidia_gpu_available():
            ordered.append(("cuda", cuda_binary))
        if cpu_binary:
            ordered.append(("cpu", cpu_binary))
        if cuda_binary and not ordered:
            ordered.append(("cuda", cuda_binary))

    unique: list[tuple[str, str]] = []
    seen: set[str] = set()
    for runtime_backend, binary in ordered:
        normalized = os.path.normcase(os.path.abspath(binary))
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append((runtime_backend, binary))
    return unique


def _nvidia_gpu_available() -> bool:
    try:
        from backend.app.core.hardware import hardware_status

        return any(
            str(gpu.get("vendor") or "").lower() == "nvidia"
            and not bool(gpu.get("shared_memory"))
            and int(gpu.get("usable_vram_bytes") or gpu.get("vram_bytes") or 0) >= 3 * 1024**3
            for gpu in hardware_status().get("gpus") or []
            if isinstance(gpu, dict)
        )
    except Exception:
        return False


def _runtime_thread_counts() -> tuple[int, int]:
    logical = max(1, int(os.cpu_count() or 1))
    try:
        import psutil

        physical = int(psutil.cpu_count(logical=False) or 0)
    except Exception:
        physical = 0
    generation_default = physical or max(1, logical // 2)
    generation = _bounded_int_env(
        "CML_LLM_RUNTIME_THREADS",
        default=min(generation_default, 16),
        minimum=1,
        maximum=64,
    )
    batch = _bounded_int_env(
        "CML_LLM_RUNTIME_BATCH_THREADS",
        default=min(max(generation, logical), 32),
        minimum=1,
        maximum=64,
    )
    return generation, batch


def _bounded_int_env(name: str, *, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(str(os.environ.get(name) or default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def _runtime_command(
    runtime_binary: str,
    model_path: str,
    model_id: str,
    port: int,
    *,
    runtime_backend: str = "cpu",
) -> list[str]:
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
    generation_threads, batch_threads = _runtime_thread_counts()
    command = [
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
        str(
            _bounded_int_env(
                "CML_LLM_RUNTIME_CONTEXT_SIZE",
                default=4096,
                minimum=1024,
                maximum=32768,
            )
        ),
        "--threads",
        str(generation_threads),
        "--threads-batch",
        str(batch_threads),
        "--no-webui",
    ]
    if runtime_backend == "cuda":
        command.extend(["--n-gpu-layers", "auto", "--fit", "on"])
    else:
        command.extend(["--device", "none"])
    return command


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
