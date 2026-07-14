from __future__ import annotations

import json

import pytest

from backend.app import odin_credential_helper as helper


@pytest.mark.skipif(helper.os.name != "nt", reason="Windows DPAPI is the production credential store")
def test_dpapi_credential_round_trip_never_writes_plaintext(tmp_path, monkeypatch):
    target = tmp_path / "credentials.json"
    monkeypatch.setenv("ODIN_CREDENTIAL_FILE", str(target))
    helper.store("client-1", "plain-secret-value")

    persisted = target.read_text(encoding="utf-8")
    assert "plain-secret-value" not in persisted
    assert json.loads(persisted)["client_id"] == "client-1"
    assert helper.read() == {"client_id": "client-1", "credential": "plain-secret-value"}

    assert helper.forget() == {"forgotten": True}
    assert helper.status() == {"stored": False}
