"""Run the loopback CartReadback fixture server with no external dependencies."""

import argparse
from pathlib import Path

from cartreadback_app.http import LocalServer
from cartreadback_app.service import Service
from cartreadback_app.storage import Store


def main() -> None:
    """Parse local server settings and run until Ctrl-C."""
    parser = argparse.ArgumentParser(
        description="CartReadback: fixture only, no money"
    )
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--db", type=Path, default=Path(".local/cartreadback.sqlite3")
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    server = LocalServer(
        ("127.0.0.1", args.port), Service(Store(args.db)), root / "ui"
    )
    print(
        f"FIXTURE ONLY — no AI/PayPal calls, no money: {server.origin}",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
