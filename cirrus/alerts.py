"""Turn a forecast and the hazard feed into alerts for one place.

These are Cirrus's own rules, applied to model forecasts and public hazard feeds. They are an early nudge, NOT an
official warning: every alert tells people to follow their national weather and disaster authority.

An alert is a dict: id, level (1 Advisory, 2 Watch, 3 Warning, 4 Extreme), label, kind, title, detail, advice, when,
source, and (for hazard events) dist_km. The id stays the same while the same situation lasts, so a device or an
e-mail is sent once, and again only if the level goes up.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from .derive import fmt_dow, fmt_hour
from .hazards import LEVEL_LABELS, km_between, parse_time
from .model import Weather

DISCLAIMER = "Early warning from forecast models and public feeds, not an official alert. Follow your local authorities."

# thresholds for levels 1..4, ascending
HEAT = (39, 42, 46, 52)               # feels-like, °C (US heat-index danger bands)
COLD = (10, 20, 30, 40)               # feels-like below -x °C
RAIN_DAY = (35, 64.5, 115.6, 204.5)   # mm in 24 h (the last three are India's heavy / very heavy / extremely heavy classes)
RAIN_HOUR = (15, 25, 40, 60)          # mm in one hour
GUST = (62, 75, 89, 118)              # km/h: gale, strong gale, storm, hurricane force (Beaufort 8, 9, 10, 12)

ADVICE = {
    "heat": "Stay in the shade or indoors in the afternoon, drink water often, and check on older people and children.",
    "cold": "Dress in layers, limit time outside, and check on people who live alone.",
    "rain": "Avoid low-lying roads and underpasses, never drive through flood water, and keep a charged phone and torch ready.",
    "wind": "Secure loose objects, stay away from trees, hoardings and power lines, and avoid the coast and open water.",
    "storm": "Move indoors when thunder is heard, stay away from trees and open ground, and unplug sensitive equipment.",
    "snow": "Avoid unnecessary travel, keep warm, and carry water and a charged phone if you must go out.",
    "fog": "Drive slowly with low-beam lights and leave extra distance.",
    "air": "Limit outdoor exercise, keep windows closed, and wear a well-fitted N95 or FFP2 mask outside.",
    "earthquake": "If you feel shaking: drop, cover and hold on. Expect aftershocks and stay away from damaged buildings.",
    "cyclone": "Follow instructions from local authorities, secure your home, stock water and food, and keep away from the coast.",
    "flood": "Move to higher ground if told to, avoid flood water, and keep documents and phone chargers dry.",
    "volcano": "Follow local authorities, avoid ash, and wear a mask and goggles if ash is falling.",
    "wildfire": "Be ready to leave if told to, keep windows closed, and avoid smoke.",
    "landslide": "Stay away from steep slopes and river valleys during heavy rain and follow local warnings.",
    "storm_event": "Follow local weather warnings and stay indoors if conditions worsen.",
}


def _steps(value: float | None, steps: tuple[float, ...]) -> int:
    return 0 if value is None else sum(1 for s in steps if value >= s)


def _alert(aid: str, level: int, kind: str, title: str, detail: str, when: str, source: str, advice_key: str | None = None, **extra) -> dict:
    return {"id": aid, "level": level, "label": LEVEL_LABELS[level], "kind": kind, "title": title, "detail": detail,
            "advice": ADVICE.get(advice_key or kind, ""), "when": when, "source": source, **extra}


def _window(wx: Weather, idxs: list[int], levels: list[int]) -> tuple[str, str]:
    """('Now – Tue 6 PM', 'Tue 3 PM') for the hours where a rule fired, and the hour it peaks."""
    hit = [k for k, lv in enumerate(levels) if lv > 0]
    first, last = idxs[hit[0]], idxs[hit[-1]]
    peak = idxs[max(hit, key=lambda k: levels[k])]
    times = wx.h["time"]
    end = min(last + 1, len(times) - 1)   # the affected hour ends at the start of the next one
    a = "Now" if first <= wx.now_i else f"{fmt_dow(times[first])} {fmt_hour(times[first])}"
    b = f"{fmt_dow(times[end])} {fmt_hour(times[end])}"
    return f"{a} – {b}", f"{fmt_dow(times[peak])} {fmt_hour(times[peak])}"


def from_forecast(wx: Weather, aq: dict | None = None, hours: int = 48) -> list[dict]:
    """Alerts for the next `hours` hours at the forecast's own location."""
    r = list(wx.hour_range(hours))
    if not r:
        return []
    u, out = wx.u, []
    hv = lambda name: [wx.hv(name, i) for i in r]  # noqa: E731
    day_of = lambda i: wx.h["time"][i][:10]  # noqa: E731

    def peak_of(vals: list, levels: list[int]) -> int:
        return max(range(len(levels)), key=lambda k: (levels[k], vals[k] if vals[k] is not None else -1e9))

    # heat and cold (feels-like)
    app = hv("apparent_temperature")
    for kind, vals, steps, titles in (
        ("heat", app, HEAT, ("Very hot conditions", "Dangerous heat", "Extreme heat: heatstroke risk", "Life-threatening heat")),
        ("cold", [None if v is None else -v for v in app], COLD, ("Very cold conditions", "Dangerous cold", "Extreme cold: frostbite risk", "Life-threatening cold")),
    ):
        levels = [_steps(v, steps) for v in vals]
        if max(levels, default=0):
            k = peak_of(vals, levels)
            lv, shown = levels[k], app[k]
            when, peak = _window(wx, r, levels)
            out.append(_alert(f"fx:{kind}:{lv}:{day_of(r[k])}", lv, kind, titles[lv - 1],
                              f"Feels like {u.temp(shown)} around {peak}.", when, "Forecast"))

    # heavy rain: rolling 24 h totals and hourly rates
    rain = [wx.hv("precipitation", i, 0) or 0 for i in range(r[0], min(len(wx.h["time"]), r[-1] + 24))]
    roll = [sum(rain[k:k + 24]) for k in range(len(r))]
    lv_day, lv_hour = [_steps(v, RAIN_DAY) for v in roll], [_steps(rain[k], RAIN_HOUR) for k in range(len(r))]
    levels = [max(a, b) for a, b in zip(lv_day, lv_hour)]
    if max(levels, default=0):
        k = peak_of(roll, levels)
        lv = levels[k]
        when, peak = _window(wx, r, levels)
        titles = ("Heavy rain expected", "Heavy rain: local flooding possible", "Very heavy rain: flood risk", "Extreme rainfall: severe flooding possible")
        rate = max(rain[: len(r)])
        out.append(_alert(f"fx:rain:{lv}:{day_of(r[k])}", lv, "rain", titles[lv - 1],
                          f"About {u.precip(roll[k])} in 24 hours, up to {u.precip(rate)} in an hour, peaking around {peak}.", when, "Forecast"))

    # strong wind gusts
    gust = hv("wind_gusts_10m")
    levels = [_steps(v, GUST) for v in gust]
    if max(levels, default=0):
        k = peak_of(gust, levels)
        lv = levels[k]
        when, peak = _window(wx, r, levels)
        titles = ("Gale-force gusts", "Strong gale gusts", "Storm-force winds", "Hurricane-force winds")
        out.append(_alert(f"fx:wind:{lv}:{day_of(r[k])}", lv, "wind", titles[lv - 1], f"Gusts up to {u.speed(gust[k])} around {peak}.", when, "Forecast"))

    # thunderstorms in the next 24 h
    codes, cape, precip = hv("weather_code"), hv("cape"), hv("precipitation")
    levels = []
    for k in range(len(r)):
        c = codes[k]
        lv = 3 if c in (96, 99) else 2 if c == 95 else 0
        if not lv and (cape[k] or 0) >= 2500 and (precip[k] or 0) >= 1:
            lv = 2
        levels.append(lv if k < 24 else 0)
    if max(levels, default=0):
        k = max(range(len(levels)), key=lambda j: (levels[j], cape[j] or 0))
        lv = levels[k]
        when, peak = _window(wx, r, levels)
        hail = lv == 3
        out.append(_alert(f"fx:storm:{lv}:{day_of(r[k])}", lv, "storm", "Severe thunderstorms with hail" if hail else "Thunderstorms likely",
                          f"Lightning and heavy downpours around {peak}." + (" Hail is possible." if hail else ""), when, "Forecast"))

    # snow and freezing rain
    levels = [3 if c in (56, 57, 66, 67) else 2 if c in (75, 86) else 1 if c in (71, 73, 77, 85) else 0 for c in codes]
    if max(levels, default=0):
        k = max(range(len(levels)), key=lambda j: levels[j])
        lv = levels[k]
        when, peak = _window(wx, r, levels)
        title = ("Snow expected", "Heavy snow", "Freezing rain: icy roads")[lv - 1]
        out.append(_alert(f"fx:snow:{lv}:{day_of(r[k])}", lv, "snow", title, f"Around {peak}.", when, "Forecast"))

    # dense fog
    vis = hv("visibility")
    levels = [1 if v is not None and v < 200 else 0 for v in vis]
    if max(levels, default=0):
        k = levels.index(1)
        when, _ = _window(wx, r, levels)
        out.append(_alert(f"fx:fog:1:{day_of(r[k])}", 1, "fog", "Dense fog", "Visibility under 200 m.", when, "Forecast"))

    # air quality right now
    aqi = ((aq or {}).get("current") or {}).get("us_aqi")
    lv = 3 if aqi is not None and aqi >= 301 else 2 if aqi is not None and aqi >= 201 else 1 if aqi is not None and aqi >= 151 else 0
    if lv:
        out.append(_alert(f"fx:air:{lv}:{wx.cur['time'][:10]}", lv, "air", ("Unhealthy air", "Very unhealthy air", "Hazardous air")[lv - 1],
                          f"US AQI is {aqi:.0f}.", "Now", "Air-quality model"))
    return out


def from_hazards(lat: float, lon: float, events: list[dict], units=None, now: datetime | None = None) -> list[dict]:
    """Earthquakes, cyclones, floods, volcanoes and wildfires close enough to matter at this point."""
    now = now or datetime.now(UTC)
    out = []
    for e in events:
        dist = km_between(lat, lon, e["lat"], e["lon"])
        if dist > e["radius_km"]:
            continue
        when = parse_time(e.get("time"))
        max_age = timedelta(hours=36) if e["kind"] == "earthquake" else timedelta(days=6)
        if when is None or now - when > max_age:
            continue
        level = e["level"]
        if level >= 3 and dist > e["radius_km"] * 0.5:   # on the outer edge of its reach the effect is milder
            level -= 1
        hours = (now - when).total_seconds() / 3600
        ago = f"{hours:.0f} h ago" if hours >= 1.5 else "just now" if hours < 0.5 else "1 h ago"
        away = units.dist(dist) if units else f"{dist:.0f} km"
        detail = " ".join(x for x in (f"About {away} away.", e.get("detail", "")) if x)
        out.append(_alert(f"hz:{e['id']}:{level}", level, e["kind"], e["title"], detail, ago.capitalize(), e.get("src", ""),
                          dist_km=round(dist), url=e.get("url", ""), lat=e["lat"], lon=e["lon"]))
    return out


def for_place(lat: float, lon: float, wx: Weather | None, events: list[dict], aq: dict | None = None, units=None,
              now: datetime | None = None) -> list[dict]:
    found = (from_forecast(wx, aq) if wx else []) + from_hazards(lat, lon, events, units or (wx.u if wx else None), now)
    found.sort(key=lambda a: (-a["level"], a["kind"]))
    return found


def top_level(alerts: list[dict]) -> int:
    return max((a["level"] for a in alerts), default=0)
