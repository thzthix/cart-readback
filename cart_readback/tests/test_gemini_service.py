"""Fabricated end-to-end Gemini Service tests; no keys, sockets or billing proof."""

import dataclasses
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from cartreadback_app.gemini_capacity import (
    MAX_INPUT_TOKENS,
    OUTPUT_TOKENS,
    GeminiCapacityPolicy,
    HostGeminiAuthorization,
    initialize_gemini_database,
)
from cartreadback_app.gemini_client import CURRENT_MODEL, MODEL, GeminiConfig
from cartreadback_app.gemini_runtime import (
    ApprovedDataScope,
    CredentialBinding,
    FabricatedTransportBinding,
    GeminiAnalysisRuntime,
    InstalledGeminiContext,
    execution_identity,
    host_provenance,
)
from cartreadback_app.inference import FixtureInferenceAdapter
from cartreadback_app.payments import FixturePaymentAdapter
from cartreadback_app.service import Service
from cartreadback_app.storage import Store, product_for
from cartreadback_app.validation import AppError, canonical, digest, text_hash
from test_domain import Workflow
from test_gemini_client import envelope
from test_responses_http import FakeConnection, FakeResponse

NOW = 1793721600
CHOICES = [
    {"condition_id": "c1", "kind": "layout", "value": "UK_QWERTY"},
    {"condition_id": "c2", "kind": "included_cable", "value": "USB-C to USB-C"},
]


class FabricatedHandle:
    def __init__(self, binding, store, state):
        self.binding, self.store, self.state = binding, store, state
        self.calls = 0

    def borrow(self, *, expected_binding, deadline):
        assert self.binding == expected_binding
        deadline.remaining()
        assert_claimed(self.store)
        self.calls += 1
        if self.state.get("borrow_hook"):
            self.state["borrow_hook"]()
        return "fabricated-gemini-key-not-real"


def assert_claimed(store):
    # Another connection sees the committed paired reservation and claim.
    with store.transaction() as connection:
        row = connection.execute(
            "SELECT a.status, g.status, a.dispatch_token, g.claim_token "
            "FROM analysis_operations a JOIN gemini_capacity_operations g "
            "ON a.operation_id=g.operation_id ORDER BY a.rowid DESC LIMIT 1"
        ).fetchone()
        assert row and tuple(row[:2]) == ("DISPATCHED", "CLAIMED")
        assert row[2] == row[3] and row[2]


def fabricate(store, owners, timeout=20.0, model=MODEL, max_calls=2):
    with store.transaction() as connection:
        database_id = initialize_gemini_database(connection)
        product = product_for(connection, "KB-UK-C2C")
    config = GeminiConfig(expected_model_version=model, model=model)
    binding = CredentialBinding(
        "project_private_fake", "credential_fake_v1", "host_fake_v1"
    )
    scope = ApprovedDataScope(
        (digest(product),),
        (digest(CHOICES),),
        tuple(text_hash(s) for s in owners),
    )
    policy = GeminiCapacityPolicy(
        NOW - 10,
        NOW + 100,
        model,
        model,
        MAX_INPUT_TOKENS,
        300_000,
        2_500_000,
        binding.project,
        "test-tier",
        "3" * 64,
        "2" * 64,
    )
    body = envelope(
        FixtureInferenceAdapter().propose(product["source"], CHOICES)
    )
    body["modelVersion"] = model
    state = {"body": body, "calls": 0, "events": []}

    def factory(host, port, *, timeout, context):
        assert_claimed(store)
        state["calls"] += 1
        raw = state.get("raw", canonical(state["body"]).encode())
        response = FakeResponse(
            raw,
            [
                ("Content-Type", "application/json"),
                ("Content-Length", str(len(raw))),
            ],
        )
        response.read_hook = state.get("read_hook")
        connection = FakeConnection(response, state["events"])
        state["connection"] = connection
        if state.get("close_hook"):
            original = connection.close

            def close():
                state["close_hook"]()
                original()

            connection.close = close
        if state.get("connect_hook"):
            original_connect = connection.connect

            def connect():
                original_connect()
                state["connect_hook"]()

            connection.connect = connect
        if state.get("factory_hook"):
            state["factory_hook"]()
        return connection

    transport = FabricatedTransportBinding(factory)
    auth = HostGeminiAuthorization(
        database_id,
        host_provenance("1" * 64, "2" * 64, "fabricated-offline"),
        digest(dataclasses.asdict(scope)),
        execution_identity(binding, config, timeout, transport=transport),
        text_hash(policy.identity),
        NOW - 5,
        NOW + 80,
        max_calls,
        max_calls * MAX_INPUT_TOKENS,
        max_calls * OUTPUT_TOKENS,
        max_calls * policy.estimate(MAX_INPUT_TOKENS, OUTPUT_TOKENS),
    )
    handle = FabricatedHandle(binding, store, state)
    installed = InstalledGeminiContext(
        binding,
        scope,
        policy,
        auth,
        "1" * 64,
        "2" * 64,
        handle,
        transport,
        config,
        timeout_seconds=timeout,
    )
    return GeminiAnalysisRuntime(installed), state, handle


class GeminiServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "app.sqlite3")
        self.sid = self.store.session(None)[0]["sid"]
        self.other = self.store.session(None)[0]["sid"]
        self.now = NOW
        self.runtime, self.state, self.handle = fabricate(
            self.store, (self.sid,)
        )
        self.service = Service(
            self.store, gemini_analysis=self.runtime, clock=self.clock
        )
        self.addCleanup(lambda: self.service.close())
        self.flow = Workflow(self.service, self.sid)
        for name in ("socket.create_connection", "http.client.HTTPSConnection"):
            guard = patch(
                name, side_effect=AssertionError("real network prohibited")
            )
            guard.start()
            self.addCleanup(guard.stop)

    def clock(self):
        return datetime.fromtimestamp(self.now, timezone.utc)

    def rows(self, table):
        with self.store.connect() as connection:
            return [
                dict(row)
                for row in connection.execute(f"SELECT * FROM {table}")
            ]

    def restart(self, runtime=None):
        self.service.close()
        self.service = Service(
            self.store, gemini_analysis=runtime, clock=self.clock
        )
        self.flow = Workflow(self.service, self.sid)

    def test_review_metadata_private_projection_and_fixture_payment_flow(self):
        result = self.flow.analyze()
        self.assertEqual(result["checkout"]["state"], "REVIEW_REQUIRED")
        self.assertEqual(
            result["providers"]["analysis"]["mode"], "genuine-gemini-capacity"
        )
        self.assertFalse(result["providers"]["network_enabled"])
        self.assertEqual(
            result["checkout"]["analysis"],
            {
                "strategy": "gemini-capacity-v1",
                "dispatch_state": "attempted",
                "accounting_state": "known",
                "usage_observed": True,
                "evidence_kind": "fabricated-offline",
            },
        )
        model = result["checkout"]["model"]
        self.assertEqual(model["provider"], "google-gemini-generate-content")
        self.assertEqual(
            set(model),
            {
                "provider",
                "model_version",
                "prompt_version",
                "adapter_version",
                "validator_version",
                "is_fixture",
                "execution_mode",
                "execution_kind",
            },
        )
        for secret in (
            self.runtime.installed.binding.project,
            self.runtime.installed.authorization.database_id,
            self.runtime.installed.execution_sha256,
        ):
            self.assertNotIn(secret, canonical(result))
        self.flow.confirm()
        self.flow.create()
        self.flow.action("fixture-approve")
        self.flow.action("verify")
        self.flow.action("capture")
        self.assertEqual(self.flow.checkout["state"], "COMPLETED")
        self.assertEqual(self.state["calls"], 1)
        self.assertEqual(self.handle.calls, 1)

    def test_default_ambient_keys_no_selection_or_socket(self):
        self.restart()
        with patch.dict(
            os.environ,
            {
                "GEMINI_API_KEY": "never-read-fake",
                "GOOGLE_API_KEY": "never-read-fake",
            },
        ):
            result = self.flow.analyze()
        self.assertEqual(result["mode"], "fixture")
        self.assertEqual(self.state["calls"], 0)

    def test_exact_payment_type_enforced_on_constructor_and_setter(self):
        class Subclass(FixturePaymentAdapter):
            pass

        with self.assertRaises(AppError):
            self.service.payments = Subclass()
        self.service.close()
        with self.assertRaises(AppError):
            Service(
                self.store, gemini_analysis=self.runtime, payments=Subclass()
            )

    def test_foreign_owner_and_changed_conditions_denied_without_dispatch(self):
        with self.assertRaises(AppError):
            Workflow(self.service, self.other).analyze()
        with self.assertRaises(AppError):
            self.flow.analyze(cable=None)
        self.assertEqual(self.state["calls"], 0)
        self.assertEqual(self.rows("analysis_operations"), [])

    def test_stale_source_before_reservation_denied(self):
        with self.store.transaction() as connection:
            product = product_for(connection, "KB-UK-C2C")
        product["price_minor"] += 1
        self.store.replace_product(product)
        with self.assertRaises(AppError):
            self.flow.analyze()
        self.assertEqual(self.state["calls"], 0)

    def test_expiry_and_changed_binding_deny_before_borrow(self):
        self.now = NOW + 80
        with self.assertRaises(AppError):
            self.flow.analyze()
        self.now = NOW
        self.handle.binding = dataclasses.replace(
            self.handle.binding, credential_version="new"
        )
        with self.assertRaises(AppError):
            self.flow.analyze()
        self.assertEqual(self.state["calls"], 0)

    def test_stale_after_reservation_retains_original_unknown(self):
        def hook(name, _operation):
            if name == "analysis_after_reservation_commit":
                self.handle.binding = dataclasses.replace(
                    self.handle.binding, credential_version="new"
                )

        self.service._checkpoint = hook
        self.flow.analyze()
        self.assertEqual(
            self.rows("analysis_operations")[0]["status"], "UNKNOWN"
        )
        self.assertEqual(
            self.rows("gemini_capacity_operations")[0]["status"], "UNKNOWN"
        )
        self.assertEqual(self.state["calls"], 0)

    def test_per_step_change_after_factory_or_connect_or_borrow_blocks_post(
        self,
    ):
        for step in ("factory_hook", "connect_hook", "borrow_hook"):
            with self.subTest(step=step):
                # New temporary DB per independent authorization scenario.
                with tempfile.TemporaryDirectory() as directory:
                    store = Store(Path(directory) / "scope.sqlite3")
                    sid = store.session(None)[0]["sid"]
                    runtime, state, handle = fabricate(store, (sid,))
                    service = Service(
                        store, gemini_analysis=runtime, clock=self.clock
                    )
                    try:

                        def invalidate():
                            handle.binding = dataclasses.replace(
                                handle.binding, credential_version="changed"
                            )

                        state[step] = invalidate
                        result = Workflow(service, sid).analyze()
                        self.assertEqual(
                            result["checkout"]["analysis"]["accounting_state"],
                            "unknown",
                        )
                        self.assertFalse(
                            any(e[0] == "request" for e in state["events"])
                        )
                    finally:
                        service.close()

    def test_fractional_backward_clock_after_connect_denies_borrow(self):
        self.now = NOW + 0.75
        self.state["connect_hook"] = lambda: setattr(self, "now", NOW + 0.5)
        self.flow.analyze()
        self.assertEqual(self.handle.calls, 0)
        self.assertEqual(
            self.rows("analysis_operations")[0]["status"], "UNKNOWN"
        )

    def test_semantic_failures_keep_independently_known_accounting(self):
        variants = (
            lambda body: body.update(
                candidates=[], promptFeedback={"blockReason": "SAFETY"}
            ),
            lambda body: body["candidates"][0].update(
                finishReason="MAX_TOKENS"
            ),
            lambda body: body["candidates"][0]["content"]["parts"][0].update(
                text="not JSON"
            ),
            lambda body: body["candidates"][0]["content"]["parts"][0].update(
                text=canonical({"results": []})
            ),
        )
        for change in variants:
            with (
                self.subTest(change=change),
                tempfile.TemporaryDirectory() as directory,
            ):
                store = Store(Path(directory) / "semantic.sqlite3")
                sid = store.session(None)[0]["sid"]
                runtime, state, _ = fabricate(store, (sid,))
                change(state["body"])
                service = Service(
                    store, gemini_analysis=runtime, clock=self.clock
                )
                try:
                    result = Workflow(service, sid).analyze()["checkout"]
                    self.assertEqual(result["state"], "ANALYSIS_BLOCKED")
                    self.assertIsNone(result["snapshot_hash"])
                    self.assertEqual(
                        result["analysis"]["accounting_state"], "known"
                    )
                    self.assertTrue(result["analysis"]["usage_observed"])
                finally:
                    service.close()

    def test_invalid_spans_retain_usage_without_snapshot(self):
        proposal = json.loads(
            self.state["body"]["candidates"][0]["content"]["parts"][0]["text"]
        )
        proposal["results"][0]["evidence"][0]["start"] += 1
        self.state["body"]["candidates"][0]["content"]["parts"][0]["text"] = (
            canonical(proposal)
        )
        self.flow.analyze()
        self.assertEqual(self.flow.checkout["state"], "ANALYSIS_BLOCKED")
        self.assertEqual(
            self.flow.checkout["analysis"]["accounting_state"], "known"
        )
        self.assertIsNone(self.flow.checkout["snapshot_hash"])

    def test_contradictory_usage_and_missing_usage_are_unknown(self):
        for missing in (False, True):
            with (
                self.subTest(missing=missing),
                tempfile.TemporaryDirectory() as directory,
            ):
                store = Store(Path(directory) / "usage.sqlite3")
                sid = store.session(None)[0]["sid"]
                runtime, state, _ = fabricate(store, (sid,))
                if missing:
                    state["body"].pop("usageMetadata")
                else:
                    state["body"]["usageMetadata"]["totalTokenCount"] += 1
                service = Service(
                    store, gemini_analysis=runtime, clock=self.clock
                )
                try:
                    checkout = Workflow(service, sid).analyze()["checkout"]
                    self.assertEqual(
                        checkout["analysis"]["accounting_state"], "unknown"
                    )
                    self.assertFalse(checkout["analysis"]["usage_observed"])
                finally:
                    service.close()

    def test_prior_fixture_unknown_blocks_gemini(self):
        self.restart()
        self.flow.analyze()
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE analysis_operations SET status='UNKNOWN'"
            )
        self.restart(self.runtime)
        with self.assertRaises(AppError):
            self.flow.analyze()
        self.assertEqual(self.state["calls"], 0)

    def test_missing_capacity_pair_blocks_fixture_and_gemini(self):
        self.flow.analyze()
        with self.store.transaction() as connection:
            connection.execute("DELETE FROM gemini_capacity_operations")
        self.restart()
        with self.assertRaises(AppError):
            self.flow.analyze()
        self.restart(self.runtime)
        with self.assertRaises(AppError):
            self.flow.analyze()

    def test_wrong_model_and_invalid_usage_unknown(self):
        self.state["body"]["modelVersion"] = "wrong-model"
        self.flow.analyze()
        self.assertEqual(
            self.flow.checkout["analysis"]["accounting_state"], "unknown"
        )
        self.assertFalse(self.flow.checkout["analysis"]["usage_observed"])

    def test_duplicate_response_id_unknown_and_reservations_never_refund(self):
        self.flow.analyze()
        before = self.rows("gemini_capacity_operations")[0]["reservation"]
        self.flow.analyze()
        rows = self.rows("gemini_capacity_operations")
        self.assertEqual(rows[0]["reservation"], before)
        self.assertEqual(rows[1]["status"], "UNKNOWN")
        self.assertEqual(json.loads(before)["input_tokens"], MAX_INPUT_TOKENS)
        self.assertEqual(self.state["calls"], 2)
        with self.assertRaises(AppError):
            self.flow.analyze()

    def test_budget_exhausted_after_restart_cannot_replenish(self):
        self.flow.analyze()
        self.state["body"]["responseId"] = "different_response"
        self.flow.analyze()
        self.restart(self.runtime)
        with self.assertRaises(AppError):
            self.flow.analyze()
        self.assertEqual(self.state["calls"], 2)

    def test_current_model_thoughts_count_toward_output(self):
        self.service.close()
        self.runtime, self.state, self.handle = fabricate(
            self.store, (self.sid,), model=CURRENT_MODEL
        )
        self.state["body"]["usageMetadata"].update(
            thoughtsTokenCount=7, totalTokenCount=127
        )
        self.service = Service(
            self.store, gemini_analysis=self.runtime, clock=self.clock
        )
        self.flow = Workflow(self.service, self.sid)
        self.flow.analyze()
        usage = json.loads(
            self.rows("gemini_capacity_operations")[0]["observation"]
        )
        self.assertEqual(
            (usage["output_tokens"], usage["thought_tokens"]), (27, 7)
        )
        self.assertEqual(self.flow.checkout["state"], "REVIEW_REQUIRED")

    def test_timeout_blocked_cleanup_retains_lease_then_late_usage_unknown(
        self,
    ):
        self.service.close()
        self.runtime, self.state, self.handle = fabricate(
            self.store, (self.sid,), timeout=0.3
        )
        entered, release = threading.Event(), threading.Event()

        def cleanup():
            entered.set()
            release.wait(3)

        self.state["close_hook"] = cleanup
        self.service = Service(
            self.store, gemini_analysis=self.runtime, clock=self.clock
        )
        self.flow = Workflow(self.service, self.sid)
        try:
            self.flow.analyze()
            self.assertTrue(entered.is_set())
            self.assertEqual(
                self.flow.checkout["analysis"]["accounting_state"], "unknown"
            )
            with self.assertRaises(AppError):
                self.service.close()
            with self.assertRaises(AppError):
                Service(Store(self.store.path))
        finally:
            release.set()
            for _ in range(200):
                if self.service._active == 0:
                    break
                time.sleep(0.01)
        checkout = self.service.bootstrap(self.sid)["checkout"]
        self.assertEqual(checkout["analysis"]["accounting_state"], "unknown")
        self.assertTrue(checkout["analysis"]["usage_observed"])
        self.assertIsNone(checkout["snapshot_hash"])
        self.assertIsNone(checkout["confirmation_id"])

    def test_unknown_blocks_fixture_otherowner_and_context(self):
        self.state["raw"] = b"not-json"
        self.flow.analyze()
        self.restart()
        for sid in (self.sid, self.other):
            with self.assertRaises(AppError):
                Workflow(self.service, sid).analyze()
        from test_context_service import fabricate as context_runtime

        runtime, state, _ = context_runtime(self.store, (self.sid,))
        self.service.close()
        self.service = Service(
            self.store, context_analysis=runtime, clock=self.clock
        )
        with self.assertRaises(AppError):
            Workflow(self.service, self.sid).analyze()
        self.assertEqual(state["calls"], 0)

    def test_prior_context_unknown_blocks_gemini(self):
        from test_context_service import fabricate as context_runtime

        self.service.close()
        runtime, state, _ = context_runtime(self.store, (self.sid,))
        state["body"].pop("usage")
        self.service = Service(
            self.store, context_analysis=runtime, clock=self.clock
        )
        Workflow(self.service, self.sid).analyze()
        self.restart(self.runtime)
        with self.assertRaises(AppError):
            self.flow.analyze()
        self.assertEqual(self.state["calls"], 0)

    def test_orphan_pairings_fail_closed_both_directions(self):
        self.flow.analyze()
        with self.store.transaction() as connection:
            connection.execute("DELETE FROM analysis_operations")
        self.restart()
        with self.assertRaises(AppError):
            self.flow.analyze()
        self.restart(self.runtime)
        with self.assertRaises(AppError):
            self.flow.analyze()
        self.assertEqual(self.state["calls"], 1)

    def test_second_service_and_concurrent_attempt_do_not_duplicate(self):
        with self.assertRaises(AppError):
            Service(Store(self.store.path), gemini_analysis=self.runtime)

        def analyze():
            try:
                return self.service.mutate(
                    self.sid,
                    "analyze",
                    {
                        "expected_revision": 0,
                        "sku_id": "KB-UK-C2C",
                        "conditions": [
                            {"kind": c["kind"], "value": c["value"]}
                            for c in CHOICES
                        ],
                    },
                )
            except AppError:
                return None

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: analyze(), range(4)))
        self.assertEqual(sum(r is not None for r in results), 1)
        self.assertEqual(self.state["calls"], 1)

    def test_stale_runtime_clears_confirmable_projection(self):
        self.flow.analyze()
        self.service.gemini_analysis = GeminiAnalysisRuntime()
        checkout = self.service.bootstrap(self.sid)["checkout"]
        self.assertTrue(checkout["stale"])
        self.assertIsNone(checkout["confirmation_id"])
        with self.assertRaises(AppError):
            self.flow.confirm()

    def test_crash_recovery_same_original_operation_no_post_replay(self):
        script = """
import os,sys
sys.path.insert(0,'tests')
from test_gemini_service import *
patch('socket.create_connection',side_effect=AssertionError('no real socket')).start()
patch('http.client.HTTPSConnection',side_effect=AssertionError('no real TLS')).start()
store=Store(sys.argv[1]);sid=store.session(None)[0]['sid']
runtime,state,handle=fabricate(store,(sid,))
service=Service(store,gemini_analysis=runtime,clock=lambda:datetime.fromtimestamp(NOW,timezone.utc))
def hook(name,operation):
    if name == sys.argv[2]: os._exit(73)
service._checkpoint=hook
Workflow(service,sid).analyze()
"""
        for checkpoint in (
            "analysis_after_reservation_commit",
            "analysis_after_dispatch_commit",
            "analysis_before_observation_commit",
        ):
            with self.subTest(checkpoint=checkpoint):
                path = Path(self.temp.name) / (checkpoint + ".sqlite3")
                result = subprocess.run(
                    [sys.executable, "-c", script, str(path), checkpoint],
                    capture_output=True,
                    timeout=10,
                )
                self.assertEqual(result.returncode, 73, result.stderr.decode())
                store = Store(path)
                service = Service(store)
                try:
                    with store.connect() as connection:
                        row = connection.execute(
                            "SELECT a.operation_id,a.status,g.status FROM analysis_operations a JOIN gemini_capacity_operations g ON a.operation_id=g.operation_id"
                        ).fetchone()
                        self.assertEqual(tuple(row[1:]), ("UNKNOWN", "UNKNOWN"))
                        sid = connection.execute(
                            "SELECT sid FROM sessions"
                        ).fetchone()[0]
                    with self.assertRaises(AppError):
                        Workflow(service, sid).analyze()
                    self.assertEqual(
                        service.bootstrap(sid)["checkout"]["analysis"][
                            "accounting_state"
                        ],
                        "unknown",
                    )
                finally:
                    service.close()


if __name__ == "__main__":
    unittest.main()
