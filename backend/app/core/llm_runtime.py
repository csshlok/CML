from dataclasses import dataclass
from contextlib import contextmanager
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen
import json
import threading

from backend.app.core.config import get_settings


@dataclass
class LLMResult:
    text: str
    provider: str
    model: str


class LLMRuntimeError(RuntimeError):
    pass


_IN_FLIGHT_LOCK = threading.Lock()
_IN_FLIGHT_GENERATIONS = 0


def runtime_status() -> dict[str, Any]:
    settings = get_settings()
    in_flight = _in_flight_count()
    status = {
        "provider": settings.llm_provider,
        "base_url": settings.llm_base_url,
        "model": settings.llm_model,
        "available": False,
        "state": "missing" if settings.llm_provider == "none" else "checking",
        "in_flight": in_flight,
        "detail": "No local model runtime configured.",
    }
    if settings.llm_provider == "none":
        return status
    if in_flight > 0:
        status["state"] = "busy"
        status["available"] = True
        status["detail"] = "Local model runtime is processing a generation."
        return status
    try:
        _openai_get("/models", timeout=2)
    except LLMRuntimeError as exc:
        status["state"] = "unreachable"
        status["detail"] = str(exc)
        return status
    status["available"] = True
    status["state"] = "ready"
    status["detail"] = "Local model runtime is reachable."
    return status


def generate_grounded_answer(
    *,
    prompt: str,
    citations: list[dict],
    clusters_used: list[dict],
) -> LLMResult:
    settings = get_settings()
    if settings.llm_provider == "none":
        raise LLMRuntimeError("No local model runtime configured.")

    messages = [
        {
            "role": "system",
            "content": (
                "You are CML's local synthesis model. Answer only from the supplied local "
                "context. If the context is insufficient, say what is missing. Keep citations "
                "implicit by referring to source titles; do not invent facts."
            ),
        },
        {
            "role": "user",
            "content": _build_context_prompt(prompt, citations, clusters_used),
        },
    ]
    payload = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": 0.2,
        "stream": False,
    }
    with generation_in_flight():
        response = _openai_post("/chat/completions", payload, timeout=_interactive_timeout())
    try:
        text = response["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMRuntimeError("Local model returned an unexpected response.") from exc
    if not text:
        raise LLMRuntimeError("Local model returned an empty response.")
    return LLMResult(text=text, provider=settings.llm_provider, model=settings.llm_model)


def stream_grounded_answer(
    *,
    prompt: str,
    citations: list[dict],
    clusters_used: list[dict],
):
    settings = get_settings()
    if settings.llm_provider == "none":
        raise LLMRuntimeError("No local model runtime configured.")

    messages = [
        {
            "role": "system",
            "content": (
                "You are CML's local synthesis model. Answer only from the supplied local "
                "context. If the context is insufficient, say what is missing. Keep citations "
                "implicit by referring to source titles; do not invent facts."
            ),
        },
        {
            "role": "user",
            "content": _build_context_prompt(prompt, citations, clusters_used),
        },
    ]
    payload = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": 0.2,
        "stream": True,
    }
    with generation_in_flight():
        yield from _openai_stream("/chat/completions", payload, timeout=_interactive_timeout())


@contextmanager
def generation_in_flight():
    global _IN_FLIGHT_GENERATIONS
    with _IN_FLIGHT_LOCK:
        _IN_FLIGHT_GENERATIONS += 1
    try:
        yield
    finally:
        with _IN_FLIGHT_LOCK:
            _IN_FLIGHT_GENERATIONS = max(0, _IN_FLIGHT_GENERATIONS - 1)


def _in_flight_count() -> int:
    with _IN_FLIGHT_LOCK:
        return _IN_FLIGHT_GENERATIONS


def _build_context_prompt(prompt: str, citations: list[dict], clusters_used: list[dict]) -> str:
    cluster_text = "\n".join(
        f"- {cluster['cluster_name']}: {cluster['reason']}" for cluster in clusters_used
    )
    citation_text = "\n\n".join(
        (
            f"Source {index}: {citation['source_title']}\n"
            f"Relevance score: {citation['score']:.3f}\n"
            f"Snippet: {citation['snippet']}"
        )
        for index, citation in enumerate(citations, start=1)
    )
    return (
        f"User prompt:\n{prompt}\n\n"
        f"Clusters used:\n{cluster_text or '- None'}\n\n"
        f"Local source context:\n{citation_text or 'No retrieved context.'}\n\n"
        "Write the best grounded answer using this context."
    )


def _openai_get(path: str, timeout: float) -> dict[str, Any]:
    settings = get_settings()
    url = settings.llm_base_url.rstrip("/") + path
    request = Request(url, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise LLMRuntimeError(f"Local model runtime is not reachable at {url}") from exc


def _openai_post(path: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    settings = get_settings()
    url = settings.llm_base_url.rstrip("/") + path
    data = json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except TimeoutError as exc:
        raise LLMRuntimeError(f"Local model runtime timed out at {url}") from exc
    except URLError as exc:
        raise LLMRuntimeError(f"Local model runtime is not reachable at {url}") from exc
    except OSError as exc:
        raise LLMRuntimeError(f"Local model runtime failed at {url}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise LLMRuntimeError("Local model returned invalid JSON.") from exc


def _openai_stream(path: str, payload: dict[str, Any], timeout: float):
    settings = get_settings()
    url = settings.llm_base_url.rstrip("/") + path
    data = json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line or not line.startswith("data:"):
                    continue
                data_line = line[5:].strip()
                if data_line == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_line)
                except json.JSONDecodeError:
                    continue
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                text = delta.get("content")
                if text:
                    yield text
    except TimeoutError as exc:
        raise LLMRuntimeError(f"Local model runtime timed out at {url}") from exc
    except URLError as exc:
        raise LLMRuntimeError(f"Local model runtime is not reachable at {url}") from exc
    except OSError as exc:
        raise LLMRuntimeError(f"Local model runtime failed at {url}: {exc}") from exc


def _interactive_timeout() -> float:
    return min(get_settings().llm_timeout_seconds, 8.0)
