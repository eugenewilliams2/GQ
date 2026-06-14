"""
Generate the GQ Dashboard app icon — a dark rounded square with a rising chart,
matching the dashboard's palette. Produces assets/icon_1024.png and, on macOS,
assets/AppIcon.icns (via sips + iconutil).

  python3 scripts/make_icon.py
"""

from __future__ import annotations
import math
import os
import shutil
import subprocess
import tempfile

import numpy as np
from PIL import Image, ImageDraw, ImageFont

SIZE = 1024
HERE = os.path.dirname(__file__)
ASSETS = os.path.join(HERE, os.pardir, "assets")


def _gradient(w, h, top, bot):
    t = np.linspace(0, 1, h)[:, None]
    col = (np.array(top)[None, :] * (1 - t) + np.array(bot)[None, :] * t)
    return np.repeat(col[:, None, :], w, axis=1).astype(np.uint8)


def _font(size):
    for p in ("/System/Library/Fonts/SFNSRounded.ttf",
              "/System/Library/Fonts/SFNS.ttf",
              "/System/Library/Fonts/Helvetica.ttc",
              "/Library/Fonts/Arial Bold.ttf"):
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                continue
    return ImageFont.load_default()


def build_png(path):
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))

    # rounded-square body with a vertical gradient (macOS content inset)
    inset, radius = 100, 188
    body_w = SIZE - 2 * inset
    grad = Image.fromarray(_gradient(body_w, body_w, (22, 34, 61), (7, 11, 20)), "RGB").convert("RGBA")
    mask = Image.new("L", (body_w, body_w), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, body_w - 1, body_w - 1], radius=radius, fill=255)
    img.paste(grad, (inset, inset), mask)

    draw = ImageDraw.Draw(img)
    # subtle top highlight rim
    draw.rounded_rectangle([inset, inset, SIZE - inset - 1, SIZE - inset - 1],
                           radius=radius, outline=(110, 168, 254, 70), width=3)

    # rising area chart
    x0, x1 = inset + 120, SIZE - inset - 110
    base = SIZE - inset - 175
    top = inset + 230
    pts_y = [0.05, 0.22, 0.12, 0.38, 0.30, 0.58, 0.72, 1.0]
    n = len(pts_y)
    pts = [(x0 + (x1 - x0) * i / (n - 1), base - (base - top) * v) for i, v in enumerate(pts_y)]

    # area fill (emerald, fading down)
    area = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ad = ImageDraw.Draw(area)
    ad.polygon(pts + [(x1, base), (x0, base)], fill=(52, 211, 153, 60))
    img.alpha_composite(area)

    # line
    draw.line(pts, fill=(52, 211, 153, 255), width=20, joint="curve")
    # glowing tip
    tx, ty = pts[-1]
    for r, a in ((48, 50), (30, 110), (16, 255)):
        draw.ellipse([tx - r, ty - r, tx + r, ty + r], fill=(110, 168, 254, a))

    # GQ wordmark
    font = _font(150)
    txt = "GQ"
    tb = draw.textbbox((0, 0), txt, font=font)
    tw, th = tb[2] - tb[0], tb[3] - tb[1]
    draw.text(((SIZE - tw) / 2 - tb[0], base + 18), txt, font=font, fill=(230, 237, 247, 235))

    os.makedirs(ASSETS, exist_ok=True)
    img.save(path)
    return path


def build_icns(png, icns):
    if not (shutil.which("iconutil") and shutil.which("sips")):
        return None
    src = Image.open(png)
    with tempfile.TemporaryDirectory() as tmp:
        iconset = os.path.join(tmp, "AppIcon.iconset")
        os.makedirs(iconset)
        for sz in (16, 32, 64, 128, 256, 512, 1024):
            src.resize((sz, sz), Image.LANCZOS).save(os.path.join(iconset, f"icon_{sz}x{sz}.png"))
            if sz <= 512:
                src.resize((sz * 2, sz * 2), Image.LANCZOS).save(
                    os.path.join(iconset, f"icon_{sz}x{sz}@2x.png"))
        subprocess.run(["iconutil", "-c", "icns", iconset, "-o", icns], check=True)
    return icns


if __name__ == "__main__":
    png = build_png(os.path.join(ASSETS, "icon_1024.png"))
    print("png  ->", png)
    icns = build_icns(png, os.path.join(ASSETS, "AppIcon.icns"))
    print("icns ->", icns or "(skipped — needs macOS iconutil/sips)")
