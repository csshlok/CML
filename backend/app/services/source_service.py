from backend.app.core.retrieval_cache import invalidate_caches_for_source


def mark_source_changed(source_id: str, conn=None) -> dict:
    return invalidate_caches_for_source(source_id, conn=conn)


def mark_source_deleted(source_id: str, conn=None) -> dict:
    return invalidate_caches_for_source(source_id, conn=conn)
