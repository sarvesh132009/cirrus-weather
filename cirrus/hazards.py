"""Natural-hazard events from free public feeds, merged into one list: earthquakes (USGS), cyclones, floods,
volcanoes and wildfires (GDACS, the UN/EU disaster alert system) and NASA EONET.

Every event is a plain dict: id, kind, title, level (1 Advisory .. 4 Extreme), lat, lon, time (UTC ISO),
radius_km (how far from the centre it matters), detail, src, url, and mag for earthquakes.
A feed that fails is skipped, so one outage never takes the whole list down.
"""

from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from . import config, demo
from .openmeteo import UpstreamError, _http_json, memo

LEVEL_LABELS = {1: "Advisory", 2: "Watch", 3: "Warning", 4: "Extreme"}
KINDS = ("earthquake", "cyclone", "flood", "volcano", "wildfire", "storm", "landslide")


def km_between(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 12742 * math.asin(min(1.0, math.sqrt(a)))


def parse_time(value) -> datetime | None:
    """ISO text or epoch milliseconds -> aware UTC datetime (None if unreadable)."""
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value / 1000, UTC)
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except (ValueError, OverflowError, OSError):
        return None


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clip(text, n: int) -> str:
    return " ".join(str(text or "").split())[:n]


# ---- USGS earthquakes --------------------------------------------------------------------------------------------

def quake_radius(mag: float) -> int:
    return 1000 if mag >= 8 else 600 if mag >= 7 else 300 if mag >= 6 else 150 if mag >= 5 else 80


def parse_usgs(data: dict) -> list[dict]:
    out = []
    for f in data.get("features") or []:
        p = f.get("properties") or {}
        coords = (f.get("geometry") or {}).get("coordinates") or []
        mag, when = p.get("mag"), parse_time(p.get("time"))
        if mag is None or len(coords) < 2 or when is None:
            continue
        level = 4 if mag >= 7 else 3 if mag >= 6 else 2 if mag >= 5 else 1
        detail = f"Depth {coords[2]:.0f} km." if len(coords) > 2 and coords[2] is not None else ""
        if p.get("tsunami"):   # USGS flags large offshore events; it does not mean a tsunami exists
            level = max(level, 3) if mag >= 6.5 else level
            detail += " Offshore quake: follow official tsunami warnings."
        out.append({"id": f"usgs:{f.get('id')}", "kind": "earthquake", "title": _clip(f"M {mag:.1f} earthquake, {p.get('place') or 'unknown area'}", 120),
                    "level": level, "lat": round(coords[1], 3), "lon": round(coords[0], 3), "time": _iso(when), "mag": round(mag, 1),
                    "radius_km": quake_radius(mag), "detail": detail.strip(), "src": "USGS", "url": _clip(p.get("url"), 200)})
    return out


# ---- GDACS ----------------------------------------------------------------------------------------------------------

_GDACS_KIND = {"TC": "cyclone", "FL": "flood", "VO": "volcano", "WF": "wildfire"}
_GDACS_RADIUS = {"cyclone": 600, "flood": 150, "volcano": 100, "wildfire": 60}
_GDACS_LEVEL = {"red": 4, "orange": 3, "green": 1}


def parse_gdacs(data: dict, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(UTC)
    out = []
    for f in data.get("features") or []:
        p = f.get("properties") or {}
        coords = (f.get("geometry") or {}).get("coordinates") or []
        kind = _GDACS_KIND.get(str(p.get("eventtype") or "").upper())
        if not kind or len(coords) < 2:
            continue
        current = p.get("iscurrent") in (True, "true", "True", 1, "1")
        end = parse_time(p.get("todate")) or parse_time(p.get("datemodified"))
        if not current and (end is None or now - end > timedelta(days=2)):
            continue
        when = parse_time(p.get("datemodified")) or parse_time(p.get("fromdate")) or now
        sev = p.get("severitydata") or {}
        title = _clip(p.get("name") or f"{kind.title()} ({p.get('country') or 'unknown'})", 120)
        urls = p.get("url") if isinstance(p.get("url"), dict) else {}
        out.append({"id": f"gdacs:{p.get('eventtype')}:{p.get('eventid')}", "kind": kind, "title": title,
                    "level": _GDACS_LEVEL.get(str(p.get("alertlevel") or "").lower(), 1),
                    "lat": round(coords[1], 3), "lon": round(coords[0], 3), "time": _iso(when), "radius_km": _GDACS_RADIUS[kind],
                    "detail": _clip(sev.get("severitytext") or p.get("description"), 200), "src": "GDACS",
                    "url": _clip(urls.get("report") or urls.get("details"), 200)})
    return out


# ---- NASA EONET -----------------------------------------------------------------------------------------------------

_EONET_KIND = {"severeStorms": "cyclone", "volcanoes": "volcano", "floods": "flood", "landslides": "landslide", "wildfires": "wildfire"}
_EONET_RADIUS = {"cyclone": 500, "volcano": 100, "flood": 150, "landslide": 60, "wildfire": 60}


def parse_eonet(data: dict) -> list[dict]:
    out = []
    for e in data.get("events") or []:
        kinds = [_EONET_KIND[c.get("id")] for c in e.get("categories") or [] if c.get("id") in _EONET_KIND]
        points = [g for g in e.get("geometry") or [] if g.get("type") == "Point" and len(g.get("coordinates") or []) >= 2]
        if not kinds or not points:
            continue
        last, kind = points[-1], kinds[0]
        when = parse_time(last.get("date"))
        if when is None:
            continue
        level, detail = 1, ""
        if kind == "cyclone" and isinstance(last.get("magnitudeValue"), (int, float)):
            kt = last["magnitudeValue"]   # knots
            level = 4 if kt >= 96 else 3 if kt >= 64 else 2 if kt >= 34 else 1
            detail = f"Winds about {kt * 1.852:.0f} km/h."
        out.append({"id": f"eonet:{e.get('id')}", "kind": kind, "title": _clip(e.get("title"), 120), "level": level,
                    "lat": round(last["coordinates"][1], 3), "lon": round(last["coordinates"][0], 3), "time": _iso(when),
                    "radius_km": _EONET_RADIUS[kind], "detail": detail, "src": "NASA EONET",
                    "url": _clip(next((s.get("url") for s in e.get("sources") or [] if s.get("url")), e.get("link")), 200)})
    return out


# ---- the merged list ---------------------------------------------------------------------------------------------------

def _fetch_gdacs(now: datetime) -> list[dict]:
    params = {"eventlist": "TC;FL;VO;WF", "fromdate": (now - timedelta(days=10)).strftime("%Y-%m-%d"), "todate": now.strftime("%Y-%m-%d")}
    try:
        return parse_gdacs(_http_json(config.GDACS_URL, params, timeout=15), now)
    except UpstreamError:   # if the filter parameters are not accepted, ask for the default list and filter it ourselves
        return parse_gdacs(_http_json(config.GDACS_URL, {}, timeout=15), now)


def merge(usgs: list[dict], gdacs: list[dict], eonet: list[dict]) -> list[dict]:
    """GDACS is the better source for cyclones, floods and volcanoes, so a NASA event near one of the same kind is dropped."""
    keep = list(usgs) + list(gdacs)
    for e in sorted(eonet, key=lambda x: x["time"], reverse=True):
        if any(g["kind"] == e["kind"] and km_between(g["lat"], g["lon"], e["lat"], e["lon"]) < 300 for g in gdacs):
            continue
        keep.append(e)
    wild = [e for e in keep if e["kind"] == "wildfire"]
    if len(wild) > 40:   # fires are the most numerous event type; keep the newest so the list stays small
        drop = {e["id"] for e in sorted(wild, key=lambda x: x["time"], reverse=True)[40:]}
        keep = [e for e in keep if e["id"] not in drop]
    keep.sort(key=lambda e: (e["level"], e["time"]), reverse=True)
    return keep[:200]


def feed() -> dict:
    """{"events": [...], "updated": iso, "sources": {"usgs": "ok" | "error", ...}}. Cached for 10 minutes."""
    def go():
        if config.DEMO:
            return demo.hazards()
        now = datetime.now(UTC)
        jobs = {"usgs": lambda: parse_usgs(_http_json(config.USGS_URL, {})),
                "gdacs": lambda: _fetch_gdacs(now),
                "eonet": lambda: parse_eonet(_http_json(config.EONET_URL, {"status": "open", "days": 10, "limit": 150,
                                                                           "category": ",".join(_EONET_KIND)}, timeout=15))}
        status: dict[str, str] = {}

        def run(name: str) -> list[dict]:
            try:
                rows = jobs[name]()
                status[name] = "ok"
                return rows
            except (UpstreamError, KeyError, TypeError, ValueError, AttributeError):
                status[name] = "error"
                return []

        with ThreadPoolExecutor(max_workers=3) as pool:
            got = dict(zip(jobs, pool.map(run, jobs)))
        if all(v == "error" for v in status.values()):
            raise UpstreamError("The hazard feeds are unavailable right now.")
        return {"events": merge(got["usgs"], got["gdacs"], got["eonet"]), "updated": _iso(now), "sources": dict(sorted(status.items()))}

    return memo(("hazards",), config.TTL["hazards"], go)
