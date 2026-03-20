"""Safe backend runner for local development.

Use this instead of a plain ``uvicorn ... --reload`` command when you want the
trading bot, websocket feeds, and Angel One sessions to stay alive.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn


REPO_ROOT = Path(__file__).resolve().parent
RELOAD_EXCLUDES = [
    ".venv/*",
    "storage/*",
    "models/artifacts/*",
    "frontend/dist/*",
    "logs/*",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the StockTrader backend safely.")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind the backend server to.")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind the backend server to.")
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Reload only backend source files. Avoid this for live feed or bot sessions.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    kwargs: dict[str, object] = {
        "app": "backend.api.main:app",
        "host": args.host,
        "port": args.port,
    }
    if args.reload:
        kwargs.update(
            reload=True,
            reload_dirs=[str(REPO_ROOT / "backend")],
            reload_excludes=RELOAD_EXCLUDES,
        )
    uvicorn.run(**kwargs)


if __name__ == "__main__":
    main()
