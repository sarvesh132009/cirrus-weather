# Cirrus Weather

A keyless weather site with the **map in front** (Split Studio layout): data column on the left, a large Windy-style map on the right.
Python 3.13, standard library only. No API keys, no pip installs.

## Run

```bash
python run.py              # live data (needs internet)
python run.py --demo       # synthetic data, works offline
python run.py --port 9000 --host 0.0.0.0
```

Open http://127.0.0.1:8000 and search for a city or town.

## Pages (per searched place)

| Page | What it shows |
|---|---|
| Overview | Current conditions, next hours, 7-day strip, and the live map |
| Hourly | 48-hour temperature / feels-like / rain chart and a full table |
| 14 days | Daily forecast plus the last 7 days |
| Map | Full-size map |
| Details | Wind (gusts, dial, Beaufort), pressure and trend, humidity, dew point, cloud layers, visibility, precipitation, storm potential (CAPE), freezing level, soil temperature and moisture, evapotranspiration, sunshine and solar radiation |
| Air & sun | US/EU AQI, pollutants, pollen (Europe), UV by hour, sun arc, moon phase |

Add `&u=f` to any URL (or use the header toggle) for °F / mph / inHg.

## The map

A custom canvas map engine (no Leaflet): pan with inertia, pinch / wheel / double-click zoom, keyboard control.

- Layers: **Wind** (animated particles), **Upper wind** (850 hPa, 700 hPa, 500 hPa and the **jet stream** at 250 hPa, with a height chooser), **Radar** (observed, RainViewer), **Temperature**, **Rain forecast**, **Storm risk** (CAPE: how much energy thunderstorms could use), **Gusts**, **Clouds**, **Pressure** (isobars with H/L), **Humidity**
- **Hazards overlay**: live earthquakes, cyclones, floods, volcanoes and wildfires (USGS, GDACS, NASA EONET). Serious ones pulse; click one for details and how far it reaches
- **Day / night**: the dark side of the Earth for the time on the timeline, with twilight bands
- **Basemaps**: dark, light and **satellite** (NASA GIBS, Terra MODIS true colour of the previous day)
- **Home** and **You are here** markers, and a "My location" button
- 48-hour forecast timeline with play/pause and a Now button
- Hover value chip, click any point for a popup with its forecast and a link to the full forecast for that spot
- Overlay opacity, dark/light basemap, fullscreen
- The weather grid is fetched for the visible area and snapped to a fixed spacing so panning reuses the cache

## Alerts: home, alarm and notifications

1. On the first visit a window asks you to **set your home**: search a city or town, or use the device location. Change it any time from the bell (top right) > *Home & notifications*.
2. Cirrus then checks the alerts for **your home** and, if you allow location, for **where you are now** (when you are more than 25 km from home). The banner at the top and the bell show what is active.
3. When a new alert reaches your chosen level (default **Warning**) the page plays an **alarm sound** (two-tone siren: 2 s for a watch, 6 s for a warning, 10 s for an extreme event, with a Stop button) and sends a **notification** (system sound and vibration, stays on screen for warnings).
4. Optional: add an **e-mail address** to be told even when the site is closed (setup below).

What raises an alert (Cirrus's own thresholds, in `cirrus/alerts.py`; they are early warnings, not official alerts):

| Source | Alerts |
|---|---|
| Forecast (Open-Meteo) | extreme heat or cold (feels-like), heavy rain and flood risk (24 h totals, India's heavy / very heavy / extremely heavy classes, and hourly rates), gale to hurricane-force gusts, thunderstorms and hail, snow and freezing rain, dense fog, unhealthy air |
| Earthquakes (USGS, magnitude 4.5+) | within a distance that grows with magnitude, for 36 hours |
| Cyclones, floods, volcanoes, wildfires (GDACS, NASA EONET) | within the event's reach; the level drops one step on the outer edge |

Levels: 1 Advisory, 2 Watch, 3 Warning, 4 Extreme. An alert is announced once, and again only if its level rises.

**What works when (honest limits)**

| Situation | Alarm sound | Notification | Alerts for where you are |
|---|---|---|---|
| Cirrus open in a tab | yes (the browser needs one tap on the page first, then it can play) | yes, once you turn them on | yes, with location allowed |
| Installed as an app (Chrome on Android) | while open | also in the background about every few hours, if Chrome allows it. Chrome decides how often | last position only |
| Browser closed, no e-mail | no | no | no |
| Browser closed, **e-mail on** | no (the e-mail app makes its own sound) | e-mail | the last position this device reported while Cirrus was open (up to 48 h old) |

A web page cannot read your location while it is closed, so "where you are" is the last position Cirrus saw while it was open. On iPhone, notifications work only after *Share > Add to Home Screen*.

### Alerts by e-mail (optional setup, all free)

E-mail needs three things the site does not have by default: a place to keep subscribers, a mailbox to send from, and something that runs the check every 30 minutes. Until you set them up, the e-mail section says it is not switched on.

1. **Subscriber store.** In Vercel open your project > *Storage* > *Create Database* > **Upstash for Redis** (free plan) and connect it. Vercel adds `KV_REST_API_URL` and `KV_REST_API_TOKEN` (the app also accepts `UPSTASH_REDIS_REST_URL` / `UPSTASH_REDIS_REST_TOKEN`).
2. **Mailbox.** Use a Gmail address: turn on 2-step verification, create an **app password** (Google Account > Security > App passwords), then add these Environment Variables in Vercel: `CIRRUS_SMTP_USER` (the Gmail address) and `CIRRUS_SMTP_PASSWORD` (the app password). Gmail allows about 500 mails a day; `CIRRUS_MAIL_DAILY_CAP` (default 400) keeps Cirrus under that.
3. **Secrets.** Add `CRON_SECRET` (any long random text) in Vercel, and `CIRRUS_BASE_URL` (for example `https://cirrus-weather.vercel.app`; Vercel's own production URL is used if you leave it out). Redeploy.
4. **Scheduler.** In your GitHub repository open *Settings > Secrets and variables > Actions* and add `SITE_URL` (your site address) and `CRON_SECRET` (the same text). The included workflow `.github/workflows/alerts.yml` then calls `/api/cron/alerts` every 30 minutes. (GitHub switches scheduled workflows off after 60 days without any repository activity; push a small change or press *Run workflow* to wake it.)

How it protects people: nothing is stored until the address is confirmed from a link in an e-mail (the link only opens a page with a button, so mail scanners cannot confirm for you); at most 3 confirmation mails per address per 15 minutes and 10 per visitor per hour; one alert mail per hour per person unless something is Extreme; every mail has an unsubscribe link and the one-click `List-Unsubscribe` header; unsubscribing deletes everything. Only the e-mail, the home place and, if allowed, the last position are stored, in your own Upstash database.

Each run checks the people who were checked longest ago first, reuses a forecast for 3 hours and makes at most 40 weather calls, so Open-Meteo's daily allowance is not used up by e-mail checks.

## Data sources and limits

| Source | Used for | Notes |
|---|---|---|
| [Open-Meteo](https://open-meteo.com) | Forecast, air quality, geocoding, map grid | Free tier is **non-commercial** only; attribution is in the footer. About 10,000 calls/day fair use |
| [RainViewer](https://www.rainviewer.com) | Radar frames | Free tier is restricted (about 100 requests/min per IP); if their format changes, adjust `radar_frames` in `cirrus/openmeteo.py` and the tile URL in `public/static/map.js` |
| [OpenStreetMap](https://tile.openstreetmap.org) | Base map tiles; Nominatim names the place for "use my device location" | Public servers are for light use only (Nominatim: about 1 request a second) |
| [USGS](https://earthquake.usgs.gov/earthquakes/feed/) | Earthquakes, magnitude 4.5+ in the last 7 days | Free, no key |
| [GDACS](https://www.gdacs.org/) | Cyclones, floods, volcanoes, wildfires with alert levels | Free, no key. The query parameters are from GDACS's documentation; if they are refused, Cirrus asks for the default list and filters it |
| [NASA EONET](https://eonet.gsfc.nasa.gov/docs/v3) | Storms, volcanoes, floods, landslides, wildfires | Free, no key |
| [NASA GIBS](https://nasa-gibs.github.io/gibs-api-docs/) | Satellite basemap (previous day, Terra MODIS) | Free, no key; sharp up to zoom 9 and stretched beyond; gaps appear where the satellite did not pass |

**Call budget.** Each map grid point counts as one Open-Meteo call, per group of variables: the everyday layers share one group, and Storm risk and each height of Upper wind are fetched on their own only when you open them. The server keeps a daily budget (default 8000) and stops fetching when it is spent.
Change it with `CIRRUS_DAILY_BUDGET=5000 python run.py`. Responses are cached (forecast 10 min, air 30 min, geocode 24 h, radar 2 min, map grid 30 min).

**Going beyond the free limits.** Self-host Open-Meteo (it is open source) and point `FORECAST_URL`, `AIR_URL` and `GEOCODE_URL` in `cirrus/config.py` at your server,
or switch to a tile provider that allows your traffic.

## Deploy for free

The app needs a host that can run Python: a serverless platform (Vercel), a container host (Render, Cloud Run) or a VM. Pure static hosts (GitHub Pages, Netlify static, Cloudflare Pages) don't fit.
The same code runs everywhere: `run.py` reads `$PORT` and binds to `0.0.0.0` when it is set, `cirrus/wsgi.py` is a WSGI app, `/healthz` is a health-check URL, and a `vercel.json`, `Dockerfile` and `render.yaml` are included.

Free tiers change often. These were checked in November 2026; confirm on each provider's pricing page before relying on one.

### A. Vercel (Hobby plan: 100 GB bandwidth, no card)

1. Put the project on GitHub (commands in option B, step 1).
2. On https://vercel.com choose **Add New > Project**, import the repo, leave every setting at its default (Framework Preset: **Other**), and click **Deploy**.
   Or use the CLI: `npm i -g vercel`, then `vercel` inside the project folder, and `vercel --prod` to publish.
3. Your site is at `https://<project-name>.vercel.app`, with HTTPS, so "Use my location" works.

How the project is set up for Vercel:

| File | Job |
|---|---|
| `api/index.py` | The function Vercel runs. It exposes the WSGI `app` from `cirrus/wsgi.py` |
| `vercel.json` | Sends each route to that function (the route travels as `?__path=...`, so it works even if Vercel shows the function its own address); caches `/static/*` for a year; leaves tests and docs out of the bundle |
| `public/static/` | CSS and JS. Vercel serves everything under `public/` from its CDN without running Python |
| `.python-version` | Asks for Python 3.13 (the app also runs on 3.12, Vercel's default) |

Hobby plan numbers (Vercel docs, November 2026): 100 GB Fast Data Transfer, 10 GB Fast Origin Transfer (data your function sends to the CDN), 1,000,000 CDN requests, 1,000,000 function invocations and 4 Active CPU-hours a month.
If you pass a limit, the feature pauses for about 30 days rather than billing you. Hobby is for personal, non-commercial use, which also matches Open-Meteo's free terms.

**Caching is what makes this fit.** Vercel's CDN keeps responses that carry `s-maxage`, so repeat visitors don't run Python or call the weather API at all:
forecast pages are reused for 5 minutes, map data for 30 minutes, radar for 2 minutes, and CSS/JS (linked as `/static/map.js?v=<hash>`) for a year.
The map also asks for its weather grid in coarse, rounded steps, so people looking at the same area at the same zoom share one cached answer.
To check it, request the same page twice and look for `x-vercel-cache: HIT` in the response headers (`curl -I <url>`).

Good to know:
- Vercel functions are short-lived, so the in-memory cache and the daily call budget exist per function instance, not once for the whole site. The CDN caching above is your real protection for Open-Meteo's daily limit; `CIRRUS_DAILY_BUDGET` (set under Project Settings > Environment Variables) is only a per-instance guard.
- The first deploy of this project has not been tested on Vercel itself (the author had no access to it). If the build fails, open the deployment's build log; the usual suspects are the Python version and the `api/index.py` path.
- Adding a new page or API route to the app? Add a matching rewrite to `vercel.json` (a test fails if one is missing).
- If a page shows "Page not found" on Vercel, open `https://<your-site>.vercel.app/anything?__debug=1`. It shows what Vercel passed to the function (`PATH_INFO`, `QUERY_STRING`, `resolved`); send that to whoever is helping you.
- Run it locally the same way Vercel does: `vercel dev` (needs the CLI), or just `python run.py`.

### B. Render (no card, always the same Docker setup)

1. Put the project on GitHub:
   ```bash
   cd cirrus-weather
   git init && git add . && git commit -m "Cirrus weather"
   git branch -M main
   git remote add origin https://github.com/<your-user>/cirrus-weather.git
   git push -u origin main
   ```
2. On https://render.com sign in with GitHub, then **New > Blueprint**, pick the repo, and approve. (Or **New > Web Service > Docker**, instance type **Free**, health check path `/healthz`.)
3. You get an `https://cirrus-weather-xxxx.onrender.com` address. HTTPS works, so "Use my location" works too.

Free-plan limits: 750 instance-hours per month (enough for one service all month), sleeps after 15 minutes without traffic and takes about a minute to wake, 512 MB RAM, no persistent disk, and Render may restart it at any time.
To keep it awake, a free uptime monitor (for example UptimeRobot) can ping `/healthz` every 5 minutes. That uses the whole monthly allowance, and Render states free services are not meant for production.

**Bandwidth.** Render's free plan includes about 5 GB of outbound traffic a month (it was 100 GB until April 2026). The app is built to use little of it:
pages are about 3 KB compressed, browsers cache the scripts and stylesheet (and re-check with a 0-byte 304 reply), and the map downloads only the weather variables for the layer being viewed (the rest load when you click a point or switch layer).
Measured with demo data, a first visit to the Overview with the map is about 50 KB, so 5 GB is roughly 50,000 to 100,000 first visits (real weather data may compress a little worse). Map tiles and radar images go straight from OpenStreetMap and RainViewer to the visitor's browser, so they don't count.
If you don't add a payment method to Render, reaching the limit suspends the site until next month instead of billing you. If the site outgrows this, move to an always-on VM (option D) or put a free CDN in front of it.

### C. Google Cloud Run (card required, generous free allowance, scales to zero)

```bash
gcloud run deploy cirrus-weather --source . --region us-central1 --allow-unauthenticated --max-instances 2
```
Free per month: 2 million requests, 180,000 vCPU-seconds and 360,000 GiB-seconds. A billing account is required, so set a budget alert. Keep `--max-instances` low so a traffic spike can't run up a bill.

### D. Oracle Cloud Always Free VM (card + phone, always on, more work)

A real virtual machine that never sleeps. Since 15 June 2026 the free Arm allowance is 2 OCPUs and 12 GB RAM (it used to be 4 and 24), and capacity is often unavailable. Idle instances can be reclaimed.
On the VM: install Docker, then
```bash
docker build -t cirrus . && docker run -d --restart unless-stopped -p 80:8000 cirrus
```
For HTTPS, put Caddy in front with a free domain name.

### E. Quick demo from your own PC (no account, temporary)

With the app running locally, [Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/) give you a public link:
```bash
cloudflared tunnel --url http://localhost:8000
```
The `trycloudflare.com` address changes each time and stops when you close it. Good for showing friends, not for a permanent site.

### Not free any more

Fly.io and Heroku have no free tier for new accounts. Hugging Face **Docker** Spaces need a paid plan. Koyeb's free offer needs a card, and sources disagree on its current terms.

### Things to know when the site is public

- Open-Meteo is free for **non-commercial** use only. No ads or paid features on the site.
- Hosting platforms share IP addresses between many apps. If forecasts occasionally fail with "Weather service unavailable", the upstream API is probably limiting that IP; wait and retry.
- The daily call budget lives in memory, so it resets whenever the host restarts or wakes the app. Lower `CIRRUS_DAILY_BUDGET` if you want a safer cap.
- OpenStreetMap's public tiles are for light use. If traffic grows, switch to a provider that allows it (change the template in `public/static/map.js`).

## Project layout

```
run.py                 entry point
cirrus/
  config.py            URLs, cache TTLs, budget, grid limits
  openmeteo.py         API clients, TTL cache, budget, map grid builder
  demo.py              offline synthetic data (--demo)
  model.py             Weather wrapper (safe accessors, summaries)
  derive.py            WMO codes, Beaufort, AQI/UV categories, units, moon phase
  charts.py            server-side SVG charts
  icons.py             inline SVG icons
  views.py             HTML for every page
  hazards.py           earthquake / cyclone / flood / volcano / wildfire feeds
  alerts.py            alert rules for a place
  notify.py            e-mail subscribers, confirmation, the scheduled check
  store.py, mailer.py  Upstash Redis client (or in-memory), SMTP sender
  server.py            routing, validation, cache headers, gzip, static files
  wsgi.py              WSGI app (what Vercel runs)
api/index.py           Vercel entry point
vercel.json            Vercel routing and headers
public/static/         files the CDN serves directly
  style.css            dark Split Studio theme
  map.js               map engine and layers
  home.js              "Use my location"
  alerts.js            home setup, banner, alarm sound, notifications, e-mail sign-up
  sw.js, manifest.webmanifest, icon-*.png   service worker and install files
.github/workflows/alerts.yml   30-minute scheduler for e-mail alerts
tests/test_app.py      offline tests
```

## Tests

```bash
python -m unittest discover -s tests -v
```

The tests run offline using demo data.
