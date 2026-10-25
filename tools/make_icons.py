"""Generate TraceForge action icons (PNG, 24 and 48 px, light and dark themes).

All icons share one style: a rounded badge so they read on KiCad's light and dark toolbars, a white
trace, an amber series part / accent and a green timing mark. Drawn at 8x and downsampled with
LANCZOS for clean anti-aliasing. Run: python tools/make_icons.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "icons"
S = 8 * 48
THEMES = {  # badge colour per KiCad theme; foreground colours are shared
    "light": {"badge": (33, 52, 92), "trace": (255, 255, 255), "accent": (255, 170, 40),
              "timing": (110, 220, 160)},
    "dark": {"badge": (44, 66, 110), "trace": (255, 255, 255), "accent": (255, 178, 60),
             "timing": (120, 230, 170)},
}


def _w(px: float) -> int:
    return int(px * S / 48)


def _badge(d: ImageDraw.ImageDraw, c: dict) -> None:
    d.rounded_rectangle([_w(1), _w(1), _w(47), _w(47)], radius=_w(10), fill=c["badge"])


def traceforge(d: ImageDraw.ImageDraw, c: dict) -> None:
    """A circuit chip with a lightning-shaped signal trace; legible at toolbar size."""
    _badge(d, c)
    # Chip body, fine rim and symmetric contacts.
    d.rounded_rectangle([_w(10), _w(10), _w(38), _w(38)], radius=_w(6),
                        fill=(18, 30, 50), outline=(88, 137, 183), width=_w(1))
    for pos in (17, 24, 31):
        for x1, y1, x2, y2 in ((5, pos, 10, pos), (38, pos, 43, pos),
                                 (pos, 5, pos, 10), (pos, 38, pos, 43)):
            d.line([(_w(x1), _w(y1)), (_w(x2), _w(y2))], fill=c["timing"], width=_w(2))
    # Amber energy mark forms the central routed signal.
    pts = [(26, 13), (17, 25), (23, 25), (21, 35), (32, 21), (26, 21)]
    d.polygon([(_w(x), _w(y)) for x, y in pts], fill=c["accent"])
    d.ellipse([_w(13), _w(13), _w(16), _w(16)], fill=c["trace"])


def highlight(d: ImageDraw.ImageDraw, c: dict) -> None:
    """Highlight Signal Chain: the same path as the TraceForge icon, highlighted end to end."""
    _badge(d, c)
    d.rounded_rectangle([_w(3), _w(19), _w(45), _w(39)], radius=_w(6), outline=c["timing"],
                        width=_w(3))
    d.line([(_w(8), _w(29)), (_w(16), _w(29))], fill=c["trace"], width=_w(4))
    d.line([(_w(32), _w(29)), (_w(40), _w(29))], fill=c["trace"], width=_w(4))
    d.rounded_rectangle([_w(16), _w(24), _w(32), _w(34)], radius=_w(2), fill=c["accent"])
    d.ellipse([_w(19), _w(6), _w(29), _w(16)], fill=c["timing"])


def export(d: ImageDraw.ImageDraw, c: dict) -> None:
    """Export Signal Paths: a table with an outgoing arrow."""
    _badge(d, c)
    d.rounded_rectangle([_w(7), _w(8), _w(29), _w(40)], radius=_w(3), outline=c["trace"],
                        width=_w(3))
    for y in (17, 24, 31):
        d.line([(_w(11), _w(y)), (_w(25), _w(y))], fill=c["trace"], width=_w(2))
    d.line([(_w(25), _w(24)), (_w(40), _w(24))], fill=c["accent"], width=_w(4))
    d.polygon([(_w(43), _w(24)), (_w(35), _w(17)), (_w(35), _w(31))], fill=c["accent"])


ICONS = {"traceforge": traceforge,
         "highlight-signal-chain": highlight, "export-signal-paths": export}


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for name, draw in ICONS.items():
        for theme, colors in THEMES.items():
            img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
            draw(ImageDraw.Draw(img), colors)
            for px in (24, 48):
                img.resize((px, px), Image.LANCZOS).save(OUT / f"{name}-{theme}-{px}.png")
    print(f"wrote {len(ICONS) * len(THEMES) * 2} icons to {OUT}")


if __name__ == "__main__":
    main()
