"""A local fake payment provider, never a genuine PayPal response."""

import json
import sqlite3
from typing import Protocol

from cartreadback_app.validation import AppError, canonical, digest


class ProviderAmbiguity(Exception):
    """A synthetic timeout whose money outcome must be reconciled, not retried."""


class PaymentAdapter(Protocol):
    """Normalized provider seam, not a claim about PayPal's raw API fields."""

    mode: str
    merchant_id: str

    def create(
        self, connection: sqlite3.Connection, request_id: str, expected: dict
    ) -> dict:
        """Create a provider order with a durable operation identifier."""
        ...

    def get(
        self, connection: sqlite3.Connection, provider_order_id: str
    ) -> dict:
        """Get the existing order; never creates or captures money."""
        ...

    def capture(
        self,
        connection: sqlite3.Connection,
        provider_order_id: str,
        request_id: str,
    ) -> dict:
        """Capture the existing order with the original operation identifier."""
        ...


class DisabledPayPalSandboxAdapter:
    """Real sandbox integration is intentionally unavailable and does no I/O."""

    mode = "disabled"
    merchant_id = "unconfigured"

    def __getattr__(self, name: str):
        """Fail instead of silently substituting a fixture or live endpoint."""
        if name in {"create", "get", "capture", "approve", "find"}:

            def unavailable(*_args, **_kwargs):
                raise AppError(
                    "PAYPAL_UNAVAILABLE",
                    "Real PayPal adapter is disabled.",
                    503,
                )

            return unavailable
        raise AttributeError(name)


class FixturePaymentAdapter:
    """SQLite-backed fake provider with test-only, validated fault injection.

    Provider writes share the fixture DB transaction. A real remote provider
    cannot share that transaction and needs independently reviewed recovery.
    No HTTP field can select a fault or a real adapter.
    """

    mode = "fixture"
    merchant_id = "synthetic-merchant-only"
    FAULTS = {
        None,
        "create_timeout_after_success",
        "capture_timeout_after_success",
        "capture_timeout_before_success",
        "capture_pending",
    }

    def __init__(self, fault: str | None = None):
        """Allow only an explicit fixture fault, never arbitrary scenario data."""
        if type(fault) not in (str, type(None)) or fault not in self.FAULTS:
            raise AppError("INVALID_FIXTURE_FAULT", "Unknown fixture fault.")
        self.fault = fault

    def create(
        self, connection: sqlite3.Connection, request_id: str, expected: dict
    ) -> dict:
        """Persist exactly one synthetic provider order per request identifier."""
        existing = self.find(connection, request_id)
        if existing:
            return existing
        order_id = "FAKE-" + digest(request_id)[:24]
        document = {
            **expected,
            "provider_order_id": order_id,
            "status": "CREATED",
            "captures": [],
        }
        connection.execute(
            "INSERT INTO fixture_provider_orders VALUES (?, ?, ?)",
            (order_id, request_id, canonical(document)),
        )
        if self.fault == "create_timeout_after_success":
            raise ProviderAmbiguity("Synthetic create timeout")
        return document

    def find(
        self, connection: sqlite3.Connection, request_id: str
    ) -> dict | None:
        """Fixture-only reconciliation by the original persisted request ID."""
        row = connection.execute(
            "SELECT document FROM fixture_provider_orders WHERE request_id = ?",
            (request_id,),
        ).fetchone()
        return json.loads(row[0]) if row else None

    def get(
        self, connection: sqlite3.Connection, provider_order_id: str
    ) -> dict:
        """Read an existing fake order without any side effect."""
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

    def approve(
        self, connection: sqlite3.Connection, provider_order_id: str
    ) -> dict:
        """Explicit fake approval action; not a PayPal redirect or buyer login."""
        document = self.get(connection, provider_order_id)
        if document["status"] != "CREATED":
            raise AppError(
                "INVALID_STATE", "Order is not awaiting approval.", 409
            )
        document["status"] = "APPROVED"
        self._save(connection, document)
        return document

    def capture(
        self,
        connection: sqlite3.Connection,
        provider_order_id: str,
        request_id: str,
    ) -> dict:
        """Simulate one capture, optionally persisting an ambiguous result."""
        document = self.get(connection, provider_order_id)
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
            self._save(connection, document)
            raise ProviderAmbiguity("Synthetic pending capture")
        document["status"] = "COMPLETED"
        document["captures"] = [
            {
                "capture_id": "FAKE-CAP-" + digest(request_id)[:20],
                "status": "COMPLETED",
                "amount_minor": document["amount_minor"],
                "currency": document["currency"],
            }
        ]
        self._save(connection, document)
        if self.fault == "capture_timeout_after_success":
            raise ProviderAmbiguity(
                "Synthetic capture timeout after completion"
            )
        return document


def verify_provider_order(
    document: object,
    expected: dict,
    provider_id: str,
    merchant_id: str,
    allowed_statuses: set[str],
    capture_request_id: str | None = None,
) -> None:
    """Compare normalized complete fake data to the immutable server snapshot.

    No environment field from provider JSON is trusted. The adapter owns its
    transport/mode. Real PayPal minimal responses require its own GET mapping;
    they must never be treated as this complete fixture representation.
    """
    if (
        type(provider_id) is not str
        or not provider_id
        or type(document) is not dict
        or (
            document.get("provider_order_id") != provider_id
            or document.get("merchant_id") != merchant_id
            or type(document.get("status")) is not str
            or document.get("status") not in allowed_statuses
            or set(document)
            != set(expected)
            | {
                "provider_order_id",
                "status",
                "captures",
            }
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
