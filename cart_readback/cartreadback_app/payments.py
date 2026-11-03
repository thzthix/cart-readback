"""Offline payment seam with independently committed synthetic provider state."""

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Protocol

from cartreadback_app.validation import AppError, canonical, digest


class ProviderAmbiguity(Exception):
    """A provider outcome that must be reconciled, never automatically replayed."""


@dataclass(frozen=True)
class PaymentRequest:
    """Exact immutable request bytes, separate from local authorization facts."""

    method: str
    path: str
    body: str


class PaymentAdapter(Protocol):
    """Transport-neutral seam: no application connection crosses this boundary.

    prepare is pure and cannot do I/O. dispatch sends the exact persisted body
    once, using operation_id as the provider request UUID. get is read-only.
    A future real transport needs its own host, normalization and timeout review.
    """

    mode: str
    merchant_id: str
    version: str

    def prepare(
        self, kind: str, expected: dict, provider_order_id: str | None
    ) -> PaymentRequest:
        """Build the exact authoritative wire-equivalent request, without I/O."""
        ...

    def dispatch(self, operation_id: str, request: PaymentRequest) -> dict:
        """Send one previously claimed request, without automatic retries."""
        ...

    def get(self, provider_order_id: str) -> dict:
        """Observe the same existing order without monetary side effects."""
        ...


class DisabledPayPalSandboxAdapter:
    """Real sandbox integration is intentionally unavailable and does no I/O."""

    mode = "disabled"
    merchant_id = "unconfigured"
    version = "disabled-v1"

    def __getattr__(self, name: str):
        """Fail instead of silently substituting a fixture or live endpoint."""
        if name in {
            "prepare",
            "dispatch",
            "create",
            "get",
            "capture",
            "approve",
        }:

            def unavailable(*_args, **_kwargs):
                raise AppError(
                    "PAYPAL_UNAVAILABLE",
                    "Real PayPal adapter is disabled.",
                    503,
                )

            return unavailable
        raise AttributeError(name)


class FixturePaymentAdapter:
    """Independent SQLite fake provider, never genuine PayPal evidence.

    Each side effect commits in a separate database before returning. Application
    rollback cannot undo a synthetic payment. No HTTP input selects faults.
    """

    mode = "fixture"
    merchant_id = "synthetic-merchant-only"
    version = "fixture-wire-v1"
    FAULTS = {
        None,
        "create_timeout_after_success",
        "capture_timeout_after_success",
        "capture_timeout_before_success",
        "capture_pending",
    }

    def __init__(self, fault: str | None = None):
        """Allow only explicit fixture faults; bind persistence at service setup."""
        if type(fault) not in (str, type(None)) or fault not in self.FAULTS:
            raise AppError("INVALID_FIXTURE_FAULT", "Unknown fixture fault.")
        self.fault = fault
        self.path = None

    def bind(self, path: Path, legacy_rows: list) -> None:
        """Bind a fixture-only store and import existing fake orders once."""
        if self.path is not None and self.path != path:
            raise AppError(
                "INVALID_STATE", "Fixture store is already bound.", 409
            )
        self.path = path
        with self.connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS fixture_provider_orders ("
                "provider_order_id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, "
                "document TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS fixture_dispatches ("
                "receipt_id INTEGER PRIMARY KEY, operation_id TEXT NOT NULL, method TEXT NOT NULL, "
                "path TEXT NOT NULL, body TEXT NOT NULL)"
            )
            connection.executemany(
                "INSERT OR IGNORE INTO fixture_provider_orders VALUES (?, ?, ?)",
                legacy_rows,
            )

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Open and close the independent fake provider transaction."""
        if self.path is None:
            raise AppError("INVALID_STATE", "Fixture store is not bound.", 409)
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def prepare(
        self, kind: str, expected: dict, provider_order_id: str | None
    ) -> PaymentRequest:
        """Freeze fixture wire bytes; capture sends exactly an empty object."""
        if kind == "orders":
            return PaymentRequest(
                "POST", "/fixture/orders", canonical(expected)
            )
        return PaymentRequest(
            "POST",
            f"/fixture/orders/{provider_order_id}/capture",
            canonical({}),
        )

    def dispatch(self, operation_id: str, request: PaymentRequest) -> dict:
        """Dispatch the exact stored fixture request without retry."""
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO fixture_dispatches(operation_id, method, path, body) VALUES (?, ?, ?, ?)",
                (operation_id, request.method, request.path, request.body),
            )
        if request.method != "POST":
            raise AppError("INVALID_STATE", "Unsupported fixture method.", 409)
        if request.path == "/fixture/orders":
            return self.create(operation_id, json.loads(request.body))
        prefix, suffix = "/fixture/orders/", "/capture"
        if (
            not request.path.startswith(prefix)
            or not request.path.endswith(suffix)
            or request.body != canonical({})
        ):
            raise AppError("INVALID_STATE", "Unsupported fixture request.", 409)
        return self.capture(
            request.path[len(prefix) : -len(suffix)], operation_id
        )

    def create(self, request_id: str, expected: dict) -> dict:
        """Commit one synthetic order before returning or raising ambiguity."""
        order_id = "FAKE-" + digest(request_id)[:24]
        document = {
            **expected,
            "provider_order_id": order_id,
            "status": "CREATED",
            "captures": [],
        }
        with self.connect() as connection:
            row = connection.execute(
                "SELECT document FROM fixture_provider_orders WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            if row:
                return json.loads(row[0])
            connection.execute(
                "INSERT INTO fixture_provider_orders VALUES (?, ?, ?)",
                (order_id, request_id, canonical(document)),
            )
        if self.fault == "create_timeout_after_success":
            raise ProviderAmbiguity("Synthetic create timeout")
        return document

    def get(self, provider_order_id: str) -> dict:
        """Read an existing fake order with no application connection."""
        with self.connect() as connection:
            row = connection.execute(
                "SELECT document FROM fixture_provider_orders WHERE provider_order_id = ?",
                (provider_order_id,),
            ).fetchone()
        if not row:
            raise AppError(
                "PROVIDER_NOT_FOUND", "Provider order unavailable.", 409
            )
        return json.loads(row[0])

    def _save(self, connection: sqlite3.Connection, document: dict) -> None:
        connection.execute(
            "UPDATE fixture_provider_orders SET document = ? WHERE provider_order_id = ?",
            (canonical(document), document["provider_order_id"]),
        )

    def approve(self, provider_order_id: str) -> dict:
        """Explicitly commit fake approval; not a PayPal buyer login."""
        document = self.get(provider_order_id)
        if document["status"] != "CREATED":
            raise AppError(
                "INVALID_STATE", "Order is not awaiting approval.", 409
            )
        document["status"] = "APPROVED"
        with self.connect() as connection:
            self._save(connection, document)
        return document

    def capture(self, provider_order_id: str, request_id: str) -> dict:
        """Commit a fake capture independently of application observation."""
        document = self.get(provider_order_id)
        if document["status"] != "APPROVED":
            raise AppError(
                "INVALID_STATE", "Provider order is not approved.", 409
            )
        if self.fault == "capture_timeout_before_success":
            raise ProviderAmbiguity(
                "Synthetic capture timeout before completion"
            )
        if self.fault == "capture_pending":
            document["status"] = "PENDING"
        else:
            document["status"] = "COMPLETED"
            document["captures"] = [
                {
                    "capture_id": "FAKE-CAP-" + digest(request_id)[:20],
                    "status": "COMPLETED",
                    "amount_minor": document["amount_minor"],
                    "currency": document["currency"],
                }
            ]
        with self.connect() as connection:
            self._save(connection, document)
        if self.fault in {"capture_pending", "capture_timeout_after_success"}:
            raise ProviderAmbiguity("Synthetic uncertain capture")
        return document


def verify_provider_order(
    document: object,
    expected: dict,
    provider_id: str,
    merchant_id: str,
    allowed_statuses: set[str],
    capture_request_id: str | None = None,
) -> None:
    """Compare normalized returned facts to the immutable server snapshot.

    No environment field from provider JSON is trusted. The adapter owns its
    transport/mode. Sparse PayPal wire observations fail closed unless all facts
    required for this transition were actually returned. No live I/O is enabled.
    """
    fields = set(expected) | {"provider_order_id", "status", "captures"}
    if (
        expected.get("provider_mode") == "paypal-sandbox-offline"
        and type(document) is dict
        and "approval_url" in document
    ):
        fields.add("approval_url")
        if document["approval_url"] != (
            "https://www.sandbox.paypal.com/checkoutnow?token="
            + str(provider_id)
        ):
            raise AppError(
                "ORDER_MISMATCH", "Invalid approval destination.", 409
            )
    # PayPal may omit payments before capture. Do not manufacture a returned
    # empty capture list merely to match the fixture's complete representation.
    if (
        expected.get("provider_mode") == "paypal-sandbox-offline"
        and capture_request_id is None
        and type(document) is dict
        and "captures" not in document
    ):
        fields.remove("captures")
    if (
        type(provider_id) is not str
        or not provider_id
        or type(document) is not dict
        or (
            document.get("provider_order_id") != provider_id
            or document.get("merchant_id") != merchant_id
            or type(document.get("status")) is not str
            or document.get("status") not in allowed_statuses
            or set(document) != fields
            or (
                expected.get("provider_mode") == "paypal-sandbox-offline"
                and capture_request_id is None
                and "captures" in document
                and document["captures"] != []
            )
            or canonical({key: document.get(key) for key in expected})
            != canonical(expected)
        )
    ):
        raise AppError(
            "ORDER_MISMATCH", "Provider order failed verification.", 409
        )
    if capture_request_id is not None:
        captures = document.get("captures")
        if type(captures) is not list or len(captures) != 1:
            raise AppError(
                "ORDER_MISMATCH", "Capture details are incomplete.", 409
            )
        capture = captures[0]
        if type(capture) is not dict or (
            set(capture) != {"capture_id", "status", "amount_minor", "currency"}
            or type(capture.get("capture_id")) is not str
            or not capture["capture_id"]
            or capture.get("status") != "COMPLETED"
            or type(capture.get("amount_minor")) is not int
            or capture.get("amount_minor") != expected["amount_minor"]
            or capture.get("currency") != expected["currency"]
        ):
            raise AppError(
                "ORDER_MISMATCH", "Capture failed verification.", 409
            )
