"""Synthetic budget regressions, not real counts, pricing or paid dispatch."""

import dataclasses
import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from cartreadback_app.inference_budget import (
    BudgetClaim,
    OfflineBudgetLedger,
    OfflineBudgetPolicy,
    OfflineInputCount,
    request_hash,
)
from cartreadback_app.validation import AppError


def policy(**changes):
    values = {
        "model": "gpt-6-luna",
        "price_revision": "fabricated-price-v1",
        "counter_revision": "fabricated-count-v1",
        "dispatch_config_sha256": "1" * 64,
        "scope_id": "fabricated-project",
        "input_micro_usd_per_million": 1_000_001,
        "output_micro_usd_per_million": 2_000_001,
        "max_calls": 4,
        "max_input_tokens": 200,
        "max_output_tokens": 100,
        "max_total_input_tokens": 800,
        "max_total_output_tokens": 400,
        "max_micro_usd": 10_000,
    }
    return OfflineBudgetPolicy(**{**values, **changes})


def payload(**changes):
    return json.dumps(
        {
            "model": "gpt-6-luna",
            "service_tier": "default",
            "max_output_tokens": 100,
            "input": "fabricated request",
            **changes,
        }
    ).encode()


def count(request=None, **changes):
    request = payload() if request is None else request
    return OfflineInputCount(
        **{
            "request_sha256": request_hash(request),
            "model": "gpt-6-luna",
            "counter_revision": "fabricated-count-v1",
            "input_tokens": 100,
            **changes,
        }
    )


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "budget.sqlite3"
        self.ledger = OfflineBudgetLedger(self.path, policy())
        self.addCleanup(lambda: self.ledger.close())

    def rows(self):
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            return [
                dict(row)
                for row in connection.execute("SELECT * FROM budget_operations")
            ]

    def known(self, ledger=None):
        ledger = ledger or self.ledger
        operation_id = ledger.reserve(payload(), count())
        claim = ledger.claim(operation_id, payload())
        ledger.settle(
            claim,
            model="gpt-6-luna",
            service_tier="default",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
        )
        return claim

    def test_integer_ceiling_each_component_and_no_discount(self):
        self.assertEqual(302, policy().cost(100, 100))
        self.assertEqual(
            2,
            policy(
                input_micro_usd_per_million=1, output_micro_usd_per_million=1
            ).cost(1, 1),
        )
        self.assertEqual(0, policy().cost(0, 0))
        for values in [(True, 1), (-1, 1), (1.5, 1), (2**54, 1)]:
            with self.subTest(values=values), self.assertRaises(AppError):
                policy().cost(*values)

    def test_known_usage_keeps_full_committed_reservation(self):
        self.known()
        row = self.rows()[0]
        self.assertEqual("KNOWN", row["status"])
        self.assertEqual(302, row["reserved_micro_usd"])
        self.assertEqual(
            202, json.loads(row["observation"])["actual_micro_usd"]
        )
        self.assertEqual(100, row["output_tokens"])
        self.assertNotIn("fabricated request", json.dumps(row))

    def test_all_policy_identity_changes_fail_without_replacing_history(self):
        self.known()
        self.ledger.close()
        for settings in [
            {"model": "other"},
            {"service_tier": "priority"},
            {"price_revision": "different"},
            {"counter_revision": "different"},
            {"dispatch_config_sha256": "2" * 64},
            {"scope_id": "different"},
            {"max_micro_usd": 20_000},
            {"max_calls": 5},
        ]:
            with self.subTest(settings=settings), self.assertRaises(AppError):
                OfflineBudgetLedger(self.path, policy(**settings))
        self.ledger = OfflineBudgetLedger(self.path, policy())
        self.assertEqual("KNOWN", self.rows()[0]["status"])

    def test_missing_count_and_wrong_bytes_or_counter_fail_before_reservation(
        self,
    ):
        for data in [
            None,
            count(request_sha256="0" * 64),
            count(model="other"),
            count(counter_revision="other"),
            count(input_tokens=True),
            count(input_tokens=0),
            count(input_tokens=201),
        ]:
            with self.subTest(data=data), self.assertRaises(AppError):
                self.ledger.reserve(payload(), data)
        self.assertEqual([], self.rows())
        for request in [
            payload(model="other"),
            payload(service_tier="auto"),
            payload(service_tier=None),
            payload(max_output_tokens=True),
            payload(max_output_tokens=99),
        ]:
            with self.subTest(request=request), self.assertRaises(AppError):
                self.ledger.reserve(request, count(request))
        self.assertEqual([], self.rows())

    def test_single_claim_commits_and_changed_bytes_do_not_dispatch(self):
        operation_id = self.ledger.reserve(payload(), count())
        with self.assertRaises(AppError):
            self.ledger.claim(operation_id, payload(input="different"))
        self.assertEqual("RESERVED", self.rows()[0]["status"])
        claim = self.ledger.claim(operation_id, payload())
        self.assertIsInstance(claim, BudgetClaim)
        self.assertEqual("DISPATCHED", self.rows()[0]["status"])
        with self.assertRaises(AppError):
            self.ledger.claim(operation_id, payload())

    def test_pending_and_unknown_block_all_new_reservations(self):
        operation_id = self.ledger.reserve(payload(), count())
        for phase in ("RESERVED", "DISPATCHED", "UNKNOWN"):
            if phase == "DISPATCHED":
                claim = self.ledger.claim(operation_id, payload())
            elif phase == "UNKNOWN":
                self.ledger.mark_unknown(claim)
            with self.subTest(phase=phase), self.assertRaises(AppError):
                self.ledger.reserve(payload(), count())
            self.assertEqual(1, len(self.rows()))

    def test_restart_recovers_reserved_or_dispatched_as_unknown(self):
        for dispatched in (False, True):
            self.ledger.close()
            self.path = Path(self.temp.name) / f"restart-{dispatched}.sqlite3"
            self.ledger = OfflineBudgetLedger(self.path, policy())
            operation_id = self.ledger.reserve(payload(), count())
            if dispatched:
                self.ledger.claim(operation_id, payload())
            self.ledger.close()
            self.ledger = OfflineBudgetLedger(self.path, policy())
            self.assertEqual("UNKNOWN", self.rows()[0]["status"])
            self.assertEqual(302, self.rows()[0]["reserved_micro_usd"])
            with self.assertRaises(AppError):
                self.ledger.reserve(payload(), count())

    def test_concurrent_reservation_and_claim_have_one_winner(self):
        def reserve(_):
            try:
                return self.ledger.reserve(payload(), count())
            except AppError:
                return None

        with ThreadPoolExecutor(max_workers=8) as executor:
            winners = [
                value for value in executor.map(reserve, range(8)) if value
            ]
        self.assertEqual(1, len(winners))

        def claim(_):
            try:
                return self.ledger.claim(winners[0], payload())
            except AppError:
                return None

        with ThreadPoolExecutor(max_workers=8) as executor:
            claims = [value for value in executor.map(claim, range(8)) if value]
        self.assertEqual(1, len(claims))

    def test_bad_identity_cannot_settle_another_operation(self):
        operation_id = self.ledger.reserve(payload(), count())
        claim = self.ledger.claim(operation_id, payload())
        for changes in [
            {"operation_id": "wrong"},
            {"request_sha256": "0" * 64},
            {"policy_sha256": "0" * 64},
            {"claim_token": "wrong"},
        ]:
            with self.subTest(changes=changes), self.assertRaises(AppError):
                self.ledger.mark_unknown(dataclasses.replace(claim, **changes))
        self.assertEqual("DISPATCHED", self.rows()[0]["status"])

    def test_invalid_usage_or_model_tier_is_committed_unknown(self):
        for index, changes in enumerate(
            [
                {"input_tokens": 101, "total_tokens": 151},
                {"output_tokens": 101, "total_tokens": 201},
                {"input_tokens": -1},
                {"output_tokens": True},
                {"total_tokens": 151},
                {"model": "other"},
                {"service_tier": "priority"},
                {"service_tier": None},
            ]
        ):
            self.ledger.close()
            self.path = Path(self.temp.name) / f"invalid-{index}.sqlite3"
            self.ledger = OfflineBudgetLedger(self.path, policy())
            operation_id = self.ledger.reserve(payload(), count())
            claim = self.ledger.claim(operation_id, payload())
            values = {
                "model": "gpt-6-luna",
                "service_tier": "default",
                "input_tokens": 100,
                "output_tokens": 50,
                "total_tokens": 150,
            }
            with self.subTest(changes=changes), self.assertRaises(AppError):
                self.ledger.settle(claim, **{**values, **changes})
            self.assertEqual("UNKNOWN", self.rows()[0]["status"])
            self.assertEqual("", self.rows()[0]["observation"])
            self.assertEqual(302, self.rows()[0]["reserved_micro_usd"])

    def test_all_aggregate_limits_remain_after_known_usage_and_restart(self):
        for name, value in [
            ("max_calls", 1),
            ("max_micro_usd", 603),
            ("max_total_input_tokens", 200),
            ("max_total_output_tokens", 100),
        ]:
            self.ledger.close()
            self.path = Path(self.temp.name) / f"limit-{name}.sqlite3"
            settings = policy(**{name: value})
            self.ledger = OfflineBudgetLedger(self.path, settings)
            self.known()
            if name == "max_total_input_tokens":
                self.known()
            self.ledger.close()
            self.ledger = OfflineBudgetLedger(self.path, settings)
            with self.subTest(name=name), self.assertRaises(AppError):
                self.ledger.reserve(payload(), count())

    def test_exclusive_owner_and_closed_instances_cannot_mutate(self):
        with self.assertRaises(OSError):
            OfflineBudgetLedger(self.path, policy())
        self.ledger.close()
        with self.assertRaises(AppError):
            self.ledger.reserve(payload(), count())

    def test_policy_rejects_unpriced_or_invalid_values(self):
        for changes in [
            {"input_micro_usd_per_million": 0},
            {"output_micro_usd_per_million": -1},
            {"max_calls": True},
            {"max_calls": 65},
            {"max_input_tokens": 801},
            {"max_micro_usd": 2**54},
            {"scope_id": "bad scope"},
            {"dispatch_config_sha256": "missing"},
            {"execution_mode": "live"},
        ]:
            with self.subTest(changes=changes), self.assertRaises(AppError):
                policy(**changes)


if __name__ == "__main__":
    unittest.main()
