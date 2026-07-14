from __future__ import annotations

import re


_NOISE_PATTERN = re.compile(
    r"[-_\s]+(gguf|awq|gptq|it|chat|instruct|q4_k_m|q4_k_s|q5_k_m|q5_k_s|q6_k|q8_0|fp16|bf16)$"
)


def normalize_family_line(value: str) -> str:
    text = str(value or "").lower().strip()
    text = text.replace("/", "-")
    text = _NOISE_PATTERN.sub("", text)
    text = re.sub(r"(\d+)\.\d+", r"\1", text)
    text = re.sub(r"\bmini\b", "mini", text)
    text = re.sub(r"[^a-z0-9._-]+", "-", text)
    return text.strip("-")


def normalize_family_name(value: str) -> str:
    text = normalize_family_line(value)
    if text.startswith("qwen"):
        return "qwen"
    if text.startswith("phi"):
        return "phi"
    if text.startswith("gemma"):
        return "gemma"
    if text.startswith("llama"):
        return "llama"
    return text.split("-", 1)[0] if text else ""


def is_probably_derivative(value: str) -> bool:
    text = normalize_family_line(value)
    return bool(re.search(r"(?:^|[-_.])(merge|abliterated|uncensored|roleplay|rp|dpo|sft)(?:$|[-_.])", text))


def guess_parameter_count_b(*values: str) -> float | None:
    patterns = (
        (r"(\d+(?:\.\d+)?)b", 1.0),
        (r"(\d+(?:\.\d+)?)m", 0.001),
    )
    for value in values:
        text = normalize_family_line(value)
        for pattern, scale in patterns:
            match = re.search(pattern, text)
            if match:
                try:
                    return float(match.group(1)) * scale
                except ValueError:
                    continue
    return None
