from __future__ import annotations

import argparse
from pathlib import Path
import sys


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--target", required=True)
    args = parser.parse_args()

    from huggingface_hub import snapshot_download

    from backend.app.core.embeddings import MINILM_DOWNLOAD_PATTERNS

    target = Path(args.target)
    target.mkdir(parents=True, exist_ok=True)
    try:
        snapshot_download(
            repo_id=args.model,
            local_dir=target,
            allow_patterns=list(MINILM_DOWNLOAD_PATTERNS),
            token=False,
            max_workers=4,
        )
    except Exception as exc:
        try:
            from huggingface_hub.errors import GatedRepoError, HfHubHTTPError

            status = getattr(getattr(exc, "response", None), "status_code", None)
            if isinstance(exc, GatedRepoError) or (
                isinstance(exc, HfHubHTTPError) and status in {401, 403}
            ):
                sys.stderr.write("CML_HF_AUTH_REQUIRED\n")
                raise SystemExit(20) from exc
        except ImportError:
            pass
        sys.stderr.write(f"CML_HF_DOWNLOAD_FAILED:{exc}\n")
        raise SystemExit(21) from exc


if __name__ == "__main__":
    main()
