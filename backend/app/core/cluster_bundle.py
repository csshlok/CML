from __future__ import annotations

from collections import OrderedDict
import json
import re
from uuid import uuid4

from backend.app.api.routes.search import semantic_search
from backend.app.core.analysis_packets import build_analysis_packets
from backend.app.core.context_memory import get_context_memory
from backend.app.core.database import connect, dict_from_row
from backend.app.schemas import SemanticSearchRequest
from backend.app.core.turbovec_runtime import UNCLUSTERED_SCOPE_ID


def build_cluster_bundle_context(
    *,
    vault_id: str,
    query: str,
    cluster_id: str | None = None,
    token_budget: int | None = None,
    mode: str = "context",
    search_func=None,
) -> dict:
    context_request_id = f"bundle-{uuid4()}"
    evidence_payload = retrieve_bundle_evidence(
        vault_id=vault_id,
        query=query,
        cluster_id=cluster_id,
        token_budget=token_budget,
        mode=mode,
        search_func=search_func,
    )
    cluster_profile = build_cluster_profile(
        vault_id=vault_id,
        cluster_id=cluster_id,
        evidence=evidence_payload["evidence"],
    )
    token_estimate = estimate_bundle_tokens(
        query=query,
        evidence=evidence_payload["evidence"],
        cluster_profile=cluster_profile,
        memory_items=evidence_payload["memory_items"],
    )
    warnings = list(evidence_payload.get("warnings") or [])
    return {
        "bundle_id": f"cluster:{cluster_id or 'vault'}:{context_request_id}",
        "context_request_id": context_request_id,
        "query": query,
        "selected_clusters": evidence_payload["selected_clusters"],
        "retrieval_authority": True,
        "evidence": evidence_payload["evidence"],
        "citations": evidence_payload["citations"],
        "expansion_handles": [item["handle"] for item in evidence_payload["evidence"]],
        "memory_items": evidence_payload["memory_items"],
        "working_memory": evidence_payload["working_memory"],
        "cluster_profile": cluster_profile,
        "token_estimate": token_estimate,
        "warnings": warnings,
        "source_snippets": evidence_payload["source_snippets"],
        "bundle_status": {
            "mode": mode,
            "cluster_id": cluster_id,
            "sources_considered": int(
                evidence_payload.get("sources_considered") or len(evidence_payload["citations"])
            ),
            "sources_analyzed": int(
                evidence_payload.get("sources_analyzed") or len(evidence_payload["citations"])
            ),
            "sources_low_relevance": int(evidence_payload.get("sources_low_relevance") or 0),
            "analysis_full_scope": bool(evidence_payload.get("analysis_full_scope")),
        },
    }


def retrieve_bundle_evidence(
    *,
    vault_id: str,
    query: str,
    cluster_id: str | None = None,
    token_budget: int | None = None,
    mode: str = "context",
    search_func=None,
) -> dict:
    if mode in {"expanded_analysis", "complete_analysis"}:
        include_chat_transcripts = bool(mode == "complete_analysis" and cluster_id is None)
        full_scope = mode == "complete_analysis"
        analysis_limit = None if full_scope else max(1, int(token_budget or 12))
        analysis_packets = build_analysis_packets(
            vault_id=vault_id,
            cluster_id=cluster_id,
            query=query,
            include_chat_transcripts=include_chat_transcripts,
            limit=analysis_limit,
            full_scope=full_scope,
        )
        packet_rows = list(analysis_packets.get("packets") or [])
        source_ids = list(
            OrderedDict.fromkeys(
                str(item.get("source_id") or "")
                for item in packet_rows
                if str(item.get("source_id") or "").strip()
            )
        )
        warnings: list[str] = []
        if not packet_rows:
            warnings.append("No retrieval evidence was found for this bundle request.")
        with connect() as conn:
            source_rows = []
            if source_ids:
                source_rows = conn.execute(
                    f"SELECT * FROM sources WHERE vault_id = ? AND id IN ({','.join('?' for _ in source_ids)})",
                    [vault_id, *source_ids],
                ).fetchall()
            cluster_rows = []
            cluster_ids = list(
                OrderedDict.fromkeys(
                    str(row["cluster_id"] or "")
                    for row in source_rows
                    if str(row["cluster_id"] or "").strip()
                )
            )
            if cluster_ids:
                cluster_rows = conn.execute(
                    f"SELECT * FROM clusters WHERE id IN ({','.join('?' for _ in cluster_ids)})",
                    cluster_ids,
                ).fetchall()
            elif cluster_id and cluster_id != UNCLUSTERED_SCOPE_ID:
                cluster_rows = conn.execute(
                    "SELECT * FROM clusters WHERE id = ? AND vault_id = ?",
                    (cluster_id, vault_id),
                ).fetchall()
            memory_items, working_memory = get_context_memory(
                conn,
                vault_id=vault_id,
                cluster_id=cluster_id,
                query=query,
            )
        source_by_id = {str(row["id"]): dict_from_row(row) for row in source_rows}
        evidence = []
        citations = []
        source_snippets = []
        raw_scope_parts: list[str] = []
        for index, item in enumerate(packet_rows, start=1):
            source = source_by_id.get(str(item.get("source_id") or ""))
            source_title = str(
                item.get("source_title") or (source or {}).get("title") or f"Source {index}"
            )
            snippet = _normalize_snippet(item.get("evidence_excerpt") or item.get("excerpt") or "")
            handle = (
                f"chunk:{item['chunk_id']}"
                if str(item.get("chunk_id") or "").strip()
                else f"source:{item.get('source_id') or f'item-{index}'}"
            )
            evidence_item = {
                "handle": handle,
                "source_id": item.get("source_id"),
                "chunk_id": item.get("chunk_id"),
                "page_id": item.get("page_id"),
                "page_number": item.get("page_number"),
                "relative_path": item.get("relative_path")
                or (source or {}).get("import_relative_path"),
                "line_start": item.get("line_start"),
                "line_end": item.get("line_end"),
                "symbol": item.get("symbol"),
                "title": source_title,
                "trust_tier": str(item.get("trust_tier") or "trusted_local"),
                "source_type": str(
                    item.get("source_type") or (source or {}).get("source_type") or "unknown"
                ),
                "snippet": snippet,
                "score": float(item.get("score") or 0.0),
                "provenance": str(item.get("provenance") or "local_import"),
                "security_labels": item.get("security_labels") or "[]",
                "status": str(item.get("status") or "ready"),
            }
            evidence.append(evidence_item)
            citations.append(
                {
                    "source_id": item.get("source_id"),
                    "source_title": source_title,
                    "chunk_id": item.get("chunk_id"),
                    "page_id": item.get("page_id"),
                    "page_number": item.get("page_number"),
                    "relative_path": item.get("relative_path")
                    or (source or {}).get("import_relative_path"),
                    "line_start": item.get("line_start"),
                    "line_end": item.get("line_end"),
                    "symbol": item.get("symbol"),
                    "snippet": snippet,
                    "score": float(item.get("score") or 0.0),
                    "provenance": str(item.get("provenance") or "local_import"),
                    "trust_tier": str(item.get("trust_tier") or "trusted_local"),
                    "security_labels": item.get("security_labels") or "[]",
                    "low_trust": bool(item.get("low_trust")),
                    "state": "current",
                    "source_type": str(
                        item.get("source_type") or (source or {}).get("source_type") or "unknown"
                    ),
                }
            )
            if source:
                summary = str(
                    source.get("summary")
                    or source.get("extracted_text")
                    or source.get("raw_text")
                    or ""
                ).strip()
                source_snippets.append(
                    {
                        "id": source.get("id"),
                        "title": source.get("title"),
                        "source_type": source.get("source_type"),
                        "trust_tier": source.get("trust_tier") or "trusted_local",
                        "summary": summary[:320],
                        "cluster_id": source.get("cluster_id"),
                    }
                )
            if snippet:
                raw_scope_parts.append(snippet)
        return {
            "selected_clusters": [dict_from_row(row) for row in cluster_rows],
            "evidence": evidence,
            "citations": citations,
            "memory_items": memory_items,
            "working_memory": working_memory,
            "warnings": warnings,
            "source_snippets": source_snippets,
            "raw_scope_text": "\n".join(raw_scope_parts),
            "mode": mode,
            "sources_considered": int(analysis_packets.get("sources_considered") or 0),
            "sources_analyzed": len(list(analysis_packets.get("analyzed_source_ids") or [])),
            "sources_low_relevance": int(analysis_packets.get("low_relevance_source_count") or 0),
            "analysis_full_scope": full_scope,
        }

    limit = max(4, min(12, int(token_budget or 6)))
    active_search = search_func or semantic_search
    search_response = active_search(
        SemanticSearchRequest(
            vault_id=vault_id,
            cluster_id=None if cluster_id == UNCLUSTERED_SCOPE_ID else cluster_id,
            unclustered_only=cluster_id == UNCLUSTERED_SCOPE_ID,
            query=query,
            limit=limit,
        )
    )
    results = list(search_response.get("results") or [])
    source_ids = list(
        OrderedDict.fromkeys(
            str(result.get("source_id") or "")
            for result in results
            if str(result.get("source_id") or "").strip()
        )
    )
    cluster_ids = list(
        OrderedDict.fromkeys(
            str(result.get("cluster_id") or "")
            for result in results
            if str(result.get("cluster_id") or "").strip()
        )
    )
    warnings: list[str] = []
    if not results:
        warnings.append("No retrieval evidence was found for this bundle request.")
    with connect() as conn:
        if cluster_ids:
            cluster_rows = conn.execute(
                f"SELECT * FROM clusters WHERE id IN ({','.join('?' for _ in cluster_ids)})",
                cluster_ids,
            ).fetchall()
        elif cluster_id:
            cluster_rows = conn.execute(
                "SELECT * FROM clusters WHERE id = ? AND vault_id = ?",
                (cluster_id, vault_id),
            ).fetchall()
        else:
            cluster_rows = []
        source_rows = []
        if source_ids:
            source_rows = conn.execute(
                f"SELECT * FROM sources WHERE vault_id = ? AND id IN ({','.join('?' for _ in source_ids)})",
                [vault_id, *source_ids],
            ).fetchall()
        memory_items, working_memory = get_context_memory(
            conn,
            vault_id=vault_id,
            cluster_id=cluster_id,
            query=query,
        )
    source_by_id = {str(row["id"]): dict_from_row(row) for row in source_rows}
    evidence = []
    citations = []
    source_snippets = []
    raw_scope_parts: list[str] = []
    for index, result in enumerate(results, start=1):
        source = source_by_id.get(str(result.get("source_id") or ""))
        source_title = str(
            result.get("source_title") or (source or {}).get("title") or f"Source {index}"
        )
        snippet = _normalize_snippet(result.get("snippet") or "")
        handle = (
            f"chunk:{result['chunk_id']}"
            if str(result.get("chunk_id") or "").strip()
            else f"source:{result.get('source_id') or f'item-{index}'}"
        )
        evidence_item = {
            "handle": handle,
            "source_id": result.get("source_id"),
            "chunk_id": result.get("chunk_id"),
            "page_id": result.get("page_id"),
            "page_number": result.get("page_number"),
            "relative_path": result.get("relative_path")
            or (source or {}).get("import_relative_path"),
            "line_start": result.get("line_start"),
            "line_end": result.get("line_end"),
            "symbol": result.get("symbol"),
            "title": source_title,
            "trust_tier": str(result.get("trust_tier") or "trusted_local"),
            "source_type": str(
                result.get("source_type") or (source or {}).get("source_type") or "unknown"
            ),
            "snippet": snippet,
            "score": float(result.get("score") or 0.0),
            "provenance": str(result.get("provenance") or "local_import"),
            "security_labels": result.get("security_labels") or "[]",
        }
        evidence.append(evidence_item)
        citations.append(
            {
                "source_id": result.get("source_id"),
                "source_title": source_title,
                "chunk_id": result.get("chunk_id"),
                "page_id": result.get("page_id"),
                "page_number": result.get("page_number"),
                "relative_path": result.get("relative_path")
                or (source or {}).get("import_relative_path"),
                "line_start": result.get("line_start"),
                "line_end": result.get("line_end"),
                "symbol": result.get("symbol"),
                "snippet": snippet,
                "score": float(result.get("score") or 0.0),
                "provenance": str(result.get("provenance") or "local_import"),
                "trust_tier": str(result.get("trust_tier") or "trusted_local"),
                "security_labels": result.get("security_labels") or "[]",
                "low_trust": bool(result.get("low_trust")),
                "state": "current",
                "source_type": str(
                    result.get("source_type") or (source or {}).get("source_type") or "unknown"
                ),
            }
        )
        if source:
            summary = str(
                source.get("summary")
                or source.get("extracted_text")
                or source.get("raw_text")
                or ""
            ).strip()
            source_snippets.append(
                {
                    "id": source.get("id"),
                    "title": source.get("title"),
                    "source_type": source.get("source_type"),
                    "trust_tier": source.get("trust_tier") or "trusted_local",
                    "summary": summary[:320],
                    "cluster_id": source.get("cluster_id"),
                }
            )
            if summary:
                raw_scope_parts.append(summary)
    return {
        "selected_clusters": [dict_from_row(row) for row in cluster_rows],
        "evidence": evidence,
        "citations": citations,
        "memory_items": memory_items,
        "working_memory": working_memory,
        "warnings": warnings,
        "source_snippets": source_snippets,
        "raw_scope_text": "\n".join(raw_scope_parts),
        "mode": mode,
        "sources_considered": len(citations),
        "sources_analyzed": len(citations),
        "sources_low_relevance": 0,
        "analysis_full_scope": False,
    }


def _normalize_snippet(value: object) -> str:
    """Normalize noisy whitespace without flattening code, logs, or tables."""
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def build_cluster_profile(*, vault_id: str, cluster_id: str | None, evidence: list[dict]) -> dict:
    summary = ""
    local_terms: list[str] = []
    style_profile = ""
    reasoning_patterns: list[str] = []
    cluster_name = ""
    if cluster_id:
        with connect() as conn:
            row = conn.execute(
                "SELECT name, description, cluster_summary, cluster_glossary FROM clusters WHERE id = ? AND vault_id = ?",
                (cluster_id, vault_id),
            ).fetchone()
        if row is not None:
            cluster_name = str(row["name"] or "").strip()
            summary = (
                str(row["cluster_summary"] or "").strip() or str(row["description"] or "").strip()
            )
            glossary = str(row["cluster_glossary"] or "").strip()
            if glossary:
                try:
                    parsed = json.loads(glossary)
                except Exception:
                    parsed = []
                if isinstance(parsed, list):
                    local_terms = [str(item).strip() for item in parsed if str(item).strip()]
            if summary:
                style_profile = f"Preserve the cluster's local framing from {row['name']}."
    if not local_terms:
        token_counts: OrderedDict[str, None] = OrderedDict()
        for item in evidence:
            title = str(item.get("title") or "")
            for token in re.findall(r"\b[A-Za-z][A-Za-z0-9_-]{3,}\b", title):
                lower = token.lower()
                if lower in {"source", "note", "page", "chunk"}:
                    continue
                token_counts.setdefault(token, None)
                if len(token_counts) >= 8:
                    break
            if len(token_counts) >= 8:
                break
        local_terms = list(token_counts.keys())
    if evidence:
        reasoning_patterns.append("Ground claims in retrieved evidence before synthesis.")
        reasoning_patterns.append("Prefer evidence, then interpretation, then conclusion.")
    behavior_profile = _build_behavior_profile(
        cluster_name=cluster_name,
        summary=summary,
        local_terms=local_terms,
        evidence=evidence,
    )
    return {
        "summary": summary,
        "local_terms": local_terms,
        "style_profile": style_profile,
        "reasoning_patterns": reasoning_patterns,
        "answer_contract": {
            "voice": behavior_profile["voice"],
            "structure": list(behavior_profile["reasoning_order"]),
            "emphasis": list(behavior_profile["framing_rules"]),
            "refusal_style": behavior_profile["refusal_style"],
        },
        "behavior_profile": behavior_profile,
    }


def estimate_bundle_tokens(
    *, query: str, evidence: list[dict], cluster_profile: dict, memory_items: list[dict]
) -> dict:
    citations_text = "\n".join(str(item.get("snippet") or "") for item in evidence)
    profile_text = "\n".join(
        part
        for part in [
            str(cluster_profile.get("summary") or "").strip(),
            str(cluster_profile.get("style_profile") or "").strip(),
            "\n".join(
                str(item).strip()
                for item in cluster_profile.get("local_terms") or []
                if str(item).strip()
            ),
            "\n".join(
                str(item).strip()
                for item in cluster_profile.get("reasoning_patterns") or []
                if str(item).strip()
            ),
        ]
        if part
    )
    memory_text = "\n".join(
        str(item.get("summary") or item.get("text") or "").strip()
        for item in memory_items
        if str(item.get("summary") or item.get("text") or "").strip()
    )
    citations_tokens = _estimate_tokens(citations_text)
    profile_tokens = _estimate_tokens(profile_text)
    memory_tokens = _estimate_tokens(memory_text)
    return {
        "citations_tokens": citations_tokens,
        "memory_tokens": memory_tokens,
        "profile_tokens": profile_tokens,
        "total_tokens": _estimate_tokens(query) + citations_tokens + memory_tokens + profile_tokens,
    }


def _estimate_tokens(text: str) -> int:
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return 0
    return max(1, (len(cleaned) + 3) // 4)


def _empty_behavior_profile() -> dict:
    return {
        "voice": "",
        "terminology_shift": [],
        "style_markers": [],
        "reasoning_order": [],
        "framing_rules": [],
        "refusal_style": "",
        "practicality_bias": "",
    }


def _build_behavior_profile(
    *,
    cluster_name: str,
    summary: str,
    local_terms: list[str],
    evidence: list[dict],
) -> dict:
    profile = _empty_behavior_profile()
    if cluster_name:
        profile["voice"] = f"{cluster_name} local-context"
    if local_terms:
        profile["terminology_shift"] = local_terms[:4]
    if summary:
        profile["style_markers"].append("preserve-local-framing")
    if evidence:
        profile["style_markers"].extend(["grounded", "concrete", "source-aware"])
        profile["reasoning_order"] = ["evidence", "interpretation", "conclusion"]
        profile["framing_rules"] = [
            "keep claims tied to retrieved evidence",
            "prefer practical takeaways over abstract restatement",
        ]
        profile["refusal_style"] = "state what evidence is missing before refusing"
        profile["practicality_bias"] = "practical"
    profile["style_markers"] = list(OrderedDict.fromkeys(profile["style_markers"]))
    return profile
