"""Draws uCANdo's icon — the brand mark (the CAN pulse) on its blue tile, exactly as the favicon
draws it (web/shell.js) — into packaging/ucando.ico, for the exe and for a button pinned to the
taskbar from uCANdo's window.

    py -3.12 packaging/make_icon.py        (needs Pillow; the .ico is committed, so only to redraw)

Ported from Runway's packaging/make_icon.py. The logo keeps its own blue (--brand), never the accent.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

TILE = (78, 161, 255, 255)       # --brand #4ea1ff, the favicon's tile
INK = (4, 18, 29, 255)           # the mark on it, #04121d
SIZES = [16, 24, 32, 48, 64, 128, 256]
OUT = Path(__file__).resolve().parent / "ucando.ico"
# the favicon's geometry: a 32-unit tile (rx 8), the 24-unit mark drawn at (4, 4), stroke 2.6
PULSE = [(3, 13), (6.5, 13), (9, 7), (13, 17), (15.5, 11), (21, 11)]


def draw(px: int) -> Image.Image:
    s = 8                                           # draw large, then scale down: smooth edges
    big = px * s
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    u = big / 32
    d.rounded_rectangle([0, 0, big - 1, big - 1], radius=8 * u, fill=TILE)
    w = max(2, round(2.6 * u))
    pts = [((x + 4) * u, (y + 4) * u) for x, y in PULSE]
    d.line(pts, fill=INK, width=w, joint="curve")
    r = w / 2
    for x, y in (pts[0], pts[-1]):                  # round caps
        d.ellipse([x - r, y - r, x + r, y + r], fill=INK)
    for x, y in pts[1:-1]:                          # round joins (Pillow's "curve" joint is thin at sharp turns)
        d.ellipse([x - r, y - r, x + r, y + r], fill=INK)
    return img.resize((px, px), Image.LANCZOS)


def main() -> None:
    images = [draw(px) for px in SIZES]
    images[-1].save(OUT, format="ICO", sizes=[(px, px) for px in SIZES], append_images=images[:-1])
    print("wrote", OUT)


if __name__ == "__main__":
    main()
