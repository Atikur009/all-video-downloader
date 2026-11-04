"""Generate launcher icon PNGs for the All Video Downloader Android app
from the verified source icon (WebP). Run from the android/ directory
or pass the project dir as argv[1].

Outputs (all from the same source image):
  mipmap-{mdpi,hdpi,xhdpi,xxhdpi,xxxhdpi}/ic_launcher.png
  mipmap-{mdpi,hdpi,xhdpi,xxhdpi,xxxhdpi}/ic_launcher_round.png
  mipmap-xxxhdpi/ic_launcher_foreground.png (432x432, adaptive icon)
"""

import os
import sys

from PIL import Image

SRC = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "apk-icon",
    "media-generation-app-icon-0-631509aa-f286-4feb-b172-90ffcb05cfb8.webp",
)
PROJ = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))

SIZES = {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}


def main():
    im = Image.open(SRC).convert("RGBA")
    for density, size in SIZES.items():
        dpath = os.path.join(PROJ, "app/src/main/res/mipmap-" + density)
        os.makedirs(dpath, exist_ok=True)
        resized = im.resize((size, size), Image.LANCZOS)
        resized.save(os.path.join(dpath, "ic_launcher.png"))
        resized.save(os.path.join(dpath, "ic_launcher_round.png"))
    im.resize((432, 432), Image.LANCZOS).save(
        os.path.join(PROJ, "app/src/main/res/mipmap-xxxhdpi/ic_launcher_foreground.png")
    )
    print("icons done")


if __name__ == "__main__":
    main()
