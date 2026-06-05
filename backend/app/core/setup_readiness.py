from backend.app.core.config import get_settings
from backend.app.core.embeddings import embedding_status
from backend.app.core.model_registry import active_model_status, model_integrity_manifest_status, list_models
from backend.app.core.ocr import ocr_runtime_status
from backend.app.core.startup_status import startup_status_staleness, validate_startup_phase_registry


def first_run_readiness() -> dict:
    settings = get_settings()
    embedding = embedding_status()
    ocr = ocr_runtime_status()
    manifest = model_integrity_manifest_status()
    installed_models = [model for model in list_models() if model.get("installed")]
    active_model = active_model_status()
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
            "id": "approved_model",
            "ok": bool(active_model and active_model.get("compatibility", {}).get("accepted")),
            "detail": (
                active_model.get("compatibility", {}).get("detail", "")
                if active_model
                else "No active approved model is configured."
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
