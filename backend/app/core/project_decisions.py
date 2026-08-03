from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import uuid

from backend.app.core.database import connect, dict_from_row, utc_now


DECISION_EXTRACTOR_VERSION = "odin-decisions-v1"
_ADR_PATH = re.compile(r"(^|/)(adr|adrs|decisions|architecture/decisions)(/|$)", re.IGNORECASE)
_MARKER = re.compile(
    r"(?im)^\s*(?:#{1,6}\s*)?(WHY|DECISION|RATIONALE|TRADE[ -]?OFFS?)\s*[:\-]?\s*(.*)$"
)


def refresh_project_decisions(project_id: str, *, max_files: int = 250) -> dict:
    now = utc_now()
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM projects WHERE id = ? AND deleted_at IS NULL", (project_id,)
        ).fetchone()
        if row is None:
            raise KeyError(project_id)
        project = dict_from_row(row)
        snapshot_id = project.get("active_manifest_snapshot_id") or project.get(
            "active_snapshot_id"
        )
        paths = [
            str(item["relative_path"])
            for item in conn.execute(
                "SELECT relative_path FROM project_sources WHERE project_id = ? ORDER BY relative_path",
                (project_id,),
            )
        ]
    root = Path(str(project["root_path"])).resolve()
    eligible = [
        path
        for path in paths
        if path.lower().endswith((".md", ".mdx", ".txt"))
        and (
            _ADR_PATH.search(path.replace("\\", "/"))
            or Path(path).name.lower().startswith(("adr-", "adr_"))
        )
    ]
    eligible = eligible[: max(1, min(int(max_files), 1000))]
    discovered: set[str] = set()
    with connect() as conn:
        for relative_path in eligible:
            absolute = (root / relative_path).resolve()
            try:
                absolute.relative_to(root)
                text = absolute.read_text(encoding="utf-8", errors="replace")[:200_000]
            except (OSError, ValueError):
                continue
            parsed = _parse_decision(text)
            if parsed is None:
                continue
            statement, rationale, start_line, end_line = parsed
            source_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            decision_id = (
                "decision-"
                + hashlib.sha256(f"{project_id}\0{relative_path}".encode()).hexdigest()[:24]
            )
            discovered.add(decision_id)
            conn.execute(
                """INSERT INTO project_decisions
                (id, project_id, owning_snapshot_id, statement, rationale, governed_paths_json, status,
                 confidence_class, verification_state, source_type, source_hash, user_created, stale_reason,
                 created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'active', 'documented', 'extracted',
                 'adr_document', ?, 0, '', ?, ?)
                ON CONFLICT(id) DO UPDATE SET owning_snapshot_id=excluded.owning_snapshot_id,
                 statement=excluded.statement, rationale=excluded.rationale, source_hash=excluded.source_hash,
                 status='active', stale_reason='', updated_at=excluded.updated_at""",
                (
                    decision_id,
                    project_id,
                    snapshot_id,
                    statement,
                    rationale,
                    _json(_governed_paths(text)),
                    source_hash,
                    now,
                    now,
                ),
            )
            evidence_id = (
                "decision-evidence-"
                + hashlib.sha256(f"{decision_id}\0{source_hash}".encode()).hexdigest()[:24]
            )
            conn.execute(
                "DELETE FROM project_decision_evidence WHERE decision_id = ?", (decision_id,)
            )
            source = conn.execute(
                "SELECT source_id FROM project_sources WHERE project_id = ? AND relative_path = ?",
                (project_id, relative_path),
            ).fetchone()
            conn.execute(
                "INSERT INTO project_decision_evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    evidence_id,
                    decision_id,
                    project_id,
                    source["source_id"] if source else None,
                    relative_path,
                    start_line,
                    end_line,
                    source_hash,
                    "adr_or_madr_structure",
                    now,
                ),
            )
        git_row = conn.execute(
            "SELECT recent_commits_json FROM project_git_snapshots WHERE project_id=? ORDER BY generated_at DESC LIMIT 1",
            (project_id,),
        ).fetchone()
        for commit in _loads(git_row["recent_commits_json"], []) if git_row else []:
            subject = str(commit.get("subject") or "").strip()
            match = re.match(
                r"(?i)^(?:adr|decision|architecture decision)\s*[:\-]\s*(.{12,})$", subject
            )
            if not match:
                continue
            commit_id = str(commit.get("id") or "")
            decision_id = (
                "decision-git-"
                + hashlib.sha256(f"{project_id}\0{commit_id}".encode()).hexdigest()[:24]
            )
            discovered.add(decision_id)
            source_hash = hashlib.sha256(subject.encode()).hexdigest()
            conn.execute(
                """INSERT INTO project_decisions VALUES (?, ?, ?, ?, '', '[]', 'active', 'explicit_commit',
                'exact', 'git_commit', ?, 0, '', ?, ?) ON CONFLICT(id) DO UPDATE SET statement=excluded.statement,
                status='active', stale_reason='', updated_at=excluded.updated_at""",
                (
                    decision_id,
                    project_id,
                    snapshot_id,
                    match.group(1)[:2000],
                    source_hash,
                    now,
                    now,
                ),
            )
            evidence_id = (
                "decision-evidence-"
                + hashlib.sha256(f"{decision_id}\0{source_hash}".encode()).hexdigest()[:24]
            )
            conn.execute(
                "DELETE FROM project_decision_evidence WHERE decision_id=?", (decision_id,)
            )
            conn.execute(
                "INSERT INTO project_decision_evidence VALUES (?, ?, ?, NULL, ?, NULL, NULL, ?, ?, ?)",
                (
                    evidence_id,
                    decision_id,
                    project_id,
                    f"git:{commit_id}",
                    source_hash,
                    "explicit_commit_subject",
                    now,
                ),
            )
        existing = conn.execute(
            "SELECT id FROM project_decisions WHERE project_id = ? AND user_created = 0 AND status != 'dismissed'",
            (project_id,),
        ).fetchall()
        for row in existing:
            if row["id"] not in discovered:
                conn.execute(
                    "UPDATE project_decisions SET status='stale', stale_reason='source_missing_or_no_longer_matches', updated_at=? WHERE id=?",
                    (now, row["id"]),
                )
        live_row = conn.execute(
            "SELECT live_state_json FROM project_git_snapshots WHERE project_id=? ORDER BY generated_at DESC LIMIT 1",
            (project_id,),
        ).fetchone()
        changed_paths = (
            {
                _normal_path(item.get("relative_path", ""))
                for item in _loads(live_row["live_state_json"], {}).get("files", [])
            }
            if live_row
            else set()
        )
        if changed_paths:
            for row in conn.execute(
                "SELECT id, governed_paths_json FROM project_decisions WHERE project_id=? AND status='active'",
                (project_id,),
            ):
                governed = {_normal_path(path) for path in _loads(row["governed_paths_json"], [])}
                if governed & changed_paths:
                    conn.execute(
                        "UPDATE project_decisions SET status='stale', stale_reason='governed_path_changed', updated_at=? WHERE id=?",
                        (now, row["id"]),
                    )
        _publish(conn, project_id, snapshot_id, now, truncated=len(eligible) >= max_files)
    return list_project_decisions(project_id)


def list_project_decisions(project_id: str, *, include_dismissed: bool = False) -> dict:
    with connect() as conn:
        if (
            conn.execute(
                "SELECT id FROM projects WHERE id=? AND deleted_at IS NULL", (project_id,)
            ).fetchone()
            is None
        ):
            raise KeyError(project_id)
        clause = "" if include_dismissed else "AND d.status != 'dismissed'"
        rows = conn.execute(
            f"SELECT d.* FROM project_decisions d WHERE d.project_id=? {clause} ORDER BY d.status, d.updated_at DESC, d.id",
            (project_id,),
        ).fetchall()
        decisions = []
        for row in rows:
            item = dict_from_row(row)
            item["governed_paths"] = _loads(item.pop("governed_paths_json"), [])
            item["user_created"] = bool(item["user_created"])
            item["evidence"] = [
                dict_from_row(value)
                for value in conn.execute(
                    "SELECT * FROM project_decision_evidence WHERE decision_id=? ORDER BY relative_path, start_line",
                    (item["id"],),
                )
            ]
            item["relationships"] = [
                dict_from_row(value)
                for value in conn.execute(
                    "SELECT * FROM project_decision_edges WHERE source_decision_id=? ORDER BY relationship_type, target_decision_id",
                    (item["id"],),
                )
            ]
            decisions.append(item)
    return {"project_id": project_id, "items": decisions, "count": len(decisions)}


def create_project_decision(
    project_id: str,
    *,
    statement: str,
    rationale: str = "",
    governed_paths: list[str] | None = None,
    idempotency_key: str = "",
) -> dict:
    clean_statement = _clean_user_text(statement, 2000)
    clean_rationale = _clean_user_text(rationale, 4000)
    if not clean_statement:
        raise ValueError("A decision statement is required.")
    now = utc_now()
    stable = idempotency_key.strip() or str(uuid.uuid4())
    decision_id = (
        "decision-user-" + hashlib.sha256(f"{project_id}\0{stable}".encode()).hexdigest()[:24]
    )
    with connect() as conn:
        project = conn.execute(
            "SELECT active_manifest_snapshot_id, active_snapshot_id FROM projects WHERE id=? AND deleted_at IS NULL",
            (project_id,),
        ).fetchone()
        if project is None:
            raise KeyError(project_id)
        conn.execute(
            """INSERT INTO project_decisions VALUES (?, ?, ?, ?, ?, ?, 'active', 'user_confirmed', 'confirmed',
            'user', ?, 1, '', ?, ?) ON CONFLICT(id) DO NOTHING""",
            (
                decision_id,
                project_id,
                project["active_manifest_snapshot_id"] or project["active_snapshot_id"],
                clean_statement,
                clean_rationale,
                _json([_normal_path(path) for path in governed_paths or []]),
                hashlib.sha256((clean_statement + "\0" + clean_rationale).encode()).hexdigest(),
                now,
                now,
            ),
        )
    return next(
        item
        for item in list_project_decisions(project_id, include_dismissed=True)["items"]
        if item["id"] == decision_id
    )


def set_decision_status(project_id: str, decision_id: str, status: str) -> dict:
    if status not in {"active", "superseded", "dismissed"}:
        raise ValueError("Unsupported decision status.")
    with connect() as conn:
        result = conn.execute(
            "UPDATE project_decisions SET status=?, updated_at=? WHERE id=? AND project_id=?",
            (status, utc_now(), decision_id, project_id),
        )
        if not result.rowcount:
            raise KeyError(decision_id)
    return next(
        item
        for item in list_project_decisions(project_id, include_dismissed=True)["items"]
        if item["id"] == decision_id
    )


def relate_project_decisions(
    project_id: str,
    source_decision_id: str,
    target_decision_id: str,
    relationship_type: str,
    *,
    confirmed: bool = False,
) -> dict:
    if relationship_type not in {"supersedes", "refines", "relates_to", "conflicts_with"}:
        raise ValueError("Unsupported decision relationship.")
    if source_decision_id == target_decision_id:
        raise ValueError("A decision cannot relate to itself.")
    now = utc_now()
    verification = "confirmed" if confirmed else "review_required"
    with connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) AS total FROM project_decisions WHERE project_id=? AND id IN (?,?)",
            (project_id, source_decision_id, target_decision_id),
        ).fetchone()["total"]
        if count != 2:
            raise KeyError(source_decision_id)
        conn.execute(
            "INSERT OR REPLACE INTO project_decision_edges VALUES (?, ?, ?, ?, ?, ?)",
            (
                project_id,
                source_decision_id,
                target_decision_id,
                relationship_type,
                verification,
                now,
            ),
        )
        if confirmed and relationship_type == "supersedes":
            conn.execute(
                "UPDATE project_decisions SET status='superseded', updated_at=? WHERE id=?",
                (now, target_decision_id),
            )
    return {
        "project_id": project_id,
        "source_decision_id": source_decision_id,
        "target_decision_id": target_decision_id,
        "relationship_type": relationship_type,
        "verification_state": verification,
    }


def _parse_decision(text: str) -> tuple[str, str, int, int] | None:
    lines = text.replace("\r\n", "\n").splitlines()
    title = next(
        (re.sub(r"^#\s*", "", line).strip() for line in lines if line.startswith("# ")), ""
    )
    markers = [
        (index, match.group(1).upper(), match.group(2).strip())
        for index, line in enumerate(lines, 1)
        if (match := _MARKER.match(line))
    ]
    if not markers and not re.search(
        r"(?im)^\s*(status|context|decision|consequences)\s*[:\n]", text
    ):
        return None
    statement = title
    rationale_parts = []
    for index, name, trailing in markers:
        if name == "DECISION" and trailing:
            statement = trailing
        if name in {"WHY", "RATIONALE", "TRADE-OFFS", "TRADE OFFS", "TRADEOFFS"} and trailing:
            rationale_parts.append(trailing)
    if not statement:
        statement = "Documented architecture decision"
    return (
        statement[:2000],
        " ".join(rationale_parts)[:4000],
        markers[0][0] if markers else 1,
        markers[-1][0] if markers else min(len(lines), 40),
    )


def _governed_paths(text: str) -> list[str]:
    match = re.search(r"(?im)^\s*(?:governs|paths?|scope)\s*:\s*(.+)$", text)
    return (
        [
            _normal_path(part.strip(" `"))
            for part in re.split(r"[,;]", match.group(1))
            if part.strip()
        ]
        if match
        else []
    )


def _publish(conn, project_id: str, snapshot_id: str | None, now: str, *, truncated: bool) -> None:
    items = conn.execute(
        "SELECT status, confidence_class FROM project_decisions WHERE project_id=? AND status!='dismissed'",
        (project_id,),
    ).fetchall()
    review_count = conn.execute(
        "SELECT COUNT(*) AS total FROM project_decision_edges WHERE project_id=? AND verification_state='review_required'",
        (project_id,),
    ).fetchone()["total"]
    summary = {
        "count": len(items),
        "active_count": sum(row["status"] == "active" for row in items),
        "stale_count": sum(row["status"] == "stale" for row in items),
        "review_needed_count": int(review_count or 0),
    }
    row = conn.execute(
        "SELECT id, layer_states_json FROM project_intelligence_snapshots WHERE project_id=? AND owning_snapshot_id=?",
        (project_id, snapshot_id),
    ).fetchone()
    if row:
        layers = _loads(row["layer_states_json"], {})
        layers["decisions"] = {
            "status": "ready" if items else "unavailable",
            "version": DECISION_EXTRACTOR_VERSION,
            "generated_at": now,
            "truncated": truncated,
            "unknown_reason": None
            if items
            else {
                "code": "no_decisions",
                "detail": "No ADR or user-confirmed decisions were found.",
            },
        }
        conn.execute(
            "UPDATE project_intelligence_snapshots SET decisions_json=?, layer_states_json=? WHERE id=?",
            (_json(summary), _json(layers), row["id"]),
        )


def _clean_user_text(value: str, maximum: int) -> str:
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(value)).strip()[:maximum]


def _normal_path(path: str) -> str:
    return str(path).replace("\\", "/").lstrip("./")


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _loads(value: object, fallback: object):
    try:
        return json.loads(str(value))
    except (TypeError, ValueError):
        return fallback
