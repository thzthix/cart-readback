"""Run a disposable actual-HTTP fixture checkout, without a browser or network API."""

import argparse
import json
import sys
import tempfile
from http.client import HTTPConnection
from pathlib import Path
from threading import Thread
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cartreadback_app.http import LocalServer  # noqa: E402
from cartreadback_app.payments import FixturePaymentAdapter  # noqa: E402
from cartreadback_app.service import Service  # noqa: E402
from cartreadback_app.storage import Store  # noqa: E402


def run(fault: str | None = None) -> list[str]:
    """Exercise explicit HTTP steps and optional same-order reconciliation."""
    with tempfile.TemporaryDirectory(prefix="cartreadback-smoke-") as directory:
        root = Path(__file__).resolve().parents[1]
        service = Service(
            Store(Path(directory) / "fixture.db"),
            payments=FixturePaymentAdapter(fault),
        )
        server = LocalServer(("127.0.0.1", 0), service, root / "ui")
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        cookie = None
        csrf = None

        def request(
            path: str, payload: dict | None = None, key: bool = False
        ) -> dict:
            nonlocal cookie, csrf
            headers = {
                "Origin": server.origin,
                "Content-Type": "application/json",
            }
            if cookie:
                headers["Cookie"] = cookie
            if csrf:
                headers["X-CSRF-Token"] = csrf
            if key:
                headers["Idempotency-Key"] = str(uuid4())
            connection = HTTPConnection(
                "127.0.0.1", server.server_port, timeout=5
            )
            try:
                connection.request(
                    "POST" if payload is not None else "GET",
                    path,
                    json.dumps(payload) if payload is not None else None,
                    headers,
                )
                response = connection.getresponse()
                body = json.loads(response.read())
                if response.status != 200:
                    raise RuntimeError(f"HTTP {response.status}: {body}")
                if response.getheader("Set-Cookie"):
                    cookie = response.getheader("Set-Cookie").split(";", 1)[0]
                csrf = body.get("csrf_token", csrf)
                return body
            finally:
                connection.close()

        states = []
        try:
            result = request("/api/bootstrap")
            result = request(
                "/api/analyze",
                {
                    "expected_revision": result["revision"],
                    "sku_id": "KB-UK-C2C",
                    "conditions": [{"kind": "layout", "value": "UK_QWERTY"}],
                },
            )
            c = result["checkout"]
            states.append(c["state"])
            result = request(
                "/api/confirm",
                {
                    "expected_revision": result["revision"],
                    "review_id": c["review_id"],
                    "snapshot_hash": c["snapshot_hash"],
                    "confirmed_sku_id": c["sku_id"],
                    "confirmed_condition_ids": ["c1"],
                    "acknowledged_unknown_ids": [],
                    "acknowledged_conflict_ids": [],
                },
            )
            c = result["checkout"]
            states.append(c["state"])
            result = request(
                "/api/orders",
                {
                    "expected_revision": result["revision"],
                    "review_id": c["review_id"],
                    "snapshot_hash": c["snapshot_hash"],
                    "confirmation_id": c["confirmation_id"],
                },
                key=True,
            )
            c = result["checkout"]
            states.append(c["state"])
            order_id = c["order"]["order_id"]
            actions = ["fixture-approve", "verify", "capture"]
            if c["state"] == "PAYMENT_UNKNOWN":
                actions = ["reconcile"]
            elif fault:
                actions.append("reconcile")
            for action in actions:
                payload = {
                    "expected_revision": result["revision"],
                    "snapshot_hash": c["snapshot_hash"],
                }
                if action == "capture":
                    payload.update(
                        confirmation_id=c["confirmation_id"],
                        final_confirmation=True,
                    )
                result = request(
                    f"/api/orders/{order_id}/{action}",
                    payload,
                    key=action == "capture",
                )
                c = result["checkout"]
                if c["order"]["order_id"] != order_id:
                    raise AssertionError(
                        "Reconciliation replaced the local order"
                    )
                states.append(c["state"])
            expected = (
                "COMPLETED"
                if fault
                in {
                    None,
                    "capture_timeout_after_success",
                }
                else "PAYMENT_UNKNOWN"
            )
            if c["state"] != expected:
                raise AssertionError(f"Expected {expected}, got {c['state']}")
            return states
        finally:
            server.shutdown()
            server.server_close()
            thread.join(5)


def main() -> None:
    """Print only synthetic workflow states; no private/session data."""
    parser = argparse.ArgumentParser(description="No-money HTTP fixture smoke")
    parser.add_argument(
        "--fault",
        choices=sorted(
            value for value in FixturePaymentAdapter.FAULTS if value is not None
        ),
    )
    args = parser.parse_args()
    print("FIXTURE ONLY — no real model, no PayPal calls, no money")
    print(" → ".join(run(args.fault)))


if __name__ == "__main__":
    main()
