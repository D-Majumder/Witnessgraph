"""Run the local-only Witnessgraph API server, bound to one case directory.

Usage::

    witnessgraph-api path/to/case [--port 8420] [--allow-origin http://127.0.0.1:5174]

Always binds to ``127.0.0.1`` -- this is not configurable from the
command line, deliberately: see
``docs/phase-ui-v1-architecture-design.md`` §11 ("no accidental remote
bind" is a hard requirement of v1's security model, not a default that a
flag should be able to override).
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from witnessgraph.service.errors import CaseNotFoundError, CaseUnreadableError

HOST = "127.0.0.1"
DEFAULT_PORT = 8420


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="witnessgraph-api",
        description=(
            "Run the local-only Witnessgraph API server, bound to one case "
            "directory. Never accepts a case directory over the network -- "
            "opening a different case means restarting this process pointed "
            "at it."
        ),
    )
    parser.add_argument("case_dir", type=Path, help="Case directory to bind this server to.")
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Port to listen on (default {DEFAULT_PORT}).",
    )
    parser.add_argument(
        "--allow-origin",
        action="append",
        dest="allowed_origins",
        default=None,
        metavar="ORIGIN",
        help=(
            "Additional frontend origin to allow via CORS (may be repeated). "
            "Defaults to the Vite dev server's own origins "
            "(http://127.0.0.1:5173, http://localhost:5173)."
        ),
    )
    args = parser.parse_args(argv)

    # Import here, not at module top level: a bad case_dir should fail
    # with this module's own clean message before FastAPI/uvicorn are
    # even touched.
    from witnessgraph.api.app import create_app

    try:
        app = create_app(args.case_dir, allowed_origins=args.allowed_origins)
    except CaseNotFoundError:
        print(
            f"error: {args.case_dir} does not look like a Witnessgraph case (no case.db)",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    except (CaseUnreadableError, sqlite3.DatabaseError):
        print(
            f"error: {args.case_dir} does not contain a readable Witnessgraph case database",
            file=sys.stderr,
        )
        raise SystemExit(1) from None

    import uvicorn

    print(f"witnessgraph-api: serving {args.case_dir.resolve()} on http://{HOST}:{args.port}")
    uvicorn.run(app, host=HOST, port=args.port)


if __name__ == "__main__":
    main()
