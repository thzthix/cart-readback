"""Offline Gemini accounting tests using fabricated records and wire only."""

import json
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from cartreadback_app.gemini_capacity import (
    MAX_INPUT_TOKENS,
    OUTPUT_TOKENS,
    GeminiCapacityPolicy,
    GeminiFence,
    HostGeminiAuthorization,
    TransactionGeminiCapacityLedger,
    gemini_database_identity,
    gemini_ledger_from_document,
    initialize_gemini_database,
    parse_accounting,
    recover_gemini_capacity,
)
from cartreadback_app.gemini_client import (
    CURRENT_MODEL,
    GeminiClient,
    GeminiConfig,
)
from cartreadback_app.storage import Store
from cartreadback_app.validation import AppError, canonical, digest, text_hash

NOW = 1_800_000_000
SOURCE = {"source_id": "catalog:unit", "revision": 1, "text": "UK QWERTY"}
SOURCE["sha256"] = text_hash(SOURCE["text"])
CONDITIONS = [{"condition_id": "c1", "kind": "layout", "value": "UK_QWERTY"}]


def policy(**kwargs):
    values = dict(
        valid_from=NOW - 10,
        expires_at=NOW + 100,
        model=CURRENT_MODEL,
        expected_model_version=CURRENT_MODEL,
        max_input_tokens=MAX_INPUT_TOKENS,
        input_rate_micro_usd_per_million=300_000,
        output_rate_micro_usd_per_million=2_500_000,
        project="fabricated-project",
        tier="fabricated-tier",
        eligibility_record_sha256="1" * 64,
        pricing_record_sha256="2" * 64,
    )
    return GeminiCapacityPolicy(**(values | kwargs))


def authorization(p, database_id, **kwargs):
    values = dict(
        database_id=database_id,
        provenance_sha256="3" * 64,
        data_scope_sha256="4" * 64,
        runtime_sha256="5" * 64,
        policy_sha256=text_hash(p.identity),
        valid_from=NOW - 5,
        expires_at=NOW + 80,
        max_calls=2,
        max_total_input_tokens=2 * MAX_INPUT_TOKENS,
        max_total_output_tokens=2 * OUTPUT_TOKENS,
        max_micro_usd=1_000_000,
    )
    return HostGeminiAuthorization(**(values | kwargs))


def fence(generation=1):
    return GeminiFence(
        "5" * 64,
        "6" * 64,
        SOURCE["sha256"],
        digest(SOURCE),
        1,
        digest(CONDITIONS),
        generation,
    )


def envelope(response_id="fabricated-response", **kwargs):
    return canonical(
        {
            "modelVersion": CURRENT_MODEL,
            "responseId": response_id,
            "usageMetadata": {
                "promptTokenCount": 10,
                "candidatesTokenCount": 2,
                "thoughtsTokenCount": 3,
                "totalTokenCount": 15,
            },
            "candidates": [
                {
                    "finishReason": "STOP",
                    "content": {
                        "role": "model",
                        "parts": [{"text": "malformed proposal"}],
                    },
                }
            ],
            **kwargs,
        }
    ).encode()


class GeminiCapacityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "store.sqlite3")
        with self.store.transaction() as connection:
            self.database_id = initialize_gemini_database(connection)
        self.policy = policy()
        self.auth = authorization(self.policy, self.database_id)
        self.request = (
            GeminiClient(GeminiConfig(CURRENT_MODEL, model=CURRENT_MODEL))
            .prepare(SOURCE, CONDITIONS)
            .body
        )

    @contextmanager
    def transaction(self, auth=None, adopted=None):
        with self.store.transaction() as connection:
            yield (
                TransactionGeminiCapacityLedger(
                    connection, adopted or self.policy, auth or self.auth
                ),
                connection,
            )

    def reserve(self, generation=1, now=NOW):
        with self.transaction() as (ledger, _):
            return ledger.reserve(self.request, fence(generation), now=now)

    def claim(self, reservation=None, now=NOW):
        reservation = reservation or self.reserve()
        with self.transaction() as (ledger, _):
            return ledger.claim(reservation, self.request, fence(), now=now)

    def observe(
        self, claim, raw=None, now=NOW, current=None, request_id="wire1"
    ):
        with self.transaction() as (ledger, _):
            return ledger.observe(
                claim,
                raw or envelope(),
                request_sha256=claim.reservation.request_sha256,
                runtime_sha256=self.auth.runtime_sha256,
                request_id=request_id,
                current_fence=current or fence(),
                now=now,
            )

    def test_full_capacity_permanent_after_small_usage(self):
        first = self.reserve()
        self.assertEqual(first.input_tokens, MAX_INPUT_TOKENS)
        self.assertEqual(first.output_tokens, OUTPUT_TOKENS)
        self.assertEqual(self.observe(self.claim(first)), "KNOWN")
        second = self.reserve(2)
        with self.transaction() as (ledger, _):
            claim = ledger.claim(second, self.request, fence(2), now=NOW)
        self.assertEqual(
            self.observe(
                claim, envelope("second"), current=fence(2), request_id="wire2"
            ),
            "KNOWN",
        )
        with self.assertRaises(AppError):
            self.reserve(3)

    def test_missing_database_identity_does_not_initialize(self):
        other = Store(Path(self.temp.name) / "other.sqlite3")
        with other.transaction() as connection:
            with self.assertRaises(AppError):
                TransactionGeminiCapacityLedger(
                    connection, self.policy, self.auth
                )
            self.assertIsNone(
                connection.execute(
                    "SELECT name FROM sqlite_master WHERE name='gemini_database_identity'"
                ).fetchone()
            )

    def test_different_prepared_database_rejects_grant(self):
        other = Store(Path(self.temp.name) / "other.sqlite3")
        with other.transaction() as connection:
            initialize_gemini_database(connection)
            with self.assertRaises(AppError):
                TransactionGeminiCapacityLedger(
                    connection, self.policy, self.auth
                )

    def test_copied_database_cannot_reuse_grant(self):
        self.reserve()
        copied = Path(self.temp.name) / "copied.sqlite3"
        shutil.copyfile(self.store.path, copied)
        with sqlite3.connect(copied, isolation_level=None) as connection:
            connection.execute("BEGIN IMMEDIATE")
            with self.assertRaises(AppError):
                TransactionGeminiCapacityLedger(
                    connection, self.policy, self.auth
                )

    def test_missing_ledger_identity_with_orphan_operations_rejected(self):
        self.reserve()
        with self.store.transaction() as connection:
            connection.execute("DELETE FROM gemini_capacity_identity")
        with self.assertRaises(AppError):
            with self.transaction():
                pass

    def test_reconstruction_preserves_identity_and_allowance(self):
        reservation = self.reserve()
        with self.transaction() as (ledger, connection):
            rebuilt = gemini_ledger_from_document(connection, ledger.identity)
            self.assertEqual(rebuilt.identity, ledger.identity)
            with self.assertRaises(AppError):
                rebuilt.reserve(self.request, fence(2), now=NOW)
            self.assertEqual(
                gemini_database_identity(connection), self.database_id
            )
        self.assertEqual(self.claim(reservation).reservation, reservation)

    def test_changed_policy_cannot_replenish(self):
        self.reserve()
        adopted = replace(self.policy, input_rate_micro_usd_per_million=1)
        changed = replace(self.auth, policy_sha256=text_hash(adopted.identity))
        with self.assertRaises(AppError):
            with self.transaction(changed, adopted):
                pass

    def test_only_full_supported_capacity_and_positive_rates(self):
        for values in (
            {"max_input_tokens": 1},
            {"max_input_tokens": 1_048_577},
            {"input_rate_micro_usd_per_million": 0},
            {"output_rate_micro_usd_per_million": True},
            {"expires_at": NOW + 100_000},
        ):
            with self.subTest(values=values), self.assertRaises(AppError):
                policy(**values)

    def test_exact_request_and_fence(self):
        for changed in (
            replace(fence(), source_revision=2),
            replace(fence(), conditions_sha256="0" * 64),
            replace(fence(), runtime_sha256="0" * 64),
        ):
            with self.subTest(changed=changed), self.assertRaises(AppError):
                with self.transaction() as (ledger, _):
                    ledger.reserve(self.request, changed, now=NOW)

    def test_claim_once_visible_to_another_connection(self):
        claim = self.claim()
        with sqlite3.connect(self.store.path) as observer:
            self.assertEqual(
                observer.execute(
                    "SELECT status,claim_token FROM gemini_capacity_operations"
                ).fetchone(),
                ("CLAIMED", claim.claim_token),
            )
        with self.assertRaises(AppError):
            self.claim(claim.reservation)

    def test_fractional_backward_clock_guard_commits_unknown(self):
        claim = self.claim(now=NOW + 0.8)
        with self.transaction() as (ledger, _):
            self.assertFalse(
                ledger.validate_claim(
                    claim, self.request, fence(), now=NOW + 0.7
                )
            )
            ledger.mark_unknown(claim.reservation)
        self.assertEqual(self.observe(claim, now=NOW + 0.9), "UNKNOWN")

    def test_expired_or_changed_fence_claim_is_unknown(self):
        reservation = self.reserve()
        with self.transaction() as (ledger, connection):
            self.assertIsNone(
                ledger.claim(
                    reservation,
                    self.request,
                    replace(fence(), owner_sha256="7" * 64),
                    now=NOW,
                )
            )
            self.assertEqual(
                connection.execute(
                    "SELECT status FROM gemini_capacity_operations"
                ).fetchone()[0],
                "UNKNOWN",
            )

    def test_restart_unknown_retains_late_accounting(self):
        claim = self.claim()
        with self.transaction() as (_, connection):
            recover_gemini_capacity(connection)
        self.assertEqual(self.observe(claim), "UNKNOWN")
        with self.transaction() as (_, connection):
            row = connection.execute(
                "SELECT status,observation FROM gemini_capacity_operations"
            ).fetchone()
            self.assertEqual(row[0], "UNKNOWN")
            self.assertEqual(json.loads(row[1])["thought_tokens"], 3)
        with self.assertRaises(AppError):
            self.reserve(2)

    def test_late_observation_never_known(self):
        claim = self.claim()
        self.assertEqual(self.observe(claim, now=claim.expires_at), "UNKNOWN")

    def test_wrong_model_or_contradictory_usage_unknown(self):
        for raw in (
            envelope(modelVersion="wrong"),
            envelope(
                usageMetadata={
                    "promptTokenCount": 10,
                    "candidatesTokenCount": 2,
                    "totalTokenCount": 13,
                }
            ),
        ):
            with self.subTest(raw=raw), self.assertRaises(AppError):
                parse_accounting(raw, self.policy)

    def test_refusal_and_invalid_prose_keep_accounting(self):
        for raw in (
            envelope(),
            envelope(candidates=[], promptFeedback={"blockReason": "SAFETY"}),
        ):
            usage = json.loads(parse_accounting(raw, self.policy))
            self.assertEqual(usage["output_tokens"], 5)
            self.assertEqual(usage["thought_tokens"], 3)

    def test_duplicate_response_unknown(self):
        self.assertEqual(self.observe(self.claim()), "KNOWN")
        second = self.reserve(2)
        with self.transaction() as (ledger, _):
            claim = ledger.claim(second, self.request, fence(2), now=NOW)
        self.assertEqual(
            self.observe(claim, current=fence(2), request_id="wire2"), "UNKNOWN"
        )


if __name__ == "__main__":
    unittest.main()
