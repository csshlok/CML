import hashlib
import json
from pathlib import Path
from types import SimpleNamespace


def test_model_download_reconciles_interrupted_process_state(tmp_path, monkeypatch):
    from backend.app.core import model_registry

    partial = tmp_path / "models" / "qwen3-4b-q4_k_m" / "model.gguf.part"
    partial.parent.mkdir(parents=True)
    partial.write_bytes(b"x" * 4096)
    monkeypatch.setattr(
        model_registry,
        "get_settings",
        lambda: SimpleNamespace(data_dir=tmp_path),
    )
    model_registry._download_state.clear()
    model_registry._download_state_loaded_from = None
    model_registry._download_state.update(
        {
            "qwen3-4b-q4_k_m": {
                "model_id": "qwen3-4b-q4_k_m",
                "status": "downloading",
                "bytes_downloaded": 1024,
                "bytes_total": 8192,
                "partial_path": str(partial),
                "updated_at": "2026-01-01T00:00:00Z",
            }
        }
    )
    with model_registry._download_lock:
        model_registry._persist_download_state_locked()
    model_registry._download_state.clear()
    model_registry._download_state_loaded_from = None

    model_registry._ensure_download_state_loaded()

    state = model_registry._download_state["qwen3-4b-q4_k_m"]
    assert state["status"] == "interrupted"
    assert state["bytes_downloaded"] == 4096
    assert state["resumable"] is True
    assert Path(model_registry._download_state_path()).exists()


def test_embedding_download_reconciles_to_resumable_interrupted_state(tmp_path, monkeypatch):
    from backend.app.core import embeddings

    model_dir = tmp_path / "embeddings" / "all-MiniLM-L6-v2"
    model_dir.mkdir(parents=True)
    (model_dir / "model.safetensors.partial").write_bytes(b"y" * 2048)
    monkeypatch.setattr(
        embeddings,
        "get_settings",
        lambda: SimpleNamespace(data_dir=tmp_path),
    )
    embeddings._EMBEDDING_DOWNLOAD_STATE.update(
        {
            "model_id": embeddings.DEFAULT_EMBEDDING_MODEL,
            "status": "downloading",
            "bytes_downloaded": 512,
            "bytes_total": 4096,
            "local_path": str(model_dir),
            "updated_at": "2026-01-01T00:00:00Z",
        }
    )
    embeddings._EMBEDDING_DOWNLOAD_STATE_LOADED_FROM = tmp_path / "seed"
    with embeddings._EMBEDDING_DOWNLOAD_LOCK:
        embeddings._persist_embedding_download_state_locked()
    embeddings._EMBEDDING_DOWNLOAD_STATE.update(
        {
            "status": "idle",
            "bytes_downloaded": 0,
            "bytes_total": None,
            "local_path": None,
        }
    )
    embeddings._EMBEDDING_DOWNLOAD_STATE_LOADED_FROM = None

    embeddings._ensure_embedding_download_state_loaded()

    state = embeddings.embedding_download_status()
    assert state["status"] == "interrupted"
    assert state["bytes_downloaded"] >= 2048
    assert state["resumable"] is True


def test_embedding_cancel_waits_for_worker_termination_before_terminal_state(tmp_path, monkeypatch):
    from backend.app.core import embeddings

    class FakeProcess:
        def __init__(self):
            self.terminated = False

        def poll(self):
            return None if not self.terminated else 0

        def terminate(self):
            self.terminated = True

        def wait(self, timeout):
            assert timeout == 5
            assert self.terminated
            return 0

    process = FakeProcess()
    monkeypatch.setattr(
        embeddings,
        "get_settings",
        lambda: SimpleNamespace(data_dir=tmp_path),
    )
    embeddings._EMBEDDING_DOWNLOAD_STATE.update(
        {
            "model_id": embeddings.DEFAULT_EMBEDDING_MODEL,
            "status": "downloading",
            "bytes_downloaded": 2048,
            "bytes_total": 4096,
            "local_path": str(tmp_path / "model"),
            "error": None,
        }
    )
    embeddings._EMBEDDING_DOWNLOAD_STATE_LOADED_FROM = tmp_path / "seed"
    embeddings._EMBEDDING_DOWNLOAD_PROCESS = process

    state = embeddings.cancel_embedding_model_download()

    assert process.terminated is True
    assert state["status"] == "cancelled"
    assert state["error"] == "Download cancelled."


def test_model_download_resumes_with_range_and_matching_etag(tmp_path, monkeypatch):
    from backend.app.core import model_registry

    model = model_registry.get_model("qwen3-4b-q4_k_m")
    assert model is not None
    content = b"0123456789"
    initial = content[:4]
    remainder = content[4:]
    digest = hashlib.sha256(content).hexdigest()
    target_root = tmp_path / "models"
    target_dir = target_root / model.id
    target_dir.mkdir(parents=True)
    target = target_dir / "model.gguf"
    partial = target.with_suffix(".gguf.part")
    metadata = partial.with_suffix(".part.json")
    partial.write_bytes(initial)
    revision = "test-revision"
    url = (
        f"https://huggingface.co/{model.hf_repo}/resolve/"
        f"{revision}/model.gguf"
    )
    metadata.write_text(
        json.dumps(
            {
                "url": url,
                "expected_sha256": digest,
                "file_name": "model.gguf",
                "etag": '"artifact-v1"',
                "total_bytes": len(content),
            }
        ),
        encoding="utf-8",
    )

    captured_request = None

    class FakeResponse:
        status = 206
        headers = {
            "Content-Range": f"bytes {len(initial)}-{len(content) - 1}/{len(content)}",
            "Content-Length": str(len(remainder)),
            "ETag": '"artifact-v1"',
        }

        def __init__(self):
            self.sent = False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _size):
            if self.sent:
                return b""
            self.sent = True
            return remainder

    def fake_urlopen(request, timeout):
        nonlocal captured_request
        captured_request = request
        assert timeout == 30
        return FakeResponse()

    monkeypatch.setattr(
        model_registry,
        "get_settings",
        lambda: SimpleNamespace(data_dir=tmp_path),
    )
    monkeypatch.setattr(model_registry, "_download_expected_model_sha256", lambda _model: digest)
    monkeypatch.setattr(model_registry, "_resolve_gguf_filename", lambda _model: "model.gguf")
    monkeypatch.setattr(model_registry, "_trusted_manifest_revision", lambda _model: revision)
    monkeypatch.setattr(model_registry, "validate_huggingface_url", lambda _url: None)
    monkeypatch.setattr(model_registry, "urlopen", fake_urlopen)
    monkeypatch.setattr(model_registry, "_write_integrity_manifest", lambda *_args: None)
    monkeypatch.setattr(model_registry, "_record_downloaded_model_path", lambda *_args: None)
    model_registry._download_state.clear()
    model_registry._cancelled_downloads.clear()
    model_registry._download_state_loaded_from = tmp_path
    model_registry._download_state[model.id] = {
        "model_id": model.id,
        "status": "resolving",
        "bytes_downloaded": len(initial),
        "bytes_total": len(content),
    }

    model_registry._download_model(model, target_root)

    assert captured_request is not None
    assert captured_request.headers["Range"] == f"bytes={len(initial)}-"
    assert captured_request.headers["If-range"] == '"artifact-v1"'
    assert target.read_bytes() == content
    assert not partial.exists()
    assert model_registry._download_state[model.id]["status"] == "installed"
