"""A thin, None-safe wrapper around the Open-Meteo forecast JSON."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from .derive import Units, describe, fmt_hour


class Weather:
    def __init__(self, raw: dict, units: Units) -> None:
        self.raw, self.u = raw, units
        self.cur, self.h, self.d = raw["current"], raw["hourly"], raw["daily"]
        self.tz = raw.get("timezone", "UTC")
        times = self.h["time"]
        # hourly times and `current.time` share one ISO format, so string comparison works
        self.now_i = max((i for i, t in enumerate(times) if t <= self.cur["time"]), default=0)
        today = self.cur["time"][:10]
        self.today_i = next((i for i, t in enumerate(self.d["time"]) if t == today), 0)

    # ---- raw access ----------------------------------------------------------------------------
    def hv(self, name: str, i: int | None = None, default=None):
        arr = self.h.get(name)
        i = self.now_i if i is None else i
        if arr is None or not 0 <= i < len(arr) or arr[i] is None:
            return default
        return arr[i]

    def dv(self, name: str, i: int | None = None, default=None):
        arr = self.d.get(name)
        i = self.today_i if i is None else i
        if arr is None or not 0 <= i < len(arr) or arr[i] is None:
            return default
        return arr[i]

    def hours(self, name: str, start: int, count: int) -> list:
        arr = self.h.get(name) or []
        return [arr[i] if 0 <= i < len(arr) else None for i in range(start, start + count)]

    def hour_range(self, count: int, offset: int = 0) -> range:
        start = max(0, self.now_i + offset)
        return range(start, min(len(self.h["time"]), start + count))

    # ---- derived -------------------------------------------------------------------------------
    @property
    def is_day(self) -> bool:
        return bool(self.cur.get("is_day", 1))

    @property
    def local_now(self) -> datetime:
        return datetime.fromisoformat(self.cur["time"])

    @property
    def utc_now(self) -> datetime:
        offset = self.raw.get("utc_offset_seconds", 0)
        return (self.local_now - timedelta(seconds=offset)).replace(tzinfo=UTC)

    def condition(self, i: int | None = None) -> tuple[str, str]:
        if i is None:
            return describe(self.cur.get("weather_code"), self.is_day)
        return describe(self.hv("weather_code", i), bool(self.hv("is_day", i, 1)))

    def day_condition(self, i: int) -> tuple[str, str]:
        return describe(self.dv("weather_code", i), True)

    def next_rain(self, within: int = 24) -> tuple[int, float] | None:
        """First upcoming hour with measurable precipitation."""
        for i in range(self.now_i + 1, min(len(self.h["time"]), self.now_i + 1 + within)):
            mm = self.hv("precipitation", i, 0) or 0
            if mm >= 0.2:
                return i, mm
        return None

    def pressure_delta_3h(self) -> float | None:
        now, before = self.hv("pressure_msl"), self.hv("pressure_msl", self.now_i - 3)
        return None if now is None or before is None else now - before

    def summary(self) -> str:
        label, _ = self.condition()
        raining = (self.cur.get("precipitation") or 0) >= 0.1
        parts = [f"{label} now." if not raining else f"{label}, raining now."]
        nr = self.next_rain()
        if nr and not raining:
            parts.append(f"Rain expected around {fmt_hour(self.h['time'][nr[0]])}.")
        elif not raining:
            parts.append("No rain expected in the next 24 hours.")
        hi, lo = self.dv("temperature_2m_max"), self.dv("temperature_2m_min")
        if hi is not None and lo is not None:
            parts.append(f"High {self.u.temp(hi)}, low {self.u.temp(lo)} today.")
        return " ".join(parts)

    def max_in(self, name: str, count: int = 24):
        vals = [v for v in self.hours(name, self.now_i, count) if v is not None]
        return max(vals) if vals else None

    def peak_hour(self, name: str, count: int = 24) -> tuple[int, float] | None:
        best = None
        for i in range(self.now_i, min(len(self.h["time"]), self.now_i + count)):
            v = self.hv(name, i)
            if v is not None and (best is None or v > best[1]):
                best = (i, v)
        return best
