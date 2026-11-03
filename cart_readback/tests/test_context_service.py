"""Fabricated host/HTTPS bridge tests; no credentials, sockets or provider claims."""

import dataclasses
import json
import os
import sqlite3
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

from cartreadback_app.context_capacity import (
    CONTEXT_TOKENS,
    OUTPUT_TOKENS,
    ContextCapacityPolicy,
    ContextClaim,
    ContextReservation,
    HostCapacityAuthorization,
)
from cartreadback_app.context_runtime import (
    ApprovedDataScope,
    ContextAnalysisRuntime,
    CredentialBinding,
    FabricatedTransportBinding,
    InstalledProviderContext,
    ProviderTransportBinding,
    execution_identity,
    host_provenance,
    resolve_installed_context,
)
from cartreadback_app.inference import FixtureInferenceAdapter
from cartreadback_app.payments import DisabledPayPalSandboxAdapter
from cartreadback_app.responses_adapter import Deadline, WireResponse
from cartreadback_app.responses_http import HTTPSRoutingConfig, valid_request_id
from cartreadback_app.service import Service
from cartreadback_app.storage import Store
from cartreadback_app.validation import AppError, canonical, digest, text_hash
from test_domain import Workflow
from test_responses_adapter import envelope
from test_responses_http import SYNTHETIC_TOKEN, FakeConnection, FakeResponse

NOW = 1793721600
CHOICES = [
    {"condition_id": "c1", "kind": "layout", "value": "UK_QWERTY"},
    {"condition_id": "c2", "kind": "included_cable", "value": "USB-C to USB-C"},
]


class FabricatedHandle:
    def __init__(self, binding, store):
        self.binding = binding
        self.store = store
        self.calls = 0

    def borrow(self, *, expected_binding, deadline):
        assert expected_binding == self.binding
        deadline.remaining()
        with self.store.transaction() as connection:
            row = connection.execute(
                "SELECT a.dispatch_token, c.claim_token, a.status, c.status FROM analysis_operations a JOIN context_capacity_operations c ON a.operation_id = c.operation_id ORDER BY a.rowid DESC LIMIT 1"
            ).fetchone()
            assert (
                row
                and row[0] == row[1]
                and row[2:] == ("DISPATCHED", "CLAIMED")
            )
        self.calls += 1
        return SYNTHETIC_TOKEN


def fabricate(store, owners, timeout=20.0, route="direct"):
    with store.connect() as connection:
        products = [
            json.loads(row[0])
            for row in connection.execute("SELECT document FROM catalog")
        ]
    binding = CredentialBinding(
        "org_fabricated_private",
        "proj_fabricated_private",
        "version_test_only",
        "host_test_only",
    )
    scope = ApprovedDataScope(
        tuple(digest(p) for p in products),
        (("layout", "UK_QWERTY"), ("included_cable", "USB-C to USB-C")),
        tuple(text_hash(sid) for sid in owners),
    )
    policy = ContextCapacityPolicy(NOW - 10, NOW + 100)
    route = HTTPSRoutingConfig(route)
    product = next(p for p in products if p["sku_id"] == "KB-UK-C2C")
    body = envelope(
        FixtureInferenceAdapter().propose(product["source"], CHOICES)
    )
    body["usage"]["input_tokens_details"] = {"cached_tokens": 0}
    body["usage"]["output_tokens_details"] = {"reasoning_tokens": 0}
    state = {
        "body": body,
        "calls": 0,
        "events": [],
        "factory": [],
        "hook": None,
        "failure": None,
    }

    def factory(host, port, *, timeout, context):
        state["calls"] += 1
        with store.transaction() as connection:
            row = connection.execute(
                "SELECT a.status, c.status FROM analysis_operations a JOIN context_capacity_operations c ON a.operation_id = c.operation_id ORDER BY a.rowid DESC LIMIT 1"
            ).fetchone()
            assert tuple(row) == ("DISPATCHED", "CLAIMED")
        state["factory"].append((host, port, timeout, context))
        response = FakeResponse(canonical(state["body"]).encode())
        response.headers[-1] = (
            "X-Request-Id",
            state.get("request_id", "req_fabricated"),
        )
        response.read_hook = state["hook"]
        result = FakeConnection(response, state["events"], state["failure"])
        if state.get("factory_hook"):
            state["factory_hook"]()
        return result

    transport = FabricatedTransportBinding(factory)
    auth = HostCapacityAuthorization(
        host_provenance("1" * 64, "2" * 64, "fabricated-offline"),
        digest(dataclasses.asdict(scope)),
        execution_identity(
            binding, route, timeout_seconds=timeout, transport=transport
        ),
        text_hash(policy.identity),
        NOW - 5,
        NOW + 80,
        4,
        4 * CONTEXT_TOKENS,
        4 * OUTPUT_TOKENS,
        1_000_000,
    )
    handle = FabricatedHandle(binding, store)
    installed = InstalledProviderContext(
        binding,
        scope,
        policy,
        auth,
        "1" * 64,
        "2" * 64,
        handle,
        transport,
        route=route,
        timeout_seconds=timeout,
    )
    return ContextAnalysisRuntime(installed), state, handle


class ContextServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "app.sqlite3"
        self.store = Store(self.path)
        self.sid = self.store.session(None)[0]["sid"]
        self.sid2 = self.store.session(None)[0]["sid"]
        self.now = NOW
        self.runtime, self.state, self.handle = fabricate(
            self.store, (self.sid, self.sid2)
        )
        self.service = Service(
            self.store,
            context_analysis=self.runtime,
            clock=lambda: datetime.fromtimestamp(self.now, timezone.utc),
        )
        self.addCleanup(lambda: self.service.close())
        self.flow = Workflow(self.service, self.sid)
        for target in (
            "socket.create_connection",
            "http.client.HTTPSConnection",
        ):
            guard = patch(
                target, side_effect=AssertionError("real sockets prohibited")
            )
            guard.start()
            self.addCleanup(guard.stop)

    def rows(self, table):
        with self.store.connect() as connection:
            return [
                dict(row)
                for row in connection.execute(f"SELECT * FROM {table}")
            ]

    def restart(self, runtime=None):
        self.service.close()
        self.service = Service(
            self.store,
            context_analysis=runtime,
            clock=lambda: datetime.fromtimestamp(self.now, timezone.utc),
        )
        self.flow = Workflow(self.service, self.sid)

    def test_vertical_known_exact_scoped_exchange_and_confirm(self):
        result = self.flow.analyze()
        self.assertEqual(result["mode"], "mixed")
        self.assertEqual(result["checkout"]["state"], "REVIEW_REQUIRED")
        self.assertEqual(
            result["providers"]["analysis"],
            {
                "mode": "genuine-context-capacity",
                "is_fixture": False,
                "dispatch_available": True,
                "execution_kind": "fabricated-offline",
            },
        )
        self.assertFalse(result["providers"]["network_enabled"])
        self.assertEqual(
            result["checkout"]["analysis"],
            {
                "strategy": "context-capacity-v1",
                "dispatch_state": "attempted",
                "accounting_state": "known",
                "usage_observed": True,
                "evidence_kind": "fabricated-offline",
            },
        )
        analysis = self.rows("analysis_operations")[0]
        capacity = self.rows("context_capacity_operations")[0]
        self.assertEqual(analysis["operation_id"], capacity["operation_id"])
        self.assertEqual(analysis["dispatch_token"], capacity["claim_token"])
        self.assertEqual(analysis["status"], "SUCCEEDED")
        self.assertEqual(capacity["status"], "KNOWN")
        self.assertFalse(self.rows("budget_operations"))
        self.assertFalse(self.rows("analysis_preflights"))
        request = next(
            event for event in self.state["events"] if event[0] == "request"
        )
        self.assertEqual(request[1:3], ("POST", "/v1/responses"))
        self.assertEqual(
            text_hash(request[3].decode()),
            json.loads(capacity["reservation"])["request_sha256"],
        )
        self.assertEqual(
            request[4]["OpenAI-Project"], self.runtime.installed.binding.project
        )
        self.assertEqual(
            request[4]["OpenAI-Organization"],
            self.runtime.installed.binding.organization,
        )
        self.assertEqual(self.handle.calls, 1)
        self.flow.confirm()
        for private in (
            "org_fabricated_private",
            "proj_fabricated_private",
            "host_binding_record",
            "pricing_adoption",
            "context_ledger",
            "req_fabricated",
            SYNTHETIC_TOKEN,
        ):
            self.assertNotIn(private, canonical(self.flow.result))
        self.assertNotIn(
            SYNTHETIC_TOKEN, canonical(self.rows("analysis_operations"))
        )
        self.assertNotIn(SYNTHETIC_TOKEN, canonical(self.rows("events")))

    def test_default_missing_context_and_env_labels_do_not_dispatch(self):
        self.restart(ContextAnalysisRuntime())
        with patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "not-a-real-key", "CONTEXT_VERIFIED": "true"},
        ):
            with self.assertRaises(AppError):
                self.flow.analyze()
        self.assertEqual(self.state["calls"], 0)
        self.assertEqual(self.handle.calls, 0)
        self.assertFalse(self.rows("analysis_operations"))
        self.assertEqual(
            self.flow.result["providers"]["analysis"]["execution_kind"],
            "unavailable",
        )
        with self.assertRaises(AppError):
            resolve_installed_context()

    def test_host_constructor_rejects_mismatched_records_and_unscoped_handle(
        self,
    ):
        installed = self.runtime.installed
        for changes in (
            {
                "authorization": dataclasses.replace(
                    installed.authorization, runtime_sha256="a" * 64
                )
            },
            {
                "binding": dataclasses.replace(
                    installed.binding, project="other"
                )
            },
            {"pricing_adoption_record_sha256": "3" * 64},
            {"credential_handle": lambda: SYNTHETIC_TOKEN},
            {"evidence_kind": "provider"},
        ):
            with (
                self.subTest(changes=tuple(changes)),
                self.assertRaises(AppError),
            ):
                dataclasses.replace(installed, **changes)
        self.assertEqual(self.state["calls"], 0)

    def test_changed_handle_version_and_expiry_are_zero_dispatch(self):
        self.handle.binding = dataclasses.replace(
            self.handle.binding, credential_version="rotated"
        )
        with self.assertRaises(AppError):
            self.flow.analyze()
        self.handle.binding = self.runtime.installed.binding
        self.now = NOW + 80
        with self.assertRaises(AppError):
            self.flow.analyze()
        self.assertEqual(self.state["calls"], 0)
        self.assertEqual(self.handle.calls, 0)

    def test_exact_source_owner_condition_scope(self):
        outsider = Workflow(self.service)
        for call in (
            outsider.analyze,
            lambda: self.flow.analyze(layout="US_QWERTY"),
        ):
            with self.assertRaises(AppError):
                call()
        with self.store.connect() as connection:
            product = json.loads(
                connection.execute(
                    "SELECT document FROM catalog WHERE sku = 'KB-UK-C2C'"
                ).fetchone()[0]
            )
        product["source"]["revision"] += 1
        self.store.replace_product(product)
        with self.assertRaises(AppError):
            self.flow.analyze()
        self.assertEqual(self.state["calls"], 0)

    def test_browser_cannot_supply_authority_fields(self):
        for key in (
            "provider",
            "project",
            "credential",
            "authorization",
            "live",
            "rate",
            "ceiling",
        ):
            body = {
                "expected_revision": 0,
                "sku_id": "KB-UK-C2C",
                "conditions": [{"kind": "layout", "value": "UK_QWERTY"}],
                key: True,
            }
            with self.assertRaises(AppError):
                self.service.mutate(self.sid, "analyze", body)
        self.assertEqual(self.state["calls"], 0)

    def test_unsupported_payment_composition_is_blocked(self):
        with self.assertRaises(AppError):
            self.service.payments = DisabledPayPalSandboxAdapter()
        self.assertEqual(self.state["calls"], 0)

    def test_semantic_refusal_incomplete_invalid_keep_known_usage(self):
        variants = [
            lambda b: b["output"][0].update(
                content=[{"type": "refusal", "refusal": "fabricated"}]
            ),
            lambda b: b.update(status="incomplete"),
            lambda b: b["output"][0]["content"][0].update(text="bad json"),
        ]
        for index, alter in enumerate(variants):
            with self.subTest(index=index):
                if index:
                    self.tear_down_new_database(index)
                alter(self.state["body"])
                result = self.flow.analyze()
                self.assertEqual(
                    result["checkout"]["state"], "ANALYSIS_BLOCKED"
                )
                self.assertIsNone(result["checkout"]["snapshot_hash"])
                self.assertEqual(
                    self.rows("context_capacity_operations")[0]["status"],
                    "KNOWN",
                )
                self.assertTrue(
                    result["checkout"]["analysis"]["usage_observed"]
                )

    def tear_down_new_database(self, index, timeout=20.0):
        self.service.close()
        self.path = Path(self.temp.name) / f"case-{index}.sqlite3"
        self.store = Store(self.path)
        self.sid = self.store.session(None)[0]["sid"]
        self.runtime, self.state, self.handle = fabricate(
            self.store, (self.sid,), timeout
        )
        self.service = Service(
            self.store,
            context_analysis=self.runtime,
            clock=lambda: datetime.fromtimestamp(self.now, timezone.utc),
        )
        self.flow = Workflow(self.service, self.sid)

    def test_protocol_fault_marks_unknown_before_supported_accounting(self):
        for index, changes in enumerate(
            (
                {"status": "queued"},
                {"background": True},
                {"tools": [{}]},
                {"tool_usage": {"x": 1}},
                {"output": [{"type": "web_search_call"}]},
            )
        ):
            if index:
                self.tear_down_new_database(index)
            self.state["body"].update(changes)
            with self.store.transaction() as connection:
                connection.execute(
                    "CREATE TRIGGER no_known BEFORE UPDATE OF status ON context_capacity_operations WHEN NEW.status = 'KNOWN' BEGIN SELECT RAISE(ABORT, 'must be UNKNOWN before observe'); END"
                )
            result = self.flow.analyze()
            row = self.rows("context_capacity_operations")[0]
            self.assertEqual(row["status"], "UNKNOWN")
            self.assertTrue(row["observation"])
            self.assertTrue(result["checkout"]["analysis"]["usage_observed"])
            self.assertIsNone(result["checkout"]["snapshot_hash"])

    def test_unsupported_billing_or_missing_usage_keeps_unknown(self):
        for index, alter in enumerate(
            (
                lambda b: b.update(model="other"),
                lambda b: b.update(service_tier="priority"),
                lambda b: b.update(usage=None),
                lambda b: b["usage"]["input_tokens_details"].update(
                    cached_tokens=1
                ),
                lambda b: b["usage"]["output_tokens_details"].update(
                    reasoning_tokens=1
                ),
            )
        ):
            if index:
                self.tear_down_new_database(index)
            alter(self.state["body"])
            self.flow.analyze()
            self.assertEqual(
                self.rows("context_capacity_operations")[0]["status"], "UNKNOWN"
            )
            self.assertFalse(
                self.rows("context_capacity_operations")[0]["observation"]
            )
            self.assertEqual(
                self.flow.checkout["analysis"]["evidence_kind"], "none"
            )

    def test_atomic_reservation_and_claim_failures(self):
        with (
            patch.object(
                self.service,
                "_write_review",
                side_effect=RuntimeError("fabricated local rollback"),
            ),
            self.assertRaises(RuntimeError),
        ):
            self.flow.analyze()
        self.assertFalse(self.rows("analysis_operations"))
        self.assertFalse(self.rows("context_capacity_operations"))
        with self.store.transaction() as connection:
            connection.execute(
                "CREATE TRIGGER fail_claim BEFORE UPDATE OF status ON analysis_operations WHEN NEW.status = 'DISPATCHED' BEGIN SELECT RAISE(ABORT, 'fabricated'); END"
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.flow.analyze()
        self.assertEqual(
            self.rows("analysis_operations")[0]["status"], "RESERVED"
        )
        self.assertEqual(
            self.rows("context_capacity_operations")[0]["status"], "RESERVED"
        )
        self.assertEqual(self.state["calls"], 0)
        self.restart(ContextAnalysisRuntime())
        self.assertEqual(
            self.rows("analysis_operations")[0]["status"], "UNKNOWN"
        )
        self.assertEqual(
            self.rows("context_capacity_operations")[0]["status"], "UNKNOWN"
        )

    def test_stale_claim_commits_unknown_without_network(self):
        def hook(name, _):
            if name == "analysis_after_reservation_commit":
                self.now = NOW + 80

        self.service._checkpoint = hook
        self.flow.analyze()
        self.assertEqual(
            self.rows("context_capacity_operations")[0]["status"], "UNKNOWN"
        )
        self.assertEqual(
            self.rows("analysis_operations")[0]["status"], "UNKNOWN"
        )
        self.assertEqual(self.state["calls"], 0)

    def capture_completed_exchange(self):
        captured = []
        original = self.service.inference.exchange

        def exchange(*args):
            result = original(*args)
            captured.append(result)
            return result

        patched = patch.object(
            self.service.inference, "exchange", side_effect=exchange
        )
        patched.start()
        self.addCleanup(patched.stop)
        return captured

    def test_timeout_late_accounting_keeps_lease_and_never_reopens(self):
        self.tear_down_new_database("late", timeout=1.0)
        captured = self.capture_completed_exchange()
        arrived, release = threading.Event(), threading.Event()

        def hook(name, _):
            if name == "analysis_before_observation_commit":
                arrived.set()
                release.wait(10)

        self.service._checkpoint = hook
        with ThreadPoolExecutor() as pool:
            result = pool.submit(self.flow.analyze)
            self.assertTrue(arrived.wait(2))
            self.assertEqual(len(captured), 1)
            self.assertFalse(captured[0].protocol_fault)
            self.assertIn("usage", json.loads(captured[0].envelope))
            first = result.result(4)
            self.assertEqual(
                first["checkout"]["analysis"]["accounting_state"], "unknown"
            )
            self.assertFalse(first["checkout"]["analysis"]["usage_observed"])
            with self.assertRaises(AppError):
                self.service.close()
            with self.assertRaises(AppError):
                Service(self.store)
            release.set()
        for _ in range(100):
            if not self.service._active:
                break
            time.sleep(0.01)
        final = self.service.bootstrap(self.sid)
        self.assertEqual(final["checkout"]["state"], "ANALYSIS_BLOCKED")
        self.assertEqual(
            final["checkout"]["analysis"]["accounting_state"], "unknown"
        )
        self.assertTrue(final["checkout"]["analysis"]["usage_observed"])
        self.assertIsNone(final["checkout"]["snapshot_hash"])
        self.flow.result = final
        with self.assertRaises(AppError):
            self.flow.analyze()
        self.assertEqual(self.state["calls"], 1)

    def test_policy_replacement_retains_original_late_accounting(self):
        self.tear_down_new_database("replacement", timeout=1.0)
        captured = self.capture_completed_exchange()
        arrived, release = threading.Event(), threading.Event()

        def hook(name, _):
            if name == "analysis_before_observation_commit":
                arrived.set()
                release.wait(10)

        self.service._checkpoint = hook
        with ThreadPoolExecutor() as pool:
            result = pool.submit(self.flow.analyze)
            self.assertTrue(arrived.wait(2))
            self.assertEqual(len(captured), 1)
            self.assertFalse(captured[0].protocol_fault)
            self.assertIn("usage", json.loads(captured[0].envelope))
            result.result(4)
            self.service.context_analysis = ContextAnalysisRuntime()
            release.set()
        for _ in range(100):
            if not self.service._active:
                break
            time.sleep(0.01)
        self.assertTrue(
            self.rows("context_capacity_operations")[0]["observation"]
        )
        self.assertEqual(
            self.rows("context_capacity_operations")[0]["status"], "UNKNOWN"
        )

    def test_orphan_capacity_and_legacy_unknown_block_admission(self):
        self.flow.analyze()
        with self.store.transaction() as connection:
            connection.execute("DELETE FROM analysis_operations")
        other = Workflow(self.service, self.sid2)
        with self.assertRaises(AppError):
            other.analyze()
        self.assertEqual(self.state["calls"], 1)

    def test_migration_and_orphan_owner_recover_without_setup(self):
        def crash(name, _):
            if name == "analysis_after_reservation_commit":
                raise RuntimeError("fabricated interruption")

        self.service._checkpoint = crash
        with self.assertRaises(RuntimeError):
            self.flow.analyze()
        with self.store.transaction() as connection:
            connection.execute(
                "DELETE FROM sessions WHERE sid = ?", (self.sid,)
            )
        self.service.close()
        self.service = Service(self.store)
        self.assertEqual(
            self.rows("analysis_operations")[0]["status"], "UNKNOWN"
        )
        self.assertEqual(
            self.rows("context_capacity_operations")[0]["status"], "UNKNOWN"
        )

    def test_request_id_shared_local_subset(self):
        self.state["request_id"] = "opaque_123-ABC"
        self.flow.analyze()
        self.assertEqual(
            self.rows("context_capacity_operations")[0]["status"], "KNOWN"
        )
        for value in ("req_fabricated", "opaque_123-ABC", "a" * 256):
            self.assertTrue(valid_request_id(value))
        for value in ("", "a" * 257, "Bearer secret", "id\r\n", None):
            self.assertFalse(valid_request_id(value))

    def test_subprocess_crash_recovers_both_without_install(self):
        script = """
import os,sys
sys.path.insert(0,'tests')
from test_context_service import *
patch("socket.create_connection",side_effect=AssertionError("real socket")).start()
patch("http.client.HTTPSConnection",side_effect=AssertionError("real factory")).start()
store=Store(sys.argv[1]); sid=store.session(None)[0]['sid']
runtime,_,_=fabricate(store,(sid,))
service=Service(store,context_analysis=runtime,clock=lambda: datetime.fromtimestamp(NOW,timezone.utc))
def hook(name, operation):
    if name == sys.argv[2]: os._exit(73)
service._checkpoint=hook
Workflow(service,sid).analyze()
"""
        for name in (
            "analysis_after_reservation_commit",
            "analysis_after_dispatch_commit",
            "analysis_before_observation_commit",
        ):
            path = Path(self.temp.name) / (name + ".sqlite3")
            result = subprocess.run(
                [sys.executable, "-c", script, str(path), name],
                capture_output=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 73, result.stderr.decode())
            store = Store(path)
            service = Service(store)
            try:
                with store.connect() as connection:
                    self.assertEqual(
                        connection.execute(
                            "SELECT status FROM analysis_operations"
                        ).fetchone()[0],
                        "UNKNOWN",
                    )
                    self.assertEqual(
                        connection.execute(
                            "SELECT status FROM context_capacity_operations"
                        ).fetchone()[0],
                        "UNKNOWN",
                    )
            finally:
                service.close()

    def test_claim_exact_bytes_and_changed_config_before_connection(self):
        original = self.service._dispatch_context

        def changed(reservation, adapter, prepared):
            return original(
                reservation,
                adapter,
                dataclasses.replace(prepared, request=prepared.request + b" "),
            )

        with patch.object(
            self.service, "_dispatch_context", side_effect=changed
        ):
            self.flow.analyze()
        self.assertEqual(self.state["calls"], 0)
        self.assertEqual(
            self.rows("context_capacity_operations")[0]["status"], "UNKNOWN"
        )
        self.tear_down_new_database("changed-runtime")

        def hook(name, _):
            if name == "analysis_after_dispatch_commit":
                self.service.context_analysis = ContextAnalysisRuntime()

        self.service._checkpoint = hook
        self.flow.analyze()
        self.assertEqual(self.state["calls"], 0)
        self.assertEqual(self.handle.calls, 0)
        self.assertEqual(
            self.rows("context_capacity_operations")[0]["status"], "UNKNOWN"
        )

    def test_full_catalog_source_conditions_and_generation_fences(self):
        for index, mutation in enumerate(
            ("catalog", "source", "conditions", "generation", "owner")
        ):
            if index:
                self.tear_down_new_database("fence-" + mutation)

            def hook(name, _):
                if name != "analysis_after_reservation_commit":
                    return
                with self.store.transaction() as connection:
                    if mutation in {"catalog", "source"}:
                        row = connection.execute(
                            "SELECT document FROM catalog WHERE sku = 'KB-UK-C2C'"
                        ).fetchone()
                        product = json.loads(row[0])
                        if mutation == "catalog":
                            product["price_minor"] += 1
                        else:
                            product["source"]["revision"] += 1
                        connection.execute(
                            "UPDATE catalog SET document = ? WHERE sku = 'KB-UK-C2C'",
                            (canonical(product),),
                        )
                    elif mutation == "conditions":
                        row = connection.execute(
                            "SELECT checkout FROM sessions WHERE sid = ?",
                            (self.sid,),
                        ).fetchone()
                        checkout = json.loads(row[0])
                        checkout["conditions"][0]["value"] = "US_QWERTY"
                        connection.execute(
                            "UPDATE sessions SET checkout = ? WHERE sid = ?",
                            (canonical(checkout), self.sid),
                        )
                    elif mutation == "generation":
                        connection.execute(
                            "UPDATE sessions SET revision = revision + 1 WHERE sid = ?",
                            (self.sid,),
                        )
                    else:
                        connection.execute(
                            "UPDATE analysis_operations SET sid = ?",
                            (self.sid2,),
                        )

            self.service._checkpoint = hook
            self.flow.analyze()
            self.assertEqual(self.state["calls"], 0)
            self.assertEqual(self.handle.calls, 0)
            self.assertEqual(
                self.rows("context_capacity_operations")[0]["status"], "UNKNOWN"
            )

    def test_global_concurrency_and_duplicate_dispatch_are_once(self):
        arrived, release = threading.Event(), threading.Event()

        def read_hook():
            arrived.set()
            release.wait(4)

        self.state["hook"] = read_hook
        with ThreadPoolExecutor() as pool:
            first = pool.submit(self.flow.analyze)
            self.assertTrue(arrived.wait(2))
            other = Workflow(self.service, self.sid2)
            with self.assertRaises(AppError):
                other.analyze()
            release.set()
            first.result(3)
        self.assertEqual(self.state["calls"], 1)
        reservation = self.rows("analysis_operations")[0]
        prepared = self.service.inference.prepare(
            self.flow.checkout["source"], self.flow.checkout["conditions"]
        )
        self.service._dispatch_context(
            reservation, self.service.inference, prepared
        )
        self.assertEqual(self.state["calls"], 1)

    def test_provider_ids_replay_retains_full_capacity_unknown(self):
        self.flow.analyze()
        self.flow.analyze()
        rows = self.rows("context_capacity_operations")
        self.assertEqual([row["status"] for row in rows], ["KNOWN", "UNKNOWN"])
        self.assertEqual(
            json.loads(rows[1]["reservation"])["input_tokens"], CONTEXT_TOKENS
        )
        self.assertFalse(rows[1]["observation"])
        self.assertEqual(self.flow.checkout["state"], "ANALYSIS_BLOCKED")
        with self.assertRaises(AppError):
            self.flow.analyze()
        self.assertEqual(self.state["calls"], 2)

    def test_protocol_frame_fault_retains_supported_usage_unknown(self):
        original = self.service.inference.exchange

        def faulty(*args):
            return dataclasses.replace(original(*args), protocol_fault=True)

        with patch.object(
            self.service.inference, "exchange", side_effect=faulty
        ):
            self.flow.analyze()
        row = self.rows("context_capacity_operations")[0]
        self.assertEqual(row["status"], "UNKNOWN")
        self.assertTrue(row["observation"])

    def test_wrong_exchange_cannot_account_or_attach_other_operation(self):
        original = self.service.inference.exchange
        for index, changes in enumerate(
            (
                {"operation_id": "different"},
                {"claim_token": "different"},
                {"request_sha256": "a" * 64},
                {"runtime_sha256": "a" * 64},
                {"evidence_kind": "provider"},
            )
        ):
            if index:
                self.tear_down_new_database("wrong-" + str(index))
                original = self.service.inference.exchange
            with patch.object(
                self.service.inference,
                "exchange",
                side_effect=lambda *args: dataclasses.replace(
                    original(*args), **changes
                ),
            ):
                self.flow.analyze()
            self.assertEqual(
                self.rows("context_capacity_operations")[0]["status"], "UNKNOWN"
            )
            self.assertFalse(
                self.rows("context_capacity_operations")[0]["observation"]
            )
            self.assertIsNone(self.flow.checkout["snapshot_hash"])

    def test_observation_rollback_keeps_both_ledgers_unknown(self):
        with self.store.transaction() as connection:
            connection.execute(
                "CREATE TRIGGER fail_success BEFORE UPDATE OF status ON analysis_operations WHEN NEW.status = 'SUCCEEDED' BEGIN SELECT RAISE(ABORT, 'fabricated'); END"
            )
        self.flow.analyze()
        self.assertEqual(
            self.rows("analysis_operations")[0]["status"], "UNKNOWN"
        )
        row = self.rows("context_capacity_operations")[0]
        self.assertEqual(row["status"], "UNKNOWN")
        self.assertFalse(row["observation"])
        self.assertIsNone(self.flow.checkout["snapshot_hash"])

    def test_semantic_parse_deadline_expiry_retains_late_usage_unknown(self):
        self.tear_down_new_database("parse-late", timeout=0.08)
        original = self.service.inference.classify

        def classify(*args):
            time.sleep(0.12)
            return original(*args)

        with patch.object(
            self.service.inference, "classify", side_effect=classify
        ):
            self.flow.analyze()
        self.assertEqual(
            self.rows("context_capacity_operations")[0]["status"], "UNKNOWN"
        )
        self.assertTrue(
            self.rows("context_capacity_operations")[0]["observation"]
        )
        self.assertIsNone(self.flow.checkout["snapshot_hash"])

    def test_unknown_cannot_be_hidden_by_fixture_strategy_restart(self):
        self.state["body"]["usage"] = None
        self.flow.analyze()
        self.restart()
        self.assertTrue(self.flow.checkout["stale"])
        self.assertEqual(
            self.flow.checkout["analysis"]["accounting_state"], "unknown"
        )
        with self.assertRaises(AppError):
            self.flow.analyze()
        self.assertEqual(len(self.rows("analysis_operations")), 1)

    def test_legacy_classification_and_unclassified_history_block(self):
        self.restart()
        self.flow.analyze()
        with self.store.transaction() as connection:
            connection.execute("UPDATE analysis_operations SET strategy = ''")
        self.restart(self.runtime)
        self.assertEqual(
            self.rows("analysis_operations")[0]["strategy"], "fixture"
        )
        self.flow.analyze()
        self.assertEqual(self.state["calls"], 1)
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE analysis_operations SET strategy = 'unsupported-legacy' WHERE is_fixture = 1"
            )
        with self.assertRaises(AppError):
            self.flow.analyze()
        self.assertEqual(self.state["calls"], 1)

    def test_orphan_preflight_recovery_does_not_roll_back_context(self):
        def crash(name, _):
            if name == "analysis_after_reservation_commit":
                raise RuntimeError("fabricated interruption")

        self.service._checkpoint = crash
        with self.assertRaises(RuntimeError):
            self.flow.analyze()
        with self.store.transaction() as connection:
            connection.execute(
                "INSERT INTO analysis_preflights(preflight_id,sid,input_document,input_hash,status,created_at) VALUES ('orphan','missing','invalid','invalid','COUNTING','test')"
            )
        self.restart(ContextAnalysisRuntime())
        self.assertEqual(
            self.rows("context_capacity_operations")[0]["status"], "UNKNOWN"
        )
        self.assertEqual(
            self.rows("analysis_preflights")[0]["status"], "UNKNOWN"
        )

    def test_explicit_proxy_route_and_tls_policy_only_fake_connections(self):
        self.service.close()
        self.runtime, self.state, self.handle = fabricate(
            self.store, (self.sid,), route="pythonanywhere"
        )
        self.service = Service(
            self.store,
            context_analysis=self.runtime,
            clock=lambda: datetime.fromtimestamp(self.now, timezone.utc),
        )
        self.flow = Workflow(self.service, self.sid)
        self.flow.analyze()
        host, port, _, context = self.state["factory"][0]
        self.assertEqual((host, port), ("proxy.server", 3128))
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, 2)
        self.assertIn(
            ("tunnel", "api.openai.com", 443, {}), self.state["events"]
        )
        self.assertEqual(self.state["calls"], 1)

    def test_fractional_wall_deadline_never_grants_the_floored_second(self):
        self.now = NOW + 0.75
        claim = ContextClaim(
            ContextReservation("unused", "a" * 64, "b" * 64, "c" * 64, 1, 1, 1),
            "token",
            NOW + 1,
        )
        before = time.monotonic()
        deadline = self.service.inference.deadline(claim)
        self.assertLessEqual(deadline.expires_at - before, 0.28)
        self.now = NOW + 1.001
        with self.assertRaises(AppError):
            self.service.inference.deadline(claim)

    def test_binding_type_precedes_any_custom_equality(self):
        class PretendBinding:
            def __eq__(self, other):
                return True

            def __ne__(self, other):
                return False

        self.handle.binding = PretendBinding()
        self.assertFalse(self.runtime.available(NOW))
        with self.assertRaises(AppError):
            self.flow.analyze()
        self.assertEqual(self.state["calls"], 0)
        self.assertEqual(self.handle.calls, 0)

    def test_binding_property_fault_is_sanitized(self):
        class BrokenHandle:
            @property
            def binding(self):
                raise RuntimeError("private host detail must not escape")

            def borrow(self, **kwargs):
                raise AssertionError("must not borrow")

        with self.assertRaises(AppError) as caught:
            dataclasses.replace(
                self.runtime.installed, credential_handle=BrokenHandle()
            )
        self.assertNotIn("private host detail", str(caught.exception))

    def test_observed_runtime_versions_invalidate_original_authority(self):
        original = self.runtime.installed.execution_sha256
        for target, value in (
            ("sys.version_info", (3, 99, 7, "final", 0)),
            ("ssl.OPENSSL_VERSION_INFO", (9, 9, 9, 9, 9)),
            ("sys.version", "fabricated different build"),
            ("ssl.OPENSSL_VERSION", "fabricated different TLS build"),
        ):
            with self.subTest(target=target), patch(target, value):
                self.assertNotEqual(
                    self.runtime.installed.execution_sha256, original
                )
                self.assertFalse(self.runtime.available(NOW))
                with self.assertRaises(AppError):
                    self.flow.analyze()
        self.assertEqual(self.state["calls"], 0)
        self.assertEqual(self.handle.calls, 0)

    def test_unrelated_factory_denies_authority_and_stales_review(self):
        self.flow.analyze()
        calls = self.state["calls"]

        def unrelated(*args, **kwargs):
            raise AssertionError("replacement must not execute")

        runtime = ContextAnalysisRuntime(self.runtime.installed, unrelated)
        self.assertFalse(runtime.available(NOW))
        self.restart(runtime)
        view = self.service.bootstrap(self.sid)
        self.assertTrue(view["checkout"]["stale"])
        self.assertFalse(view["providers"]["analysis"]["dispatch_available"])
        self.assertEqual(self.state["calls"], calls)
        self.assertEqual(len(self.rows("context_capacity_operations")), 1)

    def test_nested_fake_factory_replacement_changes_generation_and_authority(
        self,
    ):
        installed = self.runtime.installed
        original = installed.transport

        def unrelated(*args, **kwargs):
            raise AssertionError("replacement must not execute")

        for replacement in (
            dataclasses.replace(original, factory=unrelated),
            dataclasses.replace(original),
            FabricatedTransportBinding(original.factory),
        ):
            with self.subTest(generation=replacement.installation_generation):
                self.assertNotEqual(
                    replacement.installation_generation,
                    original.installation_generation,
                )
                with self.assertRaises(AppError):
                    dataclasses.replace(installed, transport=replacement)
        with self.assertRaises((TypeError, ValueError)):
            dataclasses.replace(
                original,
                installation_generation=original.installation_generation,
            )
        self.assertEqual(self.state["calls"], 0)

    def test_new_fake_transport_authority_stales_old_review_without_replay(
        self,
    ):
        self.flow.analyze()
        installed = self.runtime.installed

        def unrelated(*args, **kwargs):
            raise AssertionError("bootstrap must not execute replacement")

        transport = dataclasses.replace(installed.transport, factory=unrelated)
        authorization = dataclasses.replace(
            installed.authorization,
            runtime_sha256=execution_identity(
                installed.binding,
                installed.route,
                installed.response_language,
                installed.timeout_seconds,
                transport=transport,
            ),
        )
        replacement = dataclasses.replace(
            installed, transport=transport, authorization=authorization
        )
        runtime = ContextAnalysisRuntime(replacement)
        self.assertTrue(runtime.available(NOW))
        self.restart(runtime)
        view = self.service.bootstrap(self.sid)
        self.assertTrue(view["checkout"]["stale"])
        self.assertEqual(
            view["checkout"]["analysis"]["accounting_state"], "known"
        )
        self.assertEqual(self.state["calls"], 1)
        self.assertEqual(len(self.rows("context_capacity_operations")), 1)

    def test_same_installed_transport_survives_service_restart(self):
        result = self.flow.analyze()
        self.restart(ContextAnalysisRuntime(self.runtime.installed))
        view = self.service.bootstrap(self.sid)
        self.assertNotIn("stale", view["checkout"])
        self.assertEqual(
            view["checkout"]["snapshot_hash"],
            result["checkout"]["snapshot_hash"],
        )
        self.assertEqual(self.state["calls"], 1)

    def test_fake_transport_cannot_claim_provider_evidence(self):
        installed = self.runtime.installed
        authorization = dataclasses.replace(
            installed.authorization,
            provenance_sha256=host_provenance("1" * 64, "2" * 64, "provider"),
        )
        with self.assertRaises(AppError):
            dataclasses.replace(
                installed, evidence_kind="provider", authorization=authorization
            )
        self.assertEqual(self.handle.calls, 0)
        self.assertEqual(self.state["calls"], 0)

    def test_provider_binding_has_only_fixed_unselected_mechanics(self):
        from cartreadback_app.responses_http import unselected_stdlib_connection

        transport = ProviderTransportBinding(
            "fabricated_revision_no_live_authority"
        )
        self.assertIs(transport.factory, unselected_stdlib_connection)
        self.assertEqual(transport.metadata["kind"], "provider")
        with self.assertRaises(TypeError):
            ProviderTransportBinding("revision", factory=lambda: None)
        with self.assertRaises(TypeError):
            dataclasses.replace(transport, factory=lambda: None)
        with self.assertRaises(AppError):
            ProviderTransportBinding("invalid revision")
        self.assertNotEqual(
            transport.metadata,
            dataclasses.replace(
                transport, installation_revision="different"
            ).metadata,
        )
        self.assertEqual(self.state["calls"], 0)
        self.assertEqual(self.handle.calls, 0)

    def test_observed_transport_source_change_invalidates_authority(self):
        with patch(
            "cartreadback_app.context_runtime._transport_source_sha256",
            return_value="9" * 64,
        ):
            self.assertFalse(self.runtime.available(NOW))
            with self.assertRaises(AppError):
                self.flow.analyze()
        self.assertEqual(self.state["calls"], 0)
        self.assertEqual(self.handle.calls, 0)

    def test_approval_expiry_during_connection_prevents_credential_borrow(self):
        installed = dataclasses.replace(
            self.runtime.installed,
            authorization=dataclasses.replace(
                self.runtime.installed.authorization, expires_at=NOW + 1
            ),
        )
        self.state["factory_hook"] = lambda: setattr(self, "now", NOW + 1.01)
        self.restart(ContextAnalysisRuntime(installed))
        self.now = NOW + 0.75
        self.flow.analyze()
        self.assertEqual(self.state["calls"], 1)
        self.assertEqual(self.handle.calls, 0)
        self.assertEqual(
            self.rows("context_capacity_operations")[0]["status"], "UNKNOWN"
        )

    def test_forward_wall_clock_past_claim_denies_borrow_and_post(self):
        self.state["factory_hook"] = lambda: setattr(self, "now", NOW + 21.25)
        self.flow.analyze()
        self.assertLess(
            self.now, self.runtime.installed.authorization.expires_at
        )
        self.assertEqual(self.state["calls"], 1)
        self.assertEqual(self.handle.calls, 0)
        self.assertFalse(
            any(event[0] == "request" for event in self.state["events"])
        )
        self.assertEqual(
            self.rows("context_capacity_operations")[0]["status"], "UNKNOWN"
        )

    def test_forward_wall_clock_after_borrow_denies_post(self):
        original = self.handle.borrow

        def shifted(**kwargs):
            token = original(**kwargs)
            self.now = NOW + 21.25
            return token

        with patch.object(self.handle, "borrow", side_effect=shifted):
            self.flow.analyze()
        self.assertEqual(self.state["calls"], 1)
        self.assertEqual(self.handle.calls, 1)
        self.assertFalse(
            any(event[0] == "request" for event in self.state["events"])
        )
        self.assertEqual(
            self.rows("context_capacity_operations")[0]["status"], "UNKNOWN"
        )

    def test_backward_wall_clock_does_not_extend_monotonic_deadline(self):
        with self.store.connect() as connection:
            product = json.loads(
                connection.execute(
                    "SELECT document FROM catalog WHERE sku = 'KB-UK-C2C'"
                ).fetchone()[0]
            )
        adapter = self.service.inference
        prepared = adapter.prepare(product["source"], CHOICES)
        claim = ContextClaim(
            ContextReservation(
                "test", prepared.request_sha256, "b" * 64, "c" * 64, 1, 1, 1
            ),
            "token",
            NOW + 20,
        )
        limit = Deadline(time.monotonic() + 0.1, 3.0, 12.0)
        self.now = NOW - 1
        observed = []

        def send(endpoint, body, *, deadline):
            observed.append(deadline.expires_at)
            return WireResponse(
                200, "req_fabricated", [canonical(self.state["body"]).encode()]
            )

        with patch(
            "cartreadback_app.genuine_responses.ScopedHTTPSTransport.send",
            side_effect=send,
        ):
            result = adapter.exchange(prepared, claim, limit)
        self.assertFalse(result.protocol_fault)
        self.assertLessEqual(observed[0], limit.expires_at)
        self.assertEqual(self.handle.calls, 0)


if __name__ == "__main__":
    unittest.main()
