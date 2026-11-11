"""Inline stroke icons (24x24 grid)."""

from __future__ import annotations

_CLOUD = "M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z"
_RAIN_BASE = "M4 14.899A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 2.5 8.242"

PATHS = {
    "sun": "M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0z M12 2v2 M12 20v2 M4.93 4.93l1.41 1.41 M17.66 17.66l1.41 1.41 M2 12h2 M20 12h2 M6.34 17.66l-1.41 1.41 M19.07 4.93l-1.41 1.41",
    "moon": "M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z",
    "cloud": _CLOUD,
    "partly": "M12 2v2 M4.93 4.93l1.41 1.41 M20 12h2 M19.07 4.93l-1.41 1.41 M15.947 12.65a4 4 0 0 0-5.925-4.128 M13 22H7a5 5 0 1 1 4.9-6H13a3 3 0 0 1 0 6Z",
    "cloudmoon": "M13 16a3 3 0 1 1 0 6H7a5 5 0 1 1 4.9-6Z M10.1 9A6 6 0 0 1 16 4a4.24 4.24 0 0 0 6 6 6 6 0 0 1-3 5.197",
    "rain": _RAIN_BASE + " M16 14v6 M8 14v6 M12 16v6",
    "drizzle": _RAIN_BASE + " M8 19v1 M8 14v1 M16 19v1 M16 14v1 M12 21v1 M12 16v1",
    "snow": _RAIN_BASE + " M8 15h.01 M8 19h.01 M12 17h.01 M12 21h.01 M16 15h.01 M16 19h.01",
    "storm": "M6 16.326A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 .5 8.973 M13 12l-3 5h4l-3 5",
    "fog": _RAIN_BASE + " M16 17H7 M17 21H9",
    "wind": "M17.7 7.7a2.5 2.5 0 1 1 1.8 4.3H2 M9.6 4.6A2 2 0 1 1 11 8H2 M12.6 19.4A2 2 0 1 0 14 16H2",
    "drop": "M12 22a7 7 0 0 0 7-7c0-2-1-3.9-3-5.5s-3.5-4-4-6.5c-.5 2.5-2 4.9-4 6.5C6 11.1 5 13 5 15a7 7 0 0 0 7 7z",
    "gauge": "M12 14l4-4 M3.34 19a10 10 0 1 1 17.32 0",
    "eye": "M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
    "search": "M21 21l-4.3-4.3 M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16z",
    "thermo": "M14 4v10.54a4 4 0 1 1-4 0V4a2 2 0 0 1 4 0Z",
    "layers": "M12 2 2 7l10 5 10-5-10-5z M2 17l10 5 10-5 M2 12l10 5 10-5",
    "plus": "M12 5v14 M5 12h14",
    "minus": "M5 12h14",
    "expand": "M8 3H5a2 2 0 0 0-2 2v3 M21 8V5a2 2 0 0 0-2-2h-3 M3 16v3a2 2 0 0 0 2 2h3 M16 21h3a2 2 0 0 0 2-2v-3",
    "close": "M18 6 6 18 M6 6l12 12",
    "play": "M8 5v14l11-7z",
    "pause": "M6 5h4v14H6z M14 5h4v14h-4z",
    "bell": "M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9 M10.3 21a1.94 1.94 0 0 0 3.4 0",
    "home": "M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z",
    "alert": "M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z M12 9v4 M12 17h.01",
    "locate": "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z M12 2v3 M12 19v3 M2 12h3 M19 12h3",
    "pin": "M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z M12 13a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
}


def svg(kind: str, size: int = 24, cls: str = "", label: str | None = None, fill: bool = False) -> str:
    """Return an inline <svg>. Decorative unless `label` is given."""
    path = PATHS.get(kind, PATHS["cloud"])
    a11y = f'role="img" aria-label="{label}"' if label else 'aria-hidden="true"'
    paint = 'fill="currentColor" stroke="none"' if fill else 'fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"'
    return (f'<svg class="ic ic-{kind} {cls}" viewBox="0 0 24 24" width="{size}" height="{size}" {paint} {a11y}>'
            f'<path d="{path}"/></svg>')
