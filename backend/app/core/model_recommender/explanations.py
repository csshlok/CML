from __future__ import annotations

from typing import Any


def build_chat_reasons(choice: dict[str, Any], fit: dict[str, Any], speed: dict[str, Any], evidence: dict[str, Any]) -> list[str]:
    reasons = [
        f"Benchmark evidence: {evidence.get('source') or 'none'}",
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


def build_expert_reasons(choice: dict[str, Any], fit: dict[str, Any], evidence: dict[str, Any]) -> list[str]:
    reasons = [
        f"Evidence source: {evidence.get('source') or 'none'}",
        f"Expert runtime: {fit.get('runtime_fit_type')}",
        f"Expert training: {fit.get('training_fit_type')}",
    ]
    if evidence.get("detail"):
        reasons.append(str(evidence["detail"]))
    if fit.get("training_feasible"):
        reasons.append("This checkpoint satisfies the current conservative expert-training gate on this machine.")
    else:
        reasons.append("This checkpoint may still be accepted for expert use later, but the current machine does not pass the full local training gate.")
    return reasons


def concise_chat_summary(choice: dict[str, Any]) -> str:
    return f"{choice.get('name')} is the most feasible approved chat model for this device."


def concise_expert_summary(choice: dict[str, Any] | None) -> str:
    if not choice:
        return "No accepted local expert-compression runtime is configured yet."
    return f"{choice.get('name')} is the strongest accepted expert-compression runtime currently available on this device."


def build_operator_summary(
    chat_choice: dict[str, Any] | None,
    expert_choice: dict[str, Any] | None,
    pair: dict[str, Any],
) -> str:
    if not chat_choice:
        return "No feasible approved chat runtime candidate passed the current conservative fit gate."
    if not expert_choice:
        return (
            f"Chat recommendation resolved to {chat_choice.get('id')} with {chat_choice.get('fit', {}).get('fit_type')} fit, "
            "but no accepted expert-compression runtime passed the local recommendation path."
        )
    if pair.get("accepted"):
        return (
            f"Pair recommendation resolved to {pair.get('pair_id')} using chat {chat_choice.get('id')} "
            f"and expert {expert_choice.get('id')}."
        )
    return (
        f"Independent chat/expert winners were {chat_choice.get('id')} and {expert_choice.get('id')}, "
        "but the approved pair gate still failed."
    )


def build_scoring_breakdown(
    chat_choice: dict[str, Any] | None,
    expert_choice: dict[str, Any] | None,
    pair: dict[str, Any],
) -> dict[str, Any]:
    return {
        "chat": {
            "id": (chat_choice or {}).get("id", ""),
            "score": (chat_choice or {}).get("score"),
            "fit_type": (chat_choice or {}).get("fit", {}).get("fit_type"),
            "estimated_tok_per_sec": (chat_choice or {}).get("speed", {}).get("estimated_tok_per_sec"),
            "evidence_source": (chat_choice or {}).get("evidence", {}).get("source"),
            "evidence_confidence": (chat_choice or {}).get("evidence", {}).get("confidence"),
        },
        "expert": {
            "id": (expert_choice or {}).get("id", ""),
            "score": (expert_choice or {}).get("expert_score"),
            "runtime_fit_type": (expert_choice or {}).get("expert_fit", {}).get("runtime_fit_type"),
            "training_fit_type": (expert_choice or {}).get("expert_fit", {}).get("training_fit_type"),
            "evidence_source": (expert_choice or {}).get("evidence", {}).get("source"),
            "evidence_confidence": (expert_choice or {}).get("evidence", {}).get("confidence"),
        },
        "pair": {
            "pair_id": pair.get("pair_id", ""),
            "pair_score": pair.get("pair_score"),
            "accepted": bool(pair.get("accepted")),
            "reasons": list(pair.get("reasons") or []),
        },
    }
