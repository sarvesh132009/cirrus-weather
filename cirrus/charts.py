"""Tiny server-side SVG charts. No JavaScript, no libraries."""

from __future__ import annotations

import math

W = 720  # internal chart width; the SVG scales to its container


def _fill_gaps(values: list) -> list[float]:
    out: list[float] = []
    last = next((v for v in values if v is not None), 0.0)
    for v in values:
        last = last if v is None else v
        out.append(float(last))
    return out


def line_chart(series: list[tuple[list, str]], *, h: int = 170, ymin: float | None = None, ymax: float | None = None,
               area: bool = True, aria: str = "Chart", marker: int | None = None) -> str:
    """series: [(values, css class)]. `marker` = index of a vertical 'now' line."""
    data = [(_fill_gaps(v), cls) for v, cls in series if v]
    if not data:
        return ""
    flat = [x for vals, _ in data for x in vals]
    lo = min(flat) if ymin is None else ymin
    hi = max(flat) if ymax is None else ymax
    if hi - lo < 1e-6:
        hi, lo = hi + 1, lo - 1
    pad = (hi - lo) * 0.12
    lo, hi = (lo if ymin is not None else lo - pad), (hi if ymax is not None else hi + pad)
    n = max(len(vals) for vals, _ in data)
    top, bottom = 8, h - 8

    def xy(i: int, v: float) -> str:
        x = i / max(1, n - 1) * W
        y = bottom - (v - lo) / (hi - lo) * (bottom - top)
        return f"{x:.1f},{y:.1f}"

    parts = [f'<svg class="chart" viewBox="0 0 {W} {h}" width="100%" height="{h}" preserveAspectRatio="none" role="img" aria-label="{aria}">']
    for k in range(4):
        y = top + (bottom - top) * k / 3
        parts.append(f'<line class="grid" x1="0" y1="{y:.1f}" x2="{W}" y2="{y:.1f}"/>')
    for idx, (vals, cls) in enumerate(data):
        pts = " ".join(xy(i, v) for i, v in enumerate(vals))
        if area and idx == 0:
            parts.append(f'<polygon class="area {cls}" points="{pts} {W},{h} 0,{h}"/>')
        parts.append(f'<polyline class="line {cls}" points="{pts}" vector-effect="non-scaling-stroke"/>')
    if marker is not None and 0 <= marker < n:
        x = marker / max(1, n - 1) * W
        parts.append(f'<line class="now" x1="{x:.1f}" y1="0" x2="{x:.1f}" y2="{h}" vector-effect="non-scaling-stroke"/>')
    parts.append("</svg>")
    return "".join(parts)


def bar_chart(values: list, *, h: int = 64, vmax: float | None = None, cls: str = "bar", aria: str = "Bar chart",
              classes: list[str] | None = None) -> str:
    vals = [0.0 if v is None else float(v) for v in values]
    if not vals:
        return ""
    top = vmax if vmax else max(max(vals), 1e-6)
    n = len(vals)
    bw = W / n
    parts = [f'<svg class="chart bars" viewBox="0 0 {W} {h}" width="100%" height="{h}" preserveAspectRatio="none" role="img" aria-label="{aria}">']
    for i, v in enumerate(vals):
        bh = max(1.5, min(1, v / top) * (h - 2)) if v > 0 else 1.5
        c = classes[i] if classes else cls
        parts.append(f'<rect class="{c}" x="{i * bw + bw * 0.12:.1f}" y="{h - bh:.1f}" width="{bw * 0.76:.1f}" height="{bh:.1f}" rx="2"/>')
    parts.append("</svg>")
    return "".join(parts)


def wind_dial(from_deg: float | None, label: str) -> str:
    """Compass dial; the arrow points where the wind is blowing TO."""
    to = ((from_deg or 0) + 180) % 360
    arrow = f'<g transform="rotate({to:.0f} 60 60)"><path class="arrow" d="M60 22 L68 44 L60 39 L52 44 Z"/><line class="arrow-tail" x1="60" y1="40" x2="60" y2="92"/></g>' if from_deg is not None else ""
    return (f'<svg class="dial" viewBox="0 0 120 120" role="img" aria-label="{label}">'
            '<circle class="ring" cx="60" cy="60" r="52"/>'
            '<text x="60" y="15" text-anchor="middle">N</text><text x="107" y="64" text-anchor="middle">E</text>'
            '<text x="60" y="114" text-anchor="middle">S</text><text x="13" y="64" text-anchor="middle">W</text>'
            f'{arrow}</svg>')


def sun_arc(fraction: float | None) -> str:
    """Half-circle sun path. `fraction` 0..1 = sunrise..sunset; None/out of range hides the sun."""
    dot = ""
    if fraction is not None and 0 <= fraction <= 1:
        a = math.pi * fraction
        x, y = 110 - 95 * math.cos(a), 105 - 95 * math.sin(a)
        dot = f'<circle class="sun-dot" cx="{x:.1f}" cy="{y:.1f}" r="9"/>'
    return ('<svg class="sunarc" viewBox="0 0 220 120" role="img" aria-label="Sun position today">'
            '<path class="path" d="M15 105 A95 95 0 0 1 205 105"/><line class="horizon" x1="0" y1="105" x2="220" y2="105"/>'
            f'{dot}</svg>')


def moon_svg(fraction: float) -> str:
    """Moon disc with the lit part drawn as one path (northern-hemisphere orientation)."""
    r, c = 22, 26
    k = math.cos(2 * math.pi * fraction)  # +1 new ... -1 full
    waxing = fraction < 0.5
    limb = 1 if waxing else 0
    term = (0 if k > 0 else 1) if waxing else (1 if k > 0 else 0)
    lit = f'M{c} {c - r} A{r} {r} 0 0 {limb} {c} {c + r} A{abs(k) * r:.2f} {r} 0 0 {term} {c} {c - r} Z'
    return (f'<svg class="moon" viewBox="0 0 52 52" role="img" aria-label="Moon phase">'
            f'<circle class="dark" cx="{c}" cy="{c}" r="{r}"/><path class="lit" d="{lit}"/></svg>')


def range_bar(lo: float, hi: float, gmin: float, gmax: float) -> str:
    span = max(gmax - gmin, 1e-6)
    left = (lo - gmin) / span * 100
    width = max(4.0, (hi - lo) / span * 100)
    return f'<span class="range"><span class="range-fill" style="left:{left:.1f}%;width:{width:.1f}%"></span></span>'
