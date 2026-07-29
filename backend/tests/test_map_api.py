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


def test_map_can_add_bounded_semantic_cluster_connections_without_changing_current_view(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "map-similarity.sqlite3"
    monkeypatch.setenv("CML_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CML_DATABASE_PATH", str(database_path))
    get_settings.cache_clear()
    init_db()
    try:
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES ('vault-similar', 'Similar', ?, '2026-01-01', '2026-01-03')",
                (str(tmp_path),),
            )
            profiles = [
                ("cluster-python", "Python courses", "[1.0,0.0]", '{"python":1.0,"course":0.8}', '["source-python"]'),
                ("cluster-coding", "Coding lessons", "[0.98,0.2]", '{"python":0.7,"course":0.6}', '["source-coding"]'),
                ("cluster-travel", "Travel plans", "[0.0,1.0]", '{"travel":1.0}', '["source-travel"]'),
            ]
            for cluster_id, name, centroid, terms, representatives in profiles:
                conn.execute(
                    """
                    INSERT INTO clusters (
                        id, vault_id, name, description, color, index_status, profile_status,
                        cluster_summary, cluster_glossary, created_at, updated_at
                    ) VALUES (?, 'vault-similar', ?, '', 'sage', 'ready', 'ready', '', '[]', '2026-01-01', '2026-01-03')
                    """,
                    (cluster_id, name),
                )
                conn.execute(
                    """
                    INSERT INTO cluster_candidate_profiles (
                        cluster_id, vault_id, profile_version, source_hash,
                        derived_state_tuple, centroid, lexical_terms,
                        source_type_distribution, representative_source_ids,
                        cohesion, status, created_at, updated_at
                    ) VALUES (?, 'vault-similar', 1, ?, '{}', ?, ?, '{}', ?, 0.9, 'ready', '2026-01-02', '2026-01-03')
                    """,
                    (cluster_id, f"hash:{cluster_id}", centroid, terms, representatives),
                )

        current = map_overview("vault-similar", 120, 0)
        assert current["connection_mode"] == "current"
        assert current["relationship_policy"] == "authoritative_only"
        assert current["edges"] == []

        connected = map_overview("vault-similar", 120, 0, connections="similar")
        assert connected["connection_mode"] == "similar"
        assert connected["relationship_policy"] == "evidence_and_similarity"
        assert len(connected["edges"]) == 1
        edge = connected["edges"][0]
        assert edge["kind"] == "similarity"
        assert {edge["source"], edge["target"]} == {"cluster-python", "cluster-coding"}
        assert edge["similarity_score"] >= 0.97
        assert edge["shared_terms"] == ["python", "course"]
        assert edge["direction"] == "undirected"
    finally:
        get_settings.cache_clear()


def test_semantic_cluster_connections_are_degree_bounded_for_dense_profiles(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "map-dense.sqlite3"
    monkeypatch.setenv("CML_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CML_DATABASE_PATH", str(database_path))
    get_settings.cache_clear()
    init_db()
    try:
        with connect() as conn:
            conn.execute(
                "INSERT INTO vaults (id, name, path, created_at, updated_at) VALUES ('vault-dense', 'Dense', ?, '2026-01-01', '2026-01-03')",
                (str(tmp_path),),
            )
            for index in range(20):
                cluster_id = f"cluster-{index:02d}"
                conn.execute(
                    """
                    INSERT INTO clusters (
                        id, vault_id, name, description, color, index_status, profile_status,
                        cluster_summary, cluster_glossary, created_at, updated_at
                    ) VALUES (?, 'vault-dense', ?, '', 'sage', 'ready', 'ready', '', '[]', '2026-01-01', '2026-01-03')
                    """,
                    (cluster_id, f"Related {index}"),
                )
                conn.execute(
                    """
                    INSERT INTO cluster_candidate_profiles (
                        cluster_id, vault_id, profile_version, source_hash,
                        derived_state_tuple, centroid, lexical_terms,
                        source_type_distribution, representative_source_ids,
                        cohesion, status, created_at, updated_at
                    ) VALUES (?, 'vault-dense', 1, ?, '{}', '[1.0,0.0]', '{"shared":1.0}', '{}', '[]', 0.9, 'ready', '2026-01-02', '2026-01-03')
                    """,
                    (cluster_id, f"hash:{cluster_id}"),
                )

        connected = map_overview("vault-dense", 120, 0, connections="similar")
        degrees: dict[str, int] = {}
        for edge in connected["edges"]:
            degrees[edge["source"]] = degrees.get(edge["source"], 0) + 1
            degrees[edge["target"]] = degrees.get(edge["target"], 0) + 1
        assert connected["edges"]
        assert len(connected["edges"]) <= 30
        assert max(degrees.values()) <= 3
    finally:
        get_settings.cache_clear()
