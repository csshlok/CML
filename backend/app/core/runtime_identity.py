from uuid import uuid4

from backend.app.core.database import utc_now


BACKEND_INSTANCE_ID = f"backend-{uuid4()}"
BACKEND_INSTANCE_STARTED_AT = utc_now()


def backend_runtime_identity() -> dict[str, str]:
    return {
        "instance_id": BACKEND_INSTANCE_ID,
        "started_at": BACKEND_INSTANCE_STARTED_AT,
    }
