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
REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"   # OpenStreetMap: light use, identify the app (USER_AGENT)

# Natural-hazard feeds. All free and keyless.
USGS_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_week.geojson"
GDACS_URL = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH"
EONET_URL = "https://eonet.gsfc.nasa.gov/api/v3/events"

# Seconds to keep each kind of upstream answer in memory.
TTL = {"forecast": 600, "air": 1800, "geocode": 86_400, "radar": 120, "field": 1800, "hazards": 600, "reverse": 86_400}

# Open-Meteo's free tier asks for fewer than ~10,000 calls a day. A grid request of N points
# counts as roughly N calls, so the map keeps its own counter and stops before the limit.
DAILY_CALL_BUDGET = int(os.environ.get("CIRRUS_DAILY_BUDGET", "8000"))

# Map weather grid: most points per request, and how many forecast hours to load.
MAX_GRID_POINTS = 220
FIELD_HOURS = 48

# Offline demo mode: synthetic data, no network calls at all.
DEMO = os.environ.get("CIRRUS_DEMO") == "1"

# ---- alerts, notifications and e-mail (all optional) ------------------------------------------------
# Device alerts (alarm sound + notifications while the site is open or installed) need nothing here.
# Alerts by e-mail while the site is closed need a place to keep subscribers and a mailbox to send from:
#   Upstash Redis (free; Vercel > Storage > Upstash adds these variables for you)
#   a Gmail address with an app password (SMTP), and CRON_SECRET so only your scheduler can run the checks.
def _env(*names: str, default: str = "") -> str:
    for n in names:
        if os.environ.get(n):
            return os.environ[n]
    return default


STORE_URL = _env("UPSTASH_REDIS_REST_URL", "KV_REST_API_URL")
STORE_TOKEN = _env("UPSTASH_REDIS_REST_TOKEN", "KV_REST_API_TOKEN")
SMTP_HOST = _env("CIRRUS_SMTP_HOST", default="smtp.gmail.com")
SMTP_PORT = int(_env("CIRRUS_SMTP_PORT", default="465"))
SMTP_USER = _env("CIRRUS_SMTP_USER")
SMTP_PASSWORD = _env("CIRRUS_SMTP_PASSWORD")
MAIL_DAILY_CAP = int(_env("CIRRUS_MAIL_DAILY_CAP", default="400"))     # Gmail allows about 500 a day
CRON_SECRET = _env("CRON_SECRET")
# Links inside e-mails must never come from a request header (an attacker could forge it), so they use this.
BASE_URL = _env("CIRRUS_BASE_URL").rstrip("/") or (
    f"https://{os.environ['VERCEL_PROJECT_PRODUCTION_URL']}" if os.environ.get("VERCEL_PROJECT_PRODUCTION_URL") else "")
