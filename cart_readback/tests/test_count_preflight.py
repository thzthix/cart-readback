"""Outside-transaction count/CAS regressions; every count and price is fake."""

import dataclasses
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from cartreadback_app.count_preflight import run_offline_count
from cartreadback_app.inference import FixtureInferenceAdapter
from cartreadback_app.responses_adapter import OfflineResponsesAdapter
from cartreadback_app.service import Service
from cartreadback_app.storage import Store
from cartreadback_app.validation import AppError, canonical, text_hash
from test_analysis_dispatch import AuthoredTransport, budget_for
from test_domain import Workflow


class CountPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "app.sqlite3")
        self.transport = AuthoredTransport(self.store)
        self.adapter = OfflineResponsesAdapter(self.transport)
        self.budget = budget_for(self.adapter)
        self.service = Service(
            self.store, self.adapter, analysis_budget=self.budget
        )
        self.addCleanup(lambda: self.service.close())
        self.flow = Workflow(self.service)

    def rows(self, table):
        with self.store.connect() as connection:
            return [
                dict(row)
                for row in connection.execute(f"SELECT * FROM {table}")
            ]

    def waiting_counter(self, timeout=5):
        started, release = threading.Event(), threading.Event()
        calls = []

        def counter(raw):
            calls.append(raw)
            started.set()
            if not release.wait(4):
                raise RuntimeError("test release missing")
            return self.budget.count(raw)

        self.service.analysis_budget = dataclasses.replace(
            self.budget, count=counter, count_timeout_seconds=timeout
        )
        return started, release, calls

    def test_count_wait_holds_no_database_lock_and_binds_exact_receipt(self):
        started, release, calls = self.waiting_counter()
        with ThreadPoolExecutor() as executor:
            pending = executor.submit(self.flow.analyze)
            self.assertTrue(started.wait(2))
            try:
                current = self.service.bootstrap(self.flow.sid)["checkout"]
                self.assertEqual("ANALYSIS_BLOCKED", current["state"])
                self.assertIsNone(current["snapshot_hash"])
                self.assertIsNone(current["confirmation_id"])
                with self.store.transaction() as connection:
                    connection.execute(
                        "INSERT INTO events(sid, event, details) VALUES (?, 'count_test', '{}')",
                        (self.flow.sid,),
                    )
                other = Workflow(self.service)
                with self.assertRaises(AppError):
                    other.analyze()
                self.assertEqual(1, len(calls))
                self.assertEqual(
                    "COUNTING", self.rows("analysis_preflights")[0]["status"]
                )
                with self.assertRaises(AppError):
                    self.service.close()
            finally:
                release.set()
            result = pending.result()
        self.assertEqual("REVIEW_REQUIRED", result["checkout"]["state"])
        preflight = self.rows("analysis_preflights")[0]
        budget = self.rows("budget_operations")[0]
        self.assertEqual("USED", preflight["status"])
        self.assertEqual(
            budget["operation_id"], preflight["analysis_operation_id"]
        )
        self.assertEqual(
            budget["request_sha256"],
            json.loads(preflight["count_document"])["request_sha256"],
        )
        self.assertNotIn("count_document", canonical(result))
        self.assertEqual(1, self.transport.calls)

    def test_mutating_callers_body_cannot_rewrite_counted_request(self):
        started, release, _ = self.waiting_counter()
        body = {
            "expected_revision": 0,
            "sku_id": "KB-UK-C2C",
            "conditions": [
                {"kind": "layout", "value": "UK_QWERTY"},
                {"kind": "included_cable", "value": "USB-C to USB-C"},
            ],
        }
        with ThreadPoolExecutor() as executor:
            pending = executor.submit(
                self.service.mutate, self.flow.sid, "analyze", body
            )
            self.assertTrue(started.wait(2))
            body["expected_revision"] = 999
            body["sku_id"] = "forged"
            body["conditions"][0]["value"] = "DE_QWERTZ"
            release.set()
            result = pending.result()
        self.assertEqual("KB-UK-C2C", result["checkout"]["sku_id"])
        self.assertEqual(
            "UK_QWERTY", result["checkout"]["conditions"][0]["value"]
        )
        self.assertEqual(1, self.transport.calls)

    def test_source_change_during_count_makes_receipt_stale_without_generation(
        self,
    ):
        started, release, calls = self.waiting_counter()
        with ThreadPoolExecutor() as executor:
            pending = executor.submit(self.flow.analyze)
            self.assertTrue(started.wait(2))
            try:
                product = self.service.bootstrap(self.flow.sid)["catalog"][0]
                product["source"]["text"] += "Changed.\n"
                product["source"]["sha256"] = text_hash(
                    product["source"]["text"]
                )
                product["source"]["revision"] += 1
                product["catalog_revision"] += 1
                self.store.replace_product(product)
            finally:
                release.set()
            with self.assertRaises(AppError) as caught:
                pending.result()
        self.assertEqual("STALE_SNAPSHOT", caught.exception.code)
        self.assertEqual("STALE", self.rows("analysis_preflights")[0]["status"])
        self.assertTrue(self.rows("analysis_preflights")[0]["count_document"])
        self.assertFalse(self.rows("analysis_operations"))
        self.assertFalse(self.rows("budget_operations"))
        self.assertEqual(1, len(calls))
        self.assertEqual(0, self.transport.calls)

    def test_replaced_same_identity_counter_cannot_attach_old_preflight(self):
        started, release, _ = self.waiting_counter()
        with ThreadPoolExecutor() as executor:
            pending = executor.submit(self.flow.analyze)
            self.assertTrue(started.wait(2))
            self.service.analysis_budget = dataclasses.replace(
                self.service.analysis_budget
            )
            release.set()
            with self.assertRaises(AppError):
                pending.result()
        self.assertEqual("STALE", self.rows("analysis_preflights")[0]["status"])
        self.assertEqual(0, self.transport.calls)

    def test_newer_fixture_review_is_not_replaced_by_late_count(self):
        started, release, _ = self.waiting_counter()
        with ThreadPoolExecutor() as executor:
            pending = executor.submit(self.flow.analyze)
            self.assertTrue(started.wait(2))
            try:
                self.service.inference = FixtureInferenceAdapter()
                newer = Workflow(self.service, self.flow.sid)
                newer.analyze(layout="DE_QWERTZ")
                newer.confirm()
                expected = newer.result
            finally:
                release.set()
            with self.assertRaises(AppError):
                pending.result()
        self.assertEqual(
            expected["checkout"],
            self.service.bootstrap(self.flow.sid)["checkout"],
        )
        self.assertEqual("STALE", self.rows("analysis_preflights")[0]["status"])
        self.assertEqual(0, self.transport.calls)

    def test_count_intent_invalidates_old_consent_before_counter_finishes(self):
        self.flow.analyze()
        self.flow.confirm()
        old_review = self.flow.checkout["review_id"]
        started, release, _ = self.waiting_counter()
        with ThreadPoolExecutor() as executor:
            pending = executor.submit(self.flow.analyze)
            self.assertTrue(started.wait(2))
            try:
                current = self.service.bootstrap(self.flow.sid)["checkout"]
                self.assertEqual("ANALYSIS_BLOCKED", current["state"])
                self.assertIsNone(current["confirmation_id"])
                self.assertIsNone(current["snapshot_hash"])
                self.assertNotEqual(old_review, current["review_id"])
                with self.assertRaises(AppError):
                    self.flow.confirm()
                with self.assertRaises(AppError):
                    self.flow.create()
            finally:
                release.set()
            result = pending.result()
        self.assertEqual("REVIEW_REQUIRED", result["checkout"]["state"])
        self.assertIsNone(result["checkout"]["confirmation_id"])
        self.assertEqual(2, self.transport.calls)

    def test_duplicate_claim_and_observation_never_count_or_reserve_twice(self):
        counter = mock.Mock(side_effect=self.budget.count)
        self.service.analysis_budget = dataclasses.replace(
            self.budget, count=counter
        )
        claim, finish = self.service._claim_count, self.service._finish_count

        def duplicate_claim(*args):
            first = claim(*args)
            self.assertIsNone(claim(*args))
            return first

        def duplicate_finish(*args):
            first = finish(*args)
            self.assertEqual((None, "MODEL_BUDGET_EXCEEDED"), finish(*args))
            return first

        with (
            mock.patch.object(
                self.service, "_claim_count", side_effect=duplicate_claim
            ),
            mock.patch.object(
                self.service, "_finish_count", side_effect=duplicate_finish
            ),
        ):
            self.flow.analyze()
        self.assertEqual(1, counter.call_count)
        self.assertEqual(1, len(self.rows("budget_operations")))
        self.assertEqual(1, self.transport.calls)

    def test_timeout_is_persistent_unknown_and_late_count_has_no_write_callback(
        self,
    ):
        started, release, calls = self.waiting_counter(timeout=0.03)
        with self.assertRaises(AppError) as caught:
            self.flow.analyze()
        self.assertTrue(started.is_set())
        self.assertEqual("MODEL_TIMEOUT", caught.exception.code)
        before = self.rows("analysis_preflights")
        self.assertEqual("UNKNOWN", before[0]["status"])
        replacement_counter = mock.Mock(side_effect=self.budget.count)
        self.service.close()
        self.service = Service(
            self.store,
            self.adapter,
            analysis_budget=dataclasses.replace(
                self.budget, count=replacement_counter
            ),
        )
        self.flow = Workflow(self.service, self.flow.sid)
        with self.assertRaises(AppError):
            self.flow.analyze()
        replacement_counter.assert_not_called()
        release.set()
        self.assertEqual(before, self.rows("analysis_preflights"))
        self.assertEqual(1, len(calls))
        self.assertEqual(0, self.transport.calls)

    def test_stale_count_slots_are_global_bounded_and_not_refunded(self):
        self.service.analysis_budget = budget_for(self.adapter, max_calls=2)
        counter = mock.Mock(side_effect=self.service.analysis_budget.count)
        self.service.analysis_budget = dataclasses.replace(
            self.service.analysis_budget, count=counter
        )

        def change(name, _id):
            if name == "analysis_before_count_observation_commit":
                product = self.service.bootstrap(self.flow.sid)["catalog"][0]
                product["price_minor"] += 1
                self.store.replace_product(product)

        with mock.patch.object(self.service, "_checkpoint", side_effect=change):
            for _ in range(2):
                self.flow = Workflow(self.service, self.flow.sid)
                with self.assertRaises(AppError):
                    self.flow.analyze()
        with self.assertRaises(AppError):
            Workflow(self.service).analyze()
        self.assertEqual(2, counter.call_count)
        self.assertEqual(
            ["STALE", "STALE"],
            [row["status"] for row in self.rows("analysis_preflights")],
        )
        self.assertFalse(self.rows("budget_operations"))
        self.assertEqual(0, self.transport.calls)

    def test_known_impossible_capacity_is_rejected_before_counter(self):
        counter = mock.Mock(side_effect=self.budget.count)
        self.service.analysis_budget = dataclasses.replace(
            budget_for(self.adapter, max_micro_usd=1), count=counter
        )
        with self.assertRaises(AppError):
            self.flow.analyze()
        counter.assert_not_called()
        self.assertFalse(self.rows("analysis_preflights"))
        self.assertEqual(0, self.transport.calls)

    def test_counted_quota_rejection_retains_receipt_without_partial_reservation(
        self,
    ):
        minimum = self.budget.policy.cost(1, 2048)
        policy = budget_for(self.adapter, max_calls=1, max_micro_usd=minimum)
        counter = mock.Mock(side_effect=policy.count)
        self.service.analysis_budget = dataclasses.replace(
            policy, count=counter
        )
        with self.assertRaises(AppError):
            self.flow.analyze()
        row = self.rows("analysis_preflights")[0]
        self.assertEqual("BLOCKED", row["status"])
        self.assertTrue(row["count_document"])
        self.assertFalse(self.rows("analysis_operations"))
        self.assertFalse(self.rows("budget_operations"))
        with self.assertRaises(AppError):
            self.flow.analyze()
        self.assertEqual(1, counter.call_count)
        self.assertEqual(0, self.transport.calls)

    def test_failed_final_receipt_write_rolls_back_all_reservations(self):
        with self.store.transaction() as connection:
            connection.execute(
                "CREATE TRIGGER fail_count_finish BEFORE UPDATE ON analysis_preflights WHEN NEW.status = 'USED' BEGIN SELECT RAISE(ABORT, 'fabricated'); END"
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.flow.analyze()
        self.assertEqual(
            "COUNTING", self.rows("analysis_preflights")[0]["status"]
        )
        self.assertFalse(self.rows("analysis_operations"))
        self.assertFalse(self.rows("budget_operations"))
        current = self.service.bootstrap(self.flow.sid)["checkout"]
        self.assertEqual("ANALYSIS_BLOCKED", current["state"])
        self.assertIsNone(current["snapshot_hash"])
        self.assertEqual(0, self.transport.calls)
        self.service.close()
        self.service = Service(self.store)
        self.assertEqual(
            "UNKNOWN", self.rows("analysis_preflights")[0]["status"]
        )

    def test_new_order_during_count_preserves_existing_payment_identity(self):
        self.flow.analyze()
        self.flow.confirm()
        started, release, _ = self.waiting_counter()
        with ThreadPoolExecutor() as executor:
            pending = executor.submit(self.flow.analyze)
            self.assertTrue(started.wait(2))
            try:
                self.service.inference = FixtureInferenceAdapter()
                newer = Workflow(self.service, self.flow.sid)
                newer.analyze()
                newer.confirm()
                newer.create()
                expected = newer.result
            finally:
                release.set()
            with self.assertRaises(AppError):
                pending.result()
        self.assertEqual(
            expected["checkout"],
            self.service.bootstrap(self.flow.sid)["checkout"],
        )
        self.assertEqual(1, self.transport.calls)
        self.assertEqual(1, len(self.rows("orders")))

    def test_real_process_count_crashes_recover_without_replaying_counter(self):
        self.service.close()
        for index, checkpoint in enumerate(
            [
                "analysis_after_count_reservation_commit",
                "analysis_after_count_claim_commit",
                "analysis_before_count_observation_commit",
                "analysis_after_reservation_commit",
            ]
        ):
            path = Path(self.temp.name) / f"crash-{index}.sqlite3"
            marker = path.with_suffix(".counts")
            script = """
import dataclasses, os, sys
from pathlib import Path
from cartreadback_app.responses_adapter import OfflineResponsesAdapter
from cartreadback_app.service import Service
from cartreadback_app.storage import Store
from test_analysis_dispatch import AuthoredTransport, budget_for
from test_domain import Workflow
store = Store(sys.argv[1])
adapter = OfflineResponsesAdapter(AuthoredTransport(store))
budget = budget_for(adapter)
def count(raw):
    with Path(sys.argv[3]).open("a") as stream:
        stream.write("count\\n")
    return budget.count(raw)
class Crash(Service):
    def _checkpoint(self, name, operation_id):
        if name == sys.argv[2]: os._exit(73)
service = Crash(store, adapter, analysis_budget=dataclasses.replace(budget, count=count))
Workflow(service).analyze()
"""
            environment = {
                **os.environ,
                "PYTHONPATH": os.pathsep.join(
                    [str(Path.cwd()), str(Path.cwd() / "tests")]
                ),
            }
            crashed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    script,
                    str(path),
                    checkpoint,
                    str(marker),
                ],
                env=environment,
                capture_output=True,
                timeout=10,
            )
            self.assertEqual(73, crashed.returncode, crashed.stderr.decode())
            self.store = Store(path)
            self.transport = AuthoredTransport(self.store)
            self.adapter = OfflineResponsesAdapter(self.transport)
            self.service = Service(self.store)
            row = self.rows("analysis_preflights")[0]
            self.assertEqual("USED" if index == 3 else "UNKNOWN", row["status"])
            self.assertEqual(
                1 if index >= 2 else 0,
                len(marker.read_text().splitlines()) if marker.exists() else 0,
            )
            self.service.inference = self.adapter
            replacement = mock.Mock(side_effect=budget_for(self.adapter).count)
            self.service.analysis_budget = dataclasses.replace(
                budget_for(self.adapter), count=replacement
            )
            with self.assertRaises(AppError):
                Workflow(self.service).analyze()
            replacement.assert_not_called()
            self.assertEqual(0, self.transport.calls)
            self.service.close()
        self.service = Service(self.store)

    def test_invalid_direct_count_settings_never_invoke_counter(self):
        counter = mock.Mock()
        for timeout in [True, 0, -1, 21, float("inf"), "5"]:
            with self.subTest(timeout=timeout), self.assertRaises(AppError):
                run_offline_count(counter, b"{}", timeout)
        for raw in [None, b"", b"x" * 65_537, "{}"]:
            with self.subTest(raw_type=type(raw)), self.assertRaises(AppError):
                run_offline_count(counter, raw, 1)
        counter.assert_not_called()

    def test_timeout_configuration_is_explicit_bounded_and_not_boolean(self):
        for value in [True, 0, -1, 21, float("inf"), float("nan"), "5"]:
            with self.subTest(value=value), self.assertRaises(AppError):
                dataclasses.replace(self.budget, count_timeout_seconds=value)


if __name__ == "__main__":
    unittest.main()
