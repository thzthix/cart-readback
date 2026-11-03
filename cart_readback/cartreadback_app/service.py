"""Deterministic review, consent, and one-order fixture workflow."""

import json
import sqlite3
from datetime import datetime, timezone
from uuid import UUID, uuid4

from cartreadback_app.inference import (
    FixtureInferenceAdapter,
    InferenceAdapter,
    validate_proposal,
)
from cartreadback_app.payments import (
    FixturePaymentAdapter,
    ProviderAmbiguity,
    verify_provider_order,
)
from cartreadback_app.storage import Store, csrf_for, event, product_for
from cartreadback_app.validation import (
    AppError,
    canonical,
    conditions,
    digest,
    identifiers,
    integer,
    object_fields,
    string,
)

NOTICE = "Synthetic catalog, model and payment fixtures. No money moves."
BASE = {"expected_revision", "snapshot_hash"}


class Service:
    """Authorize every transition independently of model or browser claims."""

    def __init__(
        self,
        store: Store,
        inference: InferenceAdapter | None = None,
        payments: FixturePaymentAdapter | None = None,
        clock=None,
    ):
        """Inject offline adapters; HTTP setup never loads credentials."""
        self.store = store
        self.inference = inference or FixtureInferenceAdapter()
        self.payments = payments or FixturePaymentAdapter()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._recover_pending()

    def _recover_pending(self) -> None:
        # A reserved operation surviving service startup may have dispatched.
        # There is no automatic provider POST replay, even for a fake provider.
        with self.store.transaction() as connection:
            rows = connection.execute(
                "SELECT * FROM sessions WHERE checkout IS NOT NULL"
            ).fetchall()
            for row in rows:
                checkout = json.loads(row["checkout"])
                if checkout["state"] not in {
                    "CAPTURE_PENDING",
                    "ORDER_CREATE_PENDING",
                }:
                    continue
                session = dict(row)
                session["checkout"] = checkout
                checkout["state"] = "PAYMENT_UNKNOWN"
                checkout["order"]["status"] = "UNKNOWN"
                connection.execute(
                    "UPDATE operations SET status = 'UNKNOWN' WHERE sid = ? AND status = 'PENDING'",
                    (row["sid"],),
                )
                self._persist_order(connection, checkout)
                self._save(connection, session, "startup_unknown")

    def _session(self, connection: sqlite3.Connection, sid: str) -> dict:
        row = connection.execute(
            "SELECT * FROM sessions WHERE sid = ?",
            (sid,),
        ).fetchone()
        if not row:
            raise AppError("NOT_FOUND", "Unknown owner session.", 403)
        session = dict(row)
        session["checkout"] = (
            json.loads(row["checkout"]) if row["checkout"] else None
        )
        return session

    def _fresh(self, connection: sqlite3.Connection, checkout: dict) -> bool:
        return (
            checkout["catalog_hash"]
            == digest(product_for(connection, checkout["sku_id"]))
            and checkout["model"] == self.inference.metadata
        )

    def _public_checkout(
        self, connection: sqlite3.Connection, checkout: dict | None
    ) -> dict | None:
        if checkout is None:
            return None
        public = json.loads(canonical(checkout))
        public.pop("catalog_hash", None)
        public.pop("consent", None)
        if not self._fresh(connection, checkout):
            public["stale"] = True
            public["confirmation_id"] = None
            if public["state"] not in {"PAYMENT_UNKNOWN", "COMPLETED"}:
                public["state"] = "REVIEW_REQUIRED"
        return public

    def _envelope(self, connection: sqlite3.Connection, session: dict) -> dict:
        return {
            "api_version": "1",
            "mode": "fixture",
            "revision": session["revision"],
            "checkout": self._public_checkout(connection, session["checkout"]),
        }

    def bootstrap(self, sid: str) -> dict:
        """Restore current owned checkout without creating payment work."""
        with self.store.transaction() as connection:
            session = self._session(connection, sid)
            catalog = [
                product_for(connection, row[0])
                for row in connection.execute(
                    "SELECT sku FROM catalog ORDER BY rowid",
                ).fetchall()
            ]
            return {
                **self._envelope(connection, session),
                "notice": NOTICE,
                "csrf_token": csrf_for(sid),
                "catalog": catalog,
            }

    def revision(self, sid: str) -> int:
        """Read the latest aggregate revision for safe error envelopes."""
        with self.store.transaction() as connection:
            return self._session(connection, sid)["revision"]

    def _save(
        self, connection: sqlite3.Connection, session: dict, name: str
    ) -> None:
        session["revision"] += 1
        connection.execute(
            "UPDATE sessions SET revision = ?, checkout = ? WHERE sid = ?",
            (
                session["revision"],
                canonical(session["checkout"]),
                session["sid"],
            ),
        )
        event(
            connection,
            session["sid"],
            name,
            {
                "revision": session["revision"],
                "review_id": session["checkout"]["review_id"],
                "state": session["checkout"]["state"],
            },
        )

    def _current(
        self, connection: sqlite3.Connection, session: dict, body: dict
    ) -> dict:
        checkout = session["checkout"]
        if not checkout:
            raise AppError("NOT_FOUND", "No active review.", 404)
        if (
            not self._fresh(connection, checkout)
            or body["snapshot_hash"] != checkout["snapshot_hash"]
        ):
            raise AppError(
                "STALE_SNAPSHOT",
                "Reanalyze the changed source or selection.",
                409,
            )
        if (
            body.get("review_id", checkout["review_id"])
            != checkout["review_id"]
        ):
            raise AppError("NOT_FOUND", "Unknown owned review.", 404)
        return checkout

    def _state(self, checkout: dict, allowed: set[str]) -> None:
        if checkout["state"] not in allowed:
            raise AppError(
                "INVALID_STATE", "Action is not allowed in this state.", 409
            )

    def mutate(
        self,
        sid: str,
        action: str,
        body: dict,
        order_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict:
        """Validate owner/revision and transition under one SQLite write lock."""
        fields = {
            "analyze": {"expected_revision", "sku_id", "conditions"},
            "confirm": BASE
            | {
                "review_id",
                "confirmed_sku_id",
                "confirmed_condition_ids",
                "acknowledged_unknown_ids",
                "acknowledged_conflict_ids",
            },
            "orders": BASE | {"review_id", "confirmation_id"},
            "fixture-approve": BASE,
            "verify": BASE,
            "reconcile": BASE,
            "capture": BASE | {"confirmation_id", "final_confirmation"},
        }
        if action not in fields:
            raise AppError("NOT_FOUND", "Unknown action.", 404)
        object_fields(body, fields[action])
        integer(body["expected_revision"], "expected_revision", 0, 2**53 - 1)
        if action != "analyze":
            string(body["snapshot_hash"], "snapshot_hash", 64)
        if action == "capture" and body["final_confirmation"] is not True:
            raise AppError(
                "ACKNOWLEDGEMENT_REQUIRED",
                "Explicit final confirmation must be true.",
                409,
            )
        if action in {"orders", "capture"}:
            try:
                if (
                    type(idempotency_key) is not str
                    or str(UUID(idempotency_key)) != idempotency_key
                ):
                    raise ValueError("Not canonical UUID")
            except (ValueError, AttributeError) as error:
                raise AppError(
                    "INVALID_INPUT", "Idempotency-Key must be a UUID."
                ) from error
        with self.store.transaction() as connection:
            session = self._session(connection, sid)
            # Even a stale retry cannot bind its key to different content.
            operation = None
            if action in {"orders", "capture"}:
                operation = connection.execute(
                    "SELECT * FROM operations WHERE sid = ? AND kind = ? AND idempotency_key = ?",
                    (sid, action, idempotency_key),
                ).fetchone()
                request_hash = digest(
                    {
                        "action": action,
                        "order_id": order_id,
                        "body": {
                            key: value
                            for key, value in body.items()
                            if key != "expected_revision"
                        },
                    }
                )
                if operation and operation["request_hash"] != request_hash:
                    raise AppError(
                        "IDEMPOTENCY_CONFLICT",
                        "Key is bound to another request.",
                        409,
                    )
            if body["expected_revision"] != session["revision"]:
                raise AppError(
                    "STALE_REVISION",
                    "Reload the current review before continuing.",
                    409,
                )
            if operation:
                return self._envelope(connection, session)
            if action == "analyze":
                self._analyze(connection, session, body)
            elif action == "confirm":
                self._confirm(connection, session, body)
            elif action == "orders":
                self._create(
                    connection, session, body, idempotency_key, request_hash
                )
            else:
                self._order_action(
                    connection,
                    session,
                    action,
                    body,
                    order_id,
                    idempotency_key,
                    locals().get("request_hash"),
                )
            result = self._envelope(connection, session)
            if result["checkout"] and result["checkout"].get(
                "verification_error"
            ):
                result["error"] = {
                    "code": "ORDER_MISMATCH",
                    "message": "Provider order failed verification; reconcile this order.",
                }
            return result

    def _analyze(
        self, connection: sqlite3.Connection, session: dict, body: dict
    ) -> None:
        if connection.execute(
            "SELECT 1 FROM orders WHERE sid = ?",
            (session["sid"],),
        ).fetchone():
            raise AppError(
                "INVALID_STATE",
                "Selection is frozen after order creation.",
                409,
            )
        sku = string(body["sku_id"], "sku_id", 64)
        if not sku.isascii():
            raise AppError("INVALID_INPUT", "SKU must be ASCII.")
        choices = conditions(body["conditions"])
        product = product_for(connection, sku)
        choices = [
            {"condition_id": f"c{index + 1}", **choice}
            for index, choice in enumerate(choices)
        ]
        checkout = {
            "review_id": str(uuid4()),
            "state": "REVIEW_REQUIRED",
            "sku_id": sku,
            "conditions": choices,
            "results": [],
            "snapshot_hash": None,
            "confirmation_id": None,
            "order": None,
            "amount": {
                "minor": product["price_minor"],
                "currency": product["currency"],
            },
            "source": product["source"],
            "model": dict(self.inference.metadata),
            "catalog_hash": digest(product),
            "consent": None,
        }
        try:
            checkout["results"] = validate_proposal(
                product["source"],
                choices,
                self.inference.propose(product["source"], choices),
            )
        except AppError as error:
            checkout["state"] = "ANALYSIS_BLOCKED"
            checkout["analysis_error"] = error.code
        if checkout["state"] != "ANALYSIS_BLOCKED":
            checkout["snapshot_hash"] = digest(
                {
                    "owner": session["sid"],
                    "review_id": checkout["review_id"],
                    "catalog": product,
                    "conditions": choices,
                    "proposal": checkout["results"],
                    "model": checkout["model"],
                }
            )
        session["checkout"] = checkout
        connection.execute(
            "INSERT INTO reviews VALUES (?, ?, ?, ?)",
            (
                checkout["review_id"],
                session["sid"],
                checkout["snapshot_hash"] or "BLOCKED",
                canonical(checkout),
            ),
        )
        self._save(connection, session, "analysis_recorded")

    def _confirm(
        self, connection: sqlite3.Connection, session: dict, body: dict
    ) -> None:
        checkout = self._current(connection, session, body)
        self._state(checkout, {"REVIEW_REQUIRED", "SNAPSHOT_CONFIRMED"})
        if body["confirmed_sku_id"] != checkout["sku_id"]:
            raise AppError(
                "ACKNOWLEDGEMENT_REQUIRED", "Confirm the selected SKU.", 409
            )
        required = {
            "confirmed_condition_ids": {
                item["condition_id"] for item in checkout["conditions"]
            },
            "acknowledged_unknown_ids": {
                item["condition_id"]
                for item in checkout["results"]
                if item["status"] == "unknown"
            },
            "acknowledged_conflict_ids": {
                item["condition_id"]
                for item in checkout["results"]
                if item["status"] == "conflict"
            },
        }
        for field, expected in required.items():
            if set(identifiers(body[field], field)) != expected:
                raise AppError(
                    "ACKNOWLEDGEMENT_REQUIRED",
                    "Acknowledge each current condition separately.",
                    409,
                )
        checkout["confirmation_id"] = str(uuid4())
        checkout["consent"] = {
            **body,
            "confirmed_at": self.clock().isoformat(),
            "confirmation_id": checkout["confirmation_id"],
        }
        connection.execute(
            "INSERT INTO confirmations VALUES (?, ?, ?, ?, ?)",
            (
                checkout["confirmation_id"],
                session["sid"],
                checkout["review_id"],
                checkout["snapshot_hash"],
                canonical(checkout["consent"]),
            ),
        )
        checkout["state"] = "SNAPSHOT_CONFIRMED"
        self._save(connection, session, "buyer_confirmed")

    def _assert_confirmation(self, checkout: dict, body: dict) -> None:
        if (
            not checkout["confirmation_id"]
            or body["confirmation_id"] != checkout["confirmation_id"]
        ):
            raise AppError(
                "ACKNOWLEDGEMENT_REQUIRED",
                "Current explicit consent is required.",
                409,
            )

    def _reserve(
        self,
        connection: sqlite3.Connection,
        session: dict,
        kind: str,
        key: str,
        request_hash: str,
        order_id: str,
        upstream_payload: dict,
    ) -> str:
        operation_id = str(uuid4())
        try:
            connection.execute(
                "INSERT INTO operations(operation_id, sid, kind, idempotency_key, request_hash, order_id, status, upstream_payload, upstream_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    operation_id,
                    session["sid"],
                    kind,
                    key,
                    request_hash,
                    order_id,
                    "PENDING",
                    canonical(upstream_payload),
                    digest(upstream_payload),
                ),
            )
        except sqlite3.IntegrityError as error:
            raise AppError(
                "INVALID_STATE", "This business operation already exists.", 409
            ) from error
        return operation_id

    def _create(
        self,
        connection: sqlite3.Connection,
        session: dict,
        body: dict,
        key: str,
        request_hash: str,
    ) -> None:
        checkout = self._current(connection, session, body)
        self._state(checkout, {"SNAPSHOT_CONFIRMED"})
        self._assert_confirmation(checkout, body)
        product = product_for(connection, checkout["sku_id"])
        order_id = str(uuid4())
        expected = {
            "provider_mode": self.payments.mode,
            "intent": "CAPTURE",
            "merchant_id": self.payments.merchant_id,
            "reference_id": order_id,
            "custom_id": checkout["snapshot_hash"],
            "items": [
                {
                    "sku_id": product["sku_id"],
                    "name": product["name"],
                    "quantity": product["quantity"],
                    "unit_amount_minor": product["price_minor"],
                    "currency": product["currency"],
                }
            ],
            "amount_minor": product["price_minor"] * product["quantity"],
            "currency": product["currency"],
        }
        connection.execute(
            "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                order_id,
                session["sid"],
                checkout["review_id"],
                checkout["snapshot_hash"],
                None,
                "PENDING",
                canonical(expected),
            ),
        )
        operation_id = self._reserve(
            connection, session, "orders", key, request_hash, order_id, expected
        )
        checkout["order"] = {
            "order_id": order_id,
            "provider_order_id": None,
            "provider_mode": "fixture",
            "status": "PENDING",
            "approval_url": None,
            "operation_id": operation_id,
            "operation_kind": "orders",
        }
        checkout["state"] = "ORDER_CREATE_PENDING"
        self._save(connection, session, "create_reserved")
        # Reserve durably before dispatch. Concurrent actions observe pending.
        connection.commit()
        connection.execute("BEGIN IMMEDIATE")
        self._resume_reserved(connection, session, operation_id)
        # Fake provider writes and observation share this second transaction.
        # A real remote provider needs independently reviewed normalization.
        try:
            document = self.payments.create(connection, operation_id, expected)
            provider_id = (
                document.get("provider_order_id")
                if type(document) is dict
                else None
            )
            verify_provider_order(
                document,
                expected,
                provider_id,
                self.payments.merchant_id,
                {"CREATED"},
            )
            checkout["order"].update(
                provider_order_id=provider_id, status="CREATED"
            )
            checkout["state"] = "ORDER_CREATED"
            connection.execute(
                "UPDATE operations SET status = 'SUCCEEDED' WHERE operation_id = ?",
                (operation_id,),
            )
        except (ProviderAmbiguity, AppError):
            checkout["state"] = "PAYMENT_UNKNOWN"
            checkout["order"]["status"] = "UNKNOWN"
            connection.execute(
                "UPDATE operations SET status = 'UNKNOWN' WHERE operation_id = ?",
                (operation_id,),
            )
        self._persist_order(connection, checkout)
        self._save(connection, session, "create_observed")

    def _resume_reserved(
        self, connection: sqlite3.Connection, session: dict, operation_id: str
    ) -> None:
        current = self._session(connection, session["sid"])
        operation = connection.execute(
            "SELECT status FROM operations WHERE operation_id = ?",
            (operation_id,),
        ).fetchone()
        if (
            current["revision"] != session["revision"]
            or not operation
            or operation["status"] != "PENDING"
        ):
            raise AppError(
                "PAYMENT_UNKNOWN",
                "Reserved operation changed; reconcile instead of dispatching.",
                409,
            )

    def _checked_provider(
        self,
        connection: sqlite3.Connection,
        session: dict,
        document: object,
        expected: dict,
        provider_id: str,
        statuses: set[str],
    ) -> bool:
        try:
            verify_provider_order(
                document,
                expected,
                provider_id,
                self.payments.merchant_id,
                statuses,
            )
        except AppError as error:
            checkout = session["checkout"]
            checkout["state"] = "PAYMENT_UNKNOWN"
            checkout["order"]["status"] = "UNKNOWN"
            checkout["verification_error"] = error.code
            self._persist_order(connection, checkout)
            self._save(connection, session, "verification_failed")
            return False
        return True

    def _persist_order(
        self, connection: sqlite3.Connection, checkout: dict
    ) -> None:
        order = checkout["order"]
        connection.execute(
            "UPDATE orders SET provider_order_id = ?, status = ? WHERE order_id = ?",
            (order["provider_order_id"], order["status"], order["order_id"]),
        )

    def _order_action(
        self,
        connection: sqlite3.Connection,
        session: dict,
        action: str,
        body: dict,
        order_id: str,
        key: str | None,
        request_hash: str | None,
    ) -> None:
        checkout = session["checkout"]
        if (
            not checkout
            or not checkout["order"]
            or order_id != checkout["order"]["order_id"]
        ):
            raise AppError("NOT_FOUND", "Unknown owned order.", 404)
        row = connection.execute(
            "SELECT * FROM orders WHERE order_id = ? AND sid = ?",
            (order_id, session["sid"]),
        ).fetchone()
        if not row or body["snapshot_hash"] != row["snapshot_hash"]:
            raise AppError("NOT_FOUND", "Unknown owned order binding.", 404)
        if action != "reconcile":
            self._current(connection, session, body)
        order = checkout["order"]
        expected = json.loads(row["expected"])
        provider_id = order["provider_order_id"]
        if action == "fixture-approve":
            self._state(checkout, {"ORDER_CREATED"})
            document = self.payments.approve(connection, provider_id)
            if not self._checked_provider(
                connection,
                session,
                document,
                expected,
                provider_id,
                {"APPROVED"},
            ):
                return
            order["status"] = "APPROVED"
            checkout["state"] = "PAYPAL_APPROVED"
        elif action == "verify":
            self._state(
                checkout,
                {"ORDER_CREATED", "PAYPAL_APPROVED", "SERVER_RECHECKED"},
            )
            document = self.payments.get(connection, provider_id)
            if type(document) is dict and document.get("status") == "CREATED":
                raise AppError(
                    "ORDER_NOT_APPROVED",
                    "Explicit fixture approval is still required.",
                    409,
                )
            if not self._checked_provider(
                connection,
                session,
                document,
                expected,
                provider_id,
                {"APPROVED"},
            ):
                return
            order["status"] = "APPROVED"
            checkout["state"] = "SERVER_RECHECKED"
        elif action == "capture":
            if checkout["state"] == "COMPLETED":
                return
            self._state(checkout, {"SERVER_RECHECKED"})
            self._assert_confirmation(checkout, body)
            if body["final_confirmation"] is not True:
                raise AppError(
                    "ACKNOWLEDGEMENT_REQUIRED",
                    "Explicit final confirmation must be true.",
                    409,
                )
            document = self.payments.get(connection, provider_id)
            if not self._checked_provider(
                connection,
                session,
                document,
                expected,
                provider_id,
                {"APPROVED"},
            ):
                return
            operation_id = self._reserve(
                connection,
                session,
                "capture",
                key,
                request_hash,
                order_id,
                {
                    "provider_order_id": provider_id,
                    "snapshot_hash": checkout["snapshot_hash"],
                    "confirmation_id": checkout["confirmation_id"],
                    "expected": expected,
                },
            )
            checkout["state"] = "CAPTURE_PENDING"
            order.update(operation_id=operation_id, operation_kind="capture")
            self._save(connection, session, "capture_reserved")
            connection.commit()
            connection.execute("BEGIN IMMEDIATE")
            self._resume_reserved(connection, session, operation_id)
            try:
                document = self.payments.capture(
                    connection, provider_id, operation_id
                )
                verify_provider_order(
                    document,
                    expected,
                    provider_id,
                    self.payments.merchant_id,
                    {"COMPLETED"},
                    operation_id,
                )
                order["status"] = "COMPLETED"
                order["capture_id"] = document["captures"][0]["capture_id"]
                checkout["state"] = "COMPLETED"
                connection.execute(
                    "UPDATE operations SET status = 'SUCCEEDED' WHERE operation_id = ?",
                    (operation_id,),
                )
            except (ProviderAmbiguity, AppError):
                order["status"] = "UNKNOWN"
                checkout["state"] = "PAYMENT_UNKNOWN"
                connection.execute(
                    "UPDATE operations SET status = 'UNKNOWN' WHERE operation_id = ?",
                    (operation_id,),
                )
        elif action == "reconcile":
            self._state(
                checkout,
                {
                    "PAYMENT_UNKNOWN",
                    "COMPLETED",
                    "CAPTURE_PENDING",
                    "ORDER_CREATE_PENDING",
                },
            )
            if checkout["state"] in {"CAPTURE_PENDING", "ORDER_CREATE_PENDING"}:
                checkout["state"] = "PAYMENT_UNKNOWN"
                order["status"] = "UNKNOWN"
                connection.execute(
                    "UPDATE operations SET status = 'UNKNOWN' WHERE order_id = ? AND status = 'PENDING'",
                    (order_id,),
                )
            if provider_id is None:
                order["reconciliation_code"] = "CREATE_OUTCOME_UNKNOWN"
            else:
                document = self.payments.get(connection, provider_id)
                if (
                    type(document) is dict
                    and document.get("status") == "COMPLETED"
                ):
                    operation = connection.execute(
                        "SELECT * FROM operations WHERE order_id = ? AND kind = 'capture'",
                        (order_id,),
                    ).fetchone()
                    if not operation:
                        raise AppError(
                            "ORDER_MISMATCH",
                            "No authorized capture operation exists.",
                            409,
                        )
                    verify_provider_order(
                        document,
                        expected,
                        provider_id,
                        self.payments.merchant_id,
                        {"COMPLETED"},
                        operation["operation_id"],
                    )
                    checkout["state"] = "COMPLETED"
                    order["status"] = "COMPLETED"
                    order["capture_id"] = document["captures"][0]["capture_id"]
                    connection.execute(
                        "UPDATE operations SET status = 'SUCCEEDED' WHERE operation_id = ?",
                        (operation["operation_id"],),
                    )
                else:
                    verify_provider_order(
                        document,
                        expected,
                        provider_id,
                        self.payments.merchant_id,
                        {"CREATED", "APPROVED", "PENDING"},
                    )
                    # APPROVED on a lookup does not prove a timed-out capture
                    # cannot complete later. Never clear capture uncertainty.
                    order["reconciliation_code"] = "PAYMENT_UNKNOWN"
        self._persist_order(connection, checkout)
        self._save(connection, session, f"{action}_observed")
