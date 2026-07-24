from backend.app.api.routes.map import map_item, map_neighborhood, map_overview
from backend.app.core.config import get_settings
from backend.app.core.database import connect, init_db


def test_map_uses_only_authoritative_membership_and_provenance(tmp_path, monkeypatch):
    database_path = tmp_path / "map.sqlite3"
    monkeypatch.setenv("CML_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CML_DATABASE_PATH", str(database_path))
    get_settings.cache_clear()
    init_db()
    try:
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES ('vault-1', 'Test', ?, '2026-01-01', '2026-01-01')",
                (str(tmp_path),),
            )
            conn.execute(
                """
                INSERT INTO clusters (
                    id, vault_id, name, description, color, index_status, profile_status,
                    cluster_summary, cluster_glossary, created_at, updated_at
                ) VALUES ('cluster-1', 'vault-1', 'Research', '', 'sage', 'ready', 'ready', '', '[]', '2026-01-01', '2026-01-01')
                """
            )
            conn.execute(
                """
                INSERT INTO sources (
                    id, vault_id, cluster_id, title, source_type, state, raw_text,
                    extracted_text, summary, tags, created_at, updated_at
                ) VALUES ('source-1', 'vault-1', 'cluster-1', 'Interview', 'note', 'indexed', 'Source text', 'Source text', 'Summary', '[]', '2026-01-01', '2026-01-01')
                """
            )
            conn.execute(
                """
                INSERT INTO temporal_facts (
                    id, vault_id, cluster_id, subject_key, predicate_key, object_text,
                    assertion_kind, modality, speaker_role, source_type, source_id,
                    citation_excerpt, observed_at, valid_from, status, confidence,
                    origin_fingerprint, metadata_json, created_at
                ) VALUES (
                    'fact-1', 'vault-1', 'cluster-1', 'user', 'prefers', 'quiet interfaces',
                    'preference', 'asserted', 'user', 'source', 'source-1',
                    'The user prefers quiet interfaces.', '2026-01-01', '2026-01-01',
                    'current', 1.0, 'fact-origin-1', '{}', '2026-01-01'
                )
                """
            )

        overview = map_overview("vault-1", 120, 0)
        assert overview["relationship_policy"] == "authoritative_only"
        assert overview["edges"] == []
        assert overview["nodes"][0]["source_count"] == 1
        assert overview["nodes"][0]["fact_count"] == 1

        cluster_graph = map_neighborhood("vault-1", "cluster-1", 80)
        assert cluster_graph["edges"] == [
            {
                "id": "contains:cluster-1:source-1",
                "source": "cluster-1",
                "target": "source-1",
                "kind": "contains",
                "label": "contains",
                "direction": "outbound",
                "temporal_state": "current",
                "provenance_ids": ["source-1"],
                "updated_at": "2026-01-01",
            }
        ]

        source_graph = map_neighborhood("vault-1", "source-1", 80)
        assert any(node["id"] == "fact-1" for node in source_graph["nodes"])
        fact = map_item("fact-1", "vault-1")
        assert fact["citation_excerpt"] == "The user prefers quiet interfaces."
        assert fact["provenance"][0]["id"] == "source-1"
    finally:
        get_settings.cache_clear()


def test_map_links_typed_entities_and_exposes_unclustered_collection(tmp_path, monkeypatch):
    database_path = tmp_path / "map-large.sqlite3"
    monkeypatch.setenv("CML_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CML_DATABASE_PATH", str(database_path))
    get_settings.cache_clear()
    init_db()
    try:
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES ('vault-map', 'Map', ?, '2026-01-01', '2026-01-03')",
                (str(tmp_path),),
            )
            for cluster_id, name in [("cluster-a", "Health"), ("cluster-b", "Travel")]:
                conn.execute(
                    """
                    INSERT INTO clusters (
                        id, vault_id, name, description, color, index_status, profile_status,
                        cluster_summary, cluster_glossary, created_at, updated_at
                    ) VALUES (?, 'vault-map', ?, '', 'sage', 'ready', 'ready', '', '[]', '2026-01-01', '2026-01-03')
                    """,
                    (cluster_id, name),
                )
            sources = [
                ("source-a", "cluster-a", "Clinic notes"),
                ("source-b", "cluster-b", "Trip notes"),
                ("source-inbox", None, "Unsorted receipt"),
            ]
            for source_id, cluster_id, title in sources:
                conn.execute(
                    """
                    INSERT INTO sources (
                        id, vault_id, cluster_id, title, source_type, state, raw_text,
                        extracted_text, summary, tags, created_at, updated_at
                    ) VALUES (?, 'vault-map', ?, ?, 'note', 'indexed', 'Text', 'Text', '', '[]', '2026-01-01', '2026-01-03')
                    """,
                    (source_id, cluster_id, title),
                )
            for fact_id, cluster_id, source_id in [
                ("fact-a", "cluster-a", "source-a"),
                ("fact-b", "cluster-b", "source-b"),
            ]:
                conn.execute(
                    """
                    INSERT INTO temporal_facts (
                        id, vault_id, cluster_id, subject_key, predicate_key, object_text, object_type,
                        assertion_kind, modality, speaker_role, source_type, source_id,
                        citation_excerpt, observed_at, valid_from, status, confidence,
                        origin_fingerprint, metadata_json, created_at
                    ) VALUES (
                        ?, 'vault-map', ?, 'topic', 'mentions', 'Dr. Lee', 'person',
                        'fact', 'asserted', 'external', 'source', ?, 'Dr. Lee is mentioned.',
                        '2026-01-03', '2026-01-03', 'current', 1.0, ?, '{}', '2026-01-03'
                    )
                    """,
                    (fact_id, cluster_id, source_id, f"origin:{fact_id}"),
                )

        overview = map_overview("vault-map", 120, 0)
        assert overview["unclustered_count"] == 1
        assert any(node["kind"] == "collection" for node in overview["nodes"])
        assert overview["edges"][0]["direction"] == "undirected"
        assert overview["edges"][0]["evidence_labels"] == ["Shared person: Dr. Lee"]
        assert set(overview["edges"][0]["provenance_ids"]) == {"source-a", "source-b"}

        collection_id = "unclustered:vault-map"
        collection_graph = map_neighborhood("vault-map", collection_id, 80)
        assert any(node["id"] == "source-inbox" for node in collection_graph["nodes"])
        assert collection_graph["edges"][0]["source"] == collection_id
        collection_item = map_item(collection_id, "vault-map")
        assert collection_item["source_count"] == 1
    finally:
        get_settings.cache_clear()
