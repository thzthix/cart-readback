"""Atomic offline budget/analysis integration, with fabricated counts/rates."""

import dataclasses
import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from cartreadback_app.analysis import OfflineAnalysisBudget
from cartreadback_app.inference import FixtureInferenceAdapter
from cartreadback_app.inference_budget import (
    TransactionBudgetLedger,
)
from cartreadback_app.responses_adapter import OfflineResponsesAdapter
from cartreadback_app.service import Service
from cartreadback_app.storage import Store
from cartreadback_app.validation import AppError, canonical
from test_analysis_dispatch import AuthoredTransport, budget_for
from test_domain import Workflow


class IntegratedBudgetTests(unittest.TestCase):
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

    def restart(self, budget=None):
        self.service.close()
        self.service = Service(self.store, self.adapter, analysis_budget=budget)
        self.flow = Workflow(self.service, self.flow.sid)

    def test_default_off_and_forged_fixture_label_do_not_dispatch(self):
        self.service.analysis_budget = None
        self.adapter._metadata["is_fixture"] = True
        with self.assertRaises(AppError) as caught:
            self.flow.analyze()
        self.assertEqual("MODEL_BUDGET_EXCEEDED", caught.exception.code)
        self.assertEqual(0, self.transport.calls)
        self.assertFalse(self.rows("analysis_operations"))
        self.assertFalse(self.rows("budget_operations"))
        self.assertFalse(
            self.service.provider_contract()["analysis"]["is_fixture"]
        )

    def test_fixture_never_counts_or_reserves_budget(self):
        counter = mock.Mock(side_effect=RuntimeError("must not run"))
        self.service.inference = FixtureInferenceAdapter()
        self.service.analysis_budget = OfflineAnalysisBudget(
            self.budget.policy, counter
        )
        result = self.flow.analyze()
        self.assertEqual("REVIEW_REQUIRED", result["checkout"]["state"])
        counter.assert_not_called()
        self.assertFalse(self.rows("budget_operations"))

    def test_reserve_claim_and_observation_share_identity_and_transaction(self):
        self.flow.analyze()
        analysis = self.rows("analysis_operations")[0]
        budget = self.rows("budget_operations")[0]
        inputs = json.loads(analysis["input_document"])
        self.assertEqual(analysis["operation_id"], budget["operation_id"])
        self.assertEqual(analysis["dispatch_token"], budget["claim_token"])
        self.assertEqual("SUCCEEDED", analysis["status"])
        self.assertEqual("KNOWN", budget["status"])
        self.assertEqual(
            inputs["budget_request_sha256"], budget["request_sha256"]
        )
        self.assertEqual(
            budget["request_sha256"],
            json.loads(analysis["observation"])["request_sha256"],
        )
        self.assertEqual(2048, budget["output_tokens"])
        self.assertNotIn("budget_policy_document", canonical(self.flow.result))
        self.assertNotIn("fabricated-price", canonical(self.flow.result))
        self.flow.confirm()

    def test_count_error_or_wrong_exact_bytes_rolls_back_everything(self):
        for counter in [
            lambda _: None,
            lambda _: dataclasses.replace(
                self.budget.count(b"x"), request_sha256="0" * 64
            ),
        ]:
            self.service.analysis_budget = OfflineAnalysisBudget(
                self.budget.policy, counter
            )
            with self.assertRaises(AppError):
                self.flow.analyze()
            self.assertFalse(self.rows("analysis_operations"))
            self.assertFalse(self.rows("budget_operations"))
            self.assertFalse(self.rows("budget_identity"))
            self.assertIsNone(self.service.bootstrap(self.flow.sid)["checkout"])

        def failing(_):
            raise RuntimeError("synthetic secret must not escape")

        self.service.analysis_budget = OfflineAnalysisBudget(
            self.budget.policy, failing
        )
        with self.assertRaises(AppError) as caught:
            self.flow.analyze()
        self.assertNotIn("synthetic secret", str(caught.exception))
        self.assertEqual(0, self.transport.calls)

    def test_reservation_failure_rolls_back_budget_and_checkout(self):
        with mock.patch.object(
            self.service,
            "_write_review",
            side_effect=RuntimeError("fabricated write failure"),
        ):
            with self.assertRaises(RuntimeError):
                self.flow.analyze()
        self.assertFalse(self.rows("analysis_operations"))
        self.assertFalse(self.rows("budget_operations"))
        self.assertFalse(self.rows("budget_identity"))
        self.assertEqual(0, self.transport.calls)

    def test_claim_write_failure_rolls_back_claim_then_restart_is_unknown(self):
        with self.store.transaction() as connection:
            connection.execute(
                "CREATE TRIGGER fail_claim BEFORE UPDATE OF status ON analysis_operations WHEN NEW.status = 'DISPATCHED' BEGIN SELECT RAISE(ABORT, 'fabricated'); END"
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.flow.analyze()
        self.assertEqual(
            "RESERVED", self.rows("analysis_operations")[0]["status"]
        )
        self.assertEqual(
            "RESERVED", self.rows("budget_operations")[0]["status"]
        )
        self.assertEqual(0, self.transport.calls)
        self.restart(self.budget)
        self.assertEqual(
            "UNKNOWN", self.rows("analysis_operations")[0]["status"]
        )
        self.assertEqual("UNKNOWN", self.rows("budget_operations")[0]["status"])
        with self.assertRaises(AppError):
            self.flow.analyze()

    def test_observation_write_failure_rolls_back_both_ledgers(self):
        with self.store.transaction() as connection:
            connection.execute(
                "CREATE TRIGGER fail_observation BEFORE UPDATE OF status ON analysis_operations WHEN NEW.status = 'SUCCEEDED' BEGIN SELECT RAISE(ABORT, 'fabricated'); END"
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.flow.analyze()
        self.assertEqual(1, self.transport.calls)
        self.assertEqual(
            "DISPATCHED", self.rows("analysis_operations")[0]["status"]
        )
        self.assertEqual(
            "DISPATCHED", self.rows("budget_operations")[0]["status"]
        )
        self.assertIsNone(
            self.service.bootstrap(self.flow.sid)["checkout"]["snapshot_hash"]
        )
        self.restart(self.budget)
        self.assertEqual("UNKNOWN", self.rows("budget_operations")[0]["status"])
        self.assertEqual(
            "UNKNOWN", self.rows("analysis_operations")[0]["status"]
        )
        self.assertEqual(1, self.transport.calls)

    def test_request_drift_before_claim_is_unknown_without_call(self):
        original = self.adapter.build_request
        calls = 0

        def changed(source, conditions):
            nonlocal calls
            calls += 1
            raw = original(source, conditions)
            return raw if calls == 1 else raw + b" "

        with mock.patch.object(
            self.adapter, "build_request", side_effect=changed
        ):
            self.flow.analyze()
        self.assertEqual(0, self.transport.calls)
        self.assertEqual("UNKNOWN", self.rows("budget_operations")[0]["status"])
        self.assertIsNone(self.flow.checkout["snapshot_hash"])

    def test_request_drift_after_claim_is_rejected_before_transport(self):
        original = self.adapter.build_request

        def checkpoint(name, operation_id):
            if name == "analysis_after_dispatch_commit":
                self.adapter.build_request = (
                    lambda source, conditions: original(source, conditions)
                    + b" "
                )

        with mock.patch.object(
            self.service, "_checkpoint", side_effect=checkpoint
        ):
            self.flow.analyze()
        self.assertEqual(0, self.transport.calls)
        self.assertEqual(
            "UNKNOWN", self.rows("analysis_operations")[0]["status"]
        )
        self.assertEqual("UNKNOWN", self.rows("budget_operations")[0]["status"])

    def test_over_reserved_input_usage_is_atomic_unknown_and_persistent(self):
        value = json.loads(self.transport.raw)
        value["usage"] = {
            "input_tokens": 101,
            "output_tokens": 50,
            "total_tokens": 151,
        }
        self.transport.raw = canonical(value).encode()
        self.flow.analyze()
        self.assertEqual(
            "MODEL_BUDGET_EXCEEDED", self.flow.checkout["analysis_error"]
        )
        self.assertIsNone(self.flow.checkout["snapshot_hash"])
        self.assertEqual(
            "UNKNOWN", self.rows("analysis_operations")[0]["status"]
        )
        self.assertEqual("UNKNOWN", self.rows("budget_operations")[0]["status"])
        self.restart(self.budget)
        with self.assertRaises(AppError):
            self.flow.analyze()
        self.assertEqual(1, self.transport.calls)

    def test_aggregate_capacity_survives_known_settlement_and_new_owner(self):
        self.service.analysis_budget = budget_for(self.adapter, max_calls=1)
        self.flow.analyze()
        reserved = self.rows("budget_operations")[0]["reserved_micro_usd"]
        self.restart(budget_for(self.adapter, max_calls=1))
        other = Workflow(self.service)
        with self.assertRaises(AppError):
            other.analyze()
        self.assertEqual(
            reserved, self.rows("budget_operations")[0]["reserved_micro_usd"]
        )
        self.assertEqual(1, self.transport.calls)

    def test_aggregate_token_and_synthetic_spend_limits_are_not_refunded(self):
        settings = [
            {"max_input_tokens": 100, "max_total_input_tokens": 100},
            {"max_total_output_tokens": 2048},
            {"max_micro_usd": self.budget.policy.cost(100, 2048)},
        ]
        for index, changes in enumerate(settings):
            self.service.close()
            self.store = Store(Path(self.temp.name) / f"limit-{index}.sqlite3")
            self.transport = AuthoredTransport(self.store)
            self.adapter = OfflineResponsesAdapter(self.transport)
            self.service = Service(
                self.store,
                self.adapter,
                analysis_budget=budget_for(self.adapter, **changes),
            )
            self.flow = Workflow(self.service)
            self.flow.analyze()
            with self.subTest(changes=changes), self.assertRaises(AppError):
                Workflow(self.service).analyze()
            self.assertEqual(1, self.transport.calls)
            self.assertEqual(
                "KNOWN", self.rows("budget_operations")[0]["status"]
            )

    def test_stale_before_dispatch_keeps_unknown_capacity_and_never_calls(self):
        def checkpoint(name, operation_id):
            if name == "analysis_after_reservation_commit":
                self.service.inference = FixtureInferenceAdapter()

        with mock.patch.object(
            self.service, "_checkpoint", side_effect=checkpoint
        ):
            self.flow.analyze()
        self.assertEqual(0, self.transport.calls)
        self.assertEqual("UNKNOWN", self.rows("budget_operations")[0]["status"])
        self.service.inference = self.adapter
        with self.assertRaises(AppError):
            self.flow.analyze()

    def test_changed_policy_cannot_reset_history_or_confirm_old_snapshot(self):
        self.flow.analyze()
        self.service.analysis_budget = budget_for(self.adapter, max_calls=9)
        self.assertTrue(
            self.service.bootstrap(self.flow.sid)["checkout"]["stale"]
        )
        with self.assertRaises(AppError):
            self.flow.confirm()
        with self.assertRaises(AppError):
            self.flow.analyze()
        self.assertEqual(1, self.transport.calls)
        self.assertEqual(1, len(self.rows("budget_operations")))

    def test_stale_result_accounts_reserved_policy_but_never_attaches(self):
        self.transport.wait = True
        with ThreadPoolExecutor() as executor:
            task = executor.submit(self.flow.analyze)
            self.assertTrue(self.transport.started.wait(2))
            try:
                self.service.analysis_budget = budget_for(
                    self.adapter, price_revision="changed"
                )
                # A different transaction remains available while transport waits.
                with self.store.transaction() as connection:
                    self.assertTrue(connection.in_transaction)
            finally:
                self.transport.release.set()
            result = task.result()
        self.assertIsNone(result["checkout"]["snapshot_hash"])
        self.assertEqual("STALE", self.rows("analysis_operations")[0]["status"])
        self.assertEqual("KNOWN", self.rows("budget_operations")[0]["status"])

    def test_unbudgeted_legacy_nonfixture_history_blocks_adoption(self):
        self.flow.analyze()
        with self.store.transaction() as connection:
            connection.execute("DELETE FROM budget_operations")
        with self.assertRaises(AppError):
            self.flow.analyze()
        self.assertEqual(1, self.transport.calls)
        self.assertFalse(self.rows("budget_operations"))

    def test_transaction_seam_cannot_commit_its_owners_transaction(self):
        source = self.service.bootstrap(self.flow.sid)["catalog"][0]["source"]
        with self.assertRaises(RuntimeError):
            with self.store.transaction() as connection:
                ledger = TransactionBudgetLedger(connection, self.budget.policy)
                raw = self.adapter.build_request(
                    source,
                    [
                        {
                            "condition_id": "c1",
                            "kind": "layout",
                            "value": "UK_QWERTY",
                        }
                    ],
                )
                ledger.reserve(raw, self.budget.count(raw))
                self.assertTrue(connection.in_transaction)
                raise RuntimeError("outer rollback")
        self.assertFalse(self.rows("budget_operations"))
        self.assertFalse(self.rows("budget_identity"))


if __name__ == "__main__":
    unittest.main()
