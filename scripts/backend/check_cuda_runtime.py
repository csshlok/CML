#!/usr/bin/env python3
"""Fail closed when a model-backed benchmark would run without NVIDIA CUDA."""

from __future__ import annotations

import argparse
import json
import time


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the benchmark CUDA runtime.")
    parser.add_argument("--minimum-free-mib", type=int, default=1024)
    parser.add_argument("--smoke-size", type=int, default=1024)
    args = parser.parse_args()

    import torch

    if not torch.cuda.is_available():
        raise RuntimeError(
            "CUDA is required for model-backed evaluation; CPU fallback is disabled."
        )
    device = torch.device("cuda:0")
    free_bytes, total_bytes = torch.cuda.mem_get_info(device)
    free_mib = free_bytes // 1024**2
    if free_mib < args.minimum_free_mib:
        raise RuntimeError(
            f"CUDA device has only {free_mib} MiB free; "
            f"{args.minimum_free_mib} MiB is required."
        )
    left = torch.randn((args.smoke_size, args.smoke_size), device=device)
    right = torch.randn((args.smoke_size, args.smoke_size), device=device)
    torch.cuda.synchronize(device)
    started = time.perf_counter()
    result = left @ right
    torch.cuda.synchronize(device)
    print(
        json.dumps(
            {
                "cuda_ready": True,
                "torch_version": torch.__version__,
                "cuda_version": torch.version.cuda,
                "device": torch.cuda.get_device_name(device),
                "total_mib": total_bytes // 1024**2,
                "free_mib": free_mib,
                "smoke_seconds": round(time.perf_counter() - started, 6),
                "smoke_value": float(result[0, 0]),
                "cpu_fallback_allowed": False,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
