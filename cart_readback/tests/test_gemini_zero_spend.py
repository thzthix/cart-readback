"""Synthetic free-tier admission tests, never Google/account/consent evidence."""

import copy
import dataclasses
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import test_gemini_service as service_tests
from cartreadback_app.gemini_capacity import (
    FREE_MODE,
    MAX_INPUT_TOKENS,
    OUTPUT_TOKENS,
    PAID_MODE,
    TransactionGeminiCapacityLedger,
    charge_micro_usd,
    gemini_ledger_from_document,
    initialize_gemini_database,
    parse_accounting,
    recover_gemini_capacity,
)
from cartreadback_app.gemini_client import CURRENT_MODEL, MODEL, GeminiConfig
from cartreadback_app.gemini_runtime import (
    GeminiAnalysisRuntime,
    execution_identity,
    host_provenance,
)
from cartreadback_app.storage import Store
from cartreadback_app.validation import AppError, canonical, digest
from test_gemini_capacity import (
    CONDITIONS,
    NOW,
    SOURCE,
    authorization,
    envelope,
    fence,
    policy,
)
from test_gemini_runner import plan, runner
from test_gemini_runtime import installed


def free_policy(**changes):
    return policy(
        **(
            {
                "admission_mode": FREE_MODE,
                "tier": "free",
                "input_rate_micro_usd_per_million": 0,
                "output_rate_micro_usd_per_million": 0,
            }
            | changes
        )
    )


def free_plan():
    value = plan()
    value["policy"].update(
        admission_mode=FREE_MODE,
        tier="free",
        input_rate_micro_usd_per_million=0,
        output_rate_micro_usd_per_million=0,
    )
    value["limits"].update(admission_mode=FREE_MODE, max_micro_usd=0)
    return value


class ZeroSpendValidationTests(unittest.TestCase):
    def test_free_rates_require_explicit_mode_tier_and_external_records(self):
        for model in (MODEL, CURRENT_MODEL):
            selected = free_policy(model=model, expected_model_version=model)
            self.assertEqual(
                selected.estimate(MAX_INPUT_TOKENS, OUTPUT_TOKENS), 0
            )
            self.assertEqual(selected.estimate(0, 0), 0)
            self.assertIn('"version":"gemini-capacity-v2"', selected.identity)
        for changes in (
            {"admission_mode": PAID_MODE},
            {"admission_mode": "free"},
            {"admission_mode": True},
            {"tier": "paid"},
            {"tier": "Free"},
            {"tier": "unknown"},
            {"model": "unsupported"},
            {"eligibility_record_sha256": ""},
            {"pricing_record_sha256": ""},
            {"host_decision_record_sha256": ""},
            {"host_decision_record_sha256": True},
        ):
            with self.subTest(changes=changes), self.assertRaises(AppError):
                free_policy(**changes)
        for field in (
            "input_rate_micro_usd_per_million",
            "output_rate_micro_usd_per_million",
        ):
            for invalid in (-1, True, False, 0.0, 1, 1_000_000, None):
                with self.subTest(field=field, invalid=invalid):
                    with self.assertRaises(AppError):
                        free_policy(**{field: invalid})
        with self.assertRaises(AppError):
            free_policy(
                input_rate_micro_usd_per_million=1,
                output_rate_micro_usd_per_million=1,
            )
        for tokens in (-1, True, MAX_INPUT_TOKENS + 1):
            with self.assertRaises(AppError):
                free_policy().estimate(tokens, 1)
        with self.assertRaises(AppError):
            free_policy().estimate(1, OUTPUT_TOKENS + 1)

    def test_paid_rates_and_allowances_still_positive(self):
        adopted = policy()
        self.assertGreater(adopted.estimate(MAX_INPUT_TOKENS, OUTPUT_TOKENS), 0)
        self.assertEqual(charge_micro_usd(1, 1), 1)
        for bad in (0, -1, True, False, 0.0):
            with self.assertRaises(AppError):
                charge_micro_usd(1, bad)
            for field in (
                "input_rate_micro_usd_per_million",
                "output_rate_micro_usd_per_million",
            ):
                with self.assertRaises(AppError):
                    policy(**{field: bad})
            with self.assertRaises(AppError):
                authorization(adopted, "a" * 64, max_micro_usd=bad)
        with self.assertRaises(AppError):
            policy(tier="free")

    def test_free_zero_is_exact_but_call_and_token_bounds_stay_positive(self):
        adopted = free_policy()
        self.assertEqual(
            authorization(adopted, "a" * 64, max_micro_usd=0).max_micro_usd, 0
        )
        for invalid in (1, -1, True, False, 0.0, None):
            with self.assertRaises(AppError):
                authorization(adopted, "a" * 64, max_micro_usd=invalid)
        for field in (
            "max_calls",
            "max_total_input_tokens",
            "max_total_output_tokens",
        ):
            for invalid in (0, -1, True, False, 1.0):
                with self.subTest(field=field, invalid=invalid):
                    with self.assertRaises(AppError):
                        authorization(
                            adopted,
                            "a" * 64,
                            max_micro_usd=0,
                            **{field: invalid},
                        )

    def test_mode_and_all_external_policy_facts_stale_runtime_and_provenance(
        self,
    ):
        host = installed()
        adopted = host.policy
        base_runtime = host.execution_sha256
        base_provenance = host.authorization.provenance_sha256
        variants = (
            free_policy(),
            dataclasses.replace(adopted, project="different"),
            dataclasses.replace(
                adopted, model=MODEL, expected_model_version=MODEL
            ),
            dataclasses.replace(
                adopted, expected_model_version=CURRENT_MODEL + "-001"
            ),
            dataclasses.replace(adopted, eligibility_record_sha256="a" * 64),
            dataclasses.replace(adopted, pricing_record_sha256="a" * 64),
            dataclasses.replace(adopted, host_decision_record_sha256="a" * 64),
            dataclasses.replace(adopted, valid_from=NOW - 9),
            dataclasses.replace(adopted, expires_at=NOW + 99),
        )
        for changed in variants:
            with self.subTest(changed=changed):
                binding = dataclasses.replace(
                    host.binding, project=changed.project
                )
                config = GeminiConfig(
                    changed.expected_model_version, model=changed.model
                )
                self.assertNotEqual(
                    execution_identity(
                        binding,
                        config,
                        transport=host.transport,
                        policy=changed,
                    ),
                    base_runtime,
                )
                self.assertNotEqual(
                    host_provenance(
                        host.binding_record_sha256,
                        changed.pricing_record_sha256,
                        host.evidence_kind,
                        policy=changed,
                    ),
                    base_provenance,
                )
                with self.assertRaises(AppError):
                    dataclasses.replace(host, policy=changed)
        mismatched = dataclasses.replace(
            host.authorization, admission_mode=FREE_MODE, max_micro_usd=0
        )
        with self.assertRaises(AppError):
            dataclasses.replace(host, authorization=mismatched)
        self.assertFalse(host.credential_handle.borrowed)


class ZeroSpendLedgerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = Store(Path(temporary.name) / "synthetic.sqlite3")
        with self.store.transaction() as connection:
            self.database_id = initialize_gemini_database(connection)
        self.policy = free_policy()
        self.auth = authorization(
            self.policy, self.database_id, max_micro_usd=0
        )
        from cartreadback_app.gemini_client import GeminiClient

        self.request = (
            GeminiClient(GeminiConfig(CURRENT_MODEL, model=CURRENT_MODEL))
            .prepare(SOURCE, CONDITIONS)
            .body
        )

    def ledger(self, connection, policy=None, auth=None):
        return TransactionGeminiCapacityLedger(
            connection, policy or self.policy, auth or self.auth
        )

    def test_zero_spend_consumes_full_call_input_output_even_with_tiny_usage(
        self,
    ):
        for generation in (1, 2):
            with self.store.transaction() as connection:
                ledger = self.ledger(connection)
                reservation = ledger.reserve(
                    self.request, fence(generation), now=NOW
                )
                self.assertEqual(reservation.reserved_micro_usd, 0)
                self.assertEqual(reservation.input_tokens, MAX_INPUT_TOKENS)
                self.assertEqual(reservation.output_tokens, OUTPUT_TOKENS)
                claim = ledger.claim(
                    reservation, self.request, fence(generation), now=NOW
                )
            with self.store.transaction() as connection:
                ledger = self.ledger(connection)
                self.assertEqual(
                    ledger.observe(
                        claim,
                        envelope(f"response{generation}"),
                        request_sha256=reservation.request_sha256,
                        runtime_sha256=self.auth.runtime_sha256,
                        request_id=f"request{generation}",
                        current_fence=fence(generation),
                        now=NOW,
                    ),
                    "KNOWN",
                )
                self.assertEqual(
                    json.loads(parse_accounting(envelope(), self.policy))[
                        "estimated_micro_usd_at_adopted_rates"
                    ],
                    0,
                )
                restored = gemini_ledger_from_document(
                    connection, ledger.identity
                )
                self.assertEqual(restored.identity, ledger.identity)
        with self.store.transaction() as connection:
            with self.assertRaises(AppError):
                self.ledger(connection).reserve(self.request, fence(3), now=NOW)
        for changed_policy in (
            dataclasses.replace(self.policy, expires_at=NOW + 101),
            dataclasses.replace(
                self.policy, host_decision_record_sha256="a" * 64
            ),
            policy(),
        ):
            changed_auth = authorization(
                changed_policy,
                self.database_id,
                max_micro_usd=0
                if changed_policy.admission_mode == FREE_MODE
                else 1_000_000,
            )
            with self.store.transaction() as connection:
                with self.assertRaises(AppError):
                    self.ledger(connection, changed_policy, changed_auth)

    def test_independent_call_input_and_output_limits_cannot_be_bypassed_by_zero(
        self,
    ):
        for changes in (
            {"max_calls": 1, "max_total_input_tokens": MAX_INPUT_TOKENS - 1},
            {"max_calls": 1, "max_total_output_tokens": OUTPUT_TOKENS - 1},
        ):
            with self.subTest(changes=changes):
                auth = dataclasses.replace(self.auth, **changes)
                with self.store.transaction() as connection:
                    with self.assertRaises(AppError):
                        self.ledger(connection, auth=auth).reserve(
                            self.request, fence(), now=NOW
                        )
                    # Roll this synthetic unsuccessful authority installation back.
                    connection.execute("DELETE FROM gemini_capacity_identity")

    def test_stale_expired_repeated_and_restarted_claims_keep_unknown_no_refund(
        self,
    ):
        with self.store.transaction() as connection:
            ledger = self.ledger(connection)
            reserved = ledger.reserve(self.request, fence(), now=NOW)
        with self.store.transaction() as connection:
            ledger = self.ledger(connection)
            self.assertIsNone(
                ledger.claim(reserved, self.request, fence(), now=NOW + 80)
            )
        with self.store.transaction() as connection:
            ledger = self.ledger(connection)
            recover_gemini_capacity(connection)
            row = connection.execute(
                "SELECT status,reservation FROM gemini_capacity_operations"
            ).fetchone()
            self.assertEqual(row[0], "UNKNOWN")
            self.assertEqual(json.loads(row[1])["reserved_micro_usd"], 0)
            with self.assertRaises(AppError):
                ledger.claim(reserved, self.request, fence(), now=NOW)
            with self.assertRaises(AppError):
                ledger.reserve(self.request, fence(2), now=NOW)

    def test_legacy_ledger_never_migrates_or_renews(self):
        with self.store.transaction() as connection:
            ledger = self.ledger(connection)
            ledger.reserve(self.request, fence(), now=NOW)
            legacy = json.loads(ledger.identity)
            legacy["policy"]["version"] = "gemini-capacity-v1"
            del legacy["policy"]["admission_mode"]
            del legacy["policy"]["host_decision_record_sha256"]
            del legacy["host_authorization"]["admission_mode"]
            document = canonical(legacy)
            connection.execute(
                "UPDATE gemini_capacity_identity SET document=?", (document,)
            )
            with self.assertRaises(AppError):
                gemini_ledger_from_document(connection, document)
        with self.store.transaction() as connection:
            with self.assertRaises(AppError):
                self.ledger(connection)
            recover_gemini_capacity(connection)
            self.assertEqual(
                connection.execute(
                    "SELECT document FROM gemini_capacity_identity"
                ).fetchone()[0],
                document,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT status FROM gemini_capacity_operations"
                ).fetchone()[0],
                "UNKNOWN",
            )


class ZeroSpendRunnerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.db, self.owner = self.root / "app.sqlite3", self.root / "owner"
        guard = patch(
            "socket.create_connection", side_effect=AssertionError("no network")
        )
        guard.start()
        self.addCleanup(guard.stop)

    def prepare(self, host_plan=None):
        return runner.prepare(
            self.db,
            self.owner,
            free_plan() if host_plan is None else host_plan,
            "KB-UK-C2C",
            [{"kind": "layout", "value": "UK_QWERTY"}],
        )

    def test_free_plan_installs_only_after_matching_zero_allowance(self):
        request = self.prepare()
        installed = runner._installation(request)
        self.assertEqual(installed.policy.rates, (0, 0))
        self.assertEqual(installed.authorization.max_micro_usd, 0)
        self.assertEqual(installed.authorization.admission_mode, FREE_MODE)
        record = {
            "schema": runner.APPROVAL_SCHEMA,
            "approval_reference": "synthetic-review-only",
            "request_sha256": digest(request),
            "request": request,
        }
        with (
            patch.object(runner, "Service", autospec=True) as service_type,
            patch.object(os, "read", side_effect=AssertionError("no key read")),
        ):
            service_type.return_value.mutate.return_value = {"synthetic": True}
            self.assertEqual(
                runner.run(self.db, self.owner, record, 3), {"synthetic": True}
            )
            selected = service_type.call_args.kwargs["gemini_analysis"]
            self.assertIs(type(selected), GeminiAnalysisRuntime)
            self.assertEqual(selected.installed.authorization.max_micro_usd, 0)

    def test_real_runner_service_with_synthetic_pipe_wire_zero_ledger(self):
        from cartreadback_app.inference import FixtureInferenceAdapter
        from test_gemini_client import envelope as wire_envelope
        from test_responses_http import FakeConnection, FakeResponse

        events, calls = [], []
        raw = b""

        def factory(*_args, **_kwargs):
            calls.append(1)
            response = FakeResponse(
                raw,
                [
                    ("Content-Type", "application/json"),
                    ("Content-Length", str(len(raw))),
                ],
            )
            return FakeConnection(response, events)

        # The shipped constructor is replaced only inside this synthetic test.
        # The public provider label produced here is not provider evidence.
        with patch(
            "cartreadback_app.gemini_runtime.unselected_gemini_connection",
            factory,
        ):
            request = self.prepare()
            body = wire_envelope(
                FixtureInferenceAdapter().propose(
                    request["catalog"]["source"], request["conditions"]
                )
            )
            body["modelVersion"] = CURRENT_MODEL
            raw = canonical(body).encode()
            record = {
                "schema": runner.APPROVAL_SCHEMA,
                "approval_reference": "synthetic-only",
                "request_sha256": digest(request),
                "request": request,
            }
            read_fd, write_fd = os.pipe()
            try:
                os.write(write_fd, b"synthetic-key-not-real")
                os.close(write_fd)
                write_fd = None
                result = runner.run(self.db, self.owner, record, read_fd)
                self.assertEqual(result["checkout"]["state"], "REVIEW_REQUIRED")
                self.assertEqual(len(calls), 1)
                with closing(Store(self.db).connect()) as connection:
                    row = connection.execute(
                        "SELECT status,reservation,observation FROM gemini_capacity_operations"
                    ).fetchone()
                    self.assertEqual(row["status"], "KNOWN")
                    reservation = json.loads(row["reservation"])
                    self.assertEqual(reservation["reserved_micro_usd"], 0)
                    self.assertEqual(
                        reservation["input_tokens"], MAX_INPUT_TOKENS
                    )
                    self.assertEqual(
                        reservation["output_tokens"], OUTPUT_TOKENS
                    )
                    self.assertEqual(
                        json.loads(row["observation"])[
                            "estimated_micro_usd_at_adopted_rates"
                        ],
                        0,
                    )
                # A separately prepared current-revision request still cannot
                # replenish the same database's consumed one-call allowance.
                fresh = self.prepare(request["plan"])
                record.update(request=fresh, request_sha256=digest(fresh))
                with patch.object(
                    os, "read", side_effect=AssertionError("no second borrow")
                ):
                    with self.assertRaises(AppError):
                        runner.run(self.db, self.owner, record, read_fd)
                self.assertEqual(len(calls), 1)
            finally:
                os.close(read_fd)
                if write_fd is not None:
                    os.close(write_fd)

    def test_invalid_modes_limits_and_legacy_records_fail_before_handle(self):
        valid = self.prepare()
        variants = []
        for field, value in (
            ("admission_mode", PAID_MODE),
            ("max_micro_usd", 1),
            ("max_micro_usd", True),
            ("max_calls", 0),
            ("max_total_input_tokens", 0),
        ):
            changed = copy.deepcopy(valid)
            changed["plan"]["limits"][field] = value
            variants.append(changed)
        old = copy.deepcopy(valid)
        old["schema"] = "gemini-host-approval-request-v1"
        variants.append(old)
        missing = copy.deepcopy(valid)
        del missing["plan"]["policy"]["admission_mode"]
        variants.append(missing)
        for changed in variants:
            record = {
                "schema": runner.APPROVAL_SCHEMA,
                "approval_reference": "synthetic",
                "request_sha256": digest(changed),
                "request": changed,
            }
            with self.subTest(changed=changed):
                with patch.object(
                    runner,
                    "InheritedPipeCredential",
                    side_effect=AssertionError("no handle"),
                ):
                    with self.assertRaises(AppError):
                        runner.run(self.db, self.owner, record, 3)
        legacy = {
            "schema": "gemini-approved-host-record-v1",
            "approval_reference": "synthetic",
            "request_sha256": digest(valid),
            "request": valid,
        }
        with self.assertRaises(AppError):
            runner.approved_request(legacy)


class ZeroSpendServiceTests(service_tests.GeminiServiceTests):
    """Run all Service lifecycle regressions again with synthetic free policies."""

    def setUp(self):
        original = service_tests.fabricate
        guard = patch.object(
            service_tests,
            "fabricate",
            side_effect=lambda *a, **kw: original(*a, **kw, free=True),
        )
        guard.start()
        self.addCleanup(guard.stop)
        super().setUp()

    def test_zero_reservation_and_usage_keep_finite_capacity_after_restart(
        self,
    ):
        self.flow.analyze()
        reservation = json.loads(
            self.rows("gemini_capacity_operations")[0]["reservation"]
        )
        observation = json.loads(
            self.rows("gemini_capacity_operations")[0]["observation"]
        )
        self.assertEqual(reservation["reserved_micro_usd"], 0)
        self.assertEqual(reservation["input_tokens"], MAX_INPUT_TOKENS)
        self.assertEqual(reservation["output_tokens"], OUTPUT_TOKENS)
        self.assertEqual(observation["estimated_micro_usd_at_adopted_rates"], 0)
        self.state["body"]["responseId"] = "another-synthetic-response"
        self.flow.analyze()
        self.restart(self.runtime)
        with self.assertRaises(AppError):
            self.flow.analyze()
        self.assertEqual(self.handle.calls, 2)
        self.assertEqual(self.state["calls"], 2)

    def test_crash_recovery_same_original_operation_no_post_replay(self):
        # A subprocess cannot inherit the in-process synthetic free-mode patch.
        script = """
import os,sys
sys.path.insert(0,'tests')
from test_gemini_service import *
patch('socket.create_connection',side_effect=AssertionError('no socket')).start()
patch('http.client.HTTPSConnection',side_effect=AssertionError('no TLS')).start()
store=Store(sys.argv[1]);sid=store.session(None)[0]['sid']
runtime,state,handle=fabricate(store,(sid,),free=True)
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
                service = service_tests.Service(store)
                try:
                    with closing(store.connect()) as connection:
                        row = connection.execute(
                            "SELECT a.status,g.status,g.reservation FROM analysis_operations a JOIN gemini_capacity_operations g ON a.operation_id=g.operation_id"
                        ).fetchone()
                        self.assertEqual(tuple(row[:2]), ("UNKNOWN", "UNKNOWN"))
                        self.assertEqual(
                            json.loads(row[2])["reserved_micro_usd"], 0
                        )
                        sid = connection.execute(
                            "SELECT sid FROM sessions"
                        ).fetchone()[0]
                    with self.assertRaises(AppError):
                        service_tests.Workflow(service, sid).analyze()
                finally:
                    service.close()


if __name__ == "__main__":
    unittest.main()
