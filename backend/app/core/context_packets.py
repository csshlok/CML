def build_bridge_context_packet(
    *,
    query: str,
    context_request_id: str | None = None,
    selected_clusters: list[dict],
    source_snippets: list[dict],
    warnings: list[str],
    citations: list[dict] | None = None,
    memory_items: list[dict] | None = None,
    working_memory: dict | None = None,
    retrieval_authority: bool = True,
    cluster_profile: dict | None = None,
    token_estimate: dict | None = None,
    bundle_status: dict | None = None,
) -> dict:
    evidence = [
        {
            "handle": _bridge_handle_for_source(source),
            "title": str(source.get("title") or source.get("source_title") or "Untitled source").strip(),
            "trust_tier": str(source.get("trust_tier") or "unknown").strip() or "unknown",
            "source_type": str(source.get("source_type") or "unknown").strip() or "unknown",
            "snippet": _bridge_source_snippet(source),
        }
        for source in source_snippets
    ]
    return _packet_dict(
        query=query,
        context_request_id=context_request_id,
        selected_clusters=selected_clusters,
        evidence=evidence,
        citations=citations or [],
        warnings=warnings,
        memory_items=memory_items or [],
        working_memory=working_memory or {},
        source_count=len(source_snippets),
        retrieval_authority=retrieval_authority,
        cluster_profile=cluster_profile or {},
        token_estimate=token_estimate or {},
        bundle_status=bundle_status or {},
    )


def build_chat_context_packet(
    *,
    query: str,
    context_request_id: str | None = None,
    clusters_used: list[dict],
    warnings: list[str],
    citations: list[dict] | None = None,
    recent_turns: list[dict] | None = None,
    memory_items: list[dict] | None = None,
    working_memory: dict | None = None,
    retrieval_authority: bool = True,
    cluster_profile: dict | None = None,
    token_estimate: dict | None = None,
    bundle_status: dict | None = None,
) -> dict:
    normalized_citations = citations or []
    evidence = [
        {
            "handle": _chat_handle_for_citation(citation, index),
            "title": str(citation.get("source_title") or f"Source {index}").strip(),
            "trust_tier": str(citation.get("trust_tier") or "unknown").strip() or "unknown",
            "source_type": str(citation.get("source_type") or "unknown").strip() or "unknown",
            "snippet": " ".join(str(citation.get("snippet") or "").split()),
        }
        for index, citation in enumerate(normalized_citations, start=1)
    ]
    packet = _packet_dict(
        query=query,
        context_request_id=context_request_id,
        selected_clusters=clusters_used,
        evidence=evidence,
        citations=normalized_citations,
        warnings=warnings,
        memory_items=memory_items or [],
        working_memory=working_memory or {},
        source_count=len(normalized_citations),
        retrieval_authority=retrieval_authority,
        cluster_profile=cluster_profile or {},
        token_estimate=token_estimate or {},
        bundle_status=bundle_status or {},
    )
    if recent_turns:
        packet["recent_turns"] = [
            {
                "role": str(turn.get("role") or "").strip().lower(),
                "content": " ".join(str(turn.get("content") or "").split()),
            }
            for turn in recent_turns
            if str(turn.get("content") or "").strip()
        ]
    return packet


def render_context_packet(packet: dict) -> str:
    query = str(packet.get("query") or "").strip() or "unspecified query"
    clusters = packet.get("selected_clusters") or []
    evidence = packet.get("evidence") or []
    warnings = [str(item).strip() for item in packet.get("warnings") or [] if str(item).strip()]
    memory_items = packet.get("memory_items") or []
    working_memory = packet.get("working_memory") or {}
    recent_turns = packet.get("recent_turns") or []
    retrieval_authority = bool(packet.get("retrieval_authority", True))
    cluster_profile = packet.get("cluster_profile") or {}
    token_estimate = packet.get("token_estimate") or {}
    lines = [
        "CML Context Packet",
        "",
        "How To Use This Context",
        "- Answer only from the memory and evidence below.",
        "- Cite source titles or packet handles when relevant.",
        "- If evidence is missing, partial, conflicting, or low-trust, say so instead of inferring.",
        "",
        "Answerable From Vault",
        f"- Query: {query}",
        f"- Context request ID: {str(packet.get('context_request_id') or 'none')}",
        f"- Cluster scope: {', '.join(_cluster_label(cluster) for cluster in clusters) if clusters else 'No cluster scope selected.'}",
        f"- Evidence items: {len(evidence)}",
        "",
        "Cluster Profile",
    ]
    summary = str(cluster_profile.get("summary") or "").strip()
    lines.append(f"- Summary: {summary or 'No cluster summary is available yet.'}")
    local_terms = ", ".join(str(item).strip() for item in cluster_profile.get("local_terms") or [] if str(item).strip())
    lines.append(f"- Local terms: {local_terms or 'None cached.'}")
    style_profile = str(cluster_profile.get("style_profile") or "").strip()
    if style_profile:
        lines.append(f"- Style: {style_profile}")
    reasoning_patterns = [str(item).strip() for item in cluster_profile.get("reasoning_patterns") or [] if str(item).strip()]
    if reasoning_patterns:
        lines.append(f"- Reasoning: {'; '.join(reasoning_patterns)}")
    lines.extend(["", "Working Memory"])
    working_summary = str(working_memory.get("summary") or "").strip()
    lines.append(f"- {working_summary or 'No working-memory summary is available yet.'}")
    if memory_items:
        lines.extend(["", "Distilled Memory"])
        for item in memory_items[:8]:
            kind = str(item.get("kind") or "fact").strip()
            summary_text = str(item.get("summary") or item.get("text") or "").strip()
            if summary_text:
                lines.append(f"- [{kind}] {summary_text}")
    lines.extend(["", "Relevant Evidence"])
    if evidence:
        for item in evidence:
            lines.extend(_render_evidence_item(item))
    else:
        lines.append("- No matching evidence was returned.")
    if recent_turns:
        lines.extend(["", "Recent Conversation"])
        for turn in recent_turns[-6:]:
            role = str(turn.get("role") or "user").strip().title()
            content = str(turn.get("content") or "").strip()
            if content:
                lines.append(f"- {role}: {content}")
    lines.extend(["", "Citations"])
    if evidence:
        for item in evidence:
            lines.append(f"- [{item['handle']}] {item['title']}")
    else:
        lines.append("- No citations available.")
    lines.extend(["", "Authority", f"- Retrieval authority: {'yes' if retrieval_authority else 'no'}", "- Facts and citations come from retrieved evidence."])
    if token_estimate:
        lines.extend(
            [
                "",
                "Token Estimate",
                f"- Citations: {int(token_estimate.get('citations_tokens') or 0)}",
                f"- Memory: {int(token_estimate.get('memory_tokens') or 0)}",
                f"- Profile: {int(token_estimate.get('profile_tokens') or 0)}",
                f"- Total: {int(token_estimate.get('total_tokens') or 0)}",
            ]
        )
    lines.extend(["", "Trust And Limits", f"- Warning count: {len(warnings)}"])
    if warnings:
        lines.extend(f"- {warning}" for warning in warnings)
    else:
        lines.append("- No warnings reported.")
    lines.extend(["", "Expansion Handles"])
    if evidence:
        lines.extend(f"- {item['handle']}" for item in evidence)
    else:
        lines.append("- No expansion handles are available because no evidence was returned.")
    return "\n".join(lines)


def packet_telemetry(packet: dict, *, raw_text: str) -> dict:
    packet_text = render_context_packet(packet)
    raw_bytes = len(raw_text.encode("utf-8"))
    packet_bytes = len(packet_text.encode("utf-8"))
    savings = max(0.0, 1.0 - (packet_bytes / max(raw_bytes, 1)))
    return {
        "packet_text": packet_text,
        "raw_bytes": raw_bytes,
        "packet_bytes": packet_bytes,
        "savings_percent": round(savings * 100.0, 1),
    }


def _packet_dict(
    *,
    query: str,
    context_request_id: str | None,
    selected_clusters: list[dict],
    evidence: list[dict],
    citations: list[dict],
    warnings: list[str],
    memory_items: list[dict],
    working_memory: dict,
    source_count: int,
    retrieval_authority: bool,
    cluster_profile: dict,
    token_estimate: dict,
    bundle_status: dict,
) -> dict:
    return {
        "query": query,
        "context_request_id": context_request_id,
        "selected_clusters": selected_clusters,
        "evidence": evidence,
        "citations": citations,
        "warnings": warnings,
        "memory_items": memory_items,
        "working_memory": working_memory,
        "source_count": source_count,
        "retrieval_authority": retrieval_authority,
        "cluster_profile": cluster_profile,
        "token_estimate": token_estimate,
        "bundle_status": bundle_status,
    }


def _render_evidence_item(item: dict) -> list[str]:
    lines = [
        f"- [{item['handle']}] {item['title']}",
        f"  Type: {item['source_type']}",
        f"  Trust: {item['trust_tier']}",
    ]
    snippet = str(item.get("snippet") or "").strip()
    if snippet:
        lines.append(f"  Evidence: {snippet}")
    return lines


def _cluster_label(cluster: dict) -> str:
    name = str(cluster.get("name") or cluster.get("cluster_name") or "").strip()
    cluster_id = str(cluster.get("id") or cluster.get("cluster_id") or "").strip()
    if name and cluster_id:
        return f"{name} ({cluster_id})"
    return name or cluster_id or "unknown cluster"


def _bridge_handle_for_source(source: dict) -> str:
    source_id = str(source.get("id") or source.get("source_id") or "").strip()
    return f"source:{source_id}" if source_id else "source:unknown"


def _chat_handle_for_citation(citation: dict, index: int) -> str:
    chunk_id = str(citation.get("chunk_id") or "").strip()
    source_id = str(citation.get("source_id") or "").strip()
    if chunk_id:
        return f"chunk:{chunk_id}"
    if source_id:
        return f"source:{source_id}"
    return f"source:item-{index}"


def _bridge_source_snippet(source: dict) -> str:
    for field in ("summary", "extracted_text", "raw_text", "description"):
        value = str(source.get(field) or "").strip()
        if not value:
            continue
        cleaned = " ".join(value.split())
        if len(cleaned) <= 320:
            return cleaned
        return cleaned[:317].rstrip() + "..."
    return ""
