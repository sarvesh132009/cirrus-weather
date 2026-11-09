"""Vercel entry point. Vercel's Python runtime loads the WSGI `app` from this file;
vercel.json rewrites every path to it, and the CDN serves public/static/ directly."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cirrus.wsgi import app  # noqa: E402,F401
