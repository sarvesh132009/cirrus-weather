"""HTML pages. Plain f-strings; every dynamic value goes through esc()."""

from __future__ import annotations

import hashlib
import html
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlencode

from . import charts, config, icons
from .derive import (Units, beaufort, cape_label, compass, dew_comfort, eu_aqi_category, fmt_clock, fmt_date,
                     fmt_dow, fmt_duration, fmt_hour, moon, pressure_trend, us_aqi_category, uv_category,
                     visibility_label)
from .model import Weather


def esc(value) -> str:
    return html.escape(str(value), quote=True)


@dataclass(slots=True)
class Place:
    lat: float
    lon: float
    name: str
    region: str = ""
    country: str = ""

    @property
    def subtitle(self) -> str:
        return ", ".join(x for x in (self.region, self.country) if x)


PAGES = (("overview", "Overview"), ("hourly", "Hourly"), ("daily", "14-day"), ("map", "Map"),
         ("details", "Details"), ("air", "Air & sun"))

MAP_LAYERS = (("wind", "Wind"), ("radar", "Rain radar"), ("temp", "Temperature"), ("rain", "Rain forecast"),
              ("clouds", "Clouds"), ("pressure", "Pressure"), ("humidity", "Humidity"))


def place_query(place: Place, units: Units, **extra) -> str:
    q = {"lat": f"{place.lat:.4f}", "lon": f"{place.lon:.4f}", "name": place.name}
    if place.region:
        q["region"] = place.region
    if place.country:
        q["country"] = place.country
    if units.imperial:
        q["u"] = "f"
    q.update(extra)
    return urlencode(q)


def page_url(page: str, place: Place, units: Units, **extra) -> str:
    return f"/forecast/{page}?{place_query(place, units, **extra)}"


# ---- layout ------------------------------------------------------------------------------------

_ASSET_HASHES: dict[str, tuple[int, str]] = {}


def asset(name: str) -> str:
    """Address of a static file with a short content hash (/static/map.js?v=ab12cd34ef).
    The address changes whenever the file does, so browsers and the CDN can keep the old one for a year."""
    path = config.STATIC_DIR / name
    try:
        mtime = path.stat().st_mtime_ns
        cached = _ASSET_HASHES.get(name)
        if cached is None or cached[0] != mtime:
            cached = (mtime, hashlib.sha1(path.read_bytes()).hexdigest()[:10])
            _ASSET_HASHES[name] = cached
        return f"/static/{name}?v={cached[1]}"
    except OSError:
        return f"/static/{name}"


_FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
          '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@500;700&display=swap">')
_FAVICON = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23FFB547' "
            "stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z'/%3E%3C/svg%3E")


def layout(title: str, body: str, *, place: Place | None = None, units: Units = Units(), page: str = "",
           scripts: tuple[str, ...] = ()) -> str:
    unit_toggle = nav = ""
    if place:
        links = []
        for label, imp in (("°C", False), ("°F", True)):
            current = ' aria-current="true"' if imp == units.imperial else ""
            links.append(f'<a class="seg-btn" href="{esc(page_url(page or "overview", place, Units(imp)))}"{current}>{label}</a>')
        unit_toggle = f'<div class="seg" role="group" aria-label="Units">{"".join(links)}</div>'
        tabs = []
        for key, label in PAGES:
            current = ' aria-current="page"' if key == page else ""
            tabs.append(f'<a class="tab" href="{esc(page_url(key, place, units))}"{current}>{label}</a>')
        nav = f'<nav class="tabs" aria-label="Pages">{"".join(tabs)}</nav>'
    hidden_u = '<input type="hidden" name="u" value="f">' if units.imperial else ""
    script_tags = "".join(f'<script src="{asset(s)}" defer></script>' for s in scripts)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title><meta name="color-scheme" content="dark">
<link rel="icon" href="{_FAVICON}">{_FONTS}<link rel="stylesheet" href="{asset("style.css")}"></head>
<body>
<header class="top">
  <a class="brand" href="/">{icons.svg("cloud", 26)}<span>Cirrus</span></a>
  <form class="search" action="/search" method="get" role="search">
    {icons.svg("search", 18)}<label class="sr" for="q">Search city or town</label>
    <input id="q" name="q" type="search" placeholder="Search city or town" autocomplete="off" required minlength="2">{hidden_u}
  </form>
  {unit_toggle}
</header>
{nav}
<main>{body}</main>
<footer class="foot">Forecast &amp; air quality: <a href="https://open-meteo.com/">Open-Meteo.com</a> (CC BY 4.0) ·
Radar: <a href="https://www.rainviewer.com/">RainViewer</a> · Map © <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors</footer>
{script_tags}
</body></html>"""


def panel(title: str, body: str, cls: str = "", sub: str = "") -> str:
    sub_html = f'<p class="sub">{esc(sub)}</p>' if sub else ""
    return f'<section class="panel {cls}"><h2>{esc(title)}</h2>{sub_html}{body}</section>'


def kv(label: str, value: str) -> str:
    return f'<div class="kv"><span>{esc(label)}</span><strong>{esc(value)}</strong></div>'


def x_labels(times: list[str], count: int = 6) -> str:
    if not times:
        return ""
    idx = sorted({round(i * (len(times) - 1) / (count - 1)) for i in range(count)})
    return '<div class="xlabels">' + "".join(f"<span>{esc(fmt_dow(times[i]))} {esc(fmt_hour(times[i]))}</span>" for i in idx) + "</div>"


# ---- home / search / error ---------------------------------------------------------------------

def home(units: Units, popular: list[Place]) -> str:
    cities = "".join(f'<a class="city" href="{esc(page_url("overview", p, units))}"><strong>{esc(p.name)}</strong>'
                     f'<span>{esc(p.subtitle)}</span></a>' for p in popular)
    body = f"""<section class="hero"><h1>Weather, with the map in front.</h1>
<p>Search any city or town for the forecast, radar, wind and more. No account, no API keys.</p>
<div class="hero-actions"><button class="btn primary" id="locate" type="button">{icons.svg("pin", 18)} Use my location</button>
<span id="locate-msg" class="muted" role="status"></span></div>
<h2 class="small">Popular places</h2><div class="cities">{cities}</div></section>"""
    return layout("Cirrus weather", body, units=units, scripts=("home.js",))


def search_results(query: str, results: list[dict], units: Units) -> str:
    items = []
    for r in results:
        p = Place(r["lat"], r["lon"], r["name"], r.get("admin1", ""), r.get("country", ""))
        items.append(f'<a class="city" href="{esc(page_url("overview", p, units))}"><strong>{esc(p.name)}</strong>'
                     f'<span>{esc(p.subtitle)} · {p.lat:.2f}, {p.lon:.2f}</span></a>')
    inner = f'<div class="cities">{"".join(items)}</div>' if items else '<p class="muted">No places found. Try another spelling.</p>'
    return layout(f"Search: {query}", f'<section class="hero"><h1 class="small-h">Results for “{esc(query)}”</h1>{inner}</section>', units=units)


def error_page(title: str, message: str, units: Units = Units(), place: Place | None = None, page: str = "") -> str:
    return layout(title, f'<section class="hero"><h1 class="small-h">{esc(title)}</h1><p class="muted">{esc(message)}</p>'
                         f'<p><a class="btn" href="/">Back to search</a></p></section>', place=place, units=units, page=page)


# ---- overview ----------------------------------------------------------------------------------

def _hour_strip(wx: Weather, n: int = 10) -> str:
    cells = []
    for k, i in enumerate(wx.hour_range(n)):
        label, kind = wx.condition(i)
        pop = wx.hv("precipitation_probability", i, 0) or 0
        t = "Now" if k == 0 else fmt_hour(wx.h["time"][i])
        cells.append(f'<div class="hcell"><span class="muted">{t}</span>{icons.svg(kind, 24, label=label)}'
                     f'<strong class="mono">{wx.u.temp(wx.hv("temperature_2m", i))}</strong>'
                     f'<span class="pbar"><span style="height:{pop * 0.44:.0f}px"></span></span><span class="pop">{pop}%</span></div>')
    return f'<div class="hstrip">{"".join(cells)}</div>'


def _week_rows(wx: Weather, count: int = 7) -> str:
    days = list(range(wx.today_i, min(len(wx.d["time"]), wx.today_i + count)))
    highs = [wx.dv("temperature_2m_max", i, 0) for i in days]
    lows = [wx.dv("temperature_2m_min", i, 0) for i in days]
    gmin, gmax = min(lows), max(highs)
    rows = []
    for n, i in enumerate(days):
        label, kind = wx.day_condition(i)
        pop = wx.dv("precipitation_probability_max", i, 0) or 0
        rows.append(f'<div class="drow"><span class="dname">{"Today" if n == 0 else fmt_dow(wx.d["time"][i])}</span>'
                    f'{icons.svg(kind, 22, label=label)}<span class="pop">{pop}%</span>'
                    f'<span class="mono lo">{wx.u.temp(lows[n])}</span>{charts.range_bar(lows[n], highs[n], gmin, gmax)}'
                    f'<strong class="mono hi">{wx.u.temp(highs[n])}</strong></div>')
    return "".join(rows)


def overview(place: Place, units: Units, wx: Weather) -> str:
    u, cur = wx.u, wx.cur
    label, kind = wx.condition()
    dt = wx.local_now
    uv = wx.hv("uv_index")
    chips = "".join(f'<div class="chip-stat"><span>{esc(a)}</span><strong class="mono">{esc(b)}</strong></div>' for a, b in (
        ("Wind", f"{u.speed(cur.get('wind_speed_10m'))} {compass(cur.get('wind_direction_10m'))}"),
        ("Humidity", f"{cur.get('relative_humidity_2m', 0):.0f}%"),
        ("UV", "–" if uv is None else f"{uv:.0f} {uv_category(uv)}"),
        ("Pressure", f"{u.pressure(cur.get('pressure_msl'))}")))
    now = f"""<section class="panel now">
<div class="muted">{esc(place.name)}{', ' + esc(place.subtitle) if place.subtitle else ''} · {dt:%a} {dt.day} {dt:%b}</div>
<div class="now-main"><div class="temp mono">{u.temp(cur.get('temperature_2m'))}</div>{icons.svg(kind, 72, 'big', label)}</div>
<div class="cond">{esc(label)}</div>
<div class="muted">Feels like {u.temp(cur.get('apparent_temperature'))} · High {u.temp(wx.dv('temperature_2m_max'))} · Low {u.temp(wx.dv('temperature_2m_min'))}</div>
<p class="summary">{esc(wx.summary())}</p><div class="chips">{chips}</div></section>"""
    hourly = panel("Hourly", _hour_strip(wx), "tight")
    week = panel("Next 7 days", _week_rows(wx), "tight")
    return f'<div class="split"><div class="col-data">{now}{hourly}{week}</div>{map_panel(place, units, wx)}</div>'


# ---- map panel (shared by overview + map page) -------------------------------------------------

def map_panel(place: Place, units: Units, wx: Weather | None, tall: bool = False, layer: str = "wind") -> str:
    chips = "".join(f'<button class="chip" type="button" data-layer="{k}" aria-pressed="false">{esc(v)}</button>' for k, v in MAP_LAYERS)
    data = {"lat": f"{place.lat:.4f}", "lon": f"{place.lon:.4f}", "name": place.name, "tz": wx.tz if wx else "UTC",
            "imperial": "1" if units.imperial else "0", "layer": layer}
    attrs = " ".join(f'data-{k}="{esc(v)}"' for k, v in data.items())
    return f"""<section class="map-card{' tall' if tall else ''}" id="mapcard" {attrs} aria-label="Weather map">
<div class="map-toolbar"><div class="chips-row" role="group" aria-label="Map layers">{chips}</div>
<div class="map-tools"><label class="opacity"><span>Overlay</span><input type="range" min="30" max="100" value="85" class="opacity-range" aria-label="Overlay opacity"></label>
<button class="ctl" type="button" id="btn-base" aria-label="Switch basemap between dark and light" title="Basemap">{icons.svg("layers", 18)}</button>
<button class="ctl" type="button" id="btn-full" aria-label="Toggle full screen map" title="Full screen">{icons.svg("expand", 18)}</button></div></div>
<div class="map-stage" id="map-stage" tabindex="0" role="group" aria-label="Interactive weather map. Drag to pan, scroll or pinch to zoom, arrow keys to move, plus and minus to zoom. Click a point for its forecast.">
  <div class="map-layers" id="map-layers"></div>
  <div class="pin" id="pin" hidden><span class="dot"></span><span class="pin-label"></span></div>
  <div class="popup" id="popup" role="dialog" aria-label="Forecast for the selected point" hidden></div>
  <div class="ui tl"><div class="cursor-chip" id="cursor-chip" hidden></div></div>
  <div class="ui tr"><button class="ctl big" type="button" id="zoom-in" aria-label="Zoom in">{icons.svg("plus", 20)}</button>
    <button class="ctl big" type="button" id="zoom-out" aria-label="Zoom out">{icons.svg("minus", 20)}</button></div>
  <div class="ui bl"><div class="legend" id="legend"><div class="legend-title"></div><div class="legend-bar"></div><div class="legend-ticks"></div></div></div>
  <div class="ui bc"><div class="status" id="map-status" role="status" aria-live="polite"></div></div>
  <div class="attrib">© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> · Radar <a href="https://www.rainviewer.com/">RainViewer</a> · <a href="https://open-meteo.com/">Open-Meteo</a></div>
  <noscript><p class="noscript">The weather map needs JavaScript.</p></noscript>
</div>
<div class="timeline">
  <button class="play" type="button" id="btn-play" aria-label="Play animation"><span class="i-play">{icons.svg("play", 20, fill=True)}</span><span class="i-pause">{icons.svg("pause", 20, fill=True)}</span></button>
  <div class="tl-main"><input type="range" id="tl-range" min="0" max="47" step="1" value="0" aria-label="Forecast time">
    <div class="tl-labels"><span id="tl-start"></span><strong id="tl-now"></strong><span id="tl-end"></span></div></div>
  <button class="btn small" type="button" id="btn-now">Now</button>
</div></section>"""


def map_page(place: Place, units: Units, wx: Weather, layer: str) -> str:
    return f'<div class="full-map">{map_panel(place, units, wx, tall=True, layer=layer)}</div>'


# ---- hourly ------------------------------------------------------------------------------------

def hourly(place: Place, units: Units, wx: Weather) -> str:
    u = wx.u
    r = wx.hour_range(48)
    times = [wx.h["time"][i] for i in r]
    temps = [u.temp_val(wx.hv("temperature_2m", i)) for i in r]
    feels = [u.temp_val(wx.hv("apparent_temperature", i)) for i in r]
    rain = [wx.hv("precipitation", i, 0) for i in r]
    chart = (charts.line_chart([(temps, "s1"), (feels, "s2")], aria="Temperature and feels-like, next 48 hours") +
             charts.bar_chart(rain, h=56, cls="bar rain", aria="Hourly precipitation, next 48 hours") + x_labels(times))
    legend = f'<p class="legend-inline"><span class="sw s1"></span> Temperature <span class="sw s2"></span> Feels like <span class="sw rain"></span> Rain (mm per hour)</p>'
    rows = []
    for i in r:
        t = wx.h["time"][i]
        label, kind = wx.condition(i)
        day = f'{fmt_dow(t)} ' if datetime.fromisoformat(t).hour == 0 or i == wx.now_i else ""
        rows.append(
            f'<tr><th scope="row">{day}{fmt_hour(t)}</th><td>{icons.svg(kind, 22, label=label)}</td>'
            f'<td class="mono">{u.temp(wx.hv("temperature_2m", i))}</td><td class="mono muted">{u.temp(wx.hv("apparent_temperature", i))}</td>'
            f'<td>{wx.hv("precipitation_probability", i, 0)}%</td><td>{u.precip(wx.hv("precipitation", i, 0))}</td>'
            f'<td>{u.speed(wx.hv("wind_speed_10m", i))} {compass(wx.hv("wind_direction_10m", i))}</td>'
            f'<td>{u.speed(wx.hv("wind_gusts_10m", i))}</td><td>{wx.hv("relative_humidity_2m", i, 0):.0f}%</td>'
            f'<td>{wx.hv("cloud_cover", i, 0):.0f}%</td></tr>')
    table = ('<div class="scroll-x"><table class="data"><thead><tr><th>Time</th><th><span class="sr">Sky</span></th><th>Temp</th><th>Feels</th>'
             '<th>Rain</th><th>Amount</th><th>Wind</th><th>Gusts</th><th>Humidity</th><th>Cloud</th></tr></thead>'
             f'<tbody>{"".join(rows)}</tbody></table></div>')
    return panel("Next 48 hours", chart + legend, "wide") + panel("Hour by hour", table, "wide tight")


# ---- 14 day ------------------------------------------------------------------------------------

def daily(place: Place, units: Units, wx: Weather) -> str:
    u = wx.u
    days = list(range(wx.today_i, min(len(wx.d["time"]), wx.today_i + 14)))
    highs = [wx.dv("temperature_2m_max", i, 0) for i in days]
    lows = [wx.dv("temperature_2m_min", i, 0) for i in days]
    gmin, gmax = min(lows), max(highs)
    rows = []
    for n, i in enumerate(days):
        label, kind = wx.day_condition(i)
        t = wx.d["time"][i]
        sun = (wx.dv("sunshine_duration", i, 0) or 0) / 3600
        rows.append(
            f'<tr><th scope="row">{"Today" if n == 0 else fmt_dow(t)}<span class="muted block">{fmt_date(t)}</span></th>'
            f'<td>{icons.svg(kind, 24, label=label)}</td><td class="cond-cell">{esc(label)}</td>'
            f'<td>{wx.dv("precipitation_probability_max", i, 0)}%<span class="muted block">{u.precip(wx.dv("precipitation_sum", i, 0))}</span></td>'
            f'<td class="mono muted">{u.temp(lows[n])}</td><td class="range-cell">{charts.range_bar(lows[n], highs[n], gmin, gmax)}</td>'
            f'<td class="mono"><strong>{u.temp(highs[n])}</strong></td>'
            f'<td>{u.speed(wx.dv("wind_speed_10m_max", i))}<span class="muted block">gusts {u.speed(wx.dv("wind_gusts_10m_max", i))}</span></td>'
            f'<td>{wx.dv("uv_index_max", i, 0):.0f}<span class="muted block">{uv_category(wx.dv("uv_index_max", i))}</span></td>'
            f'<td>{sun:.1f} h</td></tr>')
    table = ('<div class="scroll-x"><table class="data"><thead><tr><th>Day</th><th><span class="sr">Sky</span></th><th>Outlook</th><th>Rain</th>'
             '<th>Low</th><th><span class="sr">Range</span></th><th>High</th><th>Wind</th><th>UV</th><th>Sun</th></tr></thead>'
             f'<tbody>{"".join(rows)}</tbody></table></div>')
    past = list(range(max(0, wx.today_i - 7), wx.today_i))
    prow = "".join(
        f'<tr><th scope="row">{fmt_dow(wx.d["time"][i])} {fmt_date(wx.d["time"][i])}</th><td class="mono">{u.temp(wx.dv("temperature_2m_max", i))}</td>'
        f'<td class="mono muted">{u.temp(wx.dv("temperature_2m_min", i))}</td><td>{u.precip(wx.dv("precipitation_sum", i, 0))}</td>'
        f'<td>{u.speed(wx.dv("wind_gusts_10m_max", i))}</td></tr>' for i in reversed(past))
    ptable = ('<div class="scroll-x"><table class="data"><thead><tr><th>Day</th><th>High</th><th>Low</th><th>Rain</th><th>Top gust</th></tr></thead>'
              f'<tbody>{prow}</tbody></table></div>') if past else ""
    total = sum(wx.dv("precipitation_sum", i, 0) or 0 for i in past)
    recap = panel("Last 7 days", ptable, "wide tight", sub=f"Total rain {u.precip(total)}") if past else ""
    return panel("Next 14 days", table, "wide tight") + recap


# ---- details (the "more weather info" page) ----------------------------------------------------

def details(place: Place, units: Units, wx: Weather) -> str:
    u, cur = wx.u, wx.cur
    r48 = wx.hour_range(48)
    t48 = [wx.h["time"][i] for i in r48]
    panels: list[str] = []

    # wind
    wd, ws, wg = cur.get("wind_direction_10m"), cur.get("wind_speed_10m"), cur.get("wind_gusts_10m")
    chart = (charts.line_chart([([wx.hv("wind_speed_10m", i) for i in r48], "s1"),
                                ([wx.hv("wind_gusts_10m", i) for i in r48], "s2")], aria="Wind speed and gusts, next 48 hours", area=False) + x_labels(t48))
    panels.append(panel("Wind", f'<div class="dial-row">{charts.wind_dial(wd, f"Wind from {compass(wd)}")}<div>'
                        f'{kv("Speed", u.speed(ws))}{kv("Gusts", u.speed(wg))}{kv("From", f"{compass(wd)} ({wd:.0f}°)" if wd is not None else "–")}'
                        f'{kv("Beaufort", beaufort(ws))}</div></div>{chart}', "wide"))

    # pressure
    delta = wx.pressure_delta_3h()
    pr = range(max(0, wx.now_i - 12), min(len(wx.h["time"]), wx.now_i + 36))
    pchart = charts.line_chart([([wx.hv("pressure_msl", i) for i in pr], "s1")], h=110, marker=wx.now_i - pr.start, aria="Sea-level pressure, past 12 and next 36 hours")
    panels.append(panel("Pressure", f'{kv("Sea level", u.pressure(cur.get("pressure_msl")))}{kv("Surface", u.pressure(cur.get("surface_pressure")))}'
                        f'{kv("Trend (3 h)", pressure_trend(delta))}{pchart}', "wide"))

    # humidity + dew point
    dew = wx.hv("dew_point_2m")
    panels.append(panel("Humidity and dew point", f'{kv("Humidity", f"{cur.get("relative_humidity_2m", 0):.0f}%")}{kv("Dew point", u.temp(dew))}'
                        f'{kv("Feels", dew_comfort(dew))}{kv("Apparent temp", u.temp(cur.get("apparent_temperature")))}'))

    # clouds
    layers = "".join(f'<div class="meter"><span>{esc(name)}</span><span class="track"><span class="fill" style="width:{(wx.hv(key, default=0) or 0):.0f}%"></span></span>'
                     f'<strong>{(wx.hv(key, default=0) or 0):.0f}%</strong></div>'
                     for name, key in (("Total", "cloud_cover"), ("Low", "cloud_cover_low"), ("Mid", "cloud_cover_mid"), ("High", "cloud_cover_high")))
    panels.append(panel("Cloud cover", layers))

    # visibility
    vis_m = wx.hv("visibility")
    vis_km = None if vis_m is None else vis_m / 1000
    panels.append(panel("Visibility", f'{kv("Distance", u.dist(vis_km))}{kv("Rating", visibility_label(vis_km))}'))

    # precipitation
    nr = wx.next_rain(48)
    nxt = f"around {fmt_dow(wx.h['time'][nr[0]])} {fmt_hour(wx.h['time'][nr[0]])}" if nr else "none in 48 h"
    d7 = range(wx.today_i, min(len(wx.d["time"]), wx.today_i + 7))
    bars = charts.bar_chart([wx.dv("precipitation_sum", i, 0) for i in d7], h=60, cls="bar rain", aria="Daily rain totals, next 7 days")
    labels = '<div class="xlabels">' + "".join(f"<span>{fmt_dow(wx.d['time'][i])}</span>" for i in d7) + "</div>"
    panels.append(panel("Precipitation", f'{kv("Today total", u.precip(wx.dv("precipitation_sum")))}{kv("Rain / showers", f"{u.precip(wx.dv("rain_sum"))} / {u.precip(wx.dv("showers_sum"))}")}'
                        f'{kv("Wet hours today", f"{wx.dv("precipitation_hours", default=0)} h")}{kv("Chance today", f"{wx.dv("precipitation_probability_max", default=0)}%")}'
                        f'{kv("Next rain", nxt)}{bars}{labels}'))

    # storms
    cape_now, cape_max = wx.hv("cape"), wx.max_in("cape", 24)
    storm_codes = [wx.hv("weather_code", i) for i in wx.hour_range(24)]
    thunder = any(c in (95, 96, 99) for c in storm_codes if c is not None)
    panels.append(panel("Storm potential", f'{kv("CAPE now", "–" if cape_now is None else f"{cape_now:.0f} J/kg")}{kv("Peak next 24 h", "–" if cape_max is None else f"{cape_max:.0f} J/kg")}'
                        f'{kv("Instability", cape_label(cape_max))}{kv("Thunderstorms forecast", "Yes" if thunder else "No")}'))

    # freezing level, soil, ET0, sun energy
    sun_h = (wx.dv("sunshine_duration", default=0) or 0) / 3600
    day_h = (wx.dv("daylight_duration", default=0) or 0) / 3600
    panels.append(panel("Upper air and ground", f'{kv("Freezing level", u.height(wx.hv("freezing_level_height")))}'
                        f'{kv("Soil temp (surface)", u.temp(wx.hv("soil_temperature_0cm"), 1))}'
                        f'{kv("Soil moisture", "–" if wx.hv("soil_moisture_0_to_1cm") is None else f"{wx.hv("soil_moisture_0_to_1cm") * 100:.0f}%")}'
                        f'{kv("Evapotranspiration today", u.precip(wx.dv("et0_fao_evapotranspiration")))}'))
    panels.append(panel("Sunshine and solar energy", f'{kv("Sunshine today", f"{sun_h:.1f} h of {day_h:.1f} h")}'
                        f'{kv("Solar radiation", "–" if wx.dv("shortwave_radiation_sum") is None else f"{wx.dv("shortwave_radiation_sum"):.1f} MJ/m²")}'
                        f'{kv("UV max today", f"{wx.dv("uv_index_max", default=0):.0f} ({uv_category(wx.dv("uv_index_max"))})")}'
                        f'{kv("Feels-like range", f"{u.temp(wx.dv("apparent_temperature_min"))} to {u.temp(wx.dv("apparent_temperature_max"))}")}'))
    return f'<div class="panels">{"".join(panels)}</div>'


# ---- air + sun + moon --------------------------------------------------------------------------

_AQI_SEGMENTS = 6


def air(place: Place, units: Units, wx: Weather, aq: dict | None) -> str:
    u = wx.u
    out: list[str] = []
    if aq:
        c = aq["current"]
        us, eu = c.get("us_aqi"), c.get("european_aqi")
        pos = 0 if us is None else min(99.0, (min(us, 300) / 300) * 100)
        scale = ('<div class="aqi-scale">' + "".join(f'<span class="seg seg{n}"></span>' for n in range(1, _AQI_SEGMENTS + 1)) +
                 f'<span class="marker" style="left:{pos:.1f}%"></span></div><div class="xlabels"><span>0 Good</span><span>300+ Hazardous</span></div>')
        pollutants = "".join(f'<div class="tile"><span class="muted">{esc(name)}</span><strong class="mono">{"–" if c.get(key) is None else f"{c[key]:.{dp}f}"}'
                             f' <small>{unit}</small></strong></div>'
                             for name, key, dp, unit in (("PM2.5", "pm2_5", 1, "µg/m³"), ("PM10", "pm10", 1, "µg/m³"), ("Ozone", "ozone", 0, "µg/m³"),
                                                         ("NO₂", "nitrogen_dioxide", 0, "µg/m³"), ("SO₂", "sulphur_dioxide", 0, "µg/m³"),
                                                         ("CO", "carbon_monoxide", 0, "µg/m³"), ("Dust", "dust", 0, "µg/m³"), ("Aerosol depth", "aerosol_optical_depth", 2, "")))
        hist = aq["hourly"]
        ah = hist.get("us_aqi", [])[:48]
        achart = charts.line_chart([(ah, "s1")], h=110, aria="US AQI, next 48 hours") + x_labels(hist["time"][:48]) if ah else ""
        out.append(panel("Air quality", f'<div class="aqi-head"><span class="big mono">{"–" if us is None else f"{us:.0f}"}</span>'
                         f'<div><strong>{esc(us_aqi_category(us))}</strong><span class="muted block">US AQI · EU index {"–" if eu is None else f"{eu:.0f}"} ({esc(eu_aqi_category(eu))})</span></div></div>'
                         f'{scale}<div class="tiles">{pollutants}</div>{achart}', "wide"))
        pollen = [(n, c.get(k)) for n, k in (("Alder", "alder_pollen"), ("Birch", "birch_pollen"), ("Grass", "grass_pollen"),
                                             ("Mugwort", "mugwort_pollen"), ("Olive", "olive_pollen"), ("Ragweed", "ragweed_pollen")) if c.get(k) is not None]
        if pollen:
            out.append(panel("Pollen", "".join(kv(n, f"{v:.0f} grains/m³") for n, v in pollen), sub="Europe only"))
    else:
        out.append(panel("Air quality", '<p class="muted">Air-quality data is unavailable right now.</p>'))

    # UV today
    start = wx.today_i * 24
    uvs = [wx.hv("uv_index", i, 0) or 0 for i in range(start, start + 24)]
    klass = ["uvl" if v < 3 else "uvm" if v < 6 else "uvh" if v < 8 else "uvv" if v < 11 else "uvx" for v in uvs]
    peak = max(uvs) if uvs else 0
    peak_i = uvs.index(peak) if uvs else 0
    uv_chart = charts.bar_chart(uvs, h=90, vmax=12, classes=[f"bar {k}" for k in klass], aria="UV index by hour today")
    labels = '<div class="xlabels"><span>12 AM</span><span>6 AM</span><span>12 PM</span><span>6 PM</span><span>12 AM</span></div>'
    out.append(panel("UV index today", f'{kv("Peak", f"{peak:.0f} ({uv_category(peak)}) at {fmt_hour(f"2000-01-01T{peak_i:02d}:00")}")}{uv_chart}{labels}'))

    # sun
    sr, ss = wx.dv("sunrise"), wx.dv("sunset")
    frac = None
    if sr and ss:
        a, b, now = (datetime.fromisoformat(x) for x in (sr, ss, wx.cur["time"]))
        frac = (now - a).total_seconds() / max(1.0, (b - a).total_seconds())
    out.append(panel("Sun", f'{charts.sun_arc(frac)}{kv("Sunrise", fmt_clock(sr) if sr else "–")}{kv("Sunset", fmt_clock(ss) if ss else "–")}'
                     f'{kv("Day length", fmt_duration(wx.dv("daylight_duration")))}{kv("Sunshine", fmt_duration(wx.dv("sunshine_duration")))}'))
    m = moon(wx.utc_now)
    out.append(panel("Moon", f'<div class="moon-row">{charts.moon_svg(m["fraction"])}<div><strong>{esc(m["name"])}</strong>'
                     f'<span class="muted block">{m["illumination"] * 100:.0f}% lit</span></div></div>'
                     f'{kv("Next full moon", f"in {m["days_to_full"]:.0f} days")}{kv("Next new moon", f"in {m["days_to_new"]:.0f} days")}',
                     sub="Calculated locally"))
    return f'<div class="panels">{"".join(out)}</div>'
