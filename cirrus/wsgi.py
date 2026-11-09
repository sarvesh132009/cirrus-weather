"""WSGI entry point. Vercel's Python runtime loads `app` from api/index.py, and any WSGI server
(gunicorn, waitress, wsgiref) can run it too."""

from __future__ import annotations

import json
from http import HTTPStatus
from urllib.parse import parse_qsl, quote, urlencode

from .server import dispatch, finalize

# Request headers that are safe to show on the ?__debug=1 page
_DEBUG_HEADERS = ("HTTP_HOST", "HTTP_X_MATCHED_PATH", "HTTP_X_VERCEL_ID", "HTTP_X_VERCEL_DEPLOYMENT_URL")


def _resolve(environ) -> tuple[str, bool]:
    """Work out which page the visitor asked for.

    vercel.json rewrites each route to /api/index?__path=<route>, and Vercel appends the visitor's own query string.
    Depending on the platform, the function may see its internal path (/api/index) instead of the visitor's, so
    the route travels in the query string, where nothing can rewrite it. Without ?__path= (local servers, tests)
    the normal WSGI path is used.
    """
    query = environ.get("QUERY_STRING", "")
    pairs = parse_qsl(query, keep_blank_values=True)
    debug = ("__debug", "1") in pairs
    routed = [value for key, value in pairs if key == "__path"]
    if not routed:
        raw = quote(environ.get("PATH_INFO") or "/", safe="/%:@")  # WSGI decodes the path; dispatch() wants it encoded
        return (raw + "?" + query if query else raw), debug
    path = routed[0] if routed[0].startswith("/") else "/" + routed[0]
    rest = [(k, v) for k, v in pairs if k not in ("__path", "__debug")]
    raw = quote(path, safe="/%:@")
    return (raw + "?" + urlencode(rest) if rest else raw), debug


def app(environ, start_response):
    method = environ.get("REQUEST_METHOD", "GET")
    if method not in ("GET", "HEAD"):
        start_response("405 Method Not Allowed", [("Allow", "GET, HEAD"), ("Content-Type", "text/plain; charset=utf-8")])
        return [b"Method not allowed"]
    raw, debug = _resolve(environ)
    if debug:  # shows what the platform handed to the function; useful when a deployment routes wrongly
        info = {"PATH_INFO": environ.get("PATH_INFO"), "SCRIPT_NAME": environ.get("SCRIPT_NAME"),
                "QUERY_STRING": environ.get("QUERY_STRING"), "resolved": raw,
                **{k: environ.get(k) for k in _DEBUG_HEADERS}}
        body = json.dumps(info, indent=2).encode()
        start_response("200 OK", [("Content-Type", "application/json"), ("Cache-Control", "no-store"),
                                  ("Content-Length", str(len(body)))])
        return [body]
    status, headers, body = finalize(
        dispatch(raw),
        accept_encoding=environ.get("HTTP_ACCEPT_ENCODING", ""),
        if_none_match=environ.get("HTTP_IF_NONE_MATCH", ""),
        send_body=method == "GET",
    )
    start_response(f"{status} {HTTPStatus(status).phrase}", list(headers.items()))
    return [body] if body else []
