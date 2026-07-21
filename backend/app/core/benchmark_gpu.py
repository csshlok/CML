from __future__ import annotations

from typing import Any


def require_cuda(*, minimum_free_mib: int = 1024) -> dict[str, Any]:
    """Return CUDA metadata or fail instead of silently evaluating on CPU."""
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError(
            "This model-backed benchmark requires NVIDIA CUDA; CPU fallback is disabled."
        )
    device = torch.device("cuda:0")
    free_bytes, total_bytes = torch.cuda.mem_get_info(device)
    free_mib = int(free_bytes // 1024**2)
    if free_mib < minimum_free_mib:
        raise RuntimeError(
            f"CUDA device has {free_mib} MiB free; at least {minimum_free_mib} MiB is required."
        )
    return {
        "device": "cuda",
        "device_name": torch.cuda.get_device_name(device),
        "torch_version": torch.__version__,
        "cuda_version": torch.version.cuda,
        "free_mib": free_mib,
        "total_mib": int(total_bytes // 1024**2),
        "cpu_fallback_allowed": False,
    }
