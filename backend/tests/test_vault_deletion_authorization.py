def test_desktop_deletion_authorization_does_not_mutate_open_database(tmp_path, monkeypatch):
    monkeypatch.setenv("CML_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CML_DATABASE_PATH", str(tmp_path / "cml.sqlite3"))
    monkeypatch.setenv("CML_ALLOW_UNAUTHENTICATED_API", "1")

    from backend.app.core.config import get_settings

    get_settings.cache_clear()
    from backend.app.core.database import connect, init_db
    from backend.app.api.routes.vaults import authorize_vault_deletion, create_vault
    from backend.app.schemas import VaultCreate, VaultDeleteRequest

    init_db()
    vault = create_vault(VaultCreate(name="Personal", path=str(tmp_path.parent)))

    result = authorize_vault_deletion(
        vault["id"],
        VaultDeleteRequest(confirmation_name="Personal", passphrase=None),
    )

    assert result == {"authorized": True, "vault_id": vault["id"]}
    with connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) AS count FROM vaults WHERE id = ?",
            (vault["id"],),
        ).fetchone()["count"] == 1

    get_settings.cache_clear()
