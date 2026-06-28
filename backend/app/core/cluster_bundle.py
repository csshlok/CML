from __future__ import annotations

from collections import OrderedDict
import re
from uuid import uuid4

from backend.app.api.routes.search import semantic_search
from backend.app.core.analysis_packets import build_analysis_packets
from backend.app.core.context_memory import get_context_memory
from backend.app.core.database import connect, dict_from_row
from backend.app.core.expert_evaluation import adapter_route_away_category
from backend.app.core.expert_runtime import run_cluster_expert_compression
from backend.app.schemas import SemanticSearchRequest


def build_cluster_bundle_context(
    *,
    vault_id: str,
    query: str,
    cluster_id: str | None = None,
    token_budget: int | None = None,
    allow_expert_compression: bool = True,
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
    expert_eligibility = should_use_expert_compression(
        vault_id=vault_id,
        cluster_id=cluster_id,
        query=query,
        citations=evidence_payload["citations"],
        evidence=evidence_payload["evidence"],
        allow_expert_compression=allow_expert_compression,
    )
    expert_digest = {
        "used": False,
        "mode": str(expert_eligibility.get("mode") or "not_eligible"),
        "text": "",
        "artifact_id": None,
        "warnings": list(expert_eligibility.get("warnings") or []),
        "local_terms": [],
        "reasoning_hints": [],
        "uncertainties": [],
        "unsupported_claims": [],
        "behavior_profile": dict(cluster_profile.get("behavior_profile") or _empty_behavior_profile()),
    }
    if expert_eligibility.get("eligible"):
        with connect() as conn:
            runtime_result = run_cluster_expert_compression(
                conn,
                cluster_id=str(cluster_id),
                prompt=query,
                citations=evidence_payload["citations"],
                cluster_profile=cluster_profile,
            )
        if runtime_result.get("ok"):
            expert_digest = {
                "used": True,
                "mode": "retrieval_grounded_behavior",
                "text": str(runtime_result.get("digest") or "").strip(),
                "artifact_id": runtime_result.get("artifact_id"),
                "warnings": list(runtime_result.get("warnings") or []),
                "local_terms": list(runtime_result.get("local_terms") or []),
                "reasoning_hints": list(runtime_result.get("reasoning_hints") or []),
                "uncertainties": list(runtime_result.get("uncertainties") or []),
                "unsupported_claims": list(runtime_result.get("unsupported_claims") or []),
                "behavior_profile": dict(
                    runtime_result.get("behavior_profile")
                    or cluster_profile.get("behavior_profile")
                    or _empty_behavior_profile()
                ),
            }
        else:
            expert_digest["warnings"].append(str(runtime_result.get("detail") or "Expert compression unavailable.").strip())
            expert_digest["mode"] = str(runtime_result.get("mode") or "fallback_retrieval_only")

    token_ledger = estimate_bundle_token_savings(
        query=query,
        evidence=evidence_payload["evidence"],
        expert_digest=expert_digest,
        raw_scope_text=evidence_payload.get("raw_scope_text") or "",
    )
    warnings = list(evidence_payload.get("warnings") or [])
    warnings.extend(item for item in expert_digest["warnings"] if item)
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
        "expert_digest": expert_digest,
        "token_ledger": token_ledger,
        "warnings": warnings,
        "source_snippets": evidence_payload["source_snippets"],
        "bundle_status": {
            "mode": mode,
            "expert_eligible": bool(expert_eligibility.get("eligible")),
            "expert_mode": expert_digest["mode"],
            "behavior_profile_available": bool(
                (expert_digest.get("behavior_profile") or {}).get("style_markers")
                or (expert_digest.get("behavior_profile") or {}).get("reasoning_order")
                or (expert_digest.get("behavior_profile") or {}).get("framing_rules")
            ),
            "cluster_id": cluster_id,
            "sources_considered": int(evidence_payload.get("sources_considered") or len(evidence_payload["citations"])),
            "sources_analyzed": int(evidence_payload.get("sources_analyzed") or len(evidence_payload["citations"])),
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
            elif cluster_id:
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
            source_title = str(item.get("source_title") or (source or {}).get("title") or f"Source {index}")
            snippet = " ".join(str(item.get("evidence_excerpt") or item.get("excerpt") or "").split())
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
                "title": source_title,
                "trust_tier": str(item.get("trust_tier") or "trusted_local"),
                "source_type": str(item.get("source_type") or (source or {}).get("source_type") or "unknown"),
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
                    "snippet": snippet,
                    "score": float(item.get("score") or 0.0),
                    "provenance": str(item.get("provenance") or "local_import"),
                    "trust_tier": str(item.get("trust_tier") or "trusted_local"),
                    "security_labels": item.get("security_labels") or "[]",
                    "low_trust": bool(item.get("low_trust")),
                    "state": "current",
                    "source_type": str(item.get("source_type") or (source or {}).get("source_type") or "unknown"),
                }
            )
            if source:
                summary = str(source.get("summary") or source.get("extracted_text") or source.get("raw_text") or "").strip()
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
            cluster_id=cluster_id,
            query=query,
            limit=limit,
        )
    )
    results = list(search_response.get("results") or [])
    source_ids = list(OrderedDict.fromkeys(str(result.get("source_id") or "") for result in results if str(result.get("source_id") or "").strip()))
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
        source_title = str(result.get("source_title") or (source or {}).get("title") or f"Source {index}")
        snippet = " ".join(str(result.get("snippet") or "").split())
        handle = f"chunk:{result['chunk_id']}" if str(result.get("chunk_id") or "").strip() else f"source:{result.get('source_id') or f'item-{index}'}"
        evidence_item = {
            "handle": handle,
            "source_id": result.get("source_id"),
            "chunk_id": result.get("chunk_id"),
            "page_id": result.get("page_id"),
            "page_number": result.get("page_number"),
            "title": source_title,
            "trust_tier": str(result.get("trust_tier") or "trusted_local"),
            "source_type": str(result.get("source_type") or (source or {}).get("source_type") or "unknown"),
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
                "snippet": snippet,
                "score": float(result.get("score") or 0.0),
                "provenance": str(result.get("provenance") or "local_import"),
                "trust_tier": str(result.get("trust_tier") or "trusted_local"),
                "security_labels": result.get("security_labels") or "[]",
                "low_trust": bool(result.get("low_trust")),
                "state": "current",
                "source_type": str(result.get("source_type") or (source or {}).get("source_type") or "unknown"),
            }
        )
        if source:
            summary = str(source.get("summary") or source.get("extracted_text") or source.get("raw_text") or "").strip()
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


def build_cluster_profile(*, vault_id: str, cluster_id: str | None, evidence: list[dict]) -> dict:
    summary = ""
    local_terms: list[str] = []
    style_profile = ""
    reasoning_patterns: list[str] = []
    cluster_name = ""
    if cluster_id:
        with connect() as conn:
            row = conn.execute(
                "SELECT name, description FROM clusters WHERE id = ? AND vault_id = ?",
                (cluster_id, vault_id),
            ).fetchone()
        if row is not None:
            cluster_name = str(row["name"] or "").strip()
            summary = str(row["description"] or "").strip()
            if summary:
                style_profile = f"Preserve the cluster's local framing from {row['name']}."
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


def should_use_expert_compression(
    *,
    vault_id: str,
    cluster_id: str | None,
    query: str,
    citations: list[dict],
    evidence: list[dict],
    allow_expert_compression: bool,
) -> dict:
    if not allow_expert_compression:
        return {"eligible": False, "mode": "disabled", "warnings": []}
    if not cluster_id:
        return {"eligible": False, "mode": "not_cluster_scoped", "warnings": []}
    if not evidence:
        return {"eligible": False, "mode": "no_evidence", "warnings": []}
    blocked_category = adapter_route_away_category(query, citations)
    if blocked_category is not None:
        return {
            "eligible": False,
            "mode": "retrieval_routed",
            "warnings": [f"Expert compression disabled for retrieval-routed category '{blocked_category}'."],
        }
    with connect() as conn:
        cluster = conn.execute(
            "SELECT expert_status FROM clusters WHERE id = ? AND vault_id = ?",
            (cluster_id, vault_id),
        ).fetchone()
        artifact = conn.execute(
            """
            SELECT id
            FROM expert_artifacts
            WHERE cluster_id = ? AND active = 1 AND status = 'ready' AND deleted_at IS NULL
            LIMIT 1
            """,
            (cluster_id,),
        ).fetchone()
    if cluster is None:
        return {"eligible": False, "mode": "cluster_missing", "warnings": []}
    expert_status = str(cluster["expert_status"] or "").strip()
    if artifact is not None and expert_status in {"training_ready", "ready", "expert_stale", "needs-update"}:
        return {
            "eligible": False,
            "mode": "expert_compression_pending",
            "warnings": [
                "Prompt-only cluster adapter generation is disabled until retrieval-grounded expert compression is available."
            ],
        }
    if artifact is None or expert_status in {
        "setting-up",
        "training_pending",
        "training_running",
        "training_failed",
        "hardware_unsupported",
        "expert_stale",
    } or expert_status != "expert_compression_ready":
        return {"eligible": False, "mode": "expert_not_ready", "warnings": []}
    return {"eligible": True, "mode": "eligible", "warnings": []}


def estimate_bundle_token_savings(*, query: str, evidence: list[dict], expert_digest: dict, raw_scope_text: str) -> dict:
    raw_scope_tokens = _estimate_tokens(raw_scope_text)
    retrieved_text = "\n".join(str(item.get("snippet") or "") for item in evidence)
    retrieved_tokens = _estimate_tokens(retrieved_text)
    digest_text = str(expert_digest.get("text") or "").strip()
    digest_tokens = _estimate_tokens(digest_text)
    packet_text = "\n".join(
        part for part in [query, retrieved_text, digest_text] if part
    )
    packet_tokens = _estimate_tokens(packet_text)
    return {
        "raw_scope_tokens_estimate": raw_scope_tokens,
        "retrieved_tokens_estimate": retrieved_tokens,
        "packet_tokens_estimate": packet_tokens,
        "expert_digest_tokens_estimate": digest_tokens,
        "estimated_tokens_saved_vs_raw_scope": max(0, raw_scope_tokens - packet_tokens),
        "estimated_tokens_saved_vs_retrieval_only": max(0, retrieved_tokens - digest_tokens),
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
        profile["voice"] = f"{cluster_name} local-expert"
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
