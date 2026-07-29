from __future__ import annotations

from typing import Any


def build_chat_reasons(choice: dict[str, Any], fit: dict[str, Any], speed: dict[str, Any], evidence: dict[str, Any]) -> list[str]:
    reasons = [
        f"Evidence: {evidence.get('source') or 'hardware estimate'}",
        f"Runtime fit: {fit.get('fit_type')}",
        f"Estimated chat speed: {speed.get('estimated_tok_per_sec')} tok/s",
    ]
    if evidence.get("detail"):
        reasons.append(str(evidence["detail"]))
    if fit.get("fit_type") == "full_gpu":
        reasons.append("This is the strongest approved chat model that still fits the current device cleanly.")
    elif fit.get("fit_type") == "partial_offload":
        reasons.append("This model trades some responsiveness for better answer quality by spilling part of the runtime into system RAM.")
    elif fit.get("fit_type") == "cpu_only":
        reasons.append("This is a conservative CPU-first fallback because the device cannot sustain a stronger local runtime cleanly.")
    return reasons
def concise_chat_summary(choice: dict[str, Any]) -> str:
    return f"{choice.get('name')} is the most feasible approved chat model for this device."
