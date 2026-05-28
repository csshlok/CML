import re

from backend.app.core.clustering import keywords_for_text


def summarize_text(text: str, max_chars: int = 360) -> str:
    cleaned = " ".join(text.split())
    if not cleaned:
        return ""

    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    summary = " ".join(sentences[:2]).strip()
    if not summary:
        summary = cleaned
    if len(summary) <= max_chars:
        return summary
    return summary[: max_chars - 1].rstrip() + "..."


def generate_tags(title: str, text: str, source_type: str, limit: int = 8) -> list[str]:
    tags: list[str] = [source_type.upper()]
    for keyword in keywords_for_text(f"{title} {text}", limit=limit * 2):
        label = keyword.upper()
        if label not in tags:
            tags.append(label)
        if len(tags) >= limit:
            break
    return tags
