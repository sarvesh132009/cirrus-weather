"""Tests for hazards, alert rules, the alert/hazard APIs and the e-mail subscription flow (all offline)."""

import json
import re
import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cirrus import alerts, config, hazards, mailer, notify, openmeteo, server  # noqa: E402
from cirrus.derive import Units  # noqa: E402
from cirrus.model import Weather  # noqa: E402

config.DEMO = True
JSON = {"content-type": "application/json"}


def call(path, method="GET", data=None, headers=None):
    body = json.dumps(data).encode() if data is not None else b""
    r = server.dispatch(path, method=method, body=body, headers={**(JSON if data is not None else {}), **(headers or {})})
    return r.status, (json.loads(r.body) if r.content_type.startswith("application/json") else r.body.decode())


def forecast_with(**series):
    """A demo forecast with some hourly series replaced from the current hour on."""
    d = openmeteo.forecast(12.97, 77.59)
    start = Weather(d, Units()).now_i
    for name, vals in series.items():
        arr = d["hourly"][name]
        for k, v in enumerate(vals):
            arr[start + k] = v
    return Weather(d, Units())


class Parsers(unittest.TestCase):
    def test_usgs(self):
        data = {"features": [{"id": "us1", "properties": {"mag": 6.4, "place": "10 km S of Somewhere", "time": 1_760_000_000_000, "tsunami": 1, "url": "https://x.test/e"},
                              "geometry": {"coordinates": [92.9, 11.9, 30.0]}}, {"id": "bad", "properties": {"mag": None}, "geometry": {}}]}
        ev = hazards.parse_usgs(data)
        self.assertEqual(len(ev), 1)
        self.assertEqual((ev[0]["kind"], ev[0]["level"], ev[0]["radius_km"]), ("earthquake", 3, 300))
        self.assertIn("tsunami", ev[0]["detail"])

    def test_gdacs(self):
        now = datetime(2026, 11, 10, tzinfo=UTC)
        data = {"features": [
            {"geometry": {"coordinates": [85.4, 14.6]}, "properties": {"eventtype": "TC", "eventid": 7, "alertlevel": "Red", "iscurrent": "true", "name": "Cyclone X",
                                                                      "datemodified": "2026-11-09T12:00:00", "severitydata": {"severitytext": "Winds 150 km/h"}, "url": {"report": "https://g.test/r"}}},
            {"geometry": {"coordinates": [1, 1]}, "properties": {"eventtype": "EQ", "eventid": 1, "alertlevel": "Red", "iscurrent": "true"}},
            {"geometry": {"coordinates": [2, 2]}, "properties": {"eventtype": "FL", "eventid": 2, "alertlevel": "Green", "iscurrent": "false", "todate": "2026-10-01T00:00:00"}}]}
        ev = hazards.parse_gdacs(data, now)
        self.assertEqual([(e["kind"], e["level"]) for e in ev], [("cyclone", 4)])
        self.assertEqual(ev[0]["url"], "https://g.test/r")

    def test_eonet_and_merge(self):
        data = {"events": [{"id": "E1", "title": "Typhoon Y", "categories": [{"id": "severeStorms"}], "sources": [{"url": "https://n.test/1"}],
                            "geometry": [{"date": "2026-11-09T00:00:00Z", "type": "Point", "coordinates": [85.5, 14.7], "magnitudeValue": 70}]},
                           {"id": "E2", "title": "Fire", "categories": [{"id": "wildfires"}], "geometry": [{"date": "2026-11-09T00:00:00Z", "type": "Point", "coordinates": [30, 40]}]}]}
        eo = hazards.parse_eonet(data)
        self.assertEqual({e["kind"]: e["level"] for e in eo}, {"cyclone": 3, "wildfire": 1})
        gd = [{"id": "g", "kind": "cyclone", "level": 3, "lat": 14.6, "lon": 85.4, "time": "2026-11-09T00:00:00Z", "radius_km": 600}]
        merged = hazards.merge([], gd, eo)
        self.assertEqual(sorted(e["id"] for e in merged), ["eonet:E2", "g"])   # the NASA cyclone duplicates the GDACS one


class Rules(unittest.TestCase):
    def test_quiet_forecast_has_no_serious_alert(self):
        self.assertTrue(all(a["level"] <= 2 for a in alerts.from_forecast(forecast_with(wind_gusts_10m=[20] * 6, apparent_temperature=[30] * 6))))

    def test_gusts_and_heat_levels(self):
        found = {a["kind"]: a for a in alerts.from_forecast(forecast_with(wind_gusts_10m=[40, 95, 60], apparent_temperature=[47, 48, 40]))}
        self.assertEqual(found["wind"]["level"], 3)       # 95 km/h is storm force
        self.assertEqual(found["heat"]["level"], 3)       # feels like 48 C
        self.assertIn("95", found["wind"]["detail"])
        self.assertTrue(found["wind"]["id"].startswith("fx:wind:3:"))

    def test_rain_uses_24h_total(self):
        found = {a["kind"]: a for a in alerts.from_forecast(forecast_with(precipitation=[10] * 12 + [0] * 12))}
        self.assertEqual(found["rain"]["level"], 3)       # 120 mm in 12 h is "very heavy"

    def test_thunder_and_air(self):
        found = {a["kind"]: a for a in alerts.from_forecast(forecast_with(weather_code=[96, 96]), aq={"current": {"us_aqi": 320}})}
        self.assertEqual((found["storm"]["level"], found["air"]["level"]), (3, 3))

    def test_hazard_distance_and_age(self):
        now = datetime.now(UTC)
        iso = lambda h: (now - timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
        ev = [{"id": "a", "kind": "earthquake", "title": "near", "level": 3, "lat": 11.9, "lon": 92.9, "time": iso(1), "radius_km": 300, "src": "USGS"},
              {"id": "b", "kind": "earthquake", "title": "old", "level": 3, "lat": 11.9, "lon": 92.9, "time": iso(70), "radius_km": 300, "src": "USGS"},
              {"id": "c", "kind": "cyclone", "title": "far", "level": 3, "lat": 14.6, "lon": 85.4, "time": iso(2), "radius_km": 600, "src": "GDACS"}]
        got = alerts.from_hazards(11.95, 92.95, ev, Units(), now)
        self.assertEqual([a["title"] for a in got], ["near"])
        self.assertEqual(got[0]["level"], 3)
        self.assertEqual(alerts.from_hazards(15, 86, ev, Units(), now)[0]["title"], "far")
        self.assertEqual(alerts.from_hazards(28.6, 77.2, ev, Units(), now), [])


class Api(unittest.TestCase):
    def test_alerts_api(self):
        status, d = call("/api/alerts?lat=11.95&lon=92.95&name=Port%20Blair")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(d["top"], 3)
        self.assertTrue(all({"id", "level", "title", "advice", "when"} <= set(a) for a in d["alerts"]))
        self.assertEqual(call("/api/alerts?lat=999&lon=1")[0], 400)

    def test_hazards_geocode_reverse_config(self):
        self.assertGreater(len(call("/api/hazards")[1]["events"]), 3)
        self.assertTrue(call("/api/geocode?q=Bengal")[1]["results"])
        self.assertEqual(call("/api/reverse?lat=12.97&lon=77.59")[1]["name"], "Bengaluru")
        self.assertTrue(call("/api/config")[1]["cloud"])

    def test_field_groups(self):
        for var in ("cape", "wind_speed_850hPa", "wind_direction_250hPa"):
            d = call(f"/api/field?south=5&west=70&north=15&east=85&zoom=5&vars={var}")[1]
            self.assertEqual(list(d["vars"]), [var])
        self.assertEqual(call("/api/field?south=5&west=70&north=15&east=85&zoom=5&vars=nope")[0], 400)

    def test_post_rules(self):
        self.assertEqual(server.dispatch("/", method="POST").status, 405)
        self.assertEqual(server.dispatch("/api/subscribe").status, 405)
        r = server.dispatch("/api/subscribe", method="POST", body=b"{}", headers={"content-type": "text/plain"})
        self.assertEqual(r.status, 400)

    def test_cron_needs_secret(self):
        config.CRON_SECRET = "s3cret"
        try:
            self.assertEqual(call("/api/cron/alerts")[0], 401)
            self.assertEqual(call("/api/cron/alerts", headers={"authorization": "Bearer nope"})[0], 401)
            status, d = call("/api/cron/alerts", headers={"authorization": "Bearer s3cret"})
            self.assertEqual(status, 200)
            self.assertIn("checked", d)
        finally:
            config.CRON_SECRET = ""


class Subscription(unittest.TestCase):
    HOME = {"lat": 11.95, "lon": 92.95, "name": "Port Blair", "region": "Andaman", "country": "India"}

    def subscribe(self, email):
        mailer.OUTBOX.clear()
        status, d = call("/api/subscribe", "POST", {"email": email, "home": self.HOME, "minLevel": 3})
        self.assertEqual(status, 200, d)
        link = re.search(r"/confirm\?t=([\w-]+)", mailer.OUTBOX[-1]["text"]).group(1)
        return d["pid"], link

    def test_confirmation_mail_asks_to_mark_not_spam(self):
        status, d = call("/api/subscribe", "POST", {"email": "spam@example.com", "home": self.HOME, "minLevel": 3})
        self.assertEqual(status, 200)
        self.assertIn("Not spam", d["message"])
        mail = mailer.OUTBOX[-1]
        self.assertIn("Not spam", mail["text"])
        self.assertIn("Not spam", mail["html"])
        self.assertIn("Not spam", (ROOT / "public" / "static" / "alerts.js").read_text(encoding="utf-8"))

    def test_full_flow(self):
        pid, link = self.subscribe("flow@example.com")
        self.assertFalse(call(f"/api/subscribe/status?pid={pid}")[1]["confirmed"])
        self.assertEqual(call(f"/confirm?t={link}")[0], 200)                 # the page only shows a button; GET never confirms
        self.assertFalse(call(f"/api/subscribe/status?pid={pid}")[1]["confirmed"])
        self.assertEqual(call("/api/confirm", "POST", {"t": link})[0], 200)
        st = call(f"/api/subscribe/status?pid={pid}")[1]
        self.assertTrue(st["confirmed"])
        token = st["token"]
        self.assertEqual(call("/api/confirm", "POST", {"t": link})[0], 410)  # single use

        mailer.OUTBOX.clear()
        out = notify.run_checks()
        self.assertEqual(out["alerts_mailed"] >= 1, True)
        mail = mailer.OUTBOX[-1]
        self.assertEqual(mail["to"], "flow@example.com")
        self.assertIn("Warning", mail["subject"])
        self.assertIn("List-Unsubscribe", mail["headers"])
        self.assertIn("What to do", mail["text"])
        mailer.OUTBOX.clear()
        notify.run_checks()
        self.assertEqual(mailer.OUTBOX, [])                                   # the same alert is not mailed twice

        # change home to somewhere quiet, report an away position near the quake: still no duplicate; position stored
        status, view = call("/api/subscribe/update", "POST", {"token": token, "home": {"lat": 28.6, "lon": 77.2, "name": "Delhi"}, "away": {"lat": 11.9, "lon": 92.9}})
        self.assertEqual((status, view["home"]["name"], view["tracking"]), (200, "Delhi", True))
        self.assertEqual(call("/api/subscribe/update", "POST", {"token": "bad"})[0], 404)

        self.assertEqual(call("/api/unsubscribe", "POST", {"token": token})[0], 200)
        self.assertEqual(call("/api/subscribe/update", "POST", {"token": token})[0], 404)
        r = server.dispatch(f"/unsubscribe?t={token}", method="POST")
        self.assertEqual(r.status, 404)                                       # already gone

    def test_away_location_is_alerted(self):
        pid, link = self.subscribe("away@example.com")
        call("/api/confirm", "POST", {"t": link})
        token = call(f"/api/subscribe/status?pid={pid}")[1]["token"]
        call("/api/subscribe/update", "POST", {"token": token, "home": {"lat": 28.6, "lon": 77.2, "name": "Delhi"}, "away": {"lat": 11.9, "lon": 92.9}})
        mailer.OUTBOX.clear()
        notify.run_checks()
        mine = [m for m in mailer.OUTBOX if m["to"] == "away@example.com"]
        self.assertTrue(mine, "an alert for the away position should be mailed")
        self.assertIn("your location", mine[0]["subject"])
        call("/api/unsubscribe", "POST", {"token": token})

    def test_validation_and_limits(self):
        self.assertEqual(call("/api/subscribe", "POST", {"email": "nope", "home": self.HOME})[0], 400)
        self.assertEqual(call("/api/subscribe", "POST", {"email": "a@example.com", "home": {"lat": 200, "lon": 0}})[0], 400)
        self.assertEqual(call("/api/subscribe", "POST", {"email": "a@example.com\r\nBcc: x@y.z", "home": self.HOME})[0], 400)
        for i in range(3):
            self.assertEqual(call("/api/subscribe", "POST", {"email": "rl@example.com", "home": self.HOME})[0], 200)
        self.assertEqual(call("/api/subscribe", "POST", {"email": "rl@example.com", "home": self.HOME})[0], 429)

    def test_email_html_is_escaped(self):
        rec = {"home": self.HOME, "token": "t"}
        new = [{"id": "x", "level": 3, "label": "Warning", "title": "<script>alert(1)</script>", "detail": "d", "advice": "a", "when": "Now", "place": "P", "source": "s"}]
        _, _, extra = notify.build_email(rec, new, "https://site.test")
        self.assertNotIn("<script>", extra["html"])


class Assets(unittest.TestCase):
    def test_static_pieces(self):
        for name in ("sw.js", "manifest.webmanifest", "icon-192.png", "icon-512.png", "alerts.js"):
            self.assertEqual(server.dispatch(f"/static/{name}").status, 200, name)
        self.assertEqual(server.dispatch("/static/sw.js").headers.get("Service-Worker-Allowed"), "/")
        self.assertIn("manifest+json", server.dispatch("/static/manifest.webmanifest").content_type)

    def test_pages_have_alert_hooks(self):
        html = server.dispatch("/forecast/overview?lat=12.97&lon=77.59&name=Bengaluru").body.decode()
        for needle in ('id="alert-bell"', 'id="alert-banner"', 'alerts.js', 'rel="manifest"', 'data-lat="12.9700"', 'data-layer="storm"', 'id="alt-levels"', 'id="tg-hazards"'):
            self.assertIn(needle, html)
        self.assertIn('id="set-home"', server.dispatch("/").body.decode())

    def test_vercel_routes(self):
        rewrites = {r["source"] for r in json.loads((ROOT / "vercel.json").read_text())["rewrites"]}
        for route in ("/api/alerts", "/api/hazards", "/api/geocode", "/api/reverse", "/api/config", "/api/subscribe", "/api/subscribe/update",
                      "/api/subscribe/status", "/api/confirm", "/api/unsubscribe", "/api/cron/alerts", "/confirm", "/unsubscribe"):
            self.assertIn(route, rewrites)


if __name__ == "__main__":
    unittest.main()
