"""Regenerate Apple's launch images from the existing Pelagia app icon.

Run from the repository root: .venv312/bin/python scripts/generate_pwa_startup_images.py
The generated files are committed; deployment does not need a build step.
"""

import json
from pathlib import Path

from PIL import Image, ImageDraw


STATIC = Path(__file__).resolve().parents[1] / "pelagia" / "static"
# CSS screen dimensions and device pixel ratio, shared across iPhone/iPad models.
DEVICES = (
    (320, 568, 2), (375, 667, 2), (414, 736, 3),
    (375, 812, 3), (414, 896, 2), (414, 896, 3),
    (390, 844, 3), (428, 926, 3), (393, 852, 3), (430, 932, 3),
    (402, 874, 3), (440, 956, 3), (420, 912, 3),
    (768, 1024, 2), (810, 1080, 2), (820, 1180, 2),
    (834, 1112, 2), (834, 1194, 2), (834, 1210, 2),
    (744, 1133, 2),
    (1024, 1366, 2), (1032, 1376, 2),
)


def main():
    output = STATIC / "img" / "startup"
    output.mkdir(parents=True, exist_ok=True)
    screens = []
    with Image.open(STATIC / "img" / "icon-512.png") as source:
        for width, height, scale in DEVICES:
            size = 112 * scale
            icon = source.convert("RGB").resize((size, size), Image.Resampling.LANCZOS)
            mask = Image.new("L", (size, size))
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius=24 * scale, fill=255)
            for orientation in ("portrait", "landscape"):
                pixels = (width * scale, height * scale)
                if orientation == "landscape":
                    pixels = pixels[::-1]
                image = Image.new("RGB", pixels, "#031e33")
                image.paste(icon, ((pixels[0] - size) // 2, (pixels[1] - size) // 2), mask)
                filename = f"img/startup/launch-{pixels[0]}x{pixels[1]}.png"
                image.save(STATIC / filename, optimize=True)
                screens.append({
                    "filename": filename,
                    "media": f"screen and (device-width: {width}px) and (device-height: {height}px) "
                             f"and (-webkit-device-pixel-ratio: {scale}) and (orientation: {orientation})",
                })
    (output / "screens.json").write_text(json.dumps(screens, indent=2) + "\n")
    print(f"Generated {len(screens)} launch screens in {output}")


if __name__ == "__main__":
    main()
