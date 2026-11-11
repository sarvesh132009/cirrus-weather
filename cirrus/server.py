"""Tiny standard-library HTTP server: routing, static files and the JSON API used by the map."""

from __future__ import annotations

import gzip
import hashlib
import json
import mimetypes
import sys
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from datetime import UTC, datetime

from . import alerts, config, demo, hazards, notify, openmeteo, views
from .derive import Units
from .model import Weather
from .openmeteo import UpstreamError
from .store import StoreError
from .views import Place

POPULAR = [Place(la, lo, n, a, c) for n, a, c, la, lo, _ in demo.CITIES[:9]]
FORECAST_PAGES = {"overview", "hourly", "daily", "map", "details", "air"}
MAP_LAYERS = {k for k, _ in views.MAP_LAYERS}
POST_ONLY = {"/api/subscribe", "/api/subscribe/update", "/api/confirm", "/api/unsubscribe"}
POST_TOO = {"/unsubscribe"}      # a page for people, and the one-click POST that mail apps send
MAX_BODY = 16_384


@dataclass
class Response:
    status: int = 200
    body: bytes = b""
    content_type: str = "text/html; charset=utf-8"
    headers: dict = field(default_factory=dict)


class BadRequest(ValueError):
    pass


def _num(q: dict, name: str, lo: float, hi: float, default: float | None = None) -> float:
    raw = (q.get(name) or [""])[0]
    if raw == "":
        if default is None:
            raise BadRequest(f"Missing parameter: {name}")
        return default
    try:
        value = float(raw)
    except ValueError:
        raise BadRequest(f"{name} must be a number") from None
    if not lo <= value <= hi:  # also rejects NaN
        raise BadRequest(f"{name} must be between {lo:g} and {hi:g}")
    return value


def _text(q: dict, name: str, maxlen: int = 80) -> str:
    return " ".join((q.get(name) or [""])[0].split())[:maxlen]


def _place(q: dict) -> Place:
    return Place(_num(q, "lat", -90, 90), _num(q, "lon", -180, 180), _text(q, "name") or "Selected point",
                 _text(q, "region"), _text(q, "country"))


def _cache(browser: int, cdn: int = 0, swr: int = 0) -> str:
    """Cache-Control for a response anyone may share. `s-maxage` is for CDNs (Vercel's strips it before the browser
    sees it) and is ignored by browsers, so it is harmless on hosts without a CDN."""
    parts = ["public", f"max-age={browser}"]
    if cdn:
        parts.append(f"s-maxage={cdn}")
        if swr:
            parts.append(f"stale-while-revalidate={swr}")
    return ", ".join(parts)


NO_STORE = "no-store"   # errors and anything that must never be cached


def _html(body: str, status: int = 200, cache: str = NO_STORE) -> Response:
    return Response(status, body.encode(), headers={"Cache-Control": cache})


def _json(data, status: int = 200, cache: str = NO_STORE) -> Response:
    return Response(status, json.dumps(data, separators=(",", ":")).encode(), "application/json; charset=utf-8",
                    {"Cache-Control": cache})


def _json_body(body: bytes, headers: dict) -> dict:
    """POST bodies are JSON from our own pages. Requiring that content type also means other websites cannot make a
    visitor's browser submit them (a cross-site request cannot send JSON without our permission)."""
    if (headers.get("content-type") or "").split(";")[0].strip().lower() != "application/json":
        raise BadRequest("Send JSON.")
    if len(body) > MAX_BODY:
        raise BadRequest("Request too large.")
    try:
        data = json.loads(body or b"{}")
    except ValueError:
        raise BadRequest("Bad JSON.") from None
    if not isinstance(data, dict):
        raise BadRequest("Send a JSON object.")
    return data


def _client_ip(headers: dict) -> str:
    fwd = (headers.get("x-forwarded-for") or "").split(",")[0].strip()
    return fwd or headers.get("x-real-ip", "") or headers.get("remote-addr", "")


def _static(rel: str, versioned: bool = False) -> Response:
    root = config.STATIC_DIR.resolve()
    target = (root / rel).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        return Response(404, b"Not found", "text/plain; charset=utf-8")
    ctype = ({".webmanifest": "application/manifest+json"}.get(target.suffix) or mimetypes.guess_type(target.name)[0]
             or "application/octet-stream")
    if ctype.startswith("text/") or ctype in ("application/javascript", "text/javascript"):
        ctype += "; charset=utf-8"
    body = target.read_bytes()
    etag = '"' + hashlib.sha1(body).hexdigest()[:20] + '"'
    # Pages link to files as /static/x.js?v=<hash>: the address changes whenever the file does, so a year is safe.
    # A plain /static/x.js is reused for 5 minutes, then re-checked and answered with a tiny 304.
    cache = "public, max-age=31536000, immutable" if versioned else "public, max-age=300"
    extra = {"Service-Worker-Allowed": "/"} if rel == "sw.js" else {}   # lets the worker cover the whole site
    return Response(200, body, ctype, {"Cache-Control": cache, "ETag": etag, **extra})


def dispatch(raw_path: str, *, method: str = "GET", body: bytes = b"", headers: dict | None = None) -> Response:
    """Route one request. `headers` has lower-case names. GET and HEAD are served by every route; POST only by a few."""
    url = urlsplit(raw_path)
    path, q = url.path, parse_qs(url.query)
    units = Units(imperial=(q.get("u") or [""])[0] == "f")
    is_api = path.startswith("/api/")
    headers = headers or {}
    if method == "POST" and path not in POST_ONLY | POST_TOO:
        return Response(405, b"Method not allowed", "text/plain; charset=utf-8", {"Allow": "GET, HEAD", "Cache-Control": NO_STORE})
    if method != "POST" and path in POST_ONLY:
        return _json({"error": "Use POST."}, 405) if is_api else Response(405, b"Method not allowed", "text/plain; charset=utf-8")
    try:
        if path == "/healthz":  # for hosting health checks and uptime pingers; makes no upstream calls
            return Response(200, b"ok", "text/plain; charset=utf-8", {"Cache-Control": "no-store"})
        if path == "/":
            return _html(views.home(units, POPULAR), cache=_cache(300, 3600, 3600))
        if path == "/search":
            query = _text(q, "q")
            results = openmeteo.geocode(query)
            if len(results) == 1:
                r = results[0]
                target = views.page_url("overview", Place(r["lat"], r["lon"], r["name"], r.get("admin1", ""), r.get("country", "")), units)
                return Response(302, b"", headers={"Location": target, "Cache-Control": _cache(300, 3600)})
            return _html(views.search_results(query, results, units), cache=_cache(300, 3600))
        if path.startswith("/forecast/"):
            page = path.removeprefix("/forecast/").strip("/")
            if page not in FORECAST_PAGES:
                return _html(views.error_page("Page not found", "That page does not exist.", units), 404)
            place = _place(q)
            wx = Weather(openmeteo.forecast(place.lat, place.lon), units)
            if page == "overview":
                body = views.overview(place, units, wx)
            elif page == "hourly":
                body = views.hourly(place, units, wx)
            elif page == "daily":
                body = views.daily(place, units, wx)
            elif page == "details":
                body = views.details(place, units, wx)
            elif page == "air":
                try:
                    aq = openmeteo.air_quality(place.lat, place.lon)
                except UpstreamError:
                    aq = None
                body = views.air(place, units, wx, aq)
            else:
                layer = _text(q, "layer", 12)
                body = views.map_page(place, units, wx, layer if layer in MAP_LAYERS else "wind")
            scripts = ("map.js",) if page in ("overview", "map") else ()
            title = f"{place.name} · {dict(views.PAGES)[page]}"
            # The CDN may reuse a forecast page for 5 minutes (then refresh it quietly), which spares the weather API.
            return _html(views.layout(title, body, place=place, units=units, page=page, scripts=scripts),
                         cache=_cache(60, 300, 300))
        if path == "/api/field":
            wanted = [v for v in _text(q, "vars", 300).split(",") if v]   # only what the layer needs: the grid is the biggest download
            unknown = [v for v in wanted if v not in openmeteo.FIELD_VARS]
            if unknown:
                raise BadRequest(f"Unknown variable: {unknown[0][:40]}")
            data = openmeteo.field(_num(q, "south", -90, 90), _num(q, "west", -180, 180), _num(q, "north", -90, 90),
                                   _num(q, "east", -180, 180), _num(q, "zoom", 0, 24, 0.0), wanted or None)
            if wanted:
                data = {**data, "vars": {k: data["vars"][k] for k in openmeteo.FIELD_VARS if k in wanted}}
            return _json(data, cache=_cache(300, 1800, 600))
        if path == "/api/radar":
            return _json(openmeteo.radar_frames(), cache=_cache(60, 120, 120))
        if path == "/api/config":
            return _json({"cloud": notify.enabled(), "demo": config.DEMO}, cache=_cache(60, 300, 300))
        if path == "/api/geocode":
            return _json({"results": openmeteo.geocode(_text(q, "q"))}, cache=_cache(300, 3600, 3600))
        if path == "/api/reverse":
            return _json(openmeteo.reverse(_num(q, "lat", -90, 90), _num(q, "lon", -180, 180)), cache=_cache(3600, 86400, 86400))
        if path == "/api/hazards":
            return _json(hazards.feed(), cache=_cache(60, 300, 300))
        if path == "/api/alerts":
            return _alerts(q, units)
        if path == "/api/subscribe":
            b = _json_body(body, headers)
            return _json(notify.subscribe(str(b.get("email", "")), b.get("home"), b.get("minLevel", 3), _client_ip(headers)))
        if path == "/api/subscribe/update":
            b = _json_body(body, headers)
            return _json(notify.update(str(b.get("token", "")), b))
        if path == "/api/subscribe/status":
            return _json(notify.confirmation_status(_text(q, "pid", 60)))
        if path == "/api/confirm":
            return _json(notify.confirm(str(_json_body(body, headers).get("t", ""))))
        if path == "/api/unsubscribe":
            return _json(notify.unsubscribe(str(_json_body(body, headers).get("token", ""))))
        if path == "/api/cron/alerts":   # run by a scheduler (see README); only with the secret
            if not notify.authorized(headers.get("authorization", "")):
                return _json({"error": "Not authorised."}, 401)
            return _json(notify.run_checks())
        if path == "/confirm":
            token = _text(q, "t", 80)
            return _html(views.notice("Confirm your e-mail", "One tap and Cirrus will e-mail you when weather or a disaster threatens your home.",
                                      action="confirm", token=token, button="Confirm my e-mail") if token else
                         views.error_page("Check the address", "This confirmation link is incomplete.", units), 200 if token else 400)
        if path == "/unsubscribe":
            token = _text(q, "t", 80)
            if method == "POST":   # one-click unsubscribe from a mail app
                notify.unsubscribe(token)
                return Response(200, b"Unsubscribed", "text/plain; charset=utf-8", {"Cache-Control": NO_STORE})
            return _html(views.notice("Stop alert e-mails", "This removes your e-mail and home from Cirrus.", action="unsubscribe",
                                      token=token, button="Unsubscribe") if token else
                         views.error_page("Check the address", "This link is incomplete.", units), 200 if token else 400)
        if path.startswith("/static/"):
            return _static(path.removeprefix("/static/"), versioned=bool(q.get("v")))
        return _html(views.error_page("Page not found", "That page does not exist.", units), 404)
    except BadRequest as exc:
        if is_api:
            return _json({"error": str(exc)}, 400)
        return _html(views.error_page("Check the address", str(exc), units), 400)
    except notify.NotifyError as exc:
        return _json({"error": exc.message}, exc.status) if is_api else _html(views.error_page("Something went wrong", exc.message, units), exc.status)
    except StoreError as exc:
        return _json({"error": str(exc)}, 503) if is_api else _html(views.error_page("Service unavailable", str(exc), units), 503)
    except UpstreamError as exc:
        if is_api:
            return _json({"error": str(exc)}, 502)
        return _html(views.error_page("Weather service unavailable", f"{exc} Try again in a moment.", units), 502)


def _alerts(q: dict, units: Units) -> Response:
    """Alerts for one place: forecast rules plus nearby earthquakes, cyclones, floods and so on. Failures of one source
    only thin the answer; if every source fails the caller gets an error."""
    lat, lon = round(_num(q, "lat", -90, 90), 2), round(_num(q, "lon", -180, 180), 2)
    failed, wx, aq, events = [], None, None, []
    try:
        wx = Weather(openmeteo.forecast(lat, lon), units)
        try:
            aq = openmeteo.air_quality(lat, lon)
        except UpstreamError:
            pass
    except UpstreamError:
        failed.append("forecast")
    try:
        events = hazards.feed()["events"]
    except UpstreamError:
        failed.append("events")
    if len(failed) == 2:
        raise UpstreamError("The weather and hazard services are unavailable.")
    found = alerts.for_place(lat, lon, wx, events, aq, units)
    return _json({"place": {"lat": lat, "lon": lon, "name": _text(q, "name") or "Selected point"},
                  "generated": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "top": alerts.top_level(found), "alerts": found,
                  "partial": failed, "disclaimer": alerts.DISCLAIMER}, cache=_cache(60, 300, 300))


_COMPRESSIBLE = ("text/", "application/json", "application/javascript")
_SECURITY_HEADERS = {"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
                     "Referrer-Policy": "strict-origin-when-cross-origin"}


def finalize(resp: Response, *, accept_encoding: str = "", if_none_match: str = "",
             send_body: bool = True) -> tuple[int, dict, bytes]:
    """Turn a Response into (status, headers, body): 304 for an unchanged file, gzip for large text.
    Used by both the local server below and the WSGI app that Vercel runs (cirrus/wsgi.py)."""
    etag = resp.headers.get("ETag")
    if resp.status == 200 and etag:
        sent = {t.strip().removeprefix("W/") for t in if_none_match.split(",")}
        if etag in sent:
            resp = Response(304, b"", resp.content_type, {k: resp.headers[k] for k in ("ETag", "Cache-Control")})
    body = resp.body
    headers = {"Content-Type": resp.content_type, **_SECURITY_HEADERS, **resp.headers}
    if len(body) > 1024 and "gzip" in accept_encoding and resp.content_type.startswith(_COMPRESSIBLE):
        body = gzip.compress(body, 5)
        headers["Content-Encoding"] = "gzip"
        headers["Vary"] = "Accept-Encoding"
    if resp.status != 304:
        headers["Content-Length"] = str(len(body))
    return resp.status, headers, (body if send_body else b"")


class Handler(BaseHTTPRequestHandler):
    server_version = "Cirrus/0.1"

    def do_GET(self) -> None:
        self._serve(True)

    def do_HEAD(self) -> None:
        self._serve(False)

    def do_POST(self) -> None:
        self._serve(True, "POST")

    def _serve(self, send_body: bool, method: str = "GET") -> None:
        hdrs = {k.lower(): v for k, v in self.headers.items()}
        hdrs["remote-addr"] = self.client_address[0]
        body = b""
        if method == "POST":
            length = int(hdrs.get("content-length") or 0) if (hdrs.get("content-length") or "0").isdigit() else MAX_BODY + 1
            body = self.rfile.read(min(length, MAX_BODY + 1))
        status, headers, body = finalize(dispatch(self.path, method=method, body=body, headers=hdrs),
                                         accept_encoding=self.headers.get("Accept-Encoding", ""),
                                         if_none_match=self.headers.get("If-None-Match", ""), send_body=send_body)
        try:
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            if body:
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, format: str, *args) -> None:  # noqa: A002 - signature set by the base class
        sys.stderr.write(f"{self.address_string()} {format % args}\n")


def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    mode = "DEMO data (offline)" if config.DEMO else "live Open-Meteo + RainViewer"
    print(f"Cirrus is running on http://{host}:{port}  [{mode}]  (Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()
