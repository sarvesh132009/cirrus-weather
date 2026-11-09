"""Settings. Everything here works without API keys."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "public" / "static"   # Vercel serves everything under public/ straight from its CDN

# A generic client name. Open-Meteo and RainViewer do not need a key or contact address.
USER_AGENT = "cirrus-weather/0.1 (personal project)"

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
AIR_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
RADAR_URL = "https://api.rainviewer.com/public/weather-maps.json"

# Seconds to keep each kind of upstream answer in memory.
TTL = {"forecast": 600, "air": 1800, "geocode": 86_400, "radar": 120, "field": 1800}

# Open-Meteo's free tier asks for fewer than ~10,000 calls a day. A grid request of N points
# counts as roughly N calls, so the map keeps its own counter and stops before the limit.
DAILY_CALL_BUDGET = int(os.environ.get("CIRRUS_DAILY_BUDGET", "8000"))

# Map weather grid: most points per request, and how many forecast hours to load.
MAX_GRID_POINTS = 220
FIELD_HOURS = 48

# Offline demo mode: synthetic data, no network calls at all.
DEMO = os.environ.get("CIRRUS_DEMO") == "1"
