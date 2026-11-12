"""E-mail alerts for people who are not looking at the site.

Flow: subscribe (e-mail + home) -> confirmation mail -> confirm -> the scheduled check (`run_checks`) mails new alerts
for the home, and for the last place the person's device reported while the site was open.

Privacy: only an e-mail, a home place and (if allowed) the last-seen position are stored. Nothing is stored until the
address is confirmed, and unsubscribing deletes everything. Tokens are random secrets: the confirm link proves
the address is yours, and the manage token lets your own device change the home or unsubscribe.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from datetime import UTC, datetime
from html import escape
from urllib.parse import urlencode

from . import alerts, config, hazards, mailer, openmeteo
from .derive import Units
from .model import Weather
from .openmeteo import UpstreamError
from .store import StoreError, get_store

AWAY_KM = 25            # a position further than this from home counts as "somewhere else"
AWAY_MAX_AGE = 48 * 3600
FORECAST_EVERY = 3 * 3600
MAIL_GAP = 3600         # at most one alert mail an hour, unless something is Extreme
CONFIRM_TTL = 24 * 3600


class NotifyError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status, self.message = status, message


def enabled() -> bool:
    return get_store() is not None and mailer.configured()


def _base() -> str:
    base = config.BASE_URL or ("http://127.0.0.1:8000" if config.DEMO else "")
    if not base:
        raise NotifyError(503, "The site address is not configured (set CIRRUS_BASE_URL).")
    return base


def _need_store():
    store = get_store()
    if store is None or not mailer.configured():
        raise NotifyError(503, "E-mail alerts are not switched on for this site.")
    return store


def _sid(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()[:24]


def _mask(email: str) -> str:
    name, _, domain = email.partition("@")
    return f"{name[:2]}{'*' * max(1, len(name) - 2)}@{domain}"


def _limit(store, key: str, maximum: int, seconds: int) -> None:
    if store.incr(f"rl:{key}", ex=seconds) > maximum:
        raise NotifyError(429, "Too many requests. Please wait a little and try again.")


def clean_home(raw) -> dict:
    if not isinstance(raw, dict):
        raise NotifyError(400, "Choose a home place first.")
    try:
        lat, lon = float(raw["lat"]), float(raw["lon"])
    except (KeyError, TypeError, ValueError):
        raise NotifyError(400, "The home place needs a latitude and longitude.") from None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise NotifyError(400, "The home place is outside the map.")
    text = lambda k, n: " ".join(str(raw.get(k) or "").split())[:n]  # noqa: E731
    return {"lat": round(lat, 3), "lon": round(lon, 3), "name": text("name", 80) or "Home", "region": text("region", 80), "country": text("country", 80)}


def _level(raw, default: int = 3) -> int:
    try:
        return min(4, max(1, int(raw)))
    except (TypeError, ValueError):
        return default


def _load(store, sid: str) -> dict | None:
    raw = store.get(f"sub:{sid}")
    return json.loads(raw) if raw else None


def _save(store, rec: dict) -> None:
    store.set(f"sub:{rec['sid']}", json.dumps(rec, separators=(",", ":")))


def _view(rec: dict) -> dict:
    away = rec.get("away")
    return {"email": _mask(rec["email"]), "home": rec["home"], "minLevel": rec["min"],
            "tracking": bool(away and time.time() - away["at"] < AWAY_MAX_AGE), "active": True}


def _confirm_mail(email: str, link: str) -> None:
    text = (f"Please confirm that you want weather and disaster alerts from Cirrus.\n\n{link}\n\n"
            "The link works for 24 hours. If you did not ask for this, ignore this message and nothing will be stored.\n\n"
            "Found this in your Spam folder? Please click \"Not spam\" so future weather alerts reach your inbox.")
    html = (f'<p>Please confirm that you want weather and disaster alerts from Cirrus.</p><p><a href="{escape(link)}">Confirm my e-mail</a></p>'
            '<p style="color:#666">The link works for 24 hours. If you did not ask for this, ignore this message and nothing will be stored.</p>'
            '<p style="color:#666">Found this in your Spam folder? Please click <b>Not spam</b> so future weather alerts reach your inbox.</p>')
    mailer.send(email, "Confirm your Cirrus alerts", text, html)


def subscribe(email: str, home, min_level, ip: str = "") -> dict:
    store = _need_store()
    email = (email or "").strip()
    if not mailer.valid_email(email):
        raise NotifyError(400, "That e-mail address does not look right.")
    home, level, sid = clean_home(home), _level(min_level), _sid(email)
    base = _base()
    _limit(store, f"ip:{hashlib.sha256((ip or '-').encode()).hexdigest()[:16]}", 10, 3600)
    _limit(store, f"em:{sid}", 3, 900)
    if store.incr(f"mail:{datetime.now(UTC):%Y-%m-%d}", ex=172_800) > config.MAIL_DAILY_CAP:
        raise NotifyError(503, "The daily e-mail limit has been reached. Please try again tomorrow.")
    ctok, pid = secrets.token_urlsafe(24), secrets.token_urlsafe(16)
    store.set(f"pend:{ctok}", json.dumps({"email": email, "home": home, "min": level, "pid": pid}), ex=CONFIRM_TTL)
    try:
        _confirm_mail(email, f"{base}/confirm?{urlencode({'t': ctok})}")
    except (RuntimeError, ValueError) as exc:
        raise NotifyError(502, str(exc)) from exc
    return {"pid": pid, "message": "Check your inbox for a confirmation e-mail. If it is in Spam, open it and click Not spam so future alerts reach your inbox."}


def confirm(ctok: str) -> dict:
    store = _need_store()
    raw = store.get(f"pend:{ctok or '-'}")
    if not raw:
        raise NotifyError(410, "This confirmation link has expired or was already used. Please subscribe again.")
    pend = json.loads(raw)
    sid = _sid(pend["email"])
    rec = _load(store, sid) or {"sid": sid, "token": secrets.token_urlsafe(24), "created": int(time.time()), "sent": {}, "fx": {}}
    rec.update(email=pend["email"], home=pend["home"], min=pend["min"], fx={})
    _save(store, rec)
    store.set(f"tok:{rec['token']}", sid)
    store.sadd("subs", sid)
    store.set(f"pidres:{pend['pid']}", rec["token"], ex=CONFIRM_TTL)
    store.delete(f"pend:{ctok}")
    return {"email": _mask(rec["email"]), "home": rec["home"]["name"]}


def confirmation_status(pid: str) -> dict:
    store = _need_store()
    token = store.get(f"pidres:{pid or '-'}")
    return {"confirmed": bool(token), "token": token or ""}


def _by_token(store, token: str) -> dict:
    sid = store.get(f"tok:{token or '-'}")
    rec = _load(store, sid) if sid else None
    if not rec:
        raise NotifyError(404, "This subscription was not found. It may have been cancelled.")
    return rec


def update(token: str, body: dict) -> dict:
    """Read or change a subscription with the manage token: new home, alert level, last-seen position."""
    store = _need_store()
    _limit(store, f"tok:{hashlib.sha256((token or '-').encode()).hexdigest()[:16]}", 120, 3600)
    rec = _by_token(store, token)
    if "home" in body:
        home = clean_home(body["home"])
        if (home["lat"], home["lon"]) != (rec["home"]["lat"], rec["home"]["lon"]):
            rec["fx"] = {}
        rec["home"] = home
    if "minLevel" in body:
        rec["min"] = _level(body["minLevel"])
    if "away" in body:   # {"lat","lon"} while the person is away from home, null to forget the position
        a = body["away"]
        if a is None:
            rec.pop("away", None)
        else:
            try:
                lat, lon = float(a["lat"]), float(a["lon"])
            except (KeyError, TypeError, ValueError):
                raise NotifyError(400, "Bad position.") from None
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise NotifyError(400, "Bad position.")
            rec["away"] = {"lat": round(lat, 2), "lon": round(lon, 2), "at": int(time.time())}
    _save(store, rec)
    return _view(rec)


def unsubscribe(token: str) -> dict:
    store = _need_store()
    rec = _by_token(store, token)
    store.srem("subs", rec["sid"])
    store.delete(f"sub:{rec['sid']}")
    store.delete(f"tok:{rec['token']}")
    return {"ok": True}


# ---- the scheduled check -------------------------------------------------------------------------------------------

def build_email(rec: dict, new: list[dict], base: str) -> tuple[str, str, dict]:
    top = max(new, key=lambda a: a["level"])
    more = f" (+{len(new) - 1} more)" if len(new) > 1 else ""
    subject = f"{top['label']}: {top['title']} - {top['place']}{more}"[:150]
    manage = f"{base}/forecast/overview?{urlencode({'lat': rec['home']['lat'], 'lon': rec['home']['lon'], 'name': rec['home']['name']})}"
    unsub = f"{base}/unsubscribe?{urlencode({'t': rec['token']})}"
    colors = {1: "#B59A1F", 2: "#D98A10", 3: "#D2402B", 4: "#A8189B"}
    text_parts, html_parts = [], []
    for a in sorted(new, key=lambda x: -x["level"]):
        text_parts.append(f"[{a['label'].upper()}] {a['title']} - {a['place']}\n{a['when']}\n{a['detail']}\nWhat to do: {a['advice']}\n")
        html_parts.append(
            f'<div style="border-left:5px solid {colors[a["level"]]};padding:6px 12px;margin:14px 0">'
            f'<strong>{escape(a["label"])}: {escape(a["title"])}</strong> <span style="color:#555">- {escape(a["place"])}</span><br>'
            f'<span style="color:#555">{escape(a["when"])}</span><br>{escape(a["detail"])}<br>'
            f'<em>What to do:</em> {escape(a["advice"])}</div>')
    text = ("\n".join(text_parts) + f"\n{alerts.DISCLAIMER}\n\nOpen the forecast: {manage}\nStop these e-mails: {unsub}\n")
    html = ("".join(html_parts) + f'<p style="color:#666;font-size:13px">{escape(alerts.DISCLAIMER)}</p>'
            f'<p><a href="{escape(manage)}">Open the forecast</a> · <a href="{escape(unsub)}">Stop these e-mails</a></p>')
    headers = {"List-Unsubscribe": f"<{unsub}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}
    return subject, text, {"html": html, "headers": headers}


def _places(rec: dict, now: float) -> list[tuple[str, dict]]:
    out = [("Home", rec["home"])]
    away = rec.get("away")
    if away and now - away["at"] < AWAY_MAX_AGE and hazards.km_between(rec["home"]["lat"], rec["home"]["lon"], away["lat"], away["lon"]) > AWAY_KM:
        out.append(("Your last known location", {"lat": away["lat"], "lon": away["lon"], "name": "your location"}))
    return out


def _forecast_alerts(rec: dict, key: str, lat: float, lon: float, now: float) -> tuple[list[dict], int]:
    cached = rec["fx"].get(key)
    if cached and now - cached["at"] < FORECAST_EVERY:
        return cached["alerts"], 0
    try:
        wx = Weather(openmeteo.forecast(lat, lon), Units())
        try:
            aq = openmeteo.air_quality(lat, lon)
        except UpstreamError:
            aq = None
        found = alerts.from_forecast(wx, aq)
    except UpstreamError:
        return (cached or {}).get("alerts", []), 1
    rec["fx"][key] = {"at": int(now), "alerts": found}
    return found, 2


def check_one(store, rec: dict, events: list[dict], now: float | None = None) -> tuple[int, int]:
    """Check one subscriber. Returns (alerts mailed, weather calls made)."""
    now = now or time.time()
    calls, new = 0, []
    places = _places(rec, now)
    rec["fx"] = {k: v for k, v in rec.get("fx", {}).items() if k in {f"{p['lat']:.1f},{p['lon']:.1f}" for _, p in places}}
    seen: set[str] = set()
    for label, p in places:
        found, used = _forecast_alerts(rec, f"{p['lat']:.1f},{p['lon']:.1f}", p["lat"], p["lon"], now)
        calls += used
        found = found + alerts.from_hazards(p["lat"], p["lon"], events, Units(), datetime.fromtimestamp(now, UTC))
        place_name = f"{p['name']} (home)" if label == "Home" else p["name"]
        for a in found:
            if a["level"] >= rec["min"] and a["id"] not in rec["sent"] and a["id"] not in seen:
                seen.add(a["id"])
                new.append({**a, "place": place_name})
    mailed = 0
    if new and (now - rec.get("lastMail", 0) >= MAIL_GAP or any(a["level"] >= 4 for a in new)):
        if store.incr(f"mail:{datetime.now(UTC):%Y-%m-%d}", ex=172_800) <= config.MAIL_DAILY_CAP:
            subject, text, extra = build_email(rec, new, _base())
            try:
                mailer.send(rec["email"], subject, text, extra["html"], extra["headers"])
                rec["lastMail"] = int(now)
                rec["sent"].update({a["id"]: int(now) for a in new})
                mailed = len(new)
            except (RuntimeError, ValueError):
                pass   # try again at the next run
    rec["sent"] = {k: v for k, v in rec["sent"].items() if now - v < 4 * 86400}
    rec["checkedAt"] = int(now)
    _save(store, rec)
    return mailed, calls


def authorized(header: str) -> bool:
    return bool(config.CRON_SECRET) and hmac.compare_digest(header.removeprefix("Bearer ").strip(), config.CRON_SECRET)


def run_checks(max_calls: int = 40, time_limit: float = 45.0) -> dict:
    """Look at every subscriber, oldest check first, and mail whatever is new. Safe to run as often as every 30 minutes."""
    store = _need_store()
    try:
        events = hazards.feed()["events"]
    except UpstreamError:
        events = []
    recs = [r for r in (_load(store, sid) for sid in store.smembers("subs")) if r]
    recs.sort(key=lambda r: r.get("checkedAt", 0))
    deadline, calls, checked, mailed, errors = time.monotonic() + time_limit, 0, 0, 0, 0
    for rec in recs:
        if time.monotonic() > deadline or calls >= max_calls:
            break
        try:
            m, c = check_one(store, rec, events)
            mailed, calls, checked = mailed + m, calls + c, checked + 1
        except (StoreError, NotifyError, KeyError, ValueError):
            errors += 1
    return {"subscribers": len(recs), "checked": checked, "alerts_mailed": mailed, "weather_calls": calls,
            "errors": errors, "events_in_feed": len(events)}
