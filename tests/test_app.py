"""Offline smoke tests. Run:  python -m unittest discover -s tests -v"""

import gzip
import importlib.util
import json
import re
import sys
import threading
import unittest
import urllib.error
import urllib.request
from datetime import UTC, datetime
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote
from wsgiref.util import setup_testing_defaults

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cirrus import config, derive, openmeteo, server, wsgi  # noqa: E402

config.DEMO = True
LOC = "lat=12.9719&lon=77.5937&name=Bengaluru&region=Karnataka&country=India"


class Pages(unittest.TestCase):
    def get(self, path: str):
        return server.dispatch(path)

    def test_home_and_search(self):
        r = self.get("/")
        self.assertEqual(r.status, 200)
        self.assertIn(b"Popular places", r.body)
        r = self.get("/search?q=Bengaluru")
        self.assertEqual(r.status, 302)  # a single match goes straight to the forecast
        self.assertIn("/forecast/overview", r.headers["Location"])
        r = self.get("/search?q=zzzz")
        self.assertIn(b"No places found", r.body)

    def test_healthz(self):
        r = self.get("/healthz")
        self.assertEqual((r.status, r.body), (200, b"ok"))

    def test_every_forecast_page_renders(self):
        for page in ("overview", "hourly", "daily", "map", "details", "air"):
            for units in ("", "&u=f"):
                r = self.get(f"/forecast/{page}?{LOC}{units}")
                self.assertEqual(r.status, 200, page)
                text = r.body.decode()
                self.assertIn("Bengaluru", text, page)
                self.assertNotIn("Traceback", text)
                self.assertNotIn("None", text.replace("No data", ""), f"{page}: stray None in output")
                if page in ("overview", "map"):
                    self.assertIn('id="mapcard"', text)
                    self.assertIn("/static/map.js", text)

    def test_details_has_extra_weather_info(self):
        text = self.get(f"/forecast/details?{LOC}").body.decode()
        for needle in ("Wind", "Pressure", "Dew point", "Cloud cover", "Visibility", "Precipitation",
                       "Storm potential", "Freezing level", "Soil", "Evapotranspiration", "Sunshine"):
            self.assertIn(needle, text)

    def test_air_page_has_uv_sun_moon(self):
        text = self.get(f"/forecast/air?{LOC}").body.decode()
        for needle in ("Air quality", "UV index today", "Sunrise", "Moon", "PM2.5"):
            self.assertIn(needle, text)

    def test_bad_input_is_rejected(self):
        self.assertEqual(self.get("/forecast/overview?lat=abc&lon=1").status, 400)
        self.assertEqual(self.get("/forecast/overview?lat=99&lon=1").status, 400)
        self.assertEqual(self.get("/forecast/nope?lat=1&lon=1").status, 404)
        self.assertEqual(self.get("/api/field?south=1&west=1").status, 400)

    def test_names_are_escaped(self):
        text = self.get("/forecast/overview?lat=1&lon=1&name=%3Cscript%3Ealert(1)%3C/script%3E").body.decode()
        self.assertNotIn("<script>alert(1)", text)

    def test_static_path_traversal_blocked(self):
        self.assertEqual(self.get("/static/../cirrus/config.py").status, 404)
        self.assertEqual(self.get("/static/%2e%2e/run.py").status, 404)
        self.assertEqual(self.get("/static/map.js").status, 200)


class MapApi(unittest.TestCase):
    def test_field_shape(self):
        r = server.dispatch("/api/field?south=8&west=72&north=18&east=84&zoom=6")
        self.assertEqual(r.status, 200)
        d = json.loads(r.body)
        self.assertEqual(len(d["times"]), config.FIELD_HOURS)
        n = d["nx"] * d["ny"]
        self.assertLessEqual(n, config.MAX_GRID_POINTS + 40)
        for name in openmeteo.CORE_VARS:
            self.assertEqual(len(d["vars"][name]), config.FIELD_HOURS)
            self.assertEqual(len(d["vars"][name][0]), n)
        # the grid must cover the requested view
        self.assertLessEqual(d["west"], 72)
        self.assertGreaterEqual(d["west"] + (d["nx"] - 1) * d["dlon"], 84)
        self.assertLessEqual(d["south"], 8)
        self.assertGreaterEqual(d["south"] + (d["ny"] - 1) * d["dlat"], 18)

    def test_field_snaps_so_panning_reuses_cache(self):
        a = json.loads(server.dispatch("/api/field?south=8&west=72&north=18&east=84").body)
        b = json.loads(server.dispatch("/api/field?south=8.1&west=72.2&north=18.1&east=84.1").body)
        self.assertEqual((a["south"], a["west"], a["nx"], a["ny"]), (b["south"], b["west"], b["nx"], b["ny"]))

    def test_spacing_gets_finer_when_zoomed_in(self):
        self.assertLess(openmeteo.pick_spacing(3, 4), openmeteo.pick_spacing(40, 60))

    def test_budget_blocks_when_spent(self):
        b = openmeteo.Budget(100)
        self.assertTrue(b.spend(60))
        self.assertFalse(b.spend(60))
        self.assertTrue(b.spend(40))

    def test_field_vars_subset(self):
        q = "/api/field?south=8&west=72&north=18&east=84"
        d = json.loads(server.dispatch(q + "&vars=wind_speed_10m,wind_direction_10m").body)
        self.assertEqual(set(d["vars"]), {"wind_speed_10m", "wind_direction_10m"})
        self.assertEqual(server.dispatch(q + "&vars=bogus").status, 400)
        full = json.loads(server.dispatch(q).body)
        self.assertEqual(set(full["vars"]), set(openmeteo.CORE_VARS))  # no vars param: the everyday layers
        self.assertLess(len(server.dispatch(q + "&vars=temperature_2m").body), len(server.dispatch(q).body) / 4)

    def test_radar_endpoint(self):
        d = json.loads(server.dispatch("/api/radar").body)
        self.assertIn("frames", d)


class Caching(unittest.TestCase):
    def test_static_files_get_etag_and_304(self):
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        url = f"http://127.0.0.1:{httpd.server_address[1]}/static/map.js"
        with urllib.request.urlopen(url) as r:
            etag = r.headers["ETag"]
            self.assertIn("max-age", r.headers["Cache-Control"])
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(urllib.request.Request(url, headers={"If-None-Match": etag}))
        self.assertEqual(cm.exception.code, 304)
        self.assertEqual(cm.exception.read(), b"")


class VercelApp(unittest.TestCase):
    """The WSGI app that Vercel runs, and the files Vercel needs."""

    def call(self, path: str, method: str = "GET", **headers):
        environ: dict = {}
        setup_testing_defaults(environ)
        raw, _, qs = path.partition("?")
        environ.update(REQUEST_METHOD=method, PATH_INFO=unquote(raw), QUERY_STRING=qs, **headers)
        seen: dict = {}

        def start(status, hdrs):
            seen["status"], seen["headers"] = status, dict(hdrs)

        body = b"".join(wsgi.app(environ, start))
        return seen["status"], seen["headers"], body

    def test_healthz_and_methods(self):
        self.assertEqual(self.call("/healthz")[::2], ("200 OK", b"ok"))
        self.assertTrue(self.call("/", "POST")[0].startswith("405"))

    def test_forecast_page_is_gzipped_and_cdn_cacheable(self):
        status, headers, body = self.call(f"/forecast/overview?{LOC}", HTTP_ACCEPT_ENCODING="gzip")
        self.assertEqual(status, "200 OK")
        self.assertEqual(headers["Content-Encoding"], "gzip")
        self.assertIn("s-maxage=300", headers["Cache-Control"])
        self.assertIn("Bengaluru", gzip.decompress(body).decode())

    def test_head_has_length_but_no_body(self):
        status, headers, body = self.call(f"/forecast/hourly?{LOC}", "HEAD")
        self.assertEqual((status, body), ("200 OK", b""))
        self.assertGreater(int(headers["Content-Length"]), 1000)

    def test_errors_are_never_cached(self):
        for path in ("/forecast/overview?lat=abc&lon=1", "/forecast/nope?lat=1&lon=1", "/api/field?south=1"):
            status, headers, _ = self.call(path)
            self.assertFalse(status.startswith("200"), path)
            self.assertEqual(headers["Cache-Control"], "no-store", path)

    def test_assets_are_versioned_and_immutable(self):
        html = self.call(f"/forecast/overview?{LOC}")[2].decode()
        found = re.findall(r'(?:src|href)="(/static/[^"]+\?v=[0-9a-f]{10})"', html)
        self.assertGreaterEqual(len(found), 2)  # style.css and map.js
        status, headers, body = self.call(found[0].split("?")[0] + "?v=" + found[0].split("=")[1])
        self.assertEqual(status, "200 OK")
        self.assertIn("immutable", headers["Cache-Control"])
        status, _, body = self.call(found[0], HTTP_IF_NONE_MATCH=headers["ETag"])
        self.assertEqual((status, body), ("304 Not Modified", b""))

    def test_api_responses_can_be_cached_by_the_cdn(self):
        q = "/api/field?south=8&west=72&north=18&east=84&vars=temperature_2m"
        self.assertIn("s-maxage=1800", self.call(q)[1]["Cache-Control"])
        self.assertIn("s-maxage=120", self.call("/api/radar")[1]["Cache-Control"])

    def vercel_call(self, route: str, original_query: str = "", **headers):
        """What the function sees when Vercel rewrites a route: its own internal path, with the route in ?__path=."""
        query = f"__path={route}" + (f"&{original_query}" if original_query else "")
        return self.call(f"/api/index?{query}", **headers)

    def test_route_survives_when_vercel_hides_the_original_path(self):
        self.assertEqual(self.vercel_call("/healthz")[::2], ("200 OK", b"ok"))
        status, headers, body = self.vercel_call("/forecast/overview", LOC, HTTP_ACCEPT_ENCODING="gzip")
        self.assertEqual(status, "200 OK")
        self.assertIn("Bengaluru", gzip.decompress(body).decode())  # the visitor's own query string came through too
        self.assertEqual(self.vercel_call("/api/radar")[0], "200 OK")
        self.assertTrue(self.vercel_call("/not-found")[0].startswith("404"))
        # ?__path= is for the platform, so it must not leak into the page's own parameters
        status, _, body = self.vercel_call("/forecast/hourly", LOC + "&__debug=0")
        self.assertEqual(status, "200 OK")

    def test_vercel_rewrites_cover_every_route(self):
        rewrites = {r["source"]: r["destination"] for r in json.loads((ROOT / "vercel.json").read_text())["rewrites"]}
        routes = ["/", "/healthz", "/search", "/api/field", "/api/radar"] + [f"/forecast/{p}" for p in server.FORECAST_PAGES]
        for route in routes:
            self.assertEqual(rewrites.get(route), f"/api/index?__path={route}", route)
        self.assertEqual(rewrites["/(.*)"], "/api/index?__path=/not-found")  # anything else gets the app's own 404

    def test_debug_page_shows_what_the_platform_passed(self):
        status, headers, body = self.call("/api/index?__path=/healthz&__debug=1")
        info = json.loads(body)
        self.assertEqual((status, info["PATH_INFO"], info["resolved"]), ("200 OK", "/api/index", "/healthz"))
        self.assertEqual(headers["Cache-Control"], "no-store")

    def test_vercel_files(self):
        spec = importlib.util.spec_from_file_location("vercel_entry", ROOT / "api" / "index.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertIs(module.app, wsgi.app)
        cfg = json.loads((ROOT / "vercel.json").read_text())
        self.assertIn("api/index.py", cfg["functions"])
        for name in ("map.js", "style.css", "home.js"):
            self.assertTrue((ROOT / "public" / "static" / name).is_file(), name)
        self.assertTrue((ROOT / ".python-version").read_text().startswith("3.13"))


class Helpers(unittest.TestCase):
    def test_compass_and_beaufort(self):
        self.assertEqual(derive.compass(0), "N")
        self.assertEqual(derive.compass(270), "W")
        self.assertEqual(derive.compass(359), "N")
        self.assertEqual(derive.beaufort(0), "Calm")
        self.assertEqual(derive.beaufort(130), "Hurricane force")

    def test_units(self):
        self.assertEqual(derive.Units(True).temp(0), "32°")
        self.assertEqual(derive.Units().temp(-0.2), "0°")
        self.assertEqual(derive.Units().speed(10), "10 km/h")
        self.assertEqual(derive.Units(True).speed(100), "62 mph")

    def test_moon_reference_points(self):
        new = derive.moon(datetime(2000, 1, 6, 18, 14, tzinfo=UTC))
        self.assertLess(new["illumination"], 0.01)
        full = derive.moon(datetime(2000, 1, 21, 4, 40, tzinfo=UTC))  # real full moon
        self.assertGreater(full["illumination"], 0.97)

    def test_categories(self):
        self.assertEqual(derive.us_aqi_category(62), "Moderate")
        self.assertEqual(derive.uv_category(9), "Very high")
        self.assertEqual(derive.describe(95)[1], "storm")
        self.assertEqual(derive.describe(0, is_day=False)[1], "moon")


if __name__ == "__main__":
    unittest.main()
