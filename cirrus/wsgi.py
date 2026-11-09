"""WSGI entry point. Vercel's Python runtime loads `app` from api/index.py, and any WSGI server
(gunicorn, waitress, wsgiref) can run it too."""

from __future__ import annotations

from http import HTTPStatus
from urllib.parse import quote

from .server import dispatch, finalize


def app(environ, start_response):
    method = environ.get("REQUEST_METHOD", "GET")
    if method not in ("GET", "HEAD"):
        start_response("405 Method Not Allowed", [("Allow", "GET, HEAD"), ("Content-Type", "text/plain; charset=utf-8")])
        return [b"Method not allowed"]
    # WSGI hands over the decoded path; dispatch() expects the raw one, so encode it again.
    raw = quote(environ.get("PATH_INFO") or "/", safe="/%:@")
    if environ.get("QUERY_STRING"):
        raw += "?" + environ["QUERY_STRING"]
    status, headers, body = finalize(
        dispatch(raw),
        accept_encoding=environ.get("HTTP_ACCEPT_ENCODING", ""),
        if_none_match=environ.get("HTTP_IF_NONE_MATCH", ""),
        send_body=method == "GET",
    )
    start_response(f"{status} {HTTPStatus(status).phrase}", list(headers.items()))
    return [body] if body else []
