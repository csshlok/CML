from backend.app.core.config import get_settings
from backend.app.core.embeddings import embedding_status
from backend.app.core.model_registry import (
    active_chat_model_status,
    active_expert_model_status,
    active_model_pair_status,
    model_integrity_manifest_status,
    list_models,
)
from backend.app.core.ocr import ocr_runtime_status
from backend.app.core.startup_status import startup_status_staleness, validate_startup_phase_registry


def first_run_readiness() -> dict:
    settings = get_settings()
    embedding = embedding_status()
    ocr = ocr_runtime_status()
    manifest = model_integrity_manifest_status()
    installed_models = [model for model in list_models() if model.get("installed")]
    active_chat_model = active_chat_model_status()
    active_expert_model = active_expert_model_status()
    active_pair = active_model_pair_status()
    checks = [
        {
            "id": "vault_path",
            "ok": settings.backend_mode == "full_vault" and str(settings.data_dir) != "data",
            "detail": f"backend_mode={settings.backend_mode}; data_dir={settings.data_dir}",
        },
        {
            "id": "embedding_setup",
            "ok": bool(embedding.get("available")) and embedding.get("provider") != "hash",
            "detail": embedding.get("detail", ""),
        },
        {
            "id": "ocr_runtime",
            "ok": bool(ocr.get("image_ocr_available")) and bool(ocr.get("pdf_ocr_available")),
            "detail": ocr.get("detail", ""),
        },
        {
            "id": "model_provenance",
            "ok": bool(manifest.get("available")) or bool(installed_models),
            "detail": (
                f"manifest_models={manifest.get('model_count', 0)}; "
                f"installed_models={len(installed_models)}"
            ),
        },
        {
            "id": "chat_model",
            "ok": bool(active_chat_model and active_chat_model.get("compatibility", {}).get("chat_role_accepted")),
            "detail": (
                active_chat_model.get("compatibility", {}).get("detail", "")
                if active_chat_model
                else "No accepted chat model is configured."
            ),
        },
        {
            "id": "expert_model",
            "ok": bool(active_expert_model and active_expert_model.get("compatibility", {}).get("expert_role_accepted")),
            "detail": (
                active_expert_model.get("compatibility", {}).get("detail", "")
                if active_expert_model
                else "No accepted expert checkpoint is configured."
            ),
        },
        {
            "id": "approved_model_pair",
            "ok": bool(active_pair.get("accepted")),
            "detail": (
                str(active_pair.get("detail") or "")
            ),
        },
        {
            "id": "startup_phases",
            "ok": bool(validate_startup_phase_registry().get("ok")),
            "detail": "Startup phase registry is valid.",
        },
    ]
    ready = all(check["ok"] for check in checks)
    return {
        "ready": ready,
        "status": "ready" if ready else "setup_required",
        "degraded_mode": not ready,
        "checks": checks,
        "startup_staleness": startup_status_staleness(),
    }
