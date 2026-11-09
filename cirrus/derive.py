"""Pure helpers: weather codes, compass points, categories, units, moon phase, time labels."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime

# WMO weather interpretation codes used by Open-Meteo -> (label, icon kind)
WMO: dict[int, tuple[str, str]] = {
    0: ("Clear sky", "clear"), 1: ("Mainly clear", "partly"), 2: ("Partly cloudy", "partly"),
    3: ("Overcast", "cloud"), 45: ("Fog", "fog"), 48: ("Rime fog", "fog"),
    51: ("Light drizzle", "drizzle"), 53: ("Drizzle", "drizzle"), 55: ("Dense drizzle", "drizzle"),
    56: ("Freezing drizzle", "drizzle"), 57: ("Dense freezing drizzle", "drizzle"),
    61: ("Light rain", "rain"), 63: ("Rain", "rain"), 65: ("Heavy rain", "rain"),
    66: ("Freezing rain", "rain"), 67: ("Heavy freezing rain", "rain"),
    71: ("Light snow", "snow"), 73: ("Snow", "snow"), 75: ("Heavy snow", "snow"), 77: ("Snow grains", "snow"),
    80: ("Light showers", "rain"), 81: ("Showers", "rain"), 82: ("Violent showers", "rain"),
    85: ("Snow showers", "snow"), 86: ("Heavy snow showers", "snow"),
    95: ("Thunderstorm", "storm"), 96: ("Thunderstorm with hail", "storm"), 99: ("Severe thunderstorm with hail", "storm"),
}


def describe(code: int | None, is_day: bool = True) -> tuple[str, str]:
    """Return (label, icon kind) for a WMO code."""
    if code is None:
        return "No data", "cloud"
    label, kind = WMO.get(int(code), ("Unknown", "cloud"))
    if kind == "clear":
        kind = "sun" if is_day else "moon"
    elif kind == "partly" and not is_day:
        kind = "cloudmoon"
    return label, kind


COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def compass(deg: float | None) -> str:
    return "–" if deg is None else COMPASS[int((deg % 360) / 22.5 + 0.5) % 16]


_BEAUFORT = [(1, "Calm"), (6, "Light air"), (12, "Light breeze"), (20, "Gentle breeze"), (29, "Moderate breeze"),
             (39, "Fresh breeze"), (50, "Strong breeze"), (62, "Near gale"), (75, "Gale"), (89, "Strong gale"),
             (103, "Storm"), (118, "Violent storm")]


def beaufort(kmh: float | None) -> str:
    if kmh is None:
        return "–"
    return next((name for limit, name in _BEAUFORT if kmh < limit), "Hurricane force")


def uv_category(v: float | None) -> str:
    if v is None:
        return "–"
    return "Low" if v < 3 else "Moderate" if v < 6 else "High" if v < 8 else "Very high" if v < 11 else "Extreme"


def us_aqi_category(v: float | None) -> str:
    if v is None:
        return "–"
    for limit, name in ((50, "Good"), (100, "Moderate"), (150, "Unhealthy for sensitive groups"),
                        (200, "Unhealthy"), (300, "Very unhealthy")):
        if v <= limit:
            return name
    return "Hazardous"


def eu_aqi_category(v: float | None) -> str:
    if v is None:
        return "–"
    for limit, name in ((20, "Good"), (40, "Fair"), (60, "Moderate"), (80, "Poor"), (100, "Very poor")):
        if v <= limit:
            return name
    return "Extremely poor"


def dew_comfort(dew_c: float | None) -> str:
    if dew_c is None:
        return "–"
    for limit, name in ((10, "Dry"), (16, "Comfortable"), (18, "Slightly humid"), (21, "Humid"), (24, "Oppressive")):
        if dew_c < limit:
            return name
    return "Miserable"


def visibility_label(km: float | None) -> str:
    if km is None:
        return "–"
    return "Very poor (fog)" if km < 1 else "Poor" if km < 4 else "Moderate" if km < 10 else "Good" if km < 20 else "Excellent"


def cape_label(cape: float | None) -> str:
    if cape is None:
        return "–"
    return "None" if cape < 100 else "Low" if cape < 1000 else "Moderate" if cape < 2500 else "High" if cape < 4000 else "Extreme"


def pressure_trend(delta_3h: float | None) -> str:
    if delta_3h is None:
        return "–"
    if abs(delta_3h) <= 1:
        return "Steady"
    word = "Rising" if delta_3h > 0 else "Falling"
    return word + (" quickly" if abs(delta_3h) > 3 else "")


# ---- units -------------------------------------------------------------------------------------

def _clean(s: str) -> str:
    return s[1:] if s.startswith("-") and float(s.rstrip("°")) == 0 else s


@dataclass(frozen=True, slots=True)
class Units:
    imperial: bool = False

    def temp_val(self, c: float | None) -> float | None:
        return None if c is None else (c * 9 / 5 + 32 if self.imperial else c)

    def temp(self, c: float | None, digits: int = 0) -> str:
        v = self.temp_val(c)
        return "–" if v is None else _clean(f"{v:.{digits}f}") + "°"

    def speed(self, kmh: float | None) -> str:
        if kmh is None:
            return "–"
        return f"{kmh * 0.621371:.0f} mph" if self.imperial else f"{kmh:.0f} km/h"

    def precip(self, mm: float | None) -> str:
        if mm is None:
            return "–"
        return f"{mm / 25.4:.2f} in" if self.imperial else f"{mm:.1f} mm"

    def dist(self, km: float | None) -> str:
        if km is None:
            return "–"
        return f"{km * 0.621371:.0f} mi" if self.imperial else f"{km:.0f} km"

    def pressure(self, hpa: float | None) -> str:
        if hpa is None:
            return "–"
        return f"{hpa * 0.02953:.2f} inHg" if self.imperial else f"{hpa:.0f} hPa"

    def height(self, m: float | None) -> str:
        if m is None:
            return "–"
        return f"{m * 3.28084:,.0f} ft" if self.imperial else f"{m:,.0f} m"


# ---- moon --------------------------------------------------------------------------------------

SYNODIC = 29.530588853
_REF_NEW_MOON = datetime(2000, 1, 6, 18, 14, tzinfo=UTC)


def moon(when_utc: datetime) -> dict:
    """Mean-phase moon calculation (good to within about a day). No network needed."""
    f = (((when_utc - _REF_NEW_MOON).total_seconds() / 86400) % SYNODIC) / SYNODIC
    if f < 0.03 or f >= 0.97:
        name = "New moon"
    elif f < 0.22:
        name = "Waxing crescent"
    elif f < 0.28:
        name = "First quarter"
    elif f < 0.47:
        name = "Waxing gibbous"
    elif f < 0.53:
        name = "Full moon"
    elif f < 0.72:
        name = "Waning gibbous"
    elif f < 0.78:
        name = "Last quarter"
    else:
        name = "Waning crescent"
    return {
        "fraction": f,
        "name": name,
        "illumination": (1 - math.cos(2 * math.pi * f)) / 2,
        "days_to_full": ((0.5 - f) % 1) * SYNODIC,
        "days_to_new": ((1 - f) % 1) * SYNODIC,
    }


# ---- time labels -------------------------------------------------------------------------------

def fmt_hour(iso: str) -> str:
    h = datetime.fromisoformat(iso).hour
    return f"{h % 12 or 12} {'AM' if h < 12 else 'PM'}"


def fmt_clock(iso: str) -> str:
    dt = datetime.fromisoformat(iso)
    return f"{dt.hour % 12 or 12}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'}"


def fmt_dow(iso: str) -> str:
    return datetime.fromisoformat(iso[:10]).strftime("%a")


def fmt_date(iso: str) -> str:
    d = datetime.fromisoformat(iso[:10])
    return f"{d.day} {d:%b}"


def fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "–"
    m = round(seconds / 60)
    return f"{m // 60} h {m % 60:02d} m"
