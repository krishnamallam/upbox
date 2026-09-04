"""Rasterise the upbox mark into packaging/upbox.ico.

The source of truth is the site favicon (a 32x32 SVG: cream rounded square,
dark "u", amber dot). No SVG rasteriser is assumed; the shapes are simple
enough to draw directly with Pillow at 32x supersampling and downscale.

    uv run --with pillow python packaging/make_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

SCALE = 32  # 32 px viewBox units -> 1024 px canvas
CREAM = (0xF4, 0xF0, 0xE7, 255)
INK = (0x22, 0x1F, 0x1B, 255)
AMBER = (0xF3, 0xA2, 0x3A, 255)
SIZES = (256, 128, 64, 48, 32, 24, 16)


def _px(value: float) -> float:
    return value * SCALE


def draw_mark() -> Image.Image:
    canvas = Image.new("RGBA", (32 * SCALE, 32 * SCALE), (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)
    # rect x=1 y=1 w=30 h=30 rx=7.5
    d.rounded_rectangle((_px(1), _px(1), _px(31), _px(31)), radius=_px(7.5), fill=CREAM)
    # path M10.5 11 V16.5 a5.5 5.5 0 0 0 11 0 V11, stroke 3.5, round caps
    w = _px(3.5)
    d.line((_px(10.5), _px(11), _px(10.5), _px(16.5)), fill=INK, width=int(w))
    d.line((_px(21.5), _px(11), _px(21.5), _px(16.5)), fill=INK, width=int(w))
    outer = 5.5 + 1.75
    d.arc(
        (_px(16 - outer), _px(16.5 - outer), _px(16 + outer), _px(16.5 + outer)),
        start=0,
        end=180,
        fill=INK,
        width=int(w),
    )
    for cx, cy in ((10.5, 11), (21.5, 11)):
        d.ellipse((_px(cx - 1.75), _px(cy - 1.75), _px(cx + 1.75), _px(cy + 1.75)), fill=INK)
    # circle cx=22.6 cy=8.4 r=4.1 fill amber, stroke cream width 2 (stroke covers r 3.1..5.1)
    d.ellipse((_px(22.6 - 5.1), _px(8.4 - 5.1), _px(22.6 + 5.1), _px(8.4 + 5.1)), fill=CREAM)
    d.ellipse((_px(22.6 - 3.1), _px(8.4 - 3.1), _px(22.6 + 3.1), _px(8.4 + 3.1)), fill=AMBER)
    return canvas


def main() -> None:
    master = draw_mark()
    frames = [master.resize((s, s), Image.LANCZOS) for s in SIZES]
    out = Path(__file__).with_name("upbox.ico")
    frames[0].save(
        out,
        format="ICO",
        sizes=[(s, s) for s in SIZES],
        append_images=frames[1:],
    )
    # Also keep a PNG preview next to it for humans and for the README.
    frames[0].save(Path(__file__).with_name("upbox-256.png"), format="PNG")
    print(f"wrote {out} ({out.stat().st_size} bytes) with sizes {SIZES}")


if __name__ == "__main__":
    main()
