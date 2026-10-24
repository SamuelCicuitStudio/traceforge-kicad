"""Generate TraceForge action icons (PNG, 24 and 48 px, light and dark themes).

Drawn at 8x and downsampled for clean anti-aliasing. Run: python tools/make_icons.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "icons"
S = 8 * 48  # drawing canvas
THEMES = {
    "light": {"ink": (38, 50, 72), "accent": (230, 120, 20), "good": (20, 140, 70)},
    "dark": {"ink": (225, 232, 245), "accent": (255, 160, 60), "good": (80, 210, 120)},
}


def _w(px: float) -> int:
    return int(px * S / 48)


def monitor(d: ImageDraw.ImageDraw, c: dict) -> None:
    """Signal Timing Monitor: a digital waveform with a delta-t marker."""
    pts = [(4, 34), (12, 34), (12, 14), (24, 14), (24, 34), (32, 34), (32, 14), (44, 14)]
    d.line([(_w(x), _w(y)) for x, y in pts], fill=c["ink"], width=_w(4), joint="curve")
    d.line([(_w(12), _w(41)), (_w(24), _w(41))], fill=c["accent"], width=_w(3))
    for x in (12, 24):
        d.line([(_w(x), _w(37)), (_w(x), _w(45))], fill=c["accent"], width=_w(3))
    d.ellipse([_w(36), _w(3), _w(46), _w(13)], fill=c["good"])


def highlight(d: ImageDraw.ImageDraw, c: dict) -> None:
    """Highlight Signal Chain: two chain links joined through a series resistor."""
    d.rounded_rectangle([_w(2), _w(17), _w(18), _w(31)], radius=_w(7), outline=c["ink"],
                        width=_w(4))
    d.rounded_rectangle([_w(30), _w(17), _w(46), _w(31)], radius=_w(7), outline=c["ink"],
                        width=_w(4))
    d.rectangle([_w(18), _w(19), _w(30), _w(29)], fill=c["accent"])
    d.line([(_w(10), _w(24)), (_w(18), _w(24))], fill=c["ink"], width=_w(3))
    d.line([(_w(30), _w(24)), (_w(38), _w(24))], fill=c["ink"], width=_w(3))


def export(d: ImageDraw.ImageDraw, c: dict) -> None:
    """Export Signal Paths: a table with an outgoing arrow."""
    d.rounded_rectangle([_w(4), _w(6), _w(32), _w(42)], radius=_w(3), outline=c["ink"], width=_w(3))
    for y in (16, 24, 32):
        d.line([(_w(9), _w(y)), (_w(27), _w(y))], fill=c["ink"], width=_w(2))
    d.line([(_w(26), _w(24)), (_w(44), _w(24))], fill=c["accent"], width=_w(4))
    d.polygon([(_w(46), _w(24)), (_w(38), _w(17)), (_w(38), _w(31))], fill=c["accent"])


def traceforge(d: ImageDraw.ImageDraw, c: dict) -> None:
    """TraceForge: a 'T' drawn as a PCB trace with a 45-degree bend ending in a via."""
    d.line([(_w(5), _w(10)), (_w(43), _w(10))], fill=c["ink"], width=_w(6))
    d.line([(_w(24), _w(10)), (_w(24), _w(28)), (_w(32), _w(36))], fill=c["ink"], width=_w(6),
           joint="curve")
    d.ellipse([_w(29), _w(33), _w(45), _w(49) - _w(2)], fill=c["accent"])
    d.ellipse([_w(34), _w(38), _w(40), _w(44) - _w(2)], fill=(0, 0, 0, 0))
    d.ellipse([_w(2), _w(5), _w(10), _w(15)], fill=c["good"])


ICONS = {"traceforge": traceforge, "signal-timing-monitor": monitor,
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
