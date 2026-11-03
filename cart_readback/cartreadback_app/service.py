"""Deterministic review, consent, and one-order fixture workflow."""

import json
import math
import re
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from cartreadback_app.analysis import (
    AnalysisPolicy,
    OfflineAnalysisBudget,
    checked_observation,
)
from cartreadback_app.context_capacity import (
    ContextFence,
    ContextReservation,
    TransactionContextCapacityLedger,
    context_ledger_from_document,
    initialize_context_capacity,
    recover_context_capacity,
)
from cartreadback_app.context_runtime import ContextAnalysisRuntime, blocked
from cartreadback_app.count_preflight import (
    PREFLIGHT_VERSION,
    run_offline_count,
)
from cartreadback_app.genuine_responses import (
    GenuineExchange,
    GenuineResponsesAdapter,
)
from cartreadback_app.inference import (
    FixtureInferenceAdapter,
    InferenceAdapter,
    validate_proposal,
)
from cartreadback_app.inference_budget import (
    BudgetClaim,
    TransactionBudgetLedger,
    policy_from_identity,
    recover_budget,
    request_hash,
    validate_input_count,
)
from cartreadback_app.payments import (
    FixturePaymentAdapter,
    PaymentAdapter,
    PaymentRequest,
    ProviderAmbiguity,
    verify_provider_order,
)
from cartreadback_app.responses_adapter import OfflineResponsesAdapter
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
    text_hash,
)

NOTICE = "Synthetic catalog, model and payment fixtures. No money moves."
BASE = {"expected_revision", "snapshot_hash"}


class Service:
    """Authorize every transition independently of model or browser claims."""

    def __init__(
        self,
        store: Store,
        inference: InferenceAdapter | None = None,
        payments: PaymentAdapter | None = None,
        clock=None,
        analysis_policy: AnalysisPolicy | None = None,
        analysis_budget: OfflineAnalysisBudget | None = None,
        context_analysis: ContextAnalysisRuntime | None = None,
    ):
        """Inject offline adapters; HTTP setup never loads credentials."""
        self.store = store
        self._lease = store.acquire_service()
        self._activity_lock = threading.Lock()
        self._active = 0
        self._closed = False
        self.analysis_policy = analysis_policy or AnalysisPolicy()
        self.analysis_budget = analysis_budget
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.context_analysis = context_analysis
        self.inference = inference or FixtureInferenceAdapter()
        if context_analysis is not None:
            if (
                type(context_analysis) is not ContextAnalysisRuntime
                or inference is not None
                or analysis_budget is not None
            ):
                self.close()
                raise blocked()
            self.inference = GenuineResponsesAdapter(
                context_analysis, self._context_wall_now
            )
        try:
            self.payments = payments or FixturePaymentAdapter()
            self._recover_pending()
        except BaseException:
            self.close()
            raise

    @property
    def payments(self) -> PaymentAdapter:
        """Return the configured offline payment adapter."""
        return self._payments

    @payments.setter
    def payments(self, adapter: PaymentAdapter) -> None:
        if (
            self.context_analysis is not None
            or type(self.inference) is GenuineResponsesAdapter
        ) and type(adapter) is not FixturePaymentAdapter:
            raise blocked()
        if isinstance(adapter, FixturePaymentAdapter):
            with self.store.transaction() as connection:
                legacy = connection.execute(
                    "SELECT * FROM fixture_provider_orders"
                ).fetchall()
            adapter.bind(
                self.store.path.with_name(
                    self.store.path.name + ".fixture.sqlite3"
                ),
                [tuple(row) for row in legacy],
            )
        self._payments = adapter

    def close(self) -> None:
        """Release ownership only when no request can still dispatch."""
        with self._activity_lock:
            if self._active:
                raise AppError(
                    "INVALID_STATE", "Service still has active work.", 409
                )
            self._closed = True
            self._lease.close()

    def __del__(self):
        """Release the OS guard when the service is discarded."""
        if hasattr(self, "_lease"):
            self._lease.close()

    @contextmanager
    def _activity(self):
        with self._activity_lock:
            if self._closed:
                raise AppError("INVALID_STATE", "Service is closed.", 409)
            self._active += 1
        try:
            yield
        finally:
            with self._activity_lock:
                self._active -= 1

    def _checkpoint(self, _name: str, _operation_id: str) -> None:
        # Test-only interruption hook, never selectable through HTTP.
        pass

    def _recover_pending(self) -> None:
        # A reserved operation surviving service startup may have dispatched.
        # There is no automatic provider POST replay, even for a fake provider.
        with self.store.transaction() as connection:
            self._recover_analysis(connection)
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
                    "UPDATE operations SET status = 'UNKNOWN' WHERE sid = ? AND status IN ('PENDING', 'RESERVED', 'DISPATCHED')",
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
        if (
            type(self.inference) is GenuineResponsesAdapter
            and self.context_analysis is not self.inference.runtime
        ):
            return False
        return checkout["catalog_hash"] == digest(
            product_for(connection, checkout["sku_id"])
        ) and checkout["model"] == self._analysis_metadata(self.inference)

    def _public_checkout(
        self, connection: sqlite3.Connection, checkout: dict | None
    ) -> dict | None:
        if checkout is None:
            return None
        allowed = {
            "review_id",
            "state",
            "analysis_error",
            "sku_id",
            "conditions",
            "results",
            "snapshot_hash",
            "confirmation_id",
            "order",
            "amount",
            "source",
            "model",
            "verification_error",
        }
        public = json.loads(
            canonical(
                {
                    key: value
                    for key, value in checkout.items()
                    if key in allowed
                }
            )
        )
        if (
            checkout["model"].get("execution_mode")
            == "genuine-context-capacity"
        ):
            keys = {
                "provider",
                "model_version",
                "prompt_version",
                "adapter_version",
                "validator_version",
                "is_fixture",
                "execution_mode",
                "execution_kind",
            }
            public["model"] = {
                key: value
                for key, value in checkout["model"].items()
                if key in keys
            }
            public["analysis"] = self._public_context_outcome(
                connection, checkout["review_id"]
            )
        if not self._fresh(connection, checkout):
            public["stale"] = True
            public["confirmation_id"] = None
            if public["state"] not in {
                "PAYMENT_UNKNOWN",
                "COMPLETED",
                "ANALYSIS_BLOCKED",
            }:
                public["state"] = "REVIEW_REQUIRED"
        return public

    def provider_contract(self) -> dict:
        """Describe analysis and payments separately, never infer live readiness.

        There is no runtime credential/transport factory. Nonfixture adapters in
        this build are explicitly injected offline test seams, not genuine calls.
        Unknown adapters remain unsupported and are blocked by the buyer UI.
        """
        if type(self.inference) is GenuineResponsesAdapter:
            installed = self.inference.runtime.installed
            kind = (
                (
                    "provider-runtime"
                    if installed.evidence_kind == "provider"
                    else "fabricated-offline"
                )
                if installed
                else "unavailable"
            )
            available = (
                self.inference.runtime.available(self._context_wall_now())
                and self.context_analysis is self.inference.runtime
                and type(self.payments) is FixturePaymentAdapter
            )
            return {
                "analysis": {
                    "mode": "genuine-context-capacity",
                    "is_fixture": False,
                    "dispatch_available": available,
                    "execution_kind": kind,
                },
                "payment": {"mode": "fixture", "is_fixture": True},
                "network_enabled": kind == "provider-runtime" and available,
            }
        analysis_fixture = (
            self._analysis_metadata(self.inference).get("is_fixture") is True
        )
        payment_mode = self.payments.mode
        return {
            "analysis": {
                "mode": "fixture" if analysis_fixture else "injected-offline",
                "is_fixture": analysis_fixture,
            },
            "payment": {
                "mode": payment_mode,
                "is_fixture": payment_mode == "fixture",
            },
            "network_enabled": False,
        }

    def runtime_mode(self) -> str:
        """Retain fixture for its exact default, otherwise identify offline mode."""
        providers = self.provider_contract()
        if providers["analysis"]["mode"] == "genuine-context-capacity":
            return "mixed"
        return (
            "fixture"
            if providers["analysis"]["is_fixture"]
            and providers["payment"]["is_fixture"]
            else "offline"
        )

    def _envelope(self, connection: sqlite3.Connection, session: dict) -> dict:
        return {
            "api_version": "1",
            "mode": self.runtime_mode(),
            "providers": self.provider_contract(),
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
                "notice": (
                    NOTICE
                    if self.runtime_mode() == "fixture"
                    else "Context analysis is host-configured; availability and observations are reported separately. Checkout is simulated; PayPal is unconnected. API charges may apply to a separately provisioned provider runtime."
                    if self.runtime_mode() == "mixed"
                    else "Synthetic catalog and injected offline adapters. "
                    "No genuine inference, PayPal connection or payment."
                ),
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
        """Authorize short local transitions; adapter I/O never holds a DB lock."""
        with self._activity():
            return self._mutate(sid, action, body, order_id, idempotency_key)

    def _mutate(self, sid, action, body, order_id, idempotency_key):
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
            "buyer-return": BASE
            | {"return_state", "provider_order_id", "outcome"},
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
        if action == "analyze":
            return self._analyze(sid, json.loads(canonical(body)))
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
            if action == "confirm":
                self._confirm(connection, session, body)
            elif action == "orders":
                adapter = self.payments
                reservation = self._create(
                    connection,
                    session,
                    body,
                    idempotency_key,
                    request_hash,
                    adapter,
                )
            else:
                adapter = self.payments
                plan = self._plan_order_action(
                    connection,
                    session,
                    action,
                    body,
                    order_id,
                    adapter,
                )
            if action == "confirm":
                return self._result(connection, session)
        if action == "orders":
            self._checkpoint(
                "after_reservation_commit", reservation["operation_id"]
            )
            self._dispatch(reservation, adapter)
        else:
            self._perform_order_action(
                sid,
                action,
                body,
                order_id,
                idempotency_key,
                locals().get("request_hash"),
                adapter,
                plan,
            )
        with self.store.transaction() as connection:
            return self._result(connection, self._session(connection, sid))

    def _result(self, connection, session):
        result = self._envelope(connection, session)
        if result["checkout"] and result["checkout"].get("verification_error"):
            result["error"] = {
                "code": "ORDER_MISMATCH",
                "message": "Provider order failed verification; reconcile this order.",
            }
        return result

    def _recover_analysis(self, connection):
        initialize_context_capacity(connection)
        self._migrate_analysis_strategies(connection)
        recover_context_capacity(connection)
        preflights = connection.execute(
            "SELECT * FROM analysis_preflights WHERE status IN ('PREPARED', 'COUNTING')"
        ).fetchall()
        for plan in preflights:
            connection.execute(
                "UPDATE analysis_preflights SET status = 'UNKNOWN', "
                "error_code = 'MODEL_OUTCOME_UNKNOWN' WHERE preflight_id = ?",
                (plan["preflight_id"],),
            )
            self._block_count_intent(connection, plan, "MODEL_OUTCOME_UNKNOWN")
        recover_budget(connection)
        rows = connection.execute(
            "SELECT * FROM analysis_operations "
            "WHERE status IN ('RESERVED', 'DISPATCHED')"
        ).fetchall()
        for operation in rows:
            connection.execute(
                "UPDATE analysis_operations SET status = 'UNKNOWN', "
                "error_code = 'MODEL_OUTCOME_UNKNOWN' WHERE operation_id = ?",
                (operation["operation_id"],),
            )
            if not connection.execute(
                "SELECT 1 FROM sessions WHERE sid = ?", (operation["sid"],)
            ).fetchone():
                continue
            session = self._session(connection, operation["sid"])
            checkout = session["checkout"]
            if checkout and checkout["review_id"] == operation["review_id"]:
                checkout["state"] = "ANALYSIS_BLOCKED"
                checkout["analysis_error"] = "MODEL_OUTCOME_UNKNOWN"
                checkout["results"] = []
                checkout["snapshot_hash"] = None
                self._write_review(connection, session)
                self._save(connection, session, "analysis_startup_unknown")

    def _write_review(self, connection, session):
        checkout = session["checkout"]
        connection.execute(
            "INSERT OR REPLACE INTO reviews VALUES (?, ?, ?, ?)",
            (
                checkout["review_id"],
                session["sid"],
                checkout["snapshot_hash"] or "BLOCKED",
                canonical(checkout),
            ),
        )

    def _analysis_metadata(self, adapter):
        if type(adapter) is GenuineResponsesAdapter:
            return adapter.metadata
        model = json.loads(canonical(adapter.metadata))
        model["is_fixture"] = (
            isinstance(adapter, FixtureInferenceAdapter)
            and model.get("is_fixture") is True
        )
        if not model["is_fixture"]:
            budget = self.analysis_budget
            model["count_preflight_version"] = PREFLIGHT_VERSION
            model["count_timeout_seconds"] = (
                budget.count_timeout_seconds
                if type(budget) is OfflineAnalysisBudget
                else None
            )
            model["budget_policy_sha256"] = (
                digest(json.loads(budget.policy.identity))
                if type(budget) is OfflineAnalysisBudget
                else None
            )
        return model

    def _configured_budget(self, connection, adapter, model):
        budget = self.analysis_budget
        if (
            type(budget) is not OfflineAnalysisBudget
            or type(adapter) is not OfflineResponsesAdapter
            or budget.policy.dispatch_config_sha256
            != model.get("config_sha256")
            or budget.policy.model != model.get("model_version")
            or budget.policy.service_tier != model.get("service_tier")
            or budget.policy.max_output_tokens != model.get("max_output_tokens")
            or model.get("execution_mode") != "offline-injected-only"
            or connection.execute(
                "SELECT 1 FROM analysis_operations a LEFT JOIN budget_operations b "
                "ON a.operation_id = b.operation_id WHERE a.strategy = 'offline-count-v1' "
                "AND b.operation_id IS NULL LIMIT 1"
            ).fetchone()
        ):
            raise AppError(
                "MODEL_BUDGET_EXCEEDED", "Offline budget unavailable.", 503
            )
        return TransactionBudgetLedger(connection, budget.policy)

    def _reserved_budget(self, connection, inputs):
        return TransactionBudgetLedger(
            connection, policy_from_identity(inputs["budget_policy_document"])
        )

    def _analysis_admission(self, connection, current_preflight_id=None):
        rows = connection.execute(
            "SELECT status, observation FROM analysis_operations "
            "WHERE is_fixture = 0"
        ).fetchall()
        if len(rows) >= self.analysis_policy.max_attempts or any(
            row["status"] == "UNKNOWN" for row in rows
        ):
            raise AppError(
                "MODEL_BUDGET_EXCEEDED",
                "Offline analysis limit or unresolved usage blocks dispatch.",
                503,
            )
        if any(row["status"] in {"RESERVED", "DISPATCHED"} for row in rows):
            raise AppError(
                "MODEL_UNAVAILABLE", "Analysis already in flight.", 503
            )
        try:
            self._analysis_history_guard(connection, current_preflight_id)
        except AppError as error:
            raise AppError(
                "MODEL_BUDGET_EXCEEDED",
                "Unresolved analysis history blocks dispatch.",
                503,
            ) from error

    def _new_analysis_checkout(self, product, choices, model):
        return {
            "review_id": str(uuid4()),
            "state": "ANALYSIS_BLOCKED",
            "analysis_error": "MODEL_PENDING",
            "sku_id": product["sku_id"],
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
            "model": model,
            "catalog_hash": digest(product),
            "consent": None,
        }

    def _preflight_document(self, connection, session, body, adapter, budget):
        product, choices, model = self._analysis_inputs(
            connection, session, body, adapter
        )
        if (
            model["is_fixture"]
            or self.inference is not adapter
            or self.analysis_budget is not budget
        ):
            raise AppError(
                "STALE_SNAPSHOT", "Analysis configuration changed.", 409
            )
        request = adapter.build_request(product["source"], choices)
        return canonical(
            {
                "sid": session["sid"],
                "revision": session["revision"],
                "review_id": session["checkout"]["review_id"],
                "checkout_sha256": digest(session["checkout"]),
                "body_sha256": digest(body),
                "catalog": product,
                "conditions": choices,
                "model": model,
                "budget_policy_document": budget.policy.identity,
                "request_sha256": request_hash(request),
            }
        ), request

    def _preflight_admission(self, connection, budget):
        rows = connection.execute(
            "SELECT status FROM analysis_preflights"
        ).fetchall()
        if len(rows) >= min(
            self.analysis_policy.max_attempts, budget.policy.max_calls
        ) or any(row["status"] == "UNKNOWN" for row in rows):
            raise AppError(
                "MODEL_BUDGET_EXCEEDED",
                "Count preflight limit or unknown outcome.",
                503,
            )
        reserved = connection.execute(
            "SELECT * FROM budget_operations"
        ).fetchall()
        policy = budget.policy
        if (
            len(reserved) >= policy.max_calls
            or any(row["status"] != "KNOWN" for row in reserved)
            or sum(row["input_tokens"] for row in reserved) + 1
            > policy.max_total_input_tokens
            or sum(row["output_tokens"] for row in reserved)
            + policy.max_output_tokens
            > policy.max_total_output_tokens
            or sum(row["reserved_micro_usd"] for row in reserved)
            + policy.cost(1, policy.max_output_tokens)
            > policy.max_micro_usd
        ):
            raise AppError(
                "MODEL_BUDGET_EXCEEDED",
                "No capacity for another analysis.",
                503,
            )
        if any(row["status"] in {"PREPARED", "COUNTING"} for row in rows):
            raise AppError(
                "MODEL_UNAVAILABLE", "Count preflight already active.", 503
            )

    def _preflight_fresh(self, connection, plan, body, adapter, budget):
        try:
            session = self._session(connection, plan["sid"])
            document, _ = self._preflight_document(
                connection, session, body, adapter, budget
            )
            return (
                document == plan["input_document"]
                and text_hash(document) == plan["input_hash"]
            )
        except (AppError, ValueError, TypeError, KeyError):
            return False

    def _block_count_intent(self, connection, plan, error_code):
        try:
            inputs = json.loads(plan["input_document"])
            if (
                type(inputs) is not dict
                or not {"revision", "review_id"} <= inputs.keys()
            ):
                return
        except (ValueError, TypeError):
            return
        if not connection.execute(
            "SELECT 1 FROM sessions WHERE sid = ?", (plan["sid"],)
        ).fetchone():
            return
        session = self._session(connection, plan["sid"])
        checkout = session["checkout"]
        if (
            checkout is None
            or session["revision"] != inputs["revision"]
            or checkout["review_id"] != inputs["review_id"]
        ):
            return
        checkout.update(
            state="ANALYSIS_BLOCKED",
            analysis_error=error_code,
            results=[],
            snapshot_hash=None,
            confirmation_id=None,
            consent=None,
        )
        self._write_review(connection, session)
        self._save(connection, session, "count_preflight_blocked")

    def _claim_count(self, plan, body, adapter, budget):
        with self.store.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM analysis_preflights WHERE preflight_id = ?",
                (plan["preflight_id"],),
            ).fetchone()
            if (
                row is None
                or row["status"] != "PREPARED"
                or row["sid"] != plan["sid"]
                or row["input_document"] != plan["input_document"]
                or row["input_hash"] != plan["input_hash"]
            ):
                return None
            if not self._preflight_fresh(
                connection, plan, body, adapter, budget
            ):
                connection.execute(
                    "UPDATE analysis_preflights SET status = 'STALE', "
                    "error_code = 'STALE_SNAPSHOT', observed_at = ? WHERE preflight_id = ?",
                    (self.clock().isoformat(), plan["preflight_id"]),
                )
                self._block_count_intent(connection, plan, "STALE_SNAPSHOT")
                return None
            token = str(uuid4())
            connection.execute(
                "UPDATE analysis_preflights SET status = 'COUNTING', claim_token = ? "
                "WHERE preflight_id = ?",
                (token, plan["preflight_id"]),
            )
            return {**plan, "claim_token": token}

    def _finish_count(self, plan, body, adapter, budget, count, error_code):
        reservation = None
        with self.store.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM analysis_preflights WHERE preflight_id = ?",
                (plan["preflight_id"],),
            ).fetchone()
            if (
                row is None
                or row["status"] != "COUNTING"
                or row["claim_token"] != plan["claim_token"]
                or row["sid"] != plan["sid"]
                or row["input_document"] != plan["input_document"]
                or row["input_hash"] != plan["input_hash"]
            ):
                return None, "MODEL_BUDGET_EXCEEDED"
            status, count_document = "UNKNOWN", ""
            if not error_code:
                count_document = canonical(asdict(count))
                if not self._preflight_fresh(
                    connection, plan, body, adapter, budget
                ):
                    status, error_code = "STALE", "STALE_SNAPSHOT"
                else:
                    session = self._session(connection, plan["sid"])
                    connection.execute("SAVEPOINT counted_reservation")
                    try:
                        reservation = self._reserve_analysis(
                            connection, session, body, adapter, plan, count
                        )
                    except AppError:
                        connection.execute("ROLLBACK TO counted_reservation")
                        connection.execute("RELEASE counted_reservation")
                        status, error_code = "BLOCKED", "MODEL_BUDGET_EXCEEDED"
                    else:
                        connection.execute("RELEASE counted_reservation")
                        status = "USED"
            if status != "USED":
                self._block_count_intent(connection, plan, error_code)
            connection.execute(
                "UPDATE analysis_preflights SET status = ?, count_document = ?, "
                "analysis_operation_id = ?, error_code = ?, observed_at = ? WHERE preflight_id = ?",
                (
                    status,
                    count_document,
                    reservation["operation_id"] if reservation else "",
                    error_code,
                    self.clock().isoformat(),
                    plan["preflight_id"],
                ),
            )
        return reservation, error_code

    def _analyze(self, sid, body):
        if type(self.inference) is GenuineResponsesAdapter:
            return self._analyze_context(sid, body)
        with self.store.transaction() as connection:
            session = self._session(connection, sid)
            if body["expected_revision"] != session["revision"]:
                raise AppError(
                    "STALE_REVISION", "Reload the current review.", 409
                )
            adapter = self.inference
            product, choices, model = self._analysis_inputs(
                connection, session, body, adapter
            )
            fixture = model["is_fixture"]
            if fixture:
                if (
                    connection.execute(
                        "SELECT 1 FROM analysis_operations WHERE strategy = 'context-capacity-v1' LIMIT 1"
                    ).fetchone()
                    or connection.execute(
                        "SELECT 1 FROM context_capacity_operations LIMIT 1"
                    ).fetchone()
                ):
                    self._analysis_history_guard(connection)
                reservation = self._reserve_analysis(
                    connection, session, body, adapter
                )
            else:
                self._analysis_admission(connection)
                self._configured_budget(connection, adapter, model)
                budget = self.analysis_budget
                self._preflight_admission(connection, budget)
                session["checkout"] = self._new_analysis_checkout(
                    product, choices, model
                )
                self._write_review(connection, session)
                self._save(connection, session, "count_preflight_intent")
                document, request = self._preflight_document(
                    connection, session, body, adapter, budget
                )
                preflight_id = str(uuid4())
                connection.execute(
                    "INSERT INTO analysis_preflights(preflight_id, sid, input_document, "
                    "input_hash, status, created_at) VALUES (?, ?, ?, ?, 'PREPARED', ?)",
                    (
                        preflight_id,
                        sid,
                        document,
                        text_hash(document),
                        self.clock().isoformat(),
                    ),
                )
                plan = dict(
                    connection.execute(
                        "SELECT * FROM analysis_preflights WHERE preflight_id = ?",
                        (preflight_id,),
                    ).fetchone()
                )
        if not fixture:
            self._checkpoint(
                "analysis_after_count_reservation_commit", plan["preflight_id"]
            )
            plan = self._claim_count(plan, body, adapter, budget)
            if plan is None:
                raise AppError(
                    "STALE_SNAPSHOT",
                    "Count preflight is no longer current.",
                    409,
                )
            self._checkpoint(
                "analysis_after_count_claim_commit", plan["preflight_id"]
            )
            count, error_code = None, ""
            try:
                timeout = json.loads(plan["input_document"])["model"][
                    "count_timeout_seconds"
                ]
                count = run_offline_count(budget.count, request, timeout)
                validate_input_count(request, count, budget.policy)
            except AppError as error:
                error_code = (
                    "MODEL_TIMEOUT"
                    if error.code == "MODEL_TIMEOUT"
                    else "MODEL_BUDGET_EXCEEDED"
                )
            self._checkpoint(
                "analysis_before_count_observation_commit", plan["preflight_id"]
            )
            reservation, error_code = self._finish_count(
                plan, body, adapter, budget, count, error_code
            )
            if error_code:
                raise AppError(
                    error_code,
                    "Count preflight failed or changed; no generation.",
                    409 if error_code == "STALE_SNAPSHOT" else 503,
                )
        self._checkpoint(
            "analysis_after_reservation_commit", reservation["operation_id"]
        )
        self._dispatch_analysis(reservation, adapter)
        with self.store.transaction() as connection:
            return self._result(connection, self._session(connection, sid))

    def _analysis_inputs(self, connection, session, body, adapter):
        if connection.execute(
            "SELECT 1 FROM orders WHERE sid = ?", (session["sid"],)
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
        model = self._analysis_metadata(adapter)
        return product, choices, model

    def _reserve_analysis(
        self, connection, session, body, adapter, preflight=None, count=None
    ):
        product, choices, model = self._analysis_inputs(
            connection, session, body, adapter
        )
        fixture = model.get("is_fixture") is True
        if not fixture:
            self._analysis_admission(
                connection, preflight["preflight_id"] if preflight else None
            )
        operation_id = str(uuid4())
        budget_fields = {}
        if not fixture:
            budget = self.analysis_budget
            ledger = self._configured_budget(connection, adapter, model)
            request = adapter.build_request(product["source"], choices)
            if preflight is None:
                raise AppError(
                    "MODEL_BUDGET_EXCEEDED", "Count preflight required.", 503
                )
            row = connection.execute(
                "SELECT * FROM analysis_preflights WHERE preflight_id = ?",
                (preflight["preflight_id"],),
            ).fetchone()
            if (
                row is None
                or row["status"] != "COUNTING"
                or row["claim_token"] != preflight["claim_token"]
                or row["input_document"] != preflight["input_document"]
                or row["input_hash"] != preflight["input_hash"]
            ):
                raise AppError(
                    "MODEL_BUDGET_EXCEEDED", "Count preflight unavailable.", 503
                )
            operation_id = ledger.reserve(request, count)
            budget_fields = {
                "budget_policy_document": budget.policy.identity,
                "budget_request_sha256": request_hash(request),
                "count_preflight_id": preflight["preflight_id"],
                "count_preflight_sha256": preflight["input_hash"],
            }
        checkout = self._new_analysis_checkout(product, choices, model)
        document = canonical(
            {
                "catalog": product,
                "conditions": choices,
                "model": model,
                **budget_fields,
            }
        )
        connection.execute(
            "INSERT INTO analysis_operations(operation_id, sid, review_id, "
            "input_document, input_hash, checkout_hash, reserved_revision, is_fixture, status, "
            "reserved_at, strategy) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'RESERVED', ?, ?)",
            (
                operation_id,
                session["sid"],
                checkout["review_id"],
                document,
                text_hash(document),
                digest(checkout),
                session["revision"] + 1,
                int(fixture),
                self.clock().isoformat(),
                "fixture" if fixture else "offline-count-v1",
            ),
        )
        session["checkout"] = checkout
        self._write_review(connection, session)
        self._save(connection, session, "analysis_reserved")
        return dict(
            connection.execute(
                "SELECT * FROM analysis_operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
        )

    def _analysis_fresh(self, connection, operation, reservation, adapter):
        immutable = (
            "operation_id",
            "sid",
            "review_id",
            "input_document",
            "input_hash",
            "checkout_hash",
            "reserved_revision",
            "is_fixture",
            "strategy",
        )
        if any(operation[key] != reservation[key] for key in immutable):
            return False
        inputs = json.loads(reservation["input_document"])
        session = self._session(connection, reservation["sid"])
        checkout = session["checkout"]
        return (
            text_hash(reservation["input_document"])
            == reservation["input_hash"]
            and session["revision"] == reservation["reserved_revision"]
            and checkout is not None
            and digest(checkout) == reservation["checkout_hash"]
            and checkout["review_id"] == reservation["review_id"]
            and checkout["state"] == "ANALYSIS_BLOCKED"
            and checkout["analysis_error"] == "MODEL_PENDING"
            and checkout["source"] == inputs["catalog"]["source"]
            and checkout["conditions"] == inputs["conditions"]
            and checkout["model"] == inputs["model"]
            and checkout["catalog_hash"] == digest(inputs["catalog"])
            and digest(product_for(connection, checkout["sku_id"]))
            == checkout["catalog_hash"]
            and self.inference is adapter
            and self._analysis_metadata(adapter) == inputs["model"]
            and not connection.execute(
                "SELECT 1 FROM orders WHERE sid = ?", (session["sid"],)
            ).fetchone()
        )

    def _dispatch_analysis(self, reservation, adapter):
        operation_id = reservation["operation_id"]
        with self.store.transaction() as connection:
            operation = connection.execute(
                "SELECT * FROM analysis_operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if not operation or operation["status"] != "RESERVED":
                return
            if not self._analysis_fresh(
                connection, operation, reservation, adapter
            ):
                self._finish_analysis(
                    connection,
                    reservation,
                    adapter,
                    "STALE_SNAPSHOT",
                    None,
                    "",
                    "",
                )
                return
            inputs = json.loads(reservation["input_document"])
            token = str(uuid4())
            if not reservation["is_fixture"]:
                ledger = self._configured_budget(
                    connection, adapter, inputs["model"]
                )
                request = adapter.build_request(
                    inputs["catalog"]["source"], inputs["conditions"]
                )
                if request_hash(request) != inputs["budget_request_sha256"]:
                    self._finish_analysis(
                        connection,
                        reservation,
                        adapter,
                        "MODEL_BUDGET_EXCEEDED",
                        None,
                        "",
                        "",
                    )
                    return
                token = ledger.claim(operation_id, request).claim_token
            connection.execute(
                "UPDATE analysis_operations SET status = 'DISPATCHED', "
                "dispatch_token = ?, dispatched_at = ? WHERE operation_id = ?",
                (token, self.clock().isoformat(), operation_id),
            )
        self._checkpoint("analysis_after_dispatch_commit", operation_id)
        inputs = json.loads(reservation["input_document"])
        source = inputs["catalog"]["source"]
        choices = inputs["conditions"]
        error_code, results, observation = "", None, ""
        try:
            # Fresh copies prevent a mutable adapter from rewriting reserved input.
            argument = json.loads(
                canonical({"source": source, "conditions": choices})
            )
            if reservation["is_fixture"]:
                proposal = adapter.propose(
                    argument["source"], argument["conditions"]
                )
            else:
                observed = adapter.observe(
                    argument["source"],
                    argument["conditions"],
                    expected_request_sha256=inputs["budget_request_sha256"],
                )
                observation = checked_observation(observed, inputs)
                try:
                    if (
                        type(observed.proposal_json) is not str
                        or len(observed.proposal_json) > 65_536
                        or len(observed.proposal_json.encode("utf-8")) > 65_536
                    ):
                        raise ValueError("Proposal exceeds local wire limit")
                    proposal = observed.results
                except (ValueError, TypeError, UnicodeError) as error:
                    raise AppError(
                        "INVALID_PROPOSAL", "Invalid model proposal.", 422
                    ) from error
            try:
                results = json.loads(
                    canonical(validate_proposal(source, choices, proposal))
                )
            except (AppError, ValueError, TypeError) as error:
                raise AppError(
                    "INVALID_PROPOSAL", "Invalid model proposal.", 422
                ) from error
        except AppError as error:
            error_code = (
                error.code
                if reservation["is_fixture"]
                else (
                    error.code
                    if error.code
                    in {
                        "INVALID_PROPOSAL",
                        "MODEL_UNAVAILABLE",
                        "MODEL_TIMEOUT",
                        "MODEL_REFUSED",
                        "MODEL_INCOMPLETE",
                        "MODEL_BUDGET_EXCEEDED",
                    }
                    else "MODEL_UNAVAILABLE"
                )
            )
        except Exception:
            # Untrusted injected adapters cannot leak their exception text.
            error_code = "MODEL_UNAVAILABLE"
        self._checkpoint("analysis_before_observation_commit", operation_id)
        with self.store.transaction() as connection:
            self._finish_analysis(
                connection,
                reservation,
                adapter,
                error_code,
                results,
                observation,
                token,
            )

    def _finish_analysis(
        self,
        connection,
        reservation,
        adapter,
        error_code,
        results,
        observation,
        token,
    ):
        operation_id = reservation["operation_id"]
        operation = connection.execute(
            "SELECT * FROM analysis_operations WHERE operation_id = ?",
            (operation_id,),
        ).fetchone()
        expected_status = "DISPATCHED" if token else "RESERVED"
        if not operation or operation["status"] != expected_status:
            return
        if token and operation["dispatch_token"] != token:
            return
        fresh = self._analysis_fresh(
            connection, operation, reservation, adapter
        )
        if not reservation["is_fixture"]:
            inputs = json.loads(reservation["input_document"])
            ledger = self._reserved_budget(connection, inputs)
            if not token:
                ledger.abandon_reservation(
                    operation_id, inputs["budget_request_sha256"]
                )
            else:
                claim = BudgetClaim(
                    operation_id,
                    inputs["budget_request_sha256"],
                    inputs["model"]["budget_policy_sha256"],
                    token,
                )
                if observation:
                    usage = json.loads(observation)
                    try:
                        ledger.settle(
                            claim,
                            model=usage["model_returned"],
                            service_tier=usage["service_tier_returned"],
                            input_tokens=usage["input_tokens"],
                            output_tokens=usage["output_tokens"],
                            total_tokens=usage["total_tokens"],
                        )
                    except AppError:
                        # Keep the shared UNKNOWN update in this transaction.
                        observation, error_code, results = (
                            "",
                            "MODEL_BUDGET_EXCEEDED",
                            None,
                        )
                else:
                    ledger.mark_unknown(claim)
        status = "SUCCEEDED" if not error_code else "BLOCKED"
        if not reservation["is_fixture"] and token and not observation:
            status = "UNKNOWN"
        elif not fresh:
            status = "STALE"
            error_code = "STALE_SNAPSHOT"
        connection.execute(
            "UPDATE analysis_operations SET status = ?, observation = ?, "
            "error_code = ?, observed_at = ? WHERE operation_id = ?",
            (
                status,
                observation,
                error_code,
                self.clock().isoformat(),
                operation_id,
            ),
        )
        session = self._session(connection, reservation["sid"])
        checkout = session["checkout"]
        # Never downgrade or attach to a newer generation or changed revision.
        if (
            not checkout
            or checkout["review_id"] != reservation["review_id"]
            or session["revision"] != reservation["reserved_revision"]
        ):
            return
        if not fresh:
            error_code = "STALE_SNAPSHOT"
        if error_code:
            checkout["state"] = "ANALYSIS_BLOCKED"
            checkout["analysis_error"] = error_code
            checkout["results"] = []
            checkout["snapshot_hash"] = None
            checkout["confirmation_id"] = None
            checkout["consent"] = None
        else:
            inputs = json.loads(reservation["input_document"])
            checkout.pop("analysis_error", None)
            checkout["state"] = "REVIEW_REQUIRED"
            checkout["results"] = results
            checkout["snapshot_hash"] = digest(
                {
                    "owner": session["sid"],
                    "review_id": checkout["review_id"],
                    "catalog": inputs["catalog"],
                    "conditions": inputs["conditions"],
                    "proposal": results,
                    "model": inputs["model"],
                }
            )
        self._write_review(connection, session)
        self._save(connection, session, "analysis_recorded")

    def _context_wall_now(self):
        now = self.clock().timestamp()
        if type(now) not in (int, float) or not math.isfinite(now):
            raise blocked()
        return now

    def _context_now(self):
        # Integer storage timestamps never define the transport's precise budget.
        return int(self._context_wall_now())

    def _migrate_analysis_strategies(self, connection):
        for row in connection.execute(
            "SELECT * FROM analysis_operations WHERE strategy = ''"
        ).fetchall():
            budget = connection.execute(
                "SELECT 1 FROM budget_operations WHERE operation_id = ?",
                (row["operation_id"],),
            ).fetchone()
            context = connection.execute(
                "SELECT 1 FROM context_capacity_operations WHERE operation_id = ?",
                (row["operation_id"],),
            ).fetchone()
            strategy = "unsupported-legacy"
            try:
                inputs = json.loads(row["input_document"])
                if (
                    row["is_fixture"] == 1
                    and not budget
                    and not context
                    and inputs["model"]["is_fixture"] is True
                ):
                    strategy = "fixture"
                elif (
                    row["is_fixture"] == 0
                    and budget
                    and not context
                    and inputs.get("budget_request_sha256")
                    and inputs.get("budget_policy_document")
                ):
                    strategy = "offline-count-v1"
            except (ValueError, TypeError, KeyError):
                pass
            connection.execute(
                "UPDATE analysis_operations SET strategy = ? WHERE operation_id = ?",
                (strategy, row["operation_id"]),
            )

    def _analysis_history_guard(self, connection, current_preflight_id=None):
        # Pair both directions. A new strategy or current installation cannot
        # discard orphan/unknown history in any of the shared admission ledgers.
        rows = connection.execute(
            "SELECT a.*, b.operation_id AS budget_id, c.operation_id AS context_id FROM analysis_operations a LEFT JOIN budget_operations b ON b.operation_id = a.operation_id LEFT JOIN context_capacity_operations c ON c.operation_id = a.operation_id"
        ).fetchall()
        for row in rows:
            strategy = row["strategy"]
            if not connection.execute(
                "SELECT 1 FROM sessions WHERE sid = ?", (row["sid"],)
            ).fetchone():
                raise blocked()
            if strategy == "fixture":
                valid = (
                    row["is_fixture"] == 1
                    and not row["budget_id"]
                    and not row["context_id"]
                )
            elif strategy == "offline-count-v1":
                valid = (
                    row["is_fixture"] == 0
                    and row["budget_id"]
                    and not row["context_id"]
                )
            elif strategy == "context-capacity-v1":
                valid = (
                    row["is_fixture"] == 0
                    and row["context_id"]
                    and not row["budget_id"]
                )
            else:
                valid = False
            if (
                not valid
                or text_hash(row["input_document"]) != row["input_hash"]
                or row["status"]
                not in {
                    "RESERVED",
                    "DISPATCHED",
                    "SUCCEEDED",
                    "BLOCKED",
                    "STALE",
                    "UNKNOWN",
                }
            ):
                raise blocked()
            if not connection.execute(
                "SELECT 1 FROM reviews WHERE review_id = ? AND sid = ?",
                (row["review_id"], row["sid"]),
            ).fetchone():
                raise blocked()
            if strategy != "fixture" and row["status"] in {
                "UNKNOWN",
                "RESERVED",
                "DISPATCHED",
            }:
                raise blocked()
        for table, strategy in (
            ("budget_operations", "offline-count-v1"),
            ("context_capacity_operations", "context-capacity-v1"),
        ):
            if connection.execute(
                f"SELECT 1 FROM {table} b LEFT JOIN analysis_operations a ON a.operation_id = b.operation_id WHERE a.operation_id IS NULL OR a.strategy != ? OR b.status != 'KNOWN' OR a.status NOT IN ('SUCCEEDED','BLOCKED','STALE') OR a.observation = '' LIMIT 1",
                (strategy,),
            ).fetchone():
                raise blocked()
        if connection.execute(
            "SELECT 1 FROM analysis_preflights p LEFT JOIN analysis_operations a ON a.operation_id = p.analysis_operation_id WHERE p.status NOT IN ('PREPARED','COUNTING','UNKNOWN','USED','BLOCKED','STALE') OR NOT EXISTS (SELECT 1 FROM sessions s WHERE s.sid = p.sid) OR p.status = 'UNKNOWN' OR (p.status IN ('PREPARED', 'COUNTING') AND p.preflight_id != ?) OR (p.status = 'USED' AND (a.operation_id IS NULL OR a.strategy != 'offline-count-v1')) LIMIT 1",
            (current_preflight_id or "",),
        ).fetchone():
            raise blocked()

    def _public_context_outcome(self, connection, review_id):
        row = connection.execute(
            "SELECT a.dispatch_token, a.input_document, c.status, c.observation FROM analysis_operations a LEFT JOIN context_capacity_operations c ON a.operation_id = c.operation_id WHERE a.review_id = ? AND a.strategy = 'context-capacity-v1'",
            (review_id,),
        ).fetchone()
        usage = bool(row and row["observation"])
        kind = "none"
        if usage:
            original = json.loads(row["input_document"])["model"][
                "execution_kind"
            ]
            kind = (
                "fabricated-offline"
                if original == "fabricated-offline"
                else "provider-observation"
            )
        return {
            "strategy": "context-capacity-v1",
            "dispatch_state": "attempted"
            if row and row["dispatch_token"]
            else "not-attempted",
            "accounting_state": "known"
            if row and row["status"] == "KNOWN"
            else "unknown"
            if row and row["status"] == "UNKNOWN"
            else "unobserved",
            "usage_observed": usage,
            "evidence_kind": kind,
        }

    def _context_fence(self, sid, product, choices, generation, runtime_sha):
        source = product["source"]
        return ContextFence(
            runtime_sha,
            text_hash(sid),
            source["sha256"],
            digest(source),
            source["revision"],
            digest(choices),
            generation,
        )

    def _require_context(self, adapter, sid, product, choices):
        if (
            type(adapter) is not GenuineResponsesAdapter
            or self.inference is not adapter
            or self.context_analysis is not adapter.runtime
            or self.analysis_budget is not None
            or type(self.payments) is not FixturePaymentAdapter
        ):
            raise blocked()
        installed = adapter.runtime.require(self._context_wall_now())
        if not installed.scope.allows(product, choices, sid):
            raise blocked()
        return installed

    def _analyze_context(self, sid, body):
        adapter = self.inference
        with self.store.transaction() as connection:
            session = self._session(connection, sid)
            if body["expected_revision"] != session["revision"]:
                raise AppError(
                    "STALE_REVISION", "Reload the current review.", 409
                )
            product, choices, model = self._analysis_inputs(
                connection, session, body, adapter
            )
            installed = self._require_context(adapter, sid, product, choices)
            self._analysis_admission(connection)
            prepared = adapter.prepare(product["source"], choices)
            fence = self._context_fence(
                sid,
                product,
                choices,
                session["revision"] + 1,
                installed.execution_sha256,
            )
            ledger = TransactionContextCapacityLedger(
                connection, installed.policy, installed.authorization
            )
            capacity = ledger.reserve(
                prepared.request, fence, now=self._context_now()
            )
            checkout = self._new_analysis_checkout(product, choices, model)
            document = canonical(
                {
                    "catalog": product,
                    "conditions": choices,
                    "model": model,
                    "context_ledger_document": ledger.identity,
                    "context_reservation": asdict(capacity),
                    "context_fence": asdict(fence),
                    "context_request_sha256": prepared.request_sha256,
                }
            )
            connection.execute(
                "INSERT INTO analysis_operations(operation_id, sid, review_id, input_document, input_hash, checkout_hash, reserved_revision, is_fixture, status, reserved_at, strategy) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 'RESERVED', ?, 'context-capacity-v1')",
                (
                    capacity.operation_id,
                    sid,
                    checkout["review_id"],
                    document,
                    text_hash(document),
                    digest(checkout),
                    session["revision"] + 1,
                    self.clock().isoformat(),
                ),
            )
            session["checkout"] = checkout
            self._write_review(connection, session)
            self._save(connection, session, "analysis_reserved")
            reservation = dict(
                connection.execute(
                    "SELECT * FROM analysis_operations WHERE operation_id = ?",
                    (capacity.operation_id,),
                ).fetchone()
            )
        self._checkpoint(
            "analysis_after_reservation_commit", capacity.operation_id
        )
        self._dispatch_context(reservation, adapter, prepared)
        with self.store.transaction() as connection:
            return self._result(connection, self._session(connection, sid))

    def _context_binding(self, connection, reservation):
        inputs = json.loads(reservation["input_document"])
        ledger = context_ledger_from_document(
            connection, inputs["context_ledger_document"]
        )
        return (
            inputs,
            ledger,
            ContextReservation(**inputs["context_reservation"]),
            ContextFence(**inputs["context_fence"]),
        )

    def _context_fresh(self, connection, row, reservation, adapter, prepared):
        try:
            if not self._analysis_fresh(connection, row, reservation, adapter):
                return False
            inputs = json.loads(reservation["input_document"])
            installed = self._require_context(
                adapter,
                reservation["sid"],
                inputs["catalog"],
                inputs["conditions"],
            )
            return (
                prepared.runtime_sha256 == installed.execution_sha256
                and prepared.request_sha256 == inputs["context_request_sha256"]
                and adapter.prepare(
                    inputs["catalog"]["source"], inputs["conditions"]
                )
                == prepared
            )
        except (AppError, ValueError, TypeError, KeyError):
            return False

    def _block_context_checkout(self, connection, reservation, error_code):
        row = connection.execute(
            "SELECT 1 FROM sessions WHERE sid = ?", (reservation["sid"],)
        ).fetchone()
        if not row:
            return
        session = self._session(connection, reservation["sid"])
        checkout = session["checkout"]
        if (
            not checkout
            or checkout["review_id"] != reservation["review_id"]
            or session["revision"] != reservation["reserved_revision"]
        ):
            return
        checkout.update(
            state="ANALYSIS_BLOCKED",
            analysis_error=error_code,
            results=[],
            snapshot_hash=None,
            confirmation_id=None,
            consent=None,
        )
        self._write_review(connection, session)
        self._save(connection, session, "context_analysis_blocked")

    def _mark_context_unknown(self, connection, reservation, claim, error_code):
        row = connection.execute(
            "SELECT * FROM analysis_operations WHERE operation_id = ?",
            (reservation["operation_id"],),
        ).fetchone()
        if (
            not row
            or row["status"] not in ("RESERVED", "DISPATCHED", "UNKNOWN")
            or (
                claim is not None and row["dispatch_token"] != claim.claim_token
            )
        ):
            return
        _, ledger, capacity, _ = self._context_binding(connection, reservation)
        ledger.mark_unknown(capacity)
        connection.execute(
            "UPDATE analysis_operations SET status = 'UNKNOWN', error_code = ?, observed_at = ? WHERE operation_id = ?",
            (error_code, self.clock().isoformat(), reservation["operation_id"]),
        )
        self._block_context_checkout(connection, reservation, error_code)

    def _dispatch_context(self, reservation, adapter, prepared):
        operation_id = reservation["operation_id"]
        with self.store.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM analysis_operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if not row or row["status"] != "RESERVED":
                return
            inputs, ledger, capacity, fence = self._context_binding(
                connection, reservation
            )
            if not self._context_fresh(
                connection, row, reservation, adapter, prepared
            ):
                self._mark_context_unknown(
                    connection, reservation, None, "STALE_SNAPSHOT"
                )
                return
            claim = ledger.claim(
                capacity, prepared.request, fence, now=self._context_now()
            )
            if claim is None:
                self._mark_context_unknown(
                    connection, reservation, None, "MODEL_OUTCOME_UNKNOWN"
                )
                return
            connection.execute(
                "UPDATE analysis_operations SET status = 'DISPATCHED', dispatch_token = ?, dispatched_at = ? WHERE operation_id = ?",
                (claim.claim_token, self.clock().isoformat(), operation_id),
            )
        self._checkpoint("analysis_after_dispatch_commit", operation_id)
        try:
            deadline = adapter.deadline(claim)
        except Exception:
            with self.store.transaction() as connection:
                self._mark_context_unknown(
                    connection, reservation, claim, "MODEL_OUTCOME_UNKNOWN"
                )
            return
        # Account for the worker before start, while mutate already owns activity.
        # The watchdog returns, but cannot release this extra lease ownership.
        done = threading.Event()
        with self._activity_lock:
            self._active += 1

        def run():
            try:
                # Recheck any changes after committed claim before constructing
                # a connection. The exchange itself holds no SQLite transaction.
                with self.store.transaction() as connection:
                    current = connection.execute(
                        "SELECT * FROM analysis_operations WHERE operation_id = ?",
                        (operation_id,),
                    ).fetchone()
                    if (
                        not current
                        or current["status"] != "DISPATCHED"
                        or current["dispatch_token"] != claim.claim_token
                    ):
                        return
                    if not self._context_fresh(
                        connection, current, reservation, adapter, prepared
                    ):
                        self._mark_context_unknown(
                            connection, reservation, claim, "STALE_SNAPSHOT"
                        )
                        return
                try:
                    exchange = adapter.exchange(prepared, claim, deadline)
                except Exception:
                    exchange = None
                self._checkpoint(
                    "analysis_before_observation_commit", operation_id
                )
                with self.store.transaction() as connection:
                    self._finish_context(
                        connection,
                        reservation,
                        adapter,
                        prepared,
                        claim,
                        exchange,
                        time.monotonic() >= deadline.expires_at,
                        deadline.expires_at,
                    )
                    pending = connection.execute(
                        "SELECT status FROM analysis_operations WHERE operation_id = ?",
                        (operation_id,),
                    ).fetchone()
                    if pending and pending[0] == "DISPATCHED":
                        self._mark_context_unknown(
                            connection,
                            reservation,
                            claim,
                            "MODEL_OUTCOME_UNKNOWN",
                        )
            except Exception:
                # Preserve ambiguity if the observation transaction rolls back.
                # Never print arbitrary exception text from trusted test seams.
                try:
                    with self.store.transaction() as connection:
                        self._mark_context_unknown(
                            connection,
                            reservation,
                            claim,
                            "MODEL_OUTCOME_UNKNOWN",
                        )
                except Exception:
                    pass  # Startup recovery owns a failed persistence boundary.
            finally:
                with self._activity_lock:
                    self._active -= 1
                done.set()

        worker = threading.Thread(target=run, daemon=True)
        try:
            worker.start()
        except BaseException:
            with self._activity_lock:
                self._active -= 1
            with self.store.transaction() as connection:
                self._mark_context_unknown(
                    connection, reservation, claim, "MODEL_OUTCOME_UNKNOWN"
                )
            raise
        if not done.wait(max(0, deadline.expires_at - time.monotonic())):
            with self.store.transaction() as connection:
                self._mark_context_unknown(
                    connection, reservation, claim, "MODEL_TIMEOUT"
                )

    def _finish_context(
        self,
        connection,
        reservation,
        adapter,
        prepared,
        claim,
        exchange,
        late=False,
        deadline_at=None,
    ):
        row = connection.execute(
            "SELECT * FROM analysis_operations WHERE operation_id = ?",
            (reservation["operation_id"],),
        ).fetchone()
        if (
            not row
            or row["status"] not in ("DISPATCHED", "UNKNOWN")
            or row["dispatch_token"] != claim.claim_token
        ):
            return
        # Never let a foreign claim/exchange fault mutate another operation.
        if exchange is not None and (
            type(exchange) is not GenuineExchange
            or exchange.operation_id != reservation["operation_id"]
            or exchange.claim_token != claim.claim_token
            or exchange.request_sha256 != prepared.request_sha256
            or exchange.runtime_sha256 != prepared.runtime_sha256
        ):
            return
        inputs, ledger, capacity, fence = self._context_binding(
            connection, reservation
        )
        fresh = self._context_fresh(
            connection, row, reservation, adapter, prepared
        )
        prior_unknown = row["status"] == "UNKNOWN"
        if exchange is None:
            self._mark_context_unknown(
                connection, reservation, claim, "MODEL_OUTCOME_UNKNOWN"
            )
            return
        expected_kind = (
            "provider"
            if inputs["model"]["execution_kind"] == "provider-runtime"
            else "fabricated-offline"
        )
        if exchange.evidence_kind != expected_kind:
            return
        # Always use original policy even when the current installation changed.
        from cartreadback_app.context_capacity import ContextCapacityPolicy

        raw_policy = json.loads(inputs["context_ledger_document"])["policy"]
        policy = ContextCapacityPolicy(
            raw_policy["valid_from"],
            raw_policy["expires_at"],
            raw_policy["reference_profile"],
            raw_policy["evidence_revision"],
        )
        protocol_fault, error_code, results = adapter.classify(
            exchange, policy, prepared
        )
        late = late or (
            deadline_at is not None and time.monotonic() >= deadline_at
        )
        if protocol_fault or late or not fresh or prior_unknown:
            ledger.mark_unknown(capacity)
        try:
            accounting_state = ledger.observe(
                claim,
                exchange.envelope,
                request_sha256=exchange.request_sha256,
                runtime_sha256=exchange.runtime_sha256,
                request_id=exchange.request_id,
                current_fence=fence,
                now=self._context_now(),
            )
        except AppError:
            # Invalid/duplicate identifiers cannot settle or overwrite accounting.
            existing = connection.execute(
                "SELECT observation FROM context_capacity_operations WHERE operation_id = ?",
                (reservation["operation_id"],),
            ).fetchone()
            if existing and existing[0]:
                return
            ledger.mark_unknown(capacity)
            accounting_state = "UNKNOWN"
        accounting = connection.execute(
            "SELECT observation FROM context_capacity_operations WHERE operation_id = ?",
            (reservation["operation_id"],),
        ).fetchone()[0]
        if accounting_state != "KNOWN":
            error_code, results = "MODEL_OUTCOME_UNKNOWN", None
        status = (
            "UNKNOWN"
            if accounting_state == "UNKNOWN"
            else "BLOCKED"
            if error_code
            else "SUCCEEDED"
        )
        connection.execute(
            "UPDATE analysis_operations SET status = ?, observation = ?, error_code = ?, observed_at = ? WHERE operation_id = ? AND dispatch_token = ?",
            (
                status,
                accounting,
                error_code,
                self.clock().isoformat(),
                reservation["operation_id"],
                claim.claim_token,
            ),
        )
        if prior_unknown or late or not fresh:
            self._block_context_checkout(
                connection, reservation, error_code or "STALE_SNAPSHOT"
            )
            return
        if error_code:
            self._block_context_checkout(connection, reservation, error_code)
            return
        session = self._session(connection, reservation["sid"])
        checkout = session["checkout"]
        checkout.pop("analysis_error", None)
        checkout.update(state="REVIEW_REQUIRED", results=results)
        checkout["snapshot_hash"] = digest(
            {
                "owner": session["sid"],
                "review_id": checkout["review_id"],
                "catalog": inputs["catalog"],
                "conditions": inputs["conditions"],
                "proposal": results,
                "model": inputs["model"],
            }
        )
        self._write_review(connection, session)
        self._save(connection, session, "context_analysis_recorded")

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

    def _config(self, adapter: PaymentAdapter) -> dict:
        return {
            "provider_mode": adapter.mode,
            "merchant_id": adapter.merchant_id,
            "adapter_version": adapter.version,
        }

    def _assert_consent(self, connection, session, checkout, body):
        self._assert_confirmation(checkout, body)
        row = connection.execute(
            "SELECT * FROM confirmations WHERE confirmation_id = ? AND sid = ?",
            (checkout["confirmation_id"], session["sid"]),
        ).fetchone()
        if (
            not row
            or row["review_id"] != checkout["review_id"]
            or row["snapshot_hash"] != checkout["snapshot_hash"]
            or row["document"] != canonical(checkout["consent"])
        ):
            raise AppError(
                "ACKNOWLEDGEMENT_REQUIRED",
                "Current explicit consent is required.",
                409,
            )

    def _assert_config(self, adapter, config, expected):
        if (
            self.payments is not adapter
            or self._config(adapter) != config
            or expected["provider_mode"] != config["provider_mode"]
            or expected["merchant_id"] != config["merchant_id"]
        ):
            raise AppError(
                "STALE_SNAPSHOT", "Payment configuration changed.", 409
            )

    def _reserve(
        self,
        connection,
        session,
        kind,
        key,
        request_hash,
        order_id,
        expected,
        provider_id,
        adapter,
        request=None,
    ):
        operation_id = str(uuid4())
        request = request or adapter.prepare(kind, expected, provider_id)
        if (
            type(request) is not PaymentRequest
            or request.method != "POST"
            or type(request.path) is not str
            or not request.path.startswith("/")
            or type(request.body) is not str
            or canonical(json.loads(request.body)) != request.body
        ):
            raise AppError(
                "INVALID_STATE", "Invalid prepared payment request.", 409
            )
        config = self._config(adapter)
        try:
            connection.execute(
                "INSERT INTO operations(operation_id, sid, kind, idempotency_key, "
                "request_hash, order_id, status, upstream_payload, upstream_hash, "
                "method, path, expected_hash, provider_mode, merchant_id, "
                "adapter_version, reserved_revision, reserved_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    operation_id,
                    session["sid"],
                    kind,
                    key,
                    request_hash,
                    order_id,
                    "RESERVED",
                    request.body,
                    text_hash(request.body),
                    request.method,
                    request.path,
                    digest(expected),
                    config["provider_mode"],
                    config["merchant_id"],
                    config["adapter_version"],
                    session["revision"] + 1,
                    self.clock().isoformat(),
                ),
            )
        except sqlite3.IntegrityError as error:
            raise AppError(
                "INVALID_STATE", "This business operation already exists.", 409
            ) from error
        return dict(
            connection.execute(
                "SELECT * FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
        )

    def _create(self, connection, session, body, key, request_hash, adapter):
        checkout = self._current(connection, session, body)
        self._state(checkout, {"SNAPSHOT_CONFIRMED"})
        self._assert_consent(connection, session, checkout, body)
        product = product_for(connection, checkout["sku_id"])
        order_id = str(uuid4())
        expected = {
            "provider_mode": adapter.mode,
            "intent": "CAPTURE",
            "merchant_id": adapter.merchant_id,
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
        request = None
        if (
            adapter.mode == "paypal-sandbox-offline"
            and getattr(adapter, "buyer_return_origin", None) is not None
        ):
            state = secrets.token_urlsafe(32)
            expires_at = (self.clock() + timedelta(minutes=20)).isoformat()
            checkout["approval_return"] = {
                "state_hash": text_hash(state),
                "expires_at": expires_at,
                "consumed": False,
                "cancelled": False,
            }
            request = adapter.prepare_checkout(expected, state)
        reservation = self._reserve(
            connection,
            session,
            "orders",
            key,
            request_hash,
            order_id,
            expected,
            None,
            adapter,
            request=request,
        )
        operation_id = reservation["operation_id"]
        checkout["order"] = {
            "order_id": order_id,
            "provider_order_id": None,
            "provider_mode": adapter.mode,
            "status": "PENDING",
            "approval_url": None,
            "operation_id": operation_id,
            "operation_kind": "orders",
        }
        if "approval_return" in checkout:
            checkout["order"]["buyer_return"] = {
                "available": True,
                **{
                    key: checkout["approval_return"][key]
                    for key in ("expires_at", "consumed", "cancelled")
                },
            }
        checkout["state"] = "ORDER_CREATE_PENDING"
        self._save(connection, session, "create_reserved")
        self._checkpoint("before_reservation_commit", operation_id)
        return reservation

    def _claim(self, reservation, adapter):
        operation_id = reservation["operation_id"]
        with self.store.transaction() as connection:
            operation = connection.execute(
                "SELECT * FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if not operation or operation["status"] != "RESERVED":
                return None
            operation = dict(operation)
            immutable = (
                "sid",
                "kind",
                "order_id",
                "upstream_payload",
                "upstream_hash",
                "method",
                "path",
                "expected_hash",
                "provider_mode",
                "merchant_id",
                "adapter_version",
                "reserved_revision",
            )
            if any(
                operation[field] != reservation[field] for field in immutable
            ):
                raise AppError(
                    "PAYMENT_UNKNOWN", "Reserved wire identity changed.", 409
                )
            session = self._session(connection, operation["sid"])
            row = connection.execute(
                "SELECT * FROM orders WHERE order_id = ? AND sid = ?",
                (operation["order_id"], operation["sid"]),
            ).fetchone()
            expected = json.loads(row["expected"])
            self._assert_config(
                adapter,
                {key: operation[key] for key in self._config(adapter)},
                expected,
            )
            if (
                session["revision"] != operation["reserved_revision"]
                or session["checkout"]["order"]["operation_id"] != operation_id
                or operation["upstream_hash"]
                != text_hash(operation["upstream_payload"])
                or operation["expected_hash"] != digest(expected)
            ):
                raise AppError(
                    "PAYMENT_UNKNOWN",
                    "Reserved operation changed; reconcile.",
                    409,
                )
            token = str(uuid4())
            changed = connection.execute(
                "UPDATE operations SET status = 'DISPATCHED', dispatch_token = ?, "
                "dispatched_at = ? WHERE operation_id = ? AND status = 'RESERVED' "
                "AND upstream_hash = ? AND expected_hash = ?",
                (
                    token,
                    self.clock().isoformat(),
                    operation_id,
                    operation["upstream_hash"],
                    operation["expected_hash"],
                ),
            ).rowcount
            if changed != 1:
                return None
            operation.update(dispatch_token=token, status="DISPATCHED")
            return operation

    def _dispatch(self, reservation, adapter):
        operation_id = reservation["operation_id"]
        operation = self._claim(reservation, adapter)
        if not operation:
            return
        self._checkpoint("after_claim_commit", operation_id)
        try:
            document = adapter.dispatch(
                operation_id,
                PaymentRequest(
                    operation["method"],
                    operation["path"],
                    operation["upstream_payload"],
                ),
            )
            error_code = None
        except ProviderAmbiguity:
            document, error_code = None, "PROVIDER_OUTCOME_UNKNOWN"
        except AppError:
            document, error_code = None, "PROVIDER_ERROR"
        self._checkpoint("after_provider_response", operation_id)
        with self.store.transaction() as connection:
            self._observe_dispatch(connection, operation, document, error_code)
            self._checkpoint("before_observation_commit", operation_id)
        self._checkpoint("after_observation_commit", operation_id)

    def _fenced(self, connection, fence):
        operation = connection.execute(
            "SELECT * FROM operations WHERE operation_id = ? AND sid = ? AND order_id = ?",
            (fence["operation_id"], fence["sid"], fence["order_id"]),
        ).fetchone()
        fields = (
            "kind",
            "dispatch_token",
            "upstream_hash",
            "upstream_payload",
            "method",
            "path",
            "expected_hash",
            "provider_mode",
            "merchant_id",
            "adapter_version",
        )
        if not operation or any(operation[key] != fence[key] for key in fields):
            raise AppError(
                "PAYMENT_UNKNOWN", "Payment observation fence rejected.", 409
            )
        session = self._session(connection, fence["sid"])
        checkout = session["checkout"]
        row = connection.execute(
            "SELECT * FROM orders WHERE order_id = ? AND sid = ?",
            (fence["order_id"], fence["sid"]),
        ).fetchone()
        if (
            not row
            or not checkout
            or not checkout["order"]
            or checkout["order"]["order_id"] != row["order_id"]
            or checkout["order"]["operation_id"] != operation["operation_id"]
            or checkout["order"]["operation_kind"] != operation["kind"]
            or checkout["review_id"] != row["review_id"]
            or checkout["snapshot_hash"] != row["snapshot_hash"]
            or (
                operation["expected_hash"]
                and digest(json.loads(row["expected"]))
                != operation["expected_hash"]
            )
        ):
            raise AppError(
                "PAYMENT_UNKNOWN", "Owned payment binding changed.", 409
            )
        return dict(operation), session, json.loads(row["expected"])

    def _observe_dispatch(self, connection, fence, document, error_code):
        operation, session, expected = self._fenced(connection, fence)
        checkout, order = session["checkout"], session["checkout"]["order"]
        if (
            operation["status"] == "SUCCEEDED"
            or checkout["state"] == "COMPLETED"
        ):
            event(
                connection,
                session["sid"],
                "late_observation_ignored",
                {
                    "operation_id": operation["operation_id"],
                    "reason": "TERMINAL_SUCCESS",
                },
            )
            return
        if operation["status"] not in {"DISPATCHED", "UNKNOWN"}:
            raise AppError(
                "PAYMENT_UNKNOWN", "Operation was never dispatched.", 409
            )
        if operation["kind"] == "orders" and type(document) is dict:
            provider_id = document.get("provider_order_id")
            if (
                type(provider_id) is str
                and 0 < len(provider_id) <= 128
                and provider_id.isascii()
                and all(c.isalnum() or c == "-" for c in provider_id)
            ):
                if order["provider_order_id"] not in {None, provider_id}:
                    raise AppError(
                        "ORDER_MISMATCH", "Provider identity changed.", 409
                    )
                order["provider_order_id"] = provider_id
        try:
            if error_code:
                raise AppError(error_code, "Provider outcome unknown.", 409)
            verify_provider_order(
                document,
                expected,
                order["provider_order_id"],
                operation["merchant_id"],
                {"CREATED"} if operation["kind"] == "orders" else {"COMPLETED"},
                operation["operation_id"]
                if operation["kind"] == "capture"
                else None,
            )
        except AppError:
            checkout["state"], order["status"] = "PAYMENT_UNKNOWN", "UNKNOWN"
            status = "UNKNOWN"
            error_code = error_code or "ORDER_MISMATCH"
        else:
            self._apply_success(checkout, document, operation["kind"])
            status = "SUCCEEDED"
        self._record_observation(
            connection, operation, checkout, status, error_code
        )
        self._persist_order(connection, checkout)
        self._save(connection, session, "dispatch_observed")

    def _record_observation(
        self, connection, operation, checkout, status, error_code
    ):
        order = checkout["order"]
        # Only bounded normalized facts, never a raw provider body/exception.
        observation = {"status": order["status"]}
        for key in ("provider_order_id", "capture_id"):
            value = order.get(key)
            if value is None or (
                type(value) is str and len(value) <= 128 and value.isascii()
            ):
                observation[key] = value
        connection.execute(
            "UPDATE operations SET status = ?, observed_at = ?, last_observation = ?, error_code = ? "
            "WHERE operation_id = ? AND status != 'SUCCEEDED'",
            (
                status,
                self.clock().isoformat(),
                canonical(observation),
                error_code or "",
                operation["operation_id"],
            ),
        )

    def _apply_success(self, checkout, document, kind):
        checkout.pop("verification_error", None)
        order = checkout["order"]
        order.pop("reconciliation_code", None)
        order["status"] = document["status"]
        if "buyer_return" in order:
            order["approval_url"] = document.get("approval_url")
        if kind == "capture":
            order["capture_id"] = document["captures"][0]["capture_id"]
            checkout["state"] = "COMPLETED"
        else:
            checkout["state"] = (
                "ORDER_CREATED"
                if document["status"] == "CREATED"
                else "PAYPAL_APPROVED"
            )

    def _persist_order(self, connection, checkout):
        order = checkout["order"]
        connection.execute(
            "UPDATE orders SET provider_order_id = ?, status = ? WHERE order_id = ?",
            (order["provider_order_id"], order["status"], order["order_id"]),
        )

    def _owned_order(self, connection, session, body, order_id, fresh=True):
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
        if fresh:
            self._current(connection, session, body)
        return checkout, json.loads(row["expected"])

    def _plan_order_action(
        self, connection, session, action, body, order_id, adapter
    ):
        checkout, expected = self._owned_order(
            connection,
            session,
            body,
            order_id,
            fresh=action != "reconcile",
        )
        allowed = {
            "fixture-approve": {"ORDER_CREATED"},
            "buyer-return": {"ORDER_CREATED", "PAYPAL_APPROVED"},
            "verify": {"ORDER_CREATED", "PAYPAL_APPROVED", "SERVER_RECHECKED"},
            "capture": {"SERVER_RECHECKED", "COMPLETED"},
            "reconcile": {
                "PAYMENT_UNKNOWN",
                "COMPLETED",
                "CAPTURE_PENDING",
                "ORDER_CREATE_PENDING",
            },
        }
        self._state(checkout, allowed[action])
        config = self._config(adapter)
        self._assert_config(adapter, config, expected)
        if action == "fixture-approve" and adapter.mode != "fixture":
            raise AppError(
                "INVALID_STATE", "Fixture approval requires fixture mode.", 409
            )
        if action == "buyer-return":
            self._validate_buyer_return(checkout, body, adapter)
        if action == "capture" and checkout["state"] != "COMPLETED":
            self._assert_consent(connection, session, checkout, body)
        operation = connection.execute(
            "SELECT * FROM operations WHERE order_id = ? AND kind = ?",
            (order_id, checkout["order"]["operation_kind"]),
        ).fetchone()
        return {
            "revision": session["revision"],
            "expected": expected,
            "config": config,
            "provider_id": checkout["order"]["provider_order_id"],
            "consent": canonical(checkout["consent"]),
            "confirmation_id": checkout["confirmation_id"],
            "completed": checkout["state"] == "COMPLETED",
            "operation": dict(operation) if operation else None,
        }

    def _validate_buyer_return(self, checkout, body, adapter):
        context = checkout.get("approval_return")
        state = body["return_state"]
        if (
            adapter.mode != "paypal-sandbox-offline"
            or not context
            or context["consumed"]
            or self.clock() >= datetime.fromisoformat(context["expires_at"])
            or type(state) is not str
            or re.fullmatch(r"[A-Za-z0-9_-]{43}", state) is None
            or not secrets.compare_digest(
                text_hash(state), context["state_hash"]
            )
            or type(body["outcome"]) is not str
            or body["outcome"] not in {"approved", "cancelled"}
            or type(body["provider_order_id"]) is not str
            or body["provider_order_id"]
            != checkout["order"]["provider_order_id"]
        ):
            raise AppError(
                "RETURN_REJECTED",
                "Return does not match the current owned order.",
                409,
            )

    def _consume_buyer_return(self, checkout, body, adapter):
        self._validate_buyer_return(checkout, body, adapter)
        context = checkout["approval_return"]
        context["consumed"] = True
        context["cancelled"] = body["outcome"] == "cancelled"
        checkout["order"]["buyer_return"].update(
            consumed=True, cancelled=context["cancelled"]
        )

    def _perform_order_action(
        self, sid, action, body, order_id, key, request_hash, adapter, plan
    ):
        if plan["completed"]:
            return
        if action == "reconcile" and plan["provider_id"] is None:
            with self.store.transaction() as connection:
                operation, session, _ = self._fenced(
                    connection, plan["operation"]
                )
                if self._ignore_stale_reconcile(connection, operation, session):
                    return
                if (
                    session["checkout"]["order"]["provider_order_id"]
                    is not None
                ):
                    # Absence belongs to the old plan, not this owned state.
                    # A fresh user reconcile can GET the now-known order.
                    return
                session["checkout"]["state"] = "PAYMENT_UNKNOWN"
                session["checkout"]["order"]["status"] = "UNKNOWN"
                session["checkout"]["order"]["reconciliation_code"] = (
                    "CREATE_OUTCOME_UNKNOWN"
                )
                self._record_observation(
                    connection,
                    operation,
                    session["checkout"],
                    "UNKNOWN",
                    "CREATE_OUTCOME_UNKNOWN",
                )
                self._persist_order(connection, session["checkout"])
                self._save(connection, session, "reconcile_unknown")
            return
        try:
            document = (
                adapter.approve(plan["provider_id"])
                if action == "fixture-approve"
                else adapter.get(plan["provider_id"])
            )
        except (ProviderAmbiguity, AppError):
            document = None
        with self.store.transaction() as connection:
            if action == "reconcile":
                self._reconcile_observation(
                    connection, plan["operation"], document
                )
                return
            session = self._session(connection, sid)
            if session["revision"] != plan["revision"]:
                raise AppError(
                    "STALE_REVISION",
                    "Reload the current review before continuing.",
                    409,
                )
            checkout, expected = self._owned_order(
                connection, session, body, order_id
            )
            self._assert_config(adapter, plan["config"], expected)
            if (
                expected != plan["expected"]
                or canonical(checkout["consent"]) != plan["consent"]
                or checkout["confirmation_id"] != plan["confirmation_id"]
            ):
                raise AppError(
                    "STALE_SNAPSHOT", "Payment authorization changed.", 409
                )
            if action == "buyer-return":
                self._consume_buyer_return(checkout, body, adapter)
                if body["outcome"] == "cancelled":
                    if not self._checked_provider(
                        connection,
                        session,
                        document,
                        expected,
                        plan["provider_id"],
                        {"CREATED", "APPROVED"},
                    ):
                        return
                    checkout["order"]["status"] = document["status"]
                    checkout["state"] = (
                        "ORDER_CREATED"
                        if document["status"] == "CREATED"
                        else "PAYPAL_APPROVED"
                    )
                    self._persist_order(connection, checkout)
                    self._save(connection, session, "buyer_return_cancelled")
                    return
            if action == "capture":
                self._state(checkout, {"SERVER_RECHECKED"})
                self._assert_consent(connection, session, checkout, body)
            if (
                action in {"verify", "buyer-return"}
                and type(document) is dict
                and document.get("status") == "CREATED"
            ):
                if action == "buyer-return":
                    if not self._checked_provider(
                        connection,
                        session,
                        document,
                        expected,
                        plan["provider_id"],
                        {"CREATED"},
                    ):
                        return
                    checkout["order"]["status"] = "CREATED"
                    checkout["state"] = "ORDER_CREATED"
                    self._save(connection, session, "buyer_return_unapproved")
                    return
                raise AppError(
                    "ORDER_NOT_APPROVED",
                    "Buyer approval has not been established.",
                    409,
                )
            if not self._checked_provider(
                connection,
                session,
                document,
                expected,
                plan["provider_id"],
                {"APPROVED"},
            ):
                return
            if action == "capture":
                reservation = self._reserve(
                    connection,
                    session,
                    "capture",
                    key,
                    request_hash,
                    order_id,
                    expected,
                    plan["provider_id"],
                    adapter,
                )
                operation_id = reservation["operation_id"]
                checkout["state"] = "CAPTURE_PENDING"
                checkout["order"].update(
                    operation_id=operation_id, operation_kind="capture"
                )
                self._save(connection, session, "capture_reserved")
                self._checkpoint("before_reservation_commit", operation_id)
            else:
                checkout["order"]["status"] = "APPROVED"
                checkout["state"] = (
                    "SERVER_RECHECKED"
                    if action in {"verify", "buyer-return"}
                    else "PAYPAL_APPROVED"
                )
                self._persist_order(connection, checkout)
                self._save(connection, session, f"{action}_observed")
        if action == "capture":
            self._checkpoint("after_reservation_commit", operation_id)
            self._dispatch(reservation, adapter)

    def _checked_provider(
        self, connection, session, document, expected, provider_id, statuses
    ):
        try:
            verify_provider_order(
                document,
                expected,
                provider_id,
                expected["merchant_id"],
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

    def _ignore_stale_reconcile(self, connection, operation, session):
        checkout = session["checkout"]
        terminal = checkout["state"] == "COMPLETED" or (
            operation["status"] == "SUCCEEDED"
            and checkout["state"] != "PAYMENT_UNKNOWN"
        )
        if terminal:
            event(
                connection,
                session["sid"],
                "late_reconcile_ignored",
                {
                    "operation_id": operation["operation_id"],
                    "reason": "TERMINAL_SUCCESS",
                },
            )
        return terminal

    def _reconcile_observation(self, connection, fence, document):
        operation, session, expected = self._fenced(connection, fence)
        checkout, order = session["checkout"], session["checkout"]["order"]
        if self._ignore_stale_reconcile(connection, operation, session):
            return
        try:
            capture = operation["kind"] == "capture"
            verify_provider_order(
                document,
                expected,
                order["provider_order_id"],
                expected["merchant_id"],
                {"COMPLETED"} if capture else {"CREATED", "APPROVED"},
                operation["operation_id"] if capture else None,
            )
            if (
                capture
                and not operation["dispatch_token"]
                and operation["adapter_version"]
            ):
                raise AppError(
                    "PAYMENT_UNKNOWN", "Capture was never claimed.", 409
                )
        except AppError:
            checkout["state"], order["status"] = "PAYMENT_UNKNOWN", "UNKNOWN"
            order["reconciliation_code"] = "PAYMENT_UNKNOWN"
            status = "UNKNOWN"
        else:
            self._apply_success(checkout, document, operation["kind"])
            status = "SUCCEEDED"
        self._record_observation(
            connection,
            operation,
            checkout,
            status,
            ("LOOKUP_UNAVAILABLE" if document is None else "ORDER_MISMATCH")
            if status == "UNKNOWN"
            else None,
        )
        self._persist_order(connection, checkout)
        self._save(connection, session, "reconcile_observed")
