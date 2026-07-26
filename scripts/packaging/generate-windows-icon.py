from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    source = Path(args.source).resolve()
    output = Path(args.output).resolve()
    if not source.is_file():
        raise SystemExit(f"Package logo does not exist: {source}")

    with Image.open(source) as image:
        rgba = image.convert("RGBA")
        if rgba.width != rgba.height:
            edge = max(rgba.size)
            square = Image.new("RGBA", (edge, edge), (0, 0, 0, 0))
            square.alpha_composite(
                rgba,
                ((edge - rgba.width) // 2, (edge - rgba.height) // 2),
            )
            rgba = square
        master = rgba.resize((256, 256), Image.Resampling.LANCZOS)
        output.parent.mkdir(parents=True, exist_ok=True)
        master.save(output, format="ICO", sizes=[(size, size) for size in ICON_SIZES])

    with Image.open(output) as generated:
        generated_sizes = set(generated.info.get("sizes", set()))
    required = {(size, size) for size in ICON_SIZES}
    if not required.issubset(generated_sizes):
        missing = sorted(required - generated_sizes)
        raise SystemExit(f"Generated Windows icon is missing sizes: {missing}")


if __name__ == "__main__":
    main()
