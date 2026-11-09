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

from . import config, demo, openmeteo, views
from .derive import Units
from .model import Weather
from .openmeteo import UpstreamError
from .views import Place

POPULAR = [Place(la, lo, n, a, c) for n, a, c, la, lo, _ in demo.CITIES[:9]]
FORECAST_PAGES = {"overview", "hourly", "daily", "map", "details", "air"}
MAP_LAYERS = {k for k, _ in views.MAP_LAYERS}


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


def _static(rel: str, versioned: bool = False) -> Response:
    root = config.STATIC_DIR.resolve()
    target = (root / rel).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        return Response(404, b"Not found", "text/plain; charset=utf-8")
    ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    if ctype.startswith("text/") or ctype in ("application/javascript", "text/javascript"):
        ctype += "; charset=utf-8"
    body = target.read_bytes()
    etag = '"' + hashlib.sha1(body).hexdigest()[:20] + '"'
    # Pages link to files as /static/x.js?v=<hash>: the address changes whenever the file does, so a year is safe.
    # A plain /static/x.js is reused for 5 minutes, then re-checked and answered with a tiny 304.
    cache = "public, max-age=31536000, immutable" if versioned else "public, max-age=300"
    return Response(200, body, ctype, {"Cache-Control": cache, "ETag": etag})


def dispatch(raw_path: str) -> Response:
    url = urlsplit(raw_path)
    path, q = url.path, parse_qs(url.query)
    units = Units(imperial=(q.get("u") or [""])[0] == "f")
    is_api = path.startswith("/api/")
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
            data = openmeteo.field(_num(q, "south", -90, 90), _num(q, "west", -180, 180), _num(q, "north", -90, 90),
                                   _num(q, "east", -180, 180), _num(q, "zoom", 0, 24, 0.0))
            wanted = [v for v in _text(q, "vars", 200).split(",") if v]
            if wanted:  # send only the variables the map layer needs: the grid is by far the biggest download
                unknown = [v for v in wanted if v not in openmeteo.FIELD_VARS]
                if unknown:
                    raise BadRequest(f"Unknown variable: {unknown[0][:40]}")
                data = {**data, "vars": {k: data["vars"][k] for k in openmeteo.FIELD_VARS if k in wanted}}
            return _json(data, cache=_cache(300, 1800, 600))
        if path == "/api/radar":
            return _json(openmeteo.radar_frames(), cache=_cache(60, 120, 120))
        if path.startswith("/static/"):
            return _static(path.removeprefix("/static/"), versioned=bool(q.get("v")))
        return _html(views.error_page("Page not found", "That page does not exist.", units), 404)
    except BadRequest as exc:
        if is_api:
            return _json({"error": str(exc)}, 400)
        return _html(views.error_page("Check the address", str(exc), units), 400)
    except UpstreamError as exc:
        if is_api:
            return _json({"error": str(exc)}, 502)
        return _html(views.error_page("Weather service unavailable", f"{exc} Try again in a moment.", units), 502)


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

    def _serve(self, send_body: bool) -> None:
        status, headers, body = finalize(dispatch(self.path), accept_encoding=self.headers.get("Accept-Encoding", ""),
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
