from __future__ import annotations

import time
from typing import Any

from backend.app.core.database import utc_now
from backend.app.core.llm_runtime import LLMRuntimeError, generate_direct_answer, runtime_status
from backend.app.core.model_recommender.benchmark_store import record_model_measurement


def run_chat_measurement(*, model_id: str, prompt: str) -> dict[str, Any]:
    started = time.perf_counter()
    runtime = runtime_status()
    if not runtime.get("available"):
        raise RuntimeError(str(runtime.get("detail") or "Local runtime is not available."))
    try:
        result = generate_direct_answer(prompt=prompt)
    except LLMRuntimeError as exc:
        raise RuntimeError(str(exc)) from exc
    elapsed = max(time.perf_counter() - started, 0.001)
    token_count = _rough_token_count(result.text)
    tok_per_sec = round(token_count / elapsed, 2)
    measured_at = utc_now()
    record = record_model_measurement(
        model_id,
        estimated_tok_per_sec=tok_per_sec,
        runtime_success=True,
        startup_seconds=round(elapsed, 3),
        measured_at=measured_at,
    )
    return {
        "kind": "chat_model",
        "model_id": model_id,
        "runtime_provider": result.provider,
        "runtime_model": result.model,
        "elapsed_seconds": round(elapsed, 3),
        "estimated_tok_per_sec": tok_per_sec,
        "response_text": result.text,
        "record": record,
        "measured_at": measured_at,
    }
def _rough_token_count(text: str) -> int:
    return max(1, len([part for part in str(text or "").split() if part.strip()]))
