from __future__ import annotations

from typing import Any

from backend.app.core.model_recommender.catalog import ApprovedPairSpec, approved_pairs, minimum_tier_satisfied
from backend.app.core.model_recommender.scoring import score_pair_candidate


def resolve_pair_recommendation(
    profile: dict[str, Any],
    chat_choice: dict[str, Any] | None,
    expert_choice: dict[str, Any] | None,
) -> dict[str, Any]:
    if not chat_choice or not expert_choice:
        return {
            "pair_id": "",
            "accepted": False,
            "detail": "Choose an approved chat model and an accepted local expert checkpoint to complete dual-model setup.",
            "reasons": [],
        }
    hardware_tier = str(profile.get("hardware_tier") or "unknown")
    expert_family = str(expert_choice.get("family") or "")
    pair = _find_pair(str(chat_choice.get("id") or ""), expert_family)
    if pair is None:
        return {
            "pair_id": "",
            "accepted": False,
            "detail": "This chat model and expert family are not in the current approved pairing matrix.",
            "reasons": ["approved_pair_missing"],
        }
    if not minimum_tier_satisfied(hardware_tier, pair.minimum_hardware_tier):
        return {
            "pair_id": pair.pair_id,
            "accepted": False,
            "detail": f"This approved pair targets {pair.minimum_hardware_tier.replace('_', ' ')} hardware or better.",
            "reasons": ["hardware_tier_below_pair_floor"],
        }
    return {
        "pair_id": pair.pair_id,
        "accepted": True,
        "detail": pair.reason,
        "reasons": [],
        "minimum_hardware_tier": pair.minimum_hardware_tier,
        "chat_model_id": pair.chat_model_id,
        "expert_model_id": str(expert_choice.get("id") or ""),
        "expert_family": pair.expert_family,
    }


def resolve_best_pair(
    profile: dict[str, Any],
    chat_candidates: list[dict[str, Any]],
    expert_candidates: list[dict[str, Any]],
) -> dict[str, Any] | None:
    pair_rows: list[dict[str, Any]] = []
    for chat_choice in chat_candidates:
        for expert_choice in expert_candidates:
            pair = resolve_pair_recommendation(profile, chat_choice, expert_choice)
            if not pair.get("accepted"):
                continue
            scored = dict(pair)
            scored["chat_choice"] = chat_choice
            scored["expert_choice"] = expert_choice
            scored["pair_score"] = round(score_pair_candidate(chat_choice, expert_choice, pair), 2)
            pair_rows.append(scored)
    if not pair_rows:
        return None
    pair_rows.sort(key=lambda item: float(item.get("pair_score") or 0.0), reverse=True)
    return pair_rows[0]


def _find_pair(chat_model_id: str, expert_family: str) -> ApprovedPairSpec | None:
    return next(
        (
            pair
            for pair in approved_pairs()
            if pair.chat_model_id == chat_model_id and pair.expert_family == expert_family and pair.status == "approved"
        ),
        None,
    )
