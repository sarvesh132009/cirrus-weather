#!/usr/bin/env python3
"""Start the Cirrus weather site.  Python 3.13, standard library only.

    python run.py                 # http://127.0.0.1:8000
    python run.py --port 9000
    python run.py --demo          # synthetic data, works with no internet
"""

import argparse
import os
import sys

if sys.version_info < (3, 12):
    sys.exit("Cirrus needs Python 3.12 or newer (built and tested on 3.13).")

from cirrus import config, server  # noqa: E402


def main() -> None:
    # Hosting platforms (Render, Cloud Run, Hugging Face ...) pass the port in $PORT and need 0.0.0.0.
    hosted = "PORT" in os.environ
    parser = argparse.ArgumentParser(description="Cirrus weather site")
    parser.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0" if hosted else "127.0.0.1"),
                        help="use 0.0.0.0 to share on your network (default: 127.0.0.1, or 0.0.0.0 when $PORT is set)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    parser.add_argument("--demo", action="store_true", help="use made-up data and make no network calls")
    args = parser.parse_args()
    if args.demo:
        config.DEMO = True
    server.serve(args.host, args.port)


if __name__ == "__main__":
    main()
