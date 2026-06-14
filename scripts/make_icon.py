"""
Generate the GQ Dashboard app icon — a large gradient "GQ" wordmark over a
detailed trading backdrop (candlesticks, grid, rising line). Matches the
dashboard palette. Produces assets/icon_1024.png and, on macOS,
assets/AppIcon.icns (via sips + iconutil).

  python3 scripts/make_icon.py
"""

from __future__ import annotations
import os
import shutil
import subprocess
import tempfile

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

SIZE = 1024
HERE = os.path.dirname(__file__)
ASSETS = os.path.join(HERE, os.pardir, "assets")
EMER = (52, 211, 153)
BLUE = (110, 168, 254)
ROSE = (251, 113, 133)


def _vgrad(w, h, top, bot):
    t = np.linspace(0, 1, h)[:, None]
    col = np.array(top)[None, :] * (1 - t) + np.array(bot)[None, :] * t
    return np.repeat(col[:, None, :], w, axis=1).astype(np.uint8)


def _radial_glow(size, center, radius, color, max_alpha):
    yy, xx = np.mgrid[0:size, 0:size]
    d = np.sqrt((xx - center[0]) ** 2 + (yy - center[1]) ** 2)
    a = np.clip(1 - d / radius, 0, 1) ** 2 * max_alpha
    img = np.zeros((size, size, 4), np.uint8)
    img[..., 0], img[..., 1], img[..., 2] = color
    img[..., 3] = a.astype(np.uint8)
    return Image.fromarray(img, "RGBA")


def _font(size):
    for p in ("/System/Library/Fonts/SFNSRounded.ttf",
              "/System/Library/Fonts/SFNS.ttf",
              "/System/Library/Fonts/SFCompact.ttf",
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
    inset, radius = 100, 188
    body = SIZE - 2 * inset

    # rounded body + gradient
    grad = Image.fromarray(_vgrad(body, body, (24, 38, 68), (6, 10, 18)), "RGB").convert("RGBA")
    mask = Image.new("L", (body, body), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, body - 1, body - 1], radius=radius, fill=255)
    img.paste(grad, (inset, inset), mask)

    # everything else is drawn on a layer then clipped to the rounded body
    layer = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    # top glow
    layer.alpha_composite(_radial_glow(SIZE, (SIZE * 0.34, SIZE * 0.26), SIZE * 0.55, BLUE, 60))

    # faint grid
    L, R, T, B = inset + 60, SIZE - inset - 60, inset + 70, SIZE - inset - 70
    for i in range(1, 6):
        y = T + (B - T) * i / 6
        d.line([(L, y), (R, y)], fill=(120, 140, 180, 26), width=2)
    for i in range(1, 7):
        x = L + (R - L) * i / 7
        d.line([(x, T), (x, B)], fill=(120, 140, 180, 16), width=2)

    # candlesticks (uptrend, green/red) along the lower half
    base = B
    cols = 9
    closes = [0.16, 0.10, 0.24, 0.20, 0.36, 0.30, 0.52, 0.66, 0.84]
    opens = [0.10, 0.18, 0.18, 0.30, 0.28, 0.42, 0.46, 0.58, 0.74]
    cw = (R - L) / cols
    def yv(v): return base - (base - T) * v
    for i in range(cols):
        cx = L + cw * (i + 0.5)
        o, c = yv(opens[i]), yv(closes[i])
        up = closes[i] >= opens[i]
        col = EMER if up else ROSE
        hi = min(o, c) - cw * 0.5
        lo = max(o, c) + cw * 0.35
        d.line([(cx, hi), (cx, lo)], fill=col + (150,), width=6)        # wick
        top_, bot_ = min(o, c), max(o, c)
        d.rounded_rectangle([cx - cw * 0.28, top_, cx + cw * 0.28, bot_],
                            radius=6, fill=col + (180,))               # body

    # rising line + area + glowing tip, riding the closes
    pts = [(L + cw * (i + 0.5), yv(closes[i])) for i in range(cols)]
    area = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ImageDraw.Draw(area).polygon(pts + [(pts[-1][0], base), (pts[0][0], base)], fill=EMER + (40,))
    layer.alpha_composite(area)
    d.line(pts, fill=EMER + (255,), width=14, joint="curve")
    tx, ty = pts[-1]
    for r, a in ((40, 60), (24, 120), (12, 255)):
        d.ellipse([tx - r, ty - r, tx + r, ty + r], fill=BLUE + (a,))

    # clip the backdrop to the rounded body, dim it so the wordmark dominates
    clipped = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    body_mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(body_mask).rounded_rectangle(
        [inset, inset, SIZE - inset - 1, SIZE - inset - 1], radius=radius, fill=255)
    clipped.paste(layer, (0, 0), body_mask)
    img.alpha_composite(clipped)

    # ── big "GQ" wordmark: gradient fill + glow + stroke ──────────────────────
    txt = "GQ"
    font = _font(150)
    # scale font so the wordmark spans ~74% of the body width
    target = body * 0.74
    tmp = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    bb = tmp.textbbox((0, 0), txt, font=font, stroke_width=0)
    fsize = int(150 * target / (bb[2] - bb[0]))
    font = _font(fsize)

    tmask = Image.new("L", (SIZE, SIZE), 0)
    td = ImageDraw.Draw(tmask)
    bb = td.textbbox((0, 0), txt, font=font)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    pos = ((SIZE - tw) / 2 - bb[0], (SIZE - th) / 2 - bb[1] - SIZE * 0.01)
    td.text(pos, txt, font=font, fill=255)

    # glow behind the letters
    glow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.text(pos, txt, font=font, fill=BLUE + (255,))
    glow = glow.filter(ImageFilter.GaussianBlur(26))
    img.alpha_composite(glow)

    # gradient-filled letters (blue -> emerald, top-left to bottom-right)
    gx = np.linspace(0, 1, SIZE)[None, :]
    gy = np.linspace(0, 1, SIZE)[:, None]
    t = np.clip((gx + gy) / 2, 0, 1)
    fill = np.zeros((SIZE, SIZE, 4), np.uint8)
    for k in range(3):
        fill[..., k] = (BLUE[k] * (1 - t) + EMER[k] * t).astype(np.uint8)
    fill[..., 3] = 255
    grad_txt = Image.fromarray(fill, "RGBA")
    img.paste(grad_txt, (0, 0), tmask)

    # crisp light stroke around the letters for definition
    stroke = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ImageDraw.Draw(stroke).text(pos, txt, font=font, fill=(0, 0, 0, 0),
                                stroke_width=6, stroke_fill=(235, 242, 252, 230))
    img.alpha_composite(stroke)

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
