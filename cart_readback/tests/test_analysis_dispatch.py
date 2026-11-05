"""Offline reserve/claim/fence regressions, not real inference or accounting."""

import dataclasses
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
from pathlib import Path
from unittest import mock

from cartreadback_app.analysis import AnalysisPolicy, OfflineAnalysisBudget
from cartreadback_app.inference import FixtureInferenceAdapter
from cartreadback_app.inference_budget import OfflineInputCount, request_hash
from cartreadback_app.inference_config import InferenceConfig
from cartreadback_app.responses_adapter import (
    OfflineResponsesAdapter,
    WireResponse,
)
from cartreadback_app.service import Service
from cartreadback_app.storage import Store
from cartreadback_app.validation import AppError, canonical, text_hash
from test_domain import Workflow
from test_inference_budget import policy
from test_responses_adapter import encode, envelope


def budget_for(adapter, **changes):
    settings = policy(
        **{
            "dispatch_config_sha256": adapter.metadata["config_sha256"],
            "max_output_tokens": 2048,
            "max_total_output_tokens": 16_384,
            "max_total_input_tokens": 1600,
            "max_calls": 8,
            "max_micro_usd": 100_000,
            **changes,
        }
    )
    return OfflineAnalysisBudget(
        settings,
        lambda request: OfflineInputCount(
            request_hash(request),
            settings.model,
            settings.counter_revision,
            100,
        ),
    )


class WaitingFixture(FixtureInferenceAdapter):
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = 0
        self.metadata = deepcopy(self.metadata)

    def propose(self, source, conditions):
        self.calls += 1
        self.started.set()
        if not self.release.wait(4):
            raise RuntimeError("Test did not release adapter")
        return super().propose(source, conditions)


class AuthoredTransport:
    def __init__(self, store, failure=None, wait=False):
        with closing(store.connect()) as connection, connection:
            product = json.loads(
                connection.execute(
                    "SELECT document FROM catalog WHERE sku = 'KB-UK-C2C'"
                ).fetchone()[0]
            )
        conditions = [
            {"condition_id": "c1", "kind": "layout", "value": "UK_QWERTY"},
            {
                "condition_id": "c2",
                "kind": "included_cable",
                "value": "USB-C to USB-C",
            },
        ]
        self.raw = encode(
            envelope(
                FixtureInferenceAdapter().propose(product["source"], conditions)
            )
        )
        self.calls = 0
        self.started = threading.Event()
        self.release = threading.Event()
        self.wait = wait
        self.failure = failure
        self.closed = threading.Event()

    def send(self, endpoint, body, *, deadline):
        self.calls += 1
        self.started.set()
        if self.wait and not self.release.wait(4):
            raise TimeoutError("fabricated timeout")
        if self.failure == "exception":
            raise RuntimeError("secret must not be echoed")
        raw = self.raw
        if self.failure == "refusal":
            document = json.loads(raw)
            document["output"][0]["content"] = [
                {"type": "refusal", "refusal": "fabricated"}
            ]
            raw = encode(document)
        return WireResponse(200, "req_fabricated", [raw], self.closed.set)


class AnalysisDispatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "db.sqlite3"
        self.store = Store(self.path)
        self.service = Service(self.store)
        self.addCleanup(lambda: self.service.close())
        self.flow = Workflow(self.service)

    def operations(self):
        with closing(self.store.connect()) as connection, connection:
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM analysis_operations ORDER BY rowid"
                )
            ]

    def use_responses(
        self, failure=None, wait=False, max_attempts=8, timeout=20
    ):
        transport = AuthoredTransport(self.store, failure, wait)
        self.service.inference = OfflineResponsesAdapter(
            transport, InferenceConfig(overall_timeout_seconds=timeout)
        )
        self.service.analysis_budget = budget_for(self.service.inference)
        self.service.analysis_policy = AnalysisPolicy(max_attempts=max_attempts)
        return transport

    def test_pending_checkout_and_unrelated_writes_do_not_wait_for_inference(
        self,
    ):
        adapter = WaitingFixture()
        self.service.inference = adapter
        with ThreadPoolExecutor() as executor:
            pending = executor.submit(self.flow.analyze)
            self.assertTrue(adapter.started.wait(2))
            try:
                current = self.service.bootstrap(self.flow.sid)
                self.assertEqual(
                    "ANALYSIS_BLOCKED", current["checkout"]["state"]
                )
                self.assertEqual(
                    "MODEL_PENDING", current["checkout"]["analysis_error"]
                )
                self.assertIsNone(current["checkout"]["snapshot_hash"])
                with self.store.transaction() as connection:
                    self.assertEqual(
                        "DISPATCHED",
                        connection.execute(
                            "SELECT status FROM analysis_operations"
                        ).fetchone()[0],
                    )
                other = Workflow(self.service)
                self.assertEqual(0, other.result["revision"])
                with self.assertRaises(AppError):
                    self.service.close()
            finally:
                adapter.release.set()
            self.assertEqual(
                "REVIEW_REQUIRED", pending.result()["checkout"]["state"]
            )
        self.assertEqual(1, adapter.calls)
        operation = self.operations()[0]
        self.assertEqual("SUCCEEDED", operation["status"])
        self.assertTrue(operation["dispatch_token"])
        self.assertEqual("", operation["observation"])

    def test_valid_offline_observation_is_bound_persisted_and_not_public(self):
        transport = self.use_responses()
        result = self.flow.analyze()
        self.assertEqual("REVIEW_REQUIRED", result["checkout"]["state"])
        operation = self.operations()[0]
        observation = json.loads(operation["observation"])
        self.assertEqual(150, observation["total_tokens"])
        self.assertEqual(
            result["checkout"]["source"]["sha256"], observation["source_sha256"]
        )
        self.assertNotIn("resp_fabricated", canonical(result))
        self.assertEqual(1, transport.calls)
        self.flow.confirm()
        self.assertEqual("SNAPSHOT_CONFIRMED", self.flow.checkout["state"])

    def test_attempt_limit_is_global_and_survives_service_restart(self):
        transport = self.use_responses(max_attempts=1)
        self.flow.analyze()
        self.service.close()
        self.service = Service(
            self.store,
            self.service.inference,
            analysis_policy=AnalysisPolicy(max_attempts=1),
        )
        other = Workflow(self.service)
        with self.assertRaises(AppError) as caught:
            other.analyze()
        self.assertEqual("MODEL_BUDGET_EXCEEDED", caught.exception.code)
        self.assertEqual(1, transport.calls)
        self.assertEqual(1, len(self.operations()))
        self.assertIsNone(self.service.bootstrap(other.sid)["checkout"])

    def test_refusal_and_transport_errors_consume_attempt_and_trip_durable_breaker(
        self,
    ):
        for failure, code in [
            ("refusal", "MODEL_REFUSED"),
            ("exception", "MODEL_UNAVAILABLE"),
        ]:
            with self.subTest(failure=failure):
                self.service.close()
                self.path = Path(self.temp.name) / f"{failure}.sqlite3"
                self.store = Store(self.path)
                self.service = Service(self.store)
                self.flow = Workflow(self.service)
                transport = self.use_responses(failure)
                self.flow.analyze()
                self.assertEqual(code, self.flow.checkout["analysis_error"])
                self.assertEqual("UNKNOWN", self.operations()[0]["status"])
                self.assertIsNone(self.flow.checkout["snapshot_hash"])
                self.service.close()
                replacement = OfflineResponsesAdapter(
                    AuthoredTransport(self.store)
                )
                self.service = Service(self.store, replacement)
                self.flow = Workflow(self.service, self.flow.sid)
                with self.assertRaises(AppError) as caught:
                    self.flow.analyze()
                self.assertEqual("MODEL_BUDGET_EXCEEDED", caught.exception.code)
                self.assertEqual(1, transport.calls)

    def test_nonfixture_concurrency_is_global_and_does_not_consume_second_slot(
        self,
    ):
        transport = self.use_responses(wait=True)
        other = Workflow(self.service)
        with ThreadPoolExecutor() as executor:
            pending = executor.submit(self.flow.analyze)
            self.assertTrue(transport.started.wait(2))
            try:
                with self.assertRaises(AppError) as caught:
                    other.analyze()
                self.assertEqual("MODEL_UNAVAILABLE", caught.exception.code)
            finally:
                transport.release.set()
            pending.result()
        self.assertEqual(1, len(self.operations()))
        self.assertEqual(1, transport.calls)

    def test_late_source_or_model_change_cannot_attach_success(self):
        for change in ("source", "adapter", "metadata"):
            with self.subTest(change=change):
                adapter = WaitingFixture()
                self.service.inference = adapter
                self.flow = Workflow(self.service, self.flow.sid)
                with ThreadPoolExecutor() as executor:
                    pending = executor.submit(self.flow.analyze)
                    self.assertTrue(adapter.started.wait(2))
                    try:
                        if change == "source":
                            product = self.service.bootstrap(self.flow.sid)[
                                "catalog"
                            ][0]
                            product["source"]["text"] += "Changed.\n"
                            product["source"]["sha256"] = text_hash(
                                product["source"]["text"]
                            )
                            product["source"]["revision"] += 1
                            product["catalog_revision"] += 1
                            self.store.replace_product(product)
                        elif change == "adapter":
                            self.service.inference = FixtureInferenceAdapter()
                        else:
                            adapter.metadata["prompt_version"] += "-changed"
                    finally:
                        adapter.release.set()
                    result = pending.result()
                self.assertEqual(
                    "ANALYSIS_BLOCKED", result["checkout"]["state"]
                )
                self.assertEqual(
                    "STALE_SNAPSHOT", result["checkout"]["analysis_error"]
                )
                self.assertIsNone(result["checkout"]["snapshot_hash"])
                self.assertEqual([], result["checkout"]["results"])
                self.assertEqual("STALE", self.operations()[-1]["status"])

    def test_old_generation_cannot_overwrite_new_review_or_its_confirmation(
        self,
    ):
        old = WaitingFixture()
        self.service.inference = old
        with ThreadPoolExecutor() as executor:
            pending = executor.submit(self.flow.analyze)
            self.assertTrue(old.started.wait(2))
            try:
                self.service.inference = FixtureInferenceAdapter()
                newer = Workflow(self.service, self.flow.sid)
                newer.analyze(layout="DE_QWERTZ")
                newer.confirm()
                expected = deepcopy(newer.result)
            finally:
                old.release.set()
            result = pending.result()
        self.assertEqual(expected, result)
        self.assertEqual("STALE", self.operations()[0]["status"])

    def test_mutating_adapter_input_cannot_rewrite_checkout_or_reserved_source(
        self,
    ):
        class Mutating(FixtureInferenceAdapter):
            def propose(self, source, conditions):
                result = super().propose(source, conditions)
                source["text"] = "forged"
                conditions[0]["value"] = "DE_QWERTZ"
                return result

        self.service.inference = Mutating()
        self.flow.analyze()
        self.assertNotEqual("forged", self.flow.checkout["source"]["text"])
        self.assertEqual(
            "UK_QWERTY", self.flow.checkout["conditions"][0]["value"]
        )
        self.assertEqual("REVIEW_REQUIRED", self.flow.checkout["state"])

    def test_claim_checks_original_reservation_and_will_not_redispatch(self):
        saved = []
        original = self.service._dispatch_analysis
        with mock.patch.object(
            self.service,
            "_dispatch_analysis",
            side_effect=lambda r, a: saved.append((r, a)),
        ):
            self.flow.analyze()
        reservation, adapter = saved[0]
        with self.store.transaction() as connection:
            inputs = json.loads(reservation["input_document"])
            inputs["conditions"][0]["value"] = "DE_QWERTZ"
            document = canonical(inputs)
            connection.execute(
                "UPDATE analysis_operations SET input_document = ?, input_hash = ?",
                (document, text_hash(document)),
            )
        original(reservation, adapter)
        self.assertEqual("STALE", self.operations()[0]["status"])
        original(reservation, adapter)
        self.assertEqual("STALE", self.operations()[0]["status"])
        self.assertIsNone(
            self.service.bootstrap(self.flow.sid)["checkout"]["snapshot_hash"]
        )

    def test_timeout_late_result_is_never_attached_and_durable_breaker_remains(
        self,
    ):
        transport = self.use_responses(wait=True, timeout=0.02)
        self.flow.analyze()
        self.assertEqual("MODEL_TIMEOUT", self.flow.checkout["analysis_error"])
        before = self.service.bootstrap(self.flow.sid)
        transport.release.set()
        self.assertTrue(transport.closed.wait(2))
        self.assertEqual("UNKNOWN", self.operations()[0]["status"])
        self.assertEqual(before, self.service.bootstrap(self.flow.sid))
        with self.assertRaises(AppError) as caught:
            self.flow.analyze()
        self.assertEqual("MODEL_BUDGET_EXCEEDED", caught.exception.code)
        self.assertEqual(1, transport.calls)

    def test_real_process_crash_reservation_dispatch_and_observation_never_replay(
        self,
    ):
        self.service.close()
        for checkpoint in (
            "analysis_after_reservation_commit",
            "analysis_after_dispatch_commit",
            "analysis_before_observation_commit",
        ):
            with self.subTest(checkpoint=checkpoint):
                path = Path(self.temp.name) / f"{checkpoint}.sqlite3"
                marker = path.with_suffix(".attempts")
                script = """
import os, sys
from cartreadback_app.responses_adapter import OfflineResponsesAdapter
from cartreadback_app.service import Service
from cartreadback_app.storage import Store
from test_domain import Workflow
from test_analysis_dispatch import budget_for
class Transport:
    def send(self, endpoint, body, *, deadline):
        with open(sys.argv[3], "a") as stream:
            stream.write("attempt\\n")
        raise RuntimeError("authored offline attempt")
class Crash(Service):
    def _checkpoint(self, name, operation_id):
        if name == sys.argv[2]:
            os._exit(73)
adapter = OfflineResponsesAdapter(Transport())
service = Crash(Store(sys.argv[1]), adapter, analysis_budget=budget_for(adapter))
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
                self.assertEqual(
                    73, crashed.returncode, crashed.stderr.decode()
                )
                self.store = Store(path)
                self.service = Service(self.store)
                with closing(self.store.connect()) as connection, connection:
                    sid = connection.execute(
                        "SELECT sid FROM sessions"
                    ).fetchone()[0]
                current = self.service.bootstrap(sid)
                self.assertEqual(
                    "MODEL_OUTCOME_UNKNOWN",
                    current["checkout"]["analysis_error"],
                )
                self.assertIsNone(current["checkout"]["snapshot_hash"])
                self.assertEqual("UNKNOWN", self.operations()[0]["status"])
                with closing(self.store.connect()) as connection, connection:
                    budget = connection.execute(
                        "SELECT * FROM budget_operations"
                    ).fetchone()
                self.assertEqual("UNKNOWN", budget["status"])
                self.assertGreater(budget["reserved_micro_usd"], 0)
                self.assertEqual(
                    1
                    if checkpoint == "analysis_before_observation_commit"
                    else 0,
                    len(marker.read_text().splitlines())
                    if marker.exists()
                    else 0,
                )
                self.service.inference = OfflineResponsesAdapter(
                    AuthoredTransport(self.store)
                )
                with self.assertRaises(AppError) as caught:
                    Workflow(self.service, sid).analyze()
                self.assertEqual("MODEL_BUDGET_EXCEEDED", caught.exception.code)
                self.service.close()
        self.service = Service(self.store)

    def test_stale_success_retains_usage_but_cannot_create_a_snapshot(self):
        transport = self.use_responses(wait=True)
        with ThreadPoolExecutor() as executor:
            pending = executor.submit(self.flow.analyze)
            self.assertTrue(transport.started.wait(2))
            try:
                self.service.inference = FixtureInferenceAdapter()
            finally:
                transport.release.set()
            result = pending.result()
        self.assertEqual("STALE_SNAPSHOT", result["checkout"]["analysis_error"])
        operation = self.operations()[0]
        self.assertEqual("STALE", operation["status"])
        self.assertEqual(
            150, json.loads(operation["observation"])["total_tokens"]
        )
        self.assertIsNone(result["checkout"]["snapshot_hash"])

    def test_mismatched_observation_identity_or_usage_is_unknown(self):
        for field, value in [
            ("conditions_sha256", "forged"),
            ("config_sha256", "forged"),
            ("source_revision", True),
            ("total_tokens", 0),
            ("request_sha256", "0" * 64),
            ("service_tier_requested", "auto"),
            ("service_tier_returned", "priority"),
            ("request_id", ""),
        ]:
            with self.subTest(field=field):
                self.service.close()
                self.store = Store(Path(self.temp.name) / f"{field}.sqlite3")
                self.service = Service(self.store)
                self.flow = Workflow(self.service)
                self.use_responses()
                original = self.service.inference.observe

                def altered(source, conditions, **kwargs):
                    return dataclasses.replace(
                        original(source, conditions, **kwargs), **{field: value}
                    )

                with mock.patch.object(
                    self.service.inference, "observe", side_effect=altered
                ):
                    self.flow.analyze()
                operation = self.operations()[0]
                self.assertEqual("UNKNOWN", operation["status"])
                self.assertEqual("", operation["observation"])
                self.assertIsNone(self.flow.checkout["snapshot_hash"])

    def test_invalid_proposal_never_enters_accounting_ledger_or_other_storage(
        self,
    ):
        marker = "SYNTHETIC_SECRET_MUST_NOT_PERSIST"
        for payload in (marker, canonical([{"extra": marker}]), marker * 3000):
            with self.subTest(payload=payload):
                self.service.close()
                self.store = Store(
                    Path(self.temp.name) / f"invalid-{len(payload)}.sqlite3"
                )
                self.service = Service(self.store)
                self.flow = Workflow(self.service)
                self.use_responses()
                original = self.service.inference.observe

                def invalid(source, conditions, **kwargs):
                    return dataclasses.replace(
                        original(source, conditions, **kwargs),
                        proposal_json=payload,
                    )

                with mock.patch.object(
                    self.service.inference, "observe", side_effect=invalid
                ):
                    self.flow.analyze()
                operation = self.operations()[0]
                self.assertEqual("BLOCKED", operation["status"])
                self.assertEqual("INVALID_PROPOSAL", operation["error_code"])
                accounting = json.loads(operation["observation"])
                self.assertEqual(150, accounting["total_tokens"])
                self.assertNotIn("proposal_json", accounting)
                self.assertNotIn(marker, canonical(self.flow.result))
                self.assertIsNone(self.flow.checkout["snapshot_hash"])
                with closing(self.store.connect()) as connection, connection:
                    for table in (
                        "analysis_operations",
                        "reviews",
                        "sessions",
                        "events",
                    ):
                        for row in connection.execute(f"SELECT * FROM {table}"):
                            self.assertNotIn(marker, canonical(list(row)))
                # Valid usage remains known: the next bounded offline call is allowed.
                self.flow.analyze()
                self.assertEqual("REVIEW_REQUIRED", self.flow.checkout["state"])

    def test_duplicate_claim_dispatches_once_and_checkout_tamper_fails_closed(
        self,
    ):
        saved = []
        original = self.service._dispatch_analysis
        with mock.patch.object(
            self.service,
            "_dispatch_analysis",
            side_effect=lambda r, a: saved.append((r, a)),
        ):
            self.flow.analyze()
        reservation, adapter = saved[0]
        with mock.patch.object(
            adapter, "propose", wraps=adapter.propose
        ) as propose:
            original(reservation, adapter)
            original(reservation, adapter)
            self.assertEqual(1, propose.call_count)
        self.flow = Workflow(self.service, self.flow.sid)
        saved.clear()
        with mock.patch.object(
            self.service,
            "_dispatch_analysis",
            side_effect=lambda r, a: saved.append((r, a)),
        ):
            self.flow.analyze()
        reservation, adapter = saved[0]
        with self.store.transaction() as connection:
            session = self.service._session(connection, self.flow.sid)
            session["checkout"]["amount"]["minor"] = 1
            connection.execute(
                "UPDATE sessions SET checkout = ? WHERE sid = ?",
                (canonical(session["checkout"]), self.flow.sid),
            )
        with mock.patch.object(
            adapter, "propose", wraps=adapter.propose
        ) as propose:
            original(reservation, adapter)
            self.assertEqual(0, propose.call_count)
        self.assertEqual("STALE", self.operations()[-1]["status"])
        self.assertIsNone(
            self.service.bootstrap(self.flow.sid)["checkout"]["snapshot_hash"]
        )

    def test_analysis_policy_rejects_unbounded_or_boolean_attempts(self):
        for limit in (True, 0, 65, 1.5):
            with self.assertRaises(AppError):
                AnalysisPolicy(max_attempts=limit)
