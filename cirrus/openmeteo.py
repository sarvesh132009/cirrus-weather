"""Keyless data sources: Open-Meteo (forecast, air quality, geocoding, map grid) and RainViewer (radar).

Everything is cached in memory, and grid requests are counted against a daily budget so a busy map
can never push the free Open-Meteo tier over its fair-use limit.
"""

from __future__ import annotations

import json
import math
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from . import config, demo


class UpstreamError(RuntimeError):
    """A weather service could not be reached or answered with an error."""


class TTLCache:
    def __init__(self, max_items: int = 600) -> None:
        self._data: dict = {}
        self._lock = threading.Lock()
        self._max = max_items

    def get(self, key):
        with self._lock:
            item = self._data.get(key)
            if item and item[0] > time.time():
                return item[1]
            self._data.pop(key, None)
            return None

    def put(self, key, value, ttl: float) -> None:
        with self._lock:
            if len(self._data) >= self._max:
                now = time.time()
                for k in [k for k, (exp, _) in self._data.items() if exp <= now] or [next(iter(self._data))]:
                    self._data.pop(k, None)
            self._data[key] = (time.time() + ttl, value)


class Budget:
    """Daily counter of (roughly) Open-Meteo API calls. Resets at UTC midnight."""

    def __init__(self, limit: int) -> None:
        self.limit, self.used, self.day = limit, 0, None
        self._lock = threading.Lock()

    def spend(self, n: int) -> bool:
        with self._lock:
            today = datetime.now(UTC).date()
            if self.day != today:
                self.day, self.used = today, 0
            if self.used + n > self.limit:
                return False
            self.used += n
            return True


_cache = TTLCache()
budget = Budget(config.DAILY_CALL_BUDGET)
_locks: dict = {}
_locks_guard = threading.Lock()


def memo(key, ttl: float, fn):
    """Return the cached value, computing it once even if many requests ask at the same time."""
    hit = _cache.get(key)
    if hit is not None:
        return hit
    with _locks_guard:
        lock = _locks.setdefault(key, threading.Lock())
    try:
        with lock:
            hit = _cache.get(key)
            if hit is not None:
                return hit
            value = fn()
            _cache.put(key, value, ttl)
            return value
    finally:
        with _locks_guard:
            _locks.pop(key, None)


def _http_json(url: str, params: dict, timeout: float = 12):
    query = urllib.parse.urlencode(params, safe=",")
    req = urllib.request.Request(f"{url}?{query}" if query else url,
                                 headers={"User-Agent": config.USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = json.load(exc).get("reason", "")
        except Exception:  # noqa: BLE001 - best effort only
            pass
        raise UpstreamError(f"{urllib.parse.urlsplit(url).netloc} answered {exc.code}. {detail}".strip()) from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        raise UpstreamError(f"Could not reach {urllib.parse.urlsplit(url).netloc}: {exc}") from exc


# ---- forecast / air / geocoding ----------------------------------------------------------------

_CURRENT = ("temperature_2m,relative_humidity_2m,apparent_temperature,is_day,precipitation,rain,showers,weather_code,"
            "cloud_cover,pressure_msl,surface_pressure,wind_speed_10m,wind_direction_10m,wind_gusts_10m")
_HOURLY = ("temperature_2m,relative_humidity_2m,dew_point_2m,apparent_temperature,precipitation_probability,"
           "precipitation,rain,showers,weather_code,pressure_msl,cloud_cover,cloud_cover_low,cloud_cover_mid,"
           "cloud_cover_high,visibility,wind_speed_10m,wind_direction_10m,wind_gusts_10m,uv_index,is_day,cape,"
           "freezing_level_height,soil_temperature_0cm,soil_moisture_0_to_1cm,evapotranspiration")
_DAILY = ("weather_code,temperature_2m_max,temperature_2m_min,apparent_temperature_max,apparent_temperature_min,"
          "sunrise,sunset,daylight_duration,sunshine_duration,uv_index_max,precipitation_sum,rain_sum,showers_sum,"
          "precipitation_hours,precipitation_probability_max,wind_speed_10m_max,wind_gusts_10m_max,"
          "wind_direction_10m_dominant,shortwave_radiation_sum,et0_fao_evapotranspiration")


def forecast(lat: float, lon: float) -> dict:
    lat, lon = round(lat, 3), round(lon, 3)

    def go():
        if config.DEMO:
            return demo.forecast(lat, lon)
        if not budget.spend(1):
            raise UpstreamError("Today's request budget is used up.")
        return _http_json(config.FORECAST_URL, {
            "latitude": lat, "longitude": lon, "current": _CURRENT, "hourly": _HOURLY, "daily": _DAILY,
            "timezone": "auto", "past_days": 7, "forecast_days": 14, "wind_speed_unit": "kmh"})

    return memo(("forecast", lat, lon), config.TTL["forecast"], go)


_POLLEN = "alder_pollen,birch_pollen,grass_pollen,mugwort_pollen,olive_pollen,ragweed_pollen"


def air_quality(lat: float, lon: float) -> dict:
    lat, lon = round(lat, 3), round(lon, 3)

    def go():
        if config.DEMO:
            return demo.air_quality(lat, lon)
        if not budget.spend(1):
            raise UpstreamError("Today's request budget is used up.")
        return _http_json(config.AIR_URL, {
            "latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": 3,
            "current": "us_aqi,european_aqi,pm10,pm2_5,carbon_monoxide,nitrogen_dioxide,sulphur_dioxide,ozone,dust,"
                       "aerosol_optical_depth," + _POLLEN,
            "hourly": "us_aqi,pm2_5,pm10"})

    return memo(("air", lat, lon), config.TTL["air"], go)


def geocode(query: str) -> list[dict]:
    q = " ".join(query.split())[:80]
    if len(q) < 2:
        return []

    def go():
        if config.DEMO:
            return demo.geocode(q)
        if not budget.spend(1):
            raise UpstreamError("Today's request budget is used up.")
        data = _http_json(config.GEOCODE_URL, {"name": q, "count": 8, "language": "en", "format": "json"})
        return [{"name": r["name"], "admin1": r.get("admin1", ""), "country": r.get("country", ""),
                 "lat": r["latitude"], "lon": r["longitude"], "tz": r.get("timezone", ""), "pop": r.get("population") or 0}
                for r in data.get("results", [])]

    return memo(("geo", q.lower()), config.TTL["geocode"], go)


# ---- radar -------------------------------------------------------------------------------------

def radar_frames() -> dict:
    """Recent observed radar frames from RainViewer. The browser loads the tiles directly."""
    def go():
        if config.DEMO:
            return demo.radar_frames()
        data = _http_json(config.RADAR_URL, {})
        frames = [{"time": f["time"], "path": f["path"]} for f in data.get("radar", {}).get("past", [])]
        return {"host": data.get("host", "https://tilecache.rainviewer.com"), "frames": frames[-12:]}

    return memo(("radar",), config.TTL["radar"], go)


# ---- map grid ----------------------------------------------------------------------------------

SPACINGS = (0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 8.0, 12.0)
FIELD_VARS = ("temperature_2m", "relative_humidity_2m", "precipitation", "pressure_msl", "cloud_cover",
              "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m")
_DECIMALS = {"temperature_2m": 1, "relative_humidity_2m": 0, "precipitation": 2, "pressure_msl": 1,
             "cloud_cover": 0, "wind_speed_10m": 1, "wind_direction_10m": 0, "wind_gusts_10m": 1}


def pick_spacing(span_lat: float, span_lon: float) -> float:
    """Finest grid spacing (degrees) that stays within the point limit."""
    for s in SPACINGS:
        if (math.ceil(span_lon / s) + 1) * (math.ceil(span_lat / s) + 1) <= config.MAX_GRID_POINTS:
            return s
    return SPACINGS[-1]


def _fetch_points(points: list[tuple[float, float]]) -> tuple[list[dict], list[str]]:
    if config.DEMO:
        return demo.grid_points(points, config.FIELD_HOURS)
    if not budget.spend(len(points)):
        raise UpstreamError("Today's weather-grid budget is used up. It resets at midnight UTC, "
                            "or raise CIRRUS_DAILY_BUDGET if you self-host Open-Meteo.")
    chunks = [points[i:i + 110] for i in range(0, len(points), 110)]

    def one(chunk: list[tuple[float, float]]) -> list[dict]:
        data = _http_json(config.FORECAST_URL, {
            "latitude": ",".join(f"{la:.3f}" for la, _ in chunk), "longitude": ",".join(f"{lo:.3f}" for _, lo in chunk),
            "hourly": ",".join(FIELD_VARS), "forecast_hours": config.FIELD_HOURS, "timezone": "GMT",
            "wind_speed_unit": "kmh"})
        return data if isinstance(data, list) else [data]

    with ThreadPoolExecutor(max_workers=3) as pool:
        flat = [r for part in pool.map(one, chunks) for r in part]
    if len(flat) != len(points):
        raise UpstreamError("The weather service returned an unexpected grid.")
    return [r["hourly"] for r in flat], flat[0]["hourly"]["time"]


def field(south: float, west: float, north: float, east: float, zoom: float = 0.0) -> dict:
    """A regular lat/lon grid of hourly weather covering the viewport (plus padding).

    The grid is snapped to multiples of its spacing so panning around reuses the cached answer.
    """
    south, north = max(-80.0, min(south, north)), min(80.0, max(south, north))
    west, east = max(-180.0, min(west, east)), min(180.0, max(west, east))
    if north - south < 1:
        south, north = south - 0.5, north + 0.5
    if east - west < 1:
        west, east = west - 0.5, east + 0.5
    pad_lat, pad_lon = (north - south) * 0.25, (east - west) * 0.25
    s_lat, n_lat = max(-80.0, south - pad_lat), min(80.0, north + pad_lat)
    w_lon, e_lon = max(-180.0, west - pad_lon), min(180.0, east + pad_lon)
    step = pick_spacing(n_lat - s_lat, e_lon - w_lon)
    s0, w0 = math.floor(s_lat / step) * step, math.floor(w_lon / step) * step
    ny, nx = math.ceil((n_lat - s0) / step) + 1, math.ceil((e_lon - w0) / step) + 1
    key = ("field", step, round(s0, 3), round(w0, 3), nx, ny)

    def go():
        pts = [(min(90.0, s0 + j * step), min(180.0, w0 + i * step)) for j in range(ny) for i in range(nx)]
        series, times = _fetch_points(pts)
        out: dict[str, list] = {}
        for name in FIELD_VARS:
            nd = _DECIMALS[name]
            out[name] = [[round(series[p][name][t] or 0.0, nd) for p in range(len(pts))] for t in range(len(times))]
        return {"spacing": step, "south": round(s0, 4), "west": round(w0, 4), "nx": nx, "ny": ny,
                "dlat": step, "dlon": step, "times": times, "vars": out, "zoom": zoom,
                "source": "demo" if config.DEMO else "open-meteo"}

    result = memo(key, config.TTL["field"], go)
    return {**result, "zoom": zoom}
