"""Offline dispatch/crash probes with a provider DB outside app rollback."""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from uuid import UUID, uuid4

from cartreadback_app.payments import FixturePaymentAdapter, PaymentRequest
from cartreadback_app.service import Service
from cartreadback_app.storage import Store
from cartreadback_app.validation import AppError, canonical, digest, text_hash
from test_domain import Workflow


class BarrierProvider(FixturePaymentAdapter):
    def __init__(self, app_path):
        super().__init__()
        self.app_path = app_path
        self.entered = threading.Event()
        self.release = threading.Event()
        self.block = None
        self.on_get = None
        self.calls = []

    def unlocked(self, label):
        connection = sqlite3.connect(self.app_path, timeout=0.1)
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.rollback()
        finally:
            connection.close()
        self.calls.append(label)
        if self.block == label:
            self.entered.set()
            if not self.release.wait(10):
                raise AssertionError("Test barrier did not release")
            self.block = None

    def dispatch(self, operation_id, request):
        self.unlocked(
            "create" if request.path == "/fixture/orders" else "capture"
        )
        return super().dispatch(operation_id, request)

    def get(self, provider_order_id):
        self.unlocked("get")
        document = super().get(provider_order_id)
        callback, self.on_get = self.on_get, None
        if callback:
            callback()
        return document

    def approve(self, provider_order_id):
        self.unlocked("approve")
        return super().approve(provider_order_id)


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "app.sqlite3"
        self.store = Store(self.path)
        self.provider = BarrierProvider(self.path)
        self.service = Service(self.store, payments=self.provider)
        self.addCleanup(lambda: self.service.close())
        self.flow = Workflow(self.service)

    def operation(self, kind):
        with self.store.transaction() as connection:
            return dict(
                connection.execute(
                    "SELECT * FROM operations WHERE kind = ?", (kind,)
                ).fetchone()
            )

    def count(self, table):
        repository = (
            self.provider if table.startswith("fixture_") else self.store
        )
        with repository.connect() as connection:
            return connection.execute(
                f"SELECT count(*) FROM {table}"
            ).fetchone()[0]

    def restart(self):
        sid = self.flow.sid
        self.service.close()
        self.service = Service(Store(self.path))
        self.flow = Workflow(self.service, sid)

    def test_request_bytes_and_server_uuid_are_reserved_before_single_dispatch(
        self,
    ):
        self.flow.ready()
        self.flow.action("capture")
        with self.store.transaction() as connection:
            expected = connection.execute(
                "SELECT expected FROM orders"
            ).fetchone()[0]
        for kind in ("orders", "capture"):
            operation = self.operation(kind)
            self.assertEqual(
                operation["operation_id"], str(UUID(operation["operation_id"]))
            )
            self.assertNotEqual(
                operation["operation_id"], operation["idempotency_key"]
            )
            self.assertEqual("POST", operation["method"])
            self.assertEqual(
                expected if kind == "orders" else "{}",
                operation["upstream_payload"],
            )
            self.assertEqual(
                text_hash(operation["upstream_payload"]),
                operation["upstream_hash"],
            )
            self.assertEqual(
                digest(json.loads(expected)), operation["expected_hash"]
            )
            self.assertTrue(operation["dispatch_token"])
            self.assertTrue(operation["reserved_at"])
            self.assertTrue(operation["dispatched_at"])
            self.assertTrue(operation["observed_at"])
            with self.provider.connect() as connection:
                actual = connection.execute(
                    "SELECT method, path, body FROM fixture_dispatches WHERE operation_id = ?",
                    (operation["operation_id"],),
                ).fetchone()
            self.assertEqual(
                tuple(
                    operation[key]
                    for key in ("method", "path", "upstream_payload")
                ),
                actual,
            )
            self.service._dispatch(operation, self.provider)
        self.assertEqual(2, self.count("fixture_dispatches"))
        self.assertEqual(
            {"create", "get", "approve", "capture"}, set(self.provider.calls)
        )

    def test_fixture_receipts_count_attempts_without_deduplicating_uuid(self):
        self.flow.analyze()
        self.flow.confirm()
        self.flow.create()
        operation = self.operation("orders")
        self.provider.dispatch(
            operation["operation_id"],
            PaymentRequest(
                operation["method"],
                operation["path"],
                operation["upstream_payload"],
            ),
        )
        self.assertEqual(2, self.count("fixture_dispatches"))
        self.assertEqual(1, self.count("fixture_provider_orders"))

    def test_provider_wait_does_not_block_bootstrap_safe_writes_or_fresh_keys(
        self,
    ):
        self.flow.analyze()
        self.flow.confirm()
        self.provider.block = "create"
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(self.flow.create)
            try:
                self.assertTrue(self.provider.entered.wait(5))
                other = Workflow(self.service)
                self.assertIsNone(other.checkout)
                current = self.service.bootstrap(self.flow.sid)
                self.assertEqual(
                    "ORDER_CREATE_PENDING", current["checkout"]["state"]
                )
                product = current["catalog"][0]
                self.store.replace_product(product)
                with self.assertRaises(AppError):
                    self.service.mutate(
                        self.flow.sid,
                        "orders",
                        {
                            **self.flow.create_body(),
                            "expected_revision": current["revision"],
                        },
                        idempotency_key=str(uuid4()),
                    )
                with self.assertRaises(AppError):
                    self.service.close()
                with self.assertRaises(AppError) as caught:
                    Service(Store(self.path))
                self.assertEqual(
                    "SERVICE_ALREADY_RUNNING", caught.exception.code
                )
            finally:
                self.provider.release.set()
            pending.result(5)
        self.assertEqual(1, self.count("fixture_dispatches"))

    def test_cross_process_instance_guard_prevents_false_startup_recovery(self):
        code = (
            "from cartreadback_app.storage import Store; "
            "from cartreadback_app.service import Service; "
            "from cartreadback_app.validation import AppError; "
            "import sys\ntry: Service(Store(sys.argv[1]))\n"
            "except AppError as e: print(e.code); sys.exit(17)\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code, str(self.path)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(17, result.returncode, result.stderr)
        self.assertEqual("SERVICE_ALREADY_RUNNING", result.stdout.strip())

    def test_capture_get_wait_rechecks_every_local_authorization_binding(self):
        def change_product(field):
            product = deepcopy(
                self.service.bootstrap(self.flow.sid)["catalog"][0]
            )
            if field == "source":
                product["source"]["text"] += "\nChanged source."
                product["source"]["sha256"] = text_hash(
                    product["source"]["text"]
                )
            elif field == "source_revision":
                product["source"]["revision"] += 1
            else:
                product[field] += 1
            self.store.replace_product(product)

        for field in (
            "source",
            "source_revision",
            "catalog_revision",
            "price_minor",
            "model",
            "prompt",
            "merchant",
            "adapter_version",
            "adapter_instance",
            "consent",
            "expected",
        ):
            with self.subTest(binding=field):
                if field != "source":
                    self.service.close()
                    self.setUp()
                self.flow.ready()
                if field in {
                    "source",
                    "source_revision",
                    "catalog_revision",
                    "price_minor",
                }:

                    def callback():
                        change_product(field)
                elif field in {"model", "prompt"}:
                    self.service.inference.metadata = deepcopy(
                        self.service.inference.metadata
                    )

                    def callback():
                        self.service.inference.metadata.update(
                            {f"{field}_version": "changed"}
                        )
                elif field == "merchant":

                    def callback():
                        self.provider.merchant_id = "changed"
                elif field == "adapter_version":

                    def callback():
                        self.provider.version = "changed"
                elif field == "adapter_instance":

                    def callback():
                        self.service.payments = FixturePaymentAdapter()
                elif field == "consent":

                    def callback():
                        with self.store.transaction() as connection:
                            connection.execute(
                                "UPDATE confirmations SET document = '{}' "
                            )
                else:

                    def callback():
                        with self.store.transaction() as connection:
                            expected = json.loads(
                                connection.execute(
                                    "SELECT expected FROM orders"
                                ).fetchone()[0]
                            )
                            expected["amount_minor"] += 1
                            connection.execute(
                                "UPDATE orders SET expected = ?",
                                (canonical(expected),),
                            )

                self.provider.on_get = callback
                with self.assertRaises(AppError):
                    self.flow.action("capture")
                self.assertEqual(1, self.count("operations"))
                self.assertEqual(1, self.count("fixture_dispatches"))

    def test_original_reservation_rejects_rehashed_wire_tampering(self):
        self.flow.analyze()
        self.flow.confirm()

        def mutate(name, _operation_id):
            if name == "after_reservation_commit":
                with self.store.transaction() as connection:
                    connection.execute(
                        "UPDATE operations SET upstream_payload = '{}', upstream_hash = ?",
                        (text_hash("{}"),),
                    )

        self.service._checkpoint = mutate
        with self.assertRaises(AppError):
            self.flow.create()
        self.assertEqual(0, self.count("fixture_dispatches"))
        self.restart()
        self.assertEqual("PAYMENT_UNKNOWN", self.flow.checkout["state"])

    def test_observation_fence_and_late_failure_cannot_downgrade_completed(
        self,
    ):
        self.flow.ready()
        self.provider.fault = "capture_timeout_after_success"
        self.flow.action("capture")
        operation = self.operation("capture")
        document = self.provider.get(
            self.flow.checkout["order"]["provider_order_id"]
        )
        for field in (
            "dispatch_token",
            "upstream_hash",
            "expected_hash",
            "method",
            "path",
            "kind",
            "sid",
            "order_id",
            "operation_id",
        ):
            bad = {**operation, field: "wrong"}
            with self.subTest(field=field), self.assertRaises(AppError):
                with self.store.transaction() as connection:
                    self.service._observe_dispatch(
                        connection, bad, document, None
                    )
        self.flow.action("reconcile")
        revision = self.flow.result["revision"]
        with self.store.transaction() as connection:
            self.service._observe_dispatch(
                connection, operation, None, "OLD_TIMEOUT"
            )
        restored = self.service.bootstrap(self.flow.sid)
        self.assertEqual("COMPLETED", restored["checkout"]["state"])
        self.assertEqual(revision, restored["revision"])
        self.assertEqual("SUCCEEDED", self.operation("capture")["status"])
        self.assertEqual(2, self.count("fixture_dispatches"))

    def test_delayed_create_reconcile_cannot_overwrite_newer_capture(self):
        class Incomplete(FixturePaymentAdapter):
            def create(self, request_id, expected):
                document = super().create(request_id, expected)
                document.pop("items")
                return document

        self.service.payments = Incomplete()
        self.provider = self.service.payments
        self.flow.analyze()
        self.flow.confirm()
        self.flow.create()
        create_operation = self.operation("orders")
        self.assertTrue(self.flow.checkout["order"]["provider_order_id"])
        created = self.provider.get(
            self.flow.checkout["order"]["provider_order_id"]
        )
        self.flow.action("reconcile")
        self.flow.action("fixture-approve")
        self.flow.action("verify")
        self.provider.fault = "capture_timeout_before_success"
        self.flow.action("capture")
        with self.assertRaises(AppError):
            with self.store.transaction() as connection:
                self.service._reconcile_observation(
                    connection, create_operation, created
                )
        self.assertEqual(
            "PAYMENT_UNKNOWN",
            self.service.bootstrap(self.flow.sid)["checkout"]["state"],
        )
        self.assertEqual(
            "capture",
            self.service.bootstrap(self.flow.sid)["checkout"]["order"][
                "operation_kind"
            ],
        )
        self.assertEqual(2, self.count("fixture_dispatches"))

    def test_delayed_same_create_lookup_cannot_regress_success_or_verification(
        self,
    ):
        class Incomplete(FixturePaymentAdapter):
            def create(self, request_id, expected):
                document = super().create(request_id, expected)
                document.pop("items")
                return document

        self.service.payments = Incomplete()
        self.provider = self.service.payments
        self.flow.analyze()
        self.flow.confirm()
        self.flow.create()
        fence = self.operation("orders")
        old_created = self.provider.get(
            self.flow.checkout["order"]["provider_order_id"]
        )
        self.flow.action("reconcile")
        revision = self.flow.result["revision"]
        with self.store.transaction() as connection:
            self.service._reconcile_observation(connection, fence, None)
        restored = self.service.bootstrap(self.flow.sid)
        self.assertEqual("ORDER_CREATED", restored["checkout"]["state"])
        self.assertEqual(revision, restored["revision"])
        self.flow.action("fixture-approve")
        self.flow.action("verify")
        revision = self.flow.result["revision"]
        with self.store.transaction() as connection:
            self.service._reconcile_observation(connection, fence, old_created)
        restored = self.service.bootstrap(self.flow.sid)
        self.assertEqual("SERVER_RECHECKED", restored["checkout"]["state"])
        self.assertEqual(revision, restored["revision"])
        self.assertEqual("SUCCEEDED", self.operation("orders")["status"])
        self.assertEqual(1, self.count("fixture_dispatches"))

    def test_reconcile_while_dispatch_waits_then_matching_completion_is_monotonic(
        self,
    ):
        self.flow.ready()
        self.provider.block = "capture"
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(self.flow.action, "capture")
            try:
                self.assertTrue(self.provider.entered.wait(5))
                other = Workflow(self.service, self.flow.sid)
                other.action("reconcile")
                self.assertEqual("PAYMENT_UNKNOWN", other.checkout["state"])
            finally:
                self.provider.release.set()
            pending.result(5)
        self.assertEqual(
            "COMPLETED",
            self.service.bootstrap(self.flow.sid)["checkout"]["state"],
        )
        self.assertEqual(2, self.count("fixture_dispatches"))

    def test_legacy_shared_fixture_rows_migrate_and_stranded_pending_is_unknown(
        self,
    ):
        self.flow.ready()
        self.provider.fault = "capture_timeout_after_success"
        self.flow.action("capture")
        with self.provider.connect() as connection:
            legacy_orders = connection.execute(
                "SELECT * FROM fixture_provider_orders"
            ).fetchall()
        with self.store.transaction() as connection:
            connection.executemany(
                "INSERT INTO fixture_provider_orders VALUES (?, ?, ?)",
                legacy_orders,
            )
            connection.execute(
                "ALTER TABLE operations RENAME TO modern_operations"
            )
            connection.execute(
                "CREATE TABLE operations AS SELECT operation_id, sid, kind, idempotency_key, request_hash, order_id, CASE WHEN kind = 'capture' THEN 'PENDING' ELSE status END AS status, upstream_payload, upstream_hash FROM modern_operations"
            )
            connection.execute("DROP TABLE modern_operations")
            session = self.service._session(connection, self.flow.sid)
            session["checkout"]["state"] = "CAPTURE_PENDING"
            connection.execute(
                "UPDATE sessions SET checkout = ? WHERE sid = ?",
                (canonical(session["checkout"]), self.flow.sid),
            )
        self.service.close()
        self.provider.path.unlink()
        self.service = Service(Store(self.path))
        self.flow = Workflow(self.service, self.flow.sid)
        self.assertEqual("PAYMENT_UNKNOWN", self.flow.checkout["state"])
        self.flow.action("reconcile")
        self.assertEqual("COMPLETED", self.flow.checkout["state"])

    def test_real_process_crash_matrix_keeps_provider_effects_and_never_replays(
        self,
    ):
        checkpoints = (
            "before_reservation_commit",
            "after_reservation_commit",
            "after_claim_commit",
            "after_request_send",
            "provider_effect_before_response",
            "after_provider_response",
            "before_observation_commit",
            "after_observation_commit",
        )
        for kind in ("orders", "capture"):
            for checkpoint in checkpoints:
                with self.subTest(kind=kind, checkpoint=checkpoint):
                    self.service.close()
                    self.setUp()
                    self.flow.analyze()
                    self.flow.confirm()
                    if kind == "capture":
                        self.flow.create()
                        self.flow.action("fixture-approve")
                        self.flow.action("verify")
                    sid = self.flow.sid
                    self.service.close()
                    result = subprocess.run(
                        [
                            sys.executable,
                            str(Path(__file__).resolve()),
                            "--crash-worker",
                            str(self.path),
                            sid,
                            kind,
                            checkpoint,
                        ],
                        capture_output=True,
                        text=True,
                        timeout=15,
                        env={
                            **os.environ,
                            "PYTHONPATH": str(
                                Path(__file__).resolve().parents[1]
                            ),
                        },
                    )
                    self.assertEqual(
                        73, result.returncode, result.stdout + result.stderr
                    )
                    self.service = Service(Store(self.path))
                    self.flow = Workflow(self.service, sid)
                    dispatched = checkpoint in {
                        "after_request_send",
                        "provider_effect_before_response",
                        "after_provider_response",
                        "before_observation_commit",
                        "after_observation_commit",
                    }
                    with self.service.payments.connect() as connection:
                        receipts = connection.execute(
                            "SELECT count(*) FROM fixture_dispatches"
                        ).fetchone()[0]
                        orders = connection.execute(
                            "SELECT document FROM fixture_provider_orders"
                        ).fetchall()
                    self.assertEqual(
                        (1 if kind == "capture" else 0) + int(dispatched),
                        receipts,
                    )
                    if checkpoint == "before_reservation_commit":
                        (
                            self.flow.create
                            if kind == "orders"
                            else lambda: self.flow.action("capture")
                        )()
                    elif checkpoint == "after_observation_commit":
                        operation = self.operation(kind)
                        if kind == "orders":
                            self.flow.create(operation["idempotency_key"])
                        else:
                            self.flow.action("capture")
                        self.assertEqual(
                            "ORDER_CREATED"
                            if kind == "orders"
                            else "COMPLETED",
                            self.flow.checkout["state"],
                        )
                    else:
                        self.assertEqual(
                            "PAYMENT_UNKNOWN", self.flow.checkout["state"]
                        )
                        self.flow.action("reconcile")
                        completed_effect = checkpoint in {
                            "provider_effect_before_response",
                            "after_provider_response",
                            "before_observation_commit",
                        }
                        self.assertEqual(
                            "COMPLETED"
                            if kind == "capture" and completed_effect
                            else "PAYMENT_UNKNOWN",
                            self.flow.checkout["state"],
                        )
                        if kind == "orders":
                            self.assertIsNone(
                                self.flow.checkout["order"]["provider_order_id"]
                            )
                            self.assertEqual(int(completed_effect), len(orders))
                        if kind == "capture" and completed_effect:
                            self.flow.action("capture")
                            self.assertEqual(
                                "COMPLETED", self.flow.checkout["state"]
                            )
                        else:
                            with self.assertRaises(AppError):
                                (
                                    self.flow.create
                                    if kind == "orders"
                                    else lambda: self.flow.action("capture")
                                )()
                    with self.service.payments.connect() as connection:
                        after = connection.execute(
                            "SELECT count(*) FROM fixture_dispatches"
                        ).fetchone()[0]
                    self.assertEqual(
                        receipts
                        + int(checkpoint == "before_reservation_commit"),
                        after,
                    )


def crash_worker(path, sid, kind, checkpoint):
    class CrashProvider(FixturePaymentAdapter):
        def create(self, request_id, expected):
            if checkpoint == "after_request_send":
                os._exit(73)
            result = super().create(request_id, expected)
            if checkpoint == "provider_effect_before_response":
                os._exit(73)
            return result

        def capture(self, provider_order_id, request_id):
            if checkpoint == "after_request_send":
                os._exit(73)
            result = super().capture(provider_order_id, request_id)
            if checkpoint == "provider_effect_before_response":
                os._exit(73)
            return result

    service = Service(Store(path), payments=CrashProvider())
    flow = Workflow(service, sid)

    def interrupt(name, _operation_id):
        if name == checkpoint:
            os._exit(73)

    service._checkpoint = interrupt
    (flow.create if kind == "orders" else lambda: flow.action("capture"))()
    raise AssertionError("Crash checkpoint was not reached")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--crash-worker":
        crash_worker(*sys.argv[2:])
    else:
        unittest.main()
