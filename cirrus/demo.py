"""Synthetic data in the same shapes as the real APIs, so the whole site runs offline (`--demo`).

The numbers are made up. They only exist so every page and map layer can be tried without a network.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

CITIES = [
    ("Bengaluru", "Karnataka", "India", 12.9719, 77.5937, "Asia/Kolkata"),
    ("Chennai", "Tamil Nadu", "India", 13.0878, 80.2785, "Asia/Kolkata"),
    ("Mumbai", "Maharashtra", "India", 19.0728, 72.8826, "Asia/Kolkata"),
    ("New Delhi", "Delhi", "India", 28.6139, 77.2090, "Asia/Kolkata"),
    ("Kolkata", "West Bengal", "India", 22.5697, 88.3697, "Asia/Kolkata"),
    ("Hyderabad", "Telangana", "India", 17.3840, 78.4564, "Asia/Kolkata"),
    ("Pune", "Maharashtra", "India", 18.5196, 73.8553, "Asia/Kolkata"),
    ("Kochi", "Kerala", "India", 9.9312, 76.2673, "Asia/Kolkata"),
    ("Jaipur", "Rajasthan", "India", 26.9124, 75.7873, "Asia/Kolkata"),
    ("London", "England", "United Kingdom", 51.5074, -0.1278, "Europe/London"),
    ("New York", "New York", "United States", 40.7128, -74.0060, "America/New_York"),
    ("Tokyo", "Tokyo", "Japan", 35.6762, 139.6503, "Asia/Tokyo"),
]


def geocode(query: str) -> list[dict]:
    q = query.strip().lower()
    return [{"name": n, "admin1": a, "country": c, "lat": la, "lon": lo, "tz": tz, "pop": 1}
            for n, a, c, la, lo, tz in CITIES if q in n.lower()]


def radar_frames() -> dict:
    return {"host": "", "frames": []}


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _noise(a: float, b: float = 0.0) -> float:
    return (math.sin(a * 12.9898 + b * 78.233) * 43758.5453) % 1


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M")


HOURLY_KEYS = ("temperature_2m", "relative_humidity_2m", "dew_point_2m", "apparent_temperature",
               "precipitation_probability", "precipitation", "rain", "showers", "weather_code", "pressure_msl",
               "cloud_cover", "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high", "visibility",
               "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m", "uv_index", "is_day", "cape",
               "freezing_level_height", "soil_temperature_0cm", "soil_moisture_0_to_1cm", "evapotranspiration")


def forecast(lat: float, lon: float) -> dict:
    india = 68 < lon < 98 and 6 < lat < 36
    offset = 5.5 if india else round(lon / 15)
    tz = "Asia/Kolkata" if india else "UTC"
    now = (datetime.now(UTC) + timedelta(hours=offset)).replace(tzinfo=None)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=7)
    n = 21 * 24
    H: dict[str, list] = {k: [] for k in HOURLY_KEYS}
    times: list[str] = []
    for k in range(n):
        t = start + timedelta(hours=k)
        hr, day = t.hour, k / 24
        diurnal = math.sin(2 * math.pi * (hr - 9) / 24)
        temp = 31 - 0.55 * abs(lat - 10) + 4.5 * diurnal + 1.5 * math.sin(day * 0.9)
        shower = max(0.0, 0.9 * math.sin(2 * math.pi * (hr - 16) / 24) + 0.5 * math.sin(day * 2.1 + lon) - 0.35)
        precip = round(shower * 6, 1) if shower > 0.05 else 0.0
        cloud = _clamp(55 + 35 * math.sin(day * 1.7 + lat) + 25 * shower + 20 * (_noise(k, lat) - 0.5), 0, 100)
        prob = int(_clamp(cloud * 0.6 + shower * 60, 0, 100))
        code = 95 if precip > 4 else 63 if precip > 0.5 else 61 if precip > 0 else 3 if cloud > 85 else 2 if cloud > 60 else 1 if cloud > 30 else 0
        rh = _clamp(85 - (temp - 22) * 2.5 + cloud * 0.1, 25, 100)
        wind = max(2.0, 10 + 5 * math.sin(day * 1.3) + 3 * diurnal)
        sunny = 6 <= hr < 18
        vals = {
            "temperature_2m": temp, "relative_humidity_2m": rh, "dew_point_2m": temp - (100 - rh) / 5,
            "apparent_temperature": temp + (rh - 50) * 0.04, "precipitation_probability": prob,
            "precipitation": precip, "rain": round(precip * 0.6, 1), "showers": round(precip * 0.4, 1),
            "weather_code": code, "pressure_msl": 1011 + 4 * math.sin(day * 0.7) - 1.5 * math.cos(2 * math.pi * hr / 12),
            "cloud_cover": cloud, "cloud_cover_low": cloud * 0.7, "cloud_cover_mid": cloud * 0.5,
            "cloud_cover_high": cloud * 0.4, "visibility": _clamp(24000 - cloud * 60 - precip * 1500, 800, 24000),
            "wind_speed_10m": wind, "wind_direction_10m": (250 + 40 * math.sin(day * 0.8)) % 360,
            "wind_gusts_10m": wind * 1.6 + 2,
            "uv_index": max(0.0, 10 * math.sin(math.pi * (hr - 6) / 12)) * (1 - cloud / 160) if sunny else 0.0,
            "is_day": 1 if sunny else 0, "cape": max(0.0, 1800 * shower * (0.5 + 0.5 * diurnal)),
            "freezing_level_height": 4800 + 120 * math.sin(day), "soil_temperature_0cm": temp - 1.5 + 0.5 * diurnal,
            "soil_moisture_0_to_1cm": 0.28 + (0.1 if precip > 0 else 0.0),
            "evapotranspiration": max(0.0, 0.35 * max(diurnal, 0) * (1 - cloud / 130)),
        }
        times.append(_iso(t))
        for key in HOURLY_KEYS:
            v = vals[key]
            H[key].append(v if key in ("weather_code", "is_day", "precipitation_probability") else round(v, 2))
    H = {"time": times, **H}

    # daily summaries built from the hourly arrays
    D: dict[str, list] = {k: [] for k in (
        "time", "weather_code", "temperature_2m_max", "temperature_2m_min", "apparent_temperature_max",
        "apparent_temperature_min", "sunrise", "sunset", "daylight_duration", "sunshine_duration", "uv_index_max",
        "precipitation_sum", "rain_sum", "showers_sum", "precipitation_hours", "precipitation_probability_max",
        "wind_speed_10m_max", "wind_gusts_10m_max", "wind_direction_10m_dominant", "shortwave_radiation_sum",
        "et0_fao_evapotranspiration")}
    for d in range(21):
        sl = slice(d * 24, d * 24 + 24)
        day = times[d * 24][:10]
        g = {k: H[k][sl] for k in HOURLY_KEYS}
        psum = sum(g["precipitation"])
        cloud_avg = sum(g["cloud_cover"]) / 24
        daylight = 42_120
        sunshine = daylight * _clamp(1 - cloud_avg / 130, 0.05, 1)
        code = 95 if max(g["weather_code"]) >= 95 else (63 if psum > 6 else 61) if psum > 1 else 3 if cloud_avg > 80 else 2 if cloud_avg > 55 else 1
        row = {
            "time": day, "weather_code": code, "temperature_2m_max": max(g["temperature_2m"]),
            "temperature_2m_min": min(g["temperature_2m"]), "apparent_temperature_max": max(g["apparent_temperature"]),
            "apparent_temperature_min": min(g["apparent_temperature"]), "sunrise": f"{day}T06:07", "sunset": f"{day}T17:49",
            "daylight_duration": daylight, "sunshine_duration": round(sunshine), "uv_index_max": round(max(g["uv_index"]), 1),
            "precipitation_sum": round(psum, 1), "rain_sum": round(sum(g["rain"]), 1), "showers_sum": round(sum(g["showers"]), 1),
            "precipitation_hours": sum(1 for p in g["precipitation"] if p > 0.1),
            "precipitation_probability_max": max(g["precipitation_probability"]),
            "wind_speed_10m_max": max(g["wind_speed_10m"]), "wind_gusts_10m_max": max(g["wind_gusts_10m"]),
            "wind_direction_10m_dominant": round(sum(g["wind_direction_10m"]) / 24),
            "shortwave_radiation_sum": round(sunshine / 3600 * 1.9, 1),
            "et0_fao_evapotranspiration": round(sum(g["evapotranspiration"]), 1),
        }
        for key, v in row.items():
            D[key].append(v)

    i = int((now - start).total_seconds() // 3600)
    cur_time = now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0)
    current = {k: H[k][i] for k in ("temperature_2m", "relative_humidity_2m", "apparent_temperature", "is_day",
                                    "precipitation", "rain", "showers", "weather_code", "cloud_cover", "pressure_msl",
                                    "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m")}
    current["surface_pressure"] = round(H["pressure_msl"][i] - 90, 1)
    current["time"] = _iso(cur_time)
    return {"latitude": lat, "longitude": lon, "timezone": tz, "utc_offset_seconds": int(offset * 3600),
            "elevation": 900.0, "current": current, "hourly": H, "daily": D}


def air_quality(lat: float, lon: float) -> dict:
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0).replace(tzinfo=None)
    times = [_iso(now + timedelta(hours=k)) for k in range(72)]
    aqi = [round(62 + 25 * math.sin(k / 7 + lat) + 8 * (_noise(k) - 0.5)) for k in range(72)]
    pm25 = [round(a * 0.3, 1) for a in aqi]
    current = {"time": times[0], "us_aqi": aqi[0], "european_aqi": round(aqi[0] * 0.55), "pm10": 34.0, "pm2_5": pm25[0],
               "carbon_monoxide": 210.0, "nitrogen_dioxide": 12.0, "sulphur_dioxide": 4.0, "ozone": 41.0, "dust": 6.0,
               "aerosol_optical_depth": 0.28, "alder_pollen": None, "birch_pollen": None, "grass_pollen": None,
               "mugwort_pollen": None, "olive_pollen": None, "ragweed_pollen": None}
    return {"current": current, "hourly": {"time": times, "us_aqi": aqi, "pm2_5": pm25, "pm10": [round(p * 1.8, 1) for p in pm25]}}


# ---- map grid ----------------------------------------------------------------------------------

def grid_points(points: list[tuple[float, float]], hours: int, names: tuple[str, ...] = ()) -> tuple[list[dict], list[str]]:
    """Synthetic hourly series for each (lat, lon). Smooth fields that drift over time."""
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0).replace(tzinfo=None)
    times = [_iso(now + timedelta(hours=t)) for t in range(hours)]
    want = set(names) or {"temperature_2m", "relative_humidity_2m", "precipitation", "pressure_msl", "cloud_cover",
                          "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m"}
    levels = [int(n.split("_")[2].removesuffix("hPa")) for n in want if n.startswith("wind_speed_") and n.endswith("hPa")]
    out = []
    for lat, lon in points:
        s: dict[str, list] = {k: [] for k in want}
        for t in range(hours):
            local_hr = (now.hour + t + lon / 15) % 24
            u = 7 * math.sin(lat * 0.22 + lon * 0.05 - t * 0.04) + 4 * math.cos(lon * 0.17 + t * 0.03) + 4
            v = 6 * math.cos(lat * 0.18 - lon * 0.11 + t * 0.035) + 2 * math.sin(lat * 0.4)
            speed = math.hypot(u, v) * 3.6
            cloud = _clamp(50 + 45 * math.sin(lat * 0.35 + lon * 0.28 - t * 0.07) * math.cos(lat * 0.11), 0, 100)
            rain = max(0.0, math.sin(lat * 0.5 + lon * 0.37 + t * 0.09) * math.sin(lon * 0.21 - lat * 0.31 - t * 0.05) - 0.45) * 18
            vals = {
                "temperature_2m": 32 - 0.55 * abs(lat - 8) + 3 * math.sin(lon * 0.3 + lat * 0.2) + 4 * math.sin(2 * math.pi * (local_hr - 9) / 24),
                "relative_humidity_2m": _clamp(45 + 0.4 * cloud + (25 if rain > 0 else 0), 20, 100),
                "precipitation": rain,
                "pressure_msl": 1010 + 9 * math.sin(lon * 0.12 + t * 0.02) * math.cos(lat * 0.16) + 4 * math.sin(lat * 0.3 - lon * 0.1),
                "cloud_cover": cloud, "wind_speed_10m": speed, "wind_direction_10m": math.degrees(math.atan2(-u, -v)) % 360,
                "wind_gusts_10m": speed * 1.5,
                # storm cells: patchy instability that drifts east
                "cape": max(0.0, 3600 * math.sin(lat * 0.45 + lon * 0.3 - t * 0.06) * math.sin(lon * 0.2 - lat * 0.25 + t * 0.03) - 400),
            }
            for lv in levels:   # winds speed up and veer with height; a jet core sits near 28 N at 250 hPa
                boost = {850: 1.5, 700: 2.2, 500: 3.2, 250: 5.0}.get(lv, 2.0)
                jet = 110 * math.exp(-(((lat - 28 - 3 * math.sin(lon * 0.12)) / 6.5) ** 2)) if lv == 250 else 0
                vals[f"wind_speed_{lv}hPa"] = speed * boost + jet + 4
                vals[f"wind_direction_{lv}hPa"] = (270 + 25 * math.sin(lat * 0.1 + t * 0.02) + (15 if lv < 700 else 0)) % 360
            for k in want:
                s[k].append(vals[k])
        out.append(s)
    return out, times


# ---- hazards (earthquakes, cyclones, floods ...) --------------------------------------------------------------

def reverse(lat: float, lon: float) -> dict:
    n, a, c, *_ = min(CITIES, key=lambda r: (r[3] - lat) ** 2 + (r[4] - lon) ** 2)
    return {"name": n, "region": a, "country": c}


def hazards() -> dict:
    """A few invented events around India so the alert screens can be tried offline."""
    now = datetime.now(UTC).replace(microsecond=0)

    def ago(hours: float) -> str:
        return (now - timedelta(hours=hours)).isoformat().replace("+00:00", "Z")

    events = [
        {"id": "demo:eq1", "kind": "earthquake", "title": "M 6.1 earthquake, Andaman Islands region", "level": 3, "lat": 11.9, "lon": 92.9,
         "time": ago(2), "mag": 6.1, "radius_km": 300, "detail": "Depth 35 km. Offshore quake: follow official tsunami warnings.", "src": "USGS (demo)", "url": ""},
        {"id": "demo:tc1", "kind": "cyclone", "title": "Tropical cyclone DEMO, Bay of Bengal", "level": 3, "lat": 14.6, "lon": 85.4,
         "time": ago(6), "radius_km": 600, "detail": "Maximum winds about 110 km/h, moving north-west.", "src": "GDACS (demo)", "url": ""},
        {"id": "demo:fl1", "kind": "flood", "title": "Flood, Assam", "level": 2, "lat": 26.2, "lon": 91.7,
         "time": ago(30), "radius_km": 150, "detail": "River levels above danger mark in several districts.", "src": "GDACS (demo)", "url": ""},
        {"id": "demo:eq2", "kind": "earthquake", "title": "M 5.0 earthquake, near Hindu Kush", "level": 2, "lat": 36.4, "lon": 70.9,
         "time": ago(9), "mag": 5.0, "radius_km": 150, "detail": "Depth 200 km.", "src": "USGS (demo)", "url": ""},
        {"id": "demo:wf1", "kind": "wildfire", "title": "Wildfire, Uttarakhand", "level": 1, "lat": 30.1, "lon": 79.2,
         "time": ago(20), "radius_km": 60, "detail": "", "src": "NASA EONET (demo)", "url": ""},
        {"id": "demo:vo1", "kind": "volcano", "title": "Volcano activity, Barren Island", "level": 1, "lat": 12.28, "lon": 93.86,
         "time": ago(48), "radius_km": 100, "detail": "", "src": "NASA EONET (demo)", "url": ""},
    ]
    return {"events": events, "updated": now.isoformat().replace("+00:00", "Z"),
            "sources": {"usgs": "demo", "gdacs": "demo", "eonet": "demo"}}
