"""Fabricated accounting and transaction tests; no provider/network evidence."""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import contextmanager
from dataclasses import FrozenInstanceError, asdict, replace
from pathlib import Path
from unittest.mock import patch

from cartreadback_app.context_capacity import (
    CONTEXT_TOKENS,
    EVIDENCE_REVISION,
    MAX_INTEGER,
    OUTPUT_TOKENS,
    ContextCapacityPolicy,
    ContextClaim,
    ContextFence,
    HostCapacityAuthorization,
    TransactionContextCapacityLedger,
    charge_micro_usd,
    parse_accounting,
    recover_context_capacity,
)
from cartreadback_app.inference_config import MODEL
from cartreadback_app.responses_adapter import OfflineResponsesAdapter
from cartreadback_app.validation import AppError, canonical, digest, text_hash

NOW = 1_793_721_600
SOURCE = {"source_id": "catalog:unit", "revision": 1, "text": "UK QWERTY"}
SOURCE["sha256"] = text_hash(SOURCE["text"])
CONDITIONS = [{"condition_id": "c1", "kind": "layout", "value": "UK_QWERTY"}]


def policy(**kwargs):
    return ContextCapacityPolicy(NOW - 10, NOW + 100, **kwargs)


def authorization(p, **kwargs):
    values = dict(
        provenance_sha256="1" * 64,
        data_scope_sha256="2" * 64,
        runtime_sha256="3" * 64,
        policy_sha256=text_hash(p.identity),
        valid_from=NOW - 5,
        expires_at=NOW + 80,
        max_calls=4,
        max_total_input_tokens=4 * CONTEXT_TOKENS,
        max_total_output_tokens=4 * OUTPUT_TOKENS,
        max_micro_usd=1_000_000,
    )
    return HostCapacityAuthorization(**(values | kwargs))


def fence(generation=1):
    return ContextFence(
        "3" * 64,
        "4" * 64,
        SOURCE["sha256"],
        digest(SOURCE),
        1,
        digest(CONDITIONS),
        generation,
    )


def request():
    return OfflineResponsesAdapter(None).build_request(SOURCE, CONDITIONS)


def envelope(incoming=10, outgoing=2, **kwargs):
    return {
        "id": "resp_fabricated",
        "object": "response",
        "status": "completed",
        "model": MODEL,
        "service_tier": "default",
        # Deliberately invalid proposal, irrelevant to independently valid usage.
        "output": [
            {
                "type": "message",
                "content": [{"text": "not valid proposal JSON"}],
            }
        ],
        "usage": {
            "input_tokens": incoming,
            "output_tokens": outgoing,
            "total_tokens": incoming + outgoing,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
    } | kwargs


class CapacityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "capacity.sqlite3"
        self.policy = policy()
        self.auth = authorization(self.policy)
        self.request = request()
        self.fence = fence()

    @contextmanager
    def transaction(self, p=None, a=None):
        connection = sqlite3.connect(self.path, isolation_level=None, timeout=5)
        try:
            connection.execute("BEGIN IMMEDIATE")
            ledger = TransactionContextCapacityLedger(
                connection, p or self.policy, a or self.auth
            )
            yield ledger, connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def reserve(self, f=None, now=NOW):
        with self.transaction() as (ledger, _):
            return ledger.reserve(self.request, f or self.fence, now=now)

    def claim(self, r=None, now=NOW):
        r = r or self.reserve()
        with self.transaction() as (ledger, _):
            return ledger.claim(r, self.request, self.fence, now=now)

    def observe(self, claim, body=None, **kwargs):
        args = dict(
            request_sha256=claim.reservation.request_sha256,
            runtime_sha256=self.auth.runtime_sha256,
            request_id="req_fabricated",
            current_fence=self.fence,
            now=NOW + 1,
        )
        with self.transaction() as (ledger, _):
            return ledger.observe(
                claim, canonical(body or envelope()).encode(), **(args | kwargs)
            )

    def rows(self):
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM context_capacity_operations"
                )
            ]

    def test_reference_costs_and_context_reservation(self):
        self.assertEqual(
            self.policy.estimate(CONTEXT_TOKENS, OUTPUT_TOKENS), 211536
        )
        regional = policy(reference_profile="regional-standard-plus-10-percent")
        self.assertEqual(
            regional.estimate(CONTEXT_TOKENS, OUTPUT_TOKENS), 232690
        )
        r = self.reserve()
        self.assertEqual(
            (r.input_tokens, r.output_tokens, r.reserved_micro_usd),
            (1050000, 2048, 211536),
        )
        self.assertEqual(
            json.loads(self.policy.identity)["billing_scope"], "unselected"
        )

    def test_arithmetic_rounding_and_overflow(self):
        self.assertEqual(charge_micro_usd(0, 1), 0)
        self.assertEqual(charge_micro_usd(1, 1), 1)
        self.assertEqual(charge_micro_usd(1_000_001, 1), 2)
        self.assertEqual(charge_micro_usd(MAX_INTEGER, 1_000_000), MAX_INTEGER)
        for tokens, rate in [
            (True, 1),
            (1, False),
            (-1, 1),
            (1.0, 1),
            (1, 0),
            (MAX_INTEGER + 1, 1),
            (MAX_INTEGER, MAX_INTEGER),
        ]:
            with (
                self.subTest(tokens=tokens, rate=rate),
                self.assertRaises(AppError),
            ):
                charge_micro_usd(tokens, rate)

    def test_policy_and_authorization_are_immutable(self):
        with self.assertRaises(FrozenInstanceError):
            self.policy.expires_at = NOW + 500
        with self.assertRaises(FrozenInstanceError):
            self.auth.max_calls = 64
        with self.assertRaises(FrozenInstanceError):
            self.fence.generation = 5
        for changes in [
            dict(valid_from=True),
            dict(expires_at=NOW - 11),
            dict(expires_at=NOW + 86401),
            dict(reference_profile="custom-discount"),
            dict(evidence_revision="latest"),
        ]:
            with self.subTest(changes=changes), self.assertRaises(AppError):
                replace(self.policy, **changes)
        for changes in [
            dict(max_calls=True),
            dict(max_calls=65),
            dict(max_micro_usd=0),
            dict(runtime_sha256="secret"),
            dict(provenance_sha256=""),
            dict(max_total_input_tokens=MAX_INTEGER + 1),
            dict(valid_from=False),
        ]:
            with self.subTest(changes=changes), self.assertRaises(AppError):
                replace(self.auth, **changes)

    def test_policy_rejects_subclass_before_comparison(self):
        class HostileString(str):
            def __ne__(self, other):
                raise RuntimeError("hostile comparison executed")

        with self.assertRaises(AppError):
            replace(
                self.policy, evidence_revision=HostileString(EVIDENCE_REVISION)
            )

    def test_no_transaction_is_rejected(self):
        with sqlite3.connect(self.path) as connection:
            with self.assertRaises(AppError):
                TransactionContextCapacityLedger(
                    connection, self.policy, self.auth
                )
            with self.assertRaises(AppError):
                recover_context_capacity(connection)
        with self.transaction() as (ledger, connection):
            connection.commit()
            with self.assertRaises(AppError):
                ledger.reserve(self.request, self.fence, now=NOW)

    def test_immutable_database_identity_and_auth_window(self):
        self.reserve()
        for name, value in [
            ("provenance_sha256", "a" * 64),
            ("runtime_sha256", "a" * 64),
            ("data_scope_sha256", "a" * 64),
            ("max_calls", 5),
            ("expires_at", NOW + 90),
        ]:
            with self.subTest(name=name), self.assertRaises(AppError):
                with self.transaction(a=replace(self.auth, **{name: value})):
                    pass
        for a in [
            replace(self.auth, policy_sha256="b" * 64),
            replace(self.auth, expires_at=NOW + 101),
            replace(self.auth, valid_from=NOW - 11),
        ]:
            with self.assertRaises(AppError):
                with self.transaction(a=a):
                    pass

    def test_request_settings_tampering(self):
        changes = {
            "model": "other",
            "service_tier": "priority",
            "tools": [{"type": "web_search"}],
            "store": 0,
            "background": True,
            "stream": True,
            "max_output_tokens": True,
            "reasoning": {"effort": "low"},
            "prompt_cache_options": {"mode": "automatic"},
            "instructions": "changed",
            "previous_response_id": "history",
            "truncation": "auto",
            "metadata": {"verified": True},
            "retry": 1,
        }
        for key, value in changes.items():
            raw = json.loads(self.request)
            raw[key] = value
            with self.subTest(key=key), self.assertRaises(AppError):
                with self.transaction() as (ledger, _):
                    ledger.reserve(canonical(raw).encode(), self.fence, now=NOW)
        for field in ["input", "text", "prompt_cache_options"]:
            raw = json.loads(self.request)
            del raw[field]
            with self.subTest(missing=field), self.assertRaises(AppError):
                with self.transaction() as (ledger, _):
                    ledger.reserve(canonical(raw).encode(), self.fence, now=NOW)

    def test_request_shape_assets_history_and_source_tampering(self):
        for mutate in [
            lambda raw: raw["input"].append(raw["input"][0]),
            lambda raw: raw["input"][0]["content"][0].update(
                type="input_image"
            ),
            lambda raw: raw["input"][0]["content"][0].update(
                text="arbitrary text"
            ),
            lambda raw: raw["text"]["format"].update(strict=1),
            lambda raw: raw["text"]["format"].update(schema={}),
            lambda raw: raw["input"][0]["content"][0].update(
                cache_control={"type": "ephemeral"}
            ),
        ]:
            raw = json.loads(self.request)
            mutate(raw)
            with self.assertRaises(AppError):
                with self.transaction() as (ledger, _):
                    ledger.reserve(canonical(raw).encode(), self.fence, now=NOW)
        for f in [
            replace(self.fence, source_sha256="a" * 64),
            replace(self.fence, source_revision=2),
            replace(self.fence, conditions_sha256="a" * 64),
            replace(self.fence, runtime_sha256="a" * 64),
        ]:
            with self.assertRaises(AppError):
                self.reserve(f)

    def test_duplicate_json_and_bytes_bound(self):
        for raw in [
            b'{"model":1,"model":2}',
            b"[]",
            b"x" * 65537,
            self.request.decode(),
            b"\xff",
        ]:
            with self.assertRaises(AppError):
                with self.transaction() as (ledger, _):
                    ledger.reserve(raw, self.fence, now=NOW)

    def test_invalid_proposal_accounted_before_semantics_without_refund(self):
        claim = self.claim()
        self.assertEqual(self.observe(claim), "KNOWN")
        row = self.rows()[0]
        self.assertNotIn("proposal", row["observation"])
        self.assertEqual(
            json.loads(row["reservation"])["reserved_micro_usd"], 211536
        )
        self.assertEqual(
            json.loads(row["observation"])[
                "estimated_micro_usd_at_reference_max_rates"
            ],
            4,
        )
        next_r = self.reserve(fence(2), now=NOW + 2)
        self.assertEqual(next_r.reserved_micro_usd, 211536)

    def test_nonterminal_usage_is_retained_but_never_renews_dispatch(self):
        for status in ("queued", "in_progress"):
            with self.subTest(status=status):
                self.path = Path(self.temp.name) / f"state-{status}.sqlite3"
                claim = self.claim()
                self.assertEqual(
                    self.observe(claim, envelope(status=status)), "UNKNOWN"
                )
                row = self.rows()[0]
                self.assertEqual(
                    json.loads(row["observation"])["usage_finality"],
                    "provisional-model-usage",
                )
                self.assertEqual(
                    json.loads(row["observation"])["response_status"], status
                )
                self.assertEqual(
                    json.loads(row["reservation"])["reserved_micro_usd"], 211536
                )
                with self.assertRaises(AppError):
                    self.reserve(fence(2), now=NOW + 2)
                with self.assertRaises(AppError):
                    self.observe(
                        claim, envelope(status="completed"), now=NOW + 2
                    )
                self.assertEqual(self.rows()[0]["status"], "UNKNOWN")

    def test_missing_unknown_and_malformed_response_status_are_unknown(self):
        for index, status in enumerate((None, "invented", True, 1, [], {})):
            with self.subTest(status=status):
                self.path = Path(self.temp.name) / f"bad-status-{index}.sqlite3"
                claim = self.claim()
                body = envelope(status=status)
                if status is None:
                    del body["status"]
                self.assertEqual(self.observe(claim, body), "UNKNOWN")
                self.assertEqual(self.rows()[0]["observation"], "")
                with self.assertRaises(AppError):
                    self.reserve(fence(2), now=NOW + 2)

    def test_final_non_success_response_can_have_known_accounting(self):
        for status in ("failed", "cancelled", "incomplete"):
            with self.subTest(status=status):
                self.path = Path(self.temp.name) / f"final-{status}.sqlite3"
                claim = self.claim()
                self.assertEqual(
                    self.observe(claim, envelope(status=status)), "KNOWN"
                )
                self.assertEqual(
                    json.loads(self.rows()[0]["reservation"])[
                        "reserved_micro_usd"
                    ],
                    211536,
                )
                self.assertNotIn("proposal", self.rows()[0]["observation"])

    def test_unexpected_provider_activity_retains_model_usage_unknown(self):
        variants = [
            {"tool_usage": {"web_search": {"num_requests": value}}}
            for value in (1, 0, True, -1, 1.5)
        ] + [
            {"tool_usage": {"unknown": {"count": 1}}},
            {"tool_usage": None},
            {"tool_usage": []},
            {"tool_usage": False},
            {"background": True},
            {"background": 0},
            {"background": None},
            {"tools": [{"type": "web_search"}]},
            {"tools": None},
            {"output": None},
            {"output": {}},
            {"output": [None]},
            {"output": [{}]},
        ]
        variants.extend(
            {"output": [{"type": kind, "status": "completed"}]}
            for kind in (
                "web_search_call",
                "image_generation_call",
                "computer_call",
                "compaction",
                "unknown",
                True,
            )
        )
        for index, changed in enumerate(variants):
            with self.subTest(changed=changed):
                self.path = Path(self.temp.name) / f"activity-{index}.sqlite3"
                claim = self.claim()
                self.assertEqual(
                    self.observe(claim, envelope(**changed)), "UNKNOWN"
                )
                row = self.rows()[0]
                observation = json.loads(row["observation"])
                self.assertEqual(
                    observation["accounting_contract"],
                    "unsupported-provider-activity",
                )
                self.assertEqual(
                    observation["estimated_micro_usd_at_reference_max_rates"], 4
                )
                self.assertNotIn("tool_usage", observation)
                self.assertEqual(
                    json.loads(row["reservation"])["reserved_micro_usd"], 211536
                )
                with self.assertRaises(AppError):
                    self.reserve(fence(2), now=NOW + 2)

    def test_explicit_empty_provider_activity_is_not_a_conflict(self):
        claim = self.claim()
        self.assertEqual(
            self.observe(
                claim, envelope(tool_usage={}, background=False, tools=[])
            ),
            "KNOWN",
        )

    def test_missing_or_semantically_invalid_message_preserves_accounting(self):
        for index, output in enumerate(
            (
                None,
                [],
                [{"type": "message"}],
                [
                    {
                        "type": "message",
                        "content": [
                            {"type": "refusal", "refusal": "fabricated"}
                        ],
                    }
                ],
            )
        ):
            self.path = Path(self.temp.name) / f"semantic-{index}.sqlite3"
            body = envelope(output=output)
            if output is None:
                del body["output"]
            claim = self.claim()
            self.assertEqual(self.observe(claim, body), "KNOWN")
            self.assertEqual(
                json.loads(self.rows()[0]["observation"])["usage_finality"],
                "terminal-model-usage",
            )

    def test_four_permanent_reservations_not_five(self):
        for generation in range(1, 5):
            f = fence(generation)
            with self.transaction() as (ledger, _):
                r = ledger.reserve(self.request, f, now=NOW + generation * 2)
                c = ledger.claim(r, self.request, f, now=NOW + generation * 2)
            self.assertEqual(
                self.observe(
                    c,
                    envelope(id=f"resp_{generation}"),
                    current_fence=f,
                    request_id=f"req_{generation}",
                    now=NOW + generation * 2 + 1,
                ),
                "KNOWN",
            )
        with self.assertRaises(AppError):
            self.reserve(fence(5), now=NOW + 10)
        self.assertEqual(
            sum(
                json.loads(r["reservation"])["reserved_micro_usd"]
                for r in self.rows()
            ),
            846144,
        )

    def test_each_aggregate_limit(self):
        for changes in [
            dict(max_total_input_tokens=CONTEXT_TOKENS - 1),
            dict(max_total_output_tokens=OUTPUT_TOKENS - 1),
            dict(max_micro_usd=211535),
        ]:
            with self.subTest(changes=changes), self.assertRaises(AppError):
                with self.transaction(
                    a=authorization(self.policy, **changes)
                ) as (ledger, _):
                    ledger.reserve(self.request, self.fence, now=NOW)

    def test_duplicate_claim_and_reservation(self):
        r = self.reserve()
        with self.assertRaises(AppError):
            self.reserve()
        self.claim(r)
        with self.assertRaises(AppError):
            self.claim(r)
        self.assertEqual(len(self.rows()), 1)

    def test_changed_exact_bytes_at_claim_become_unknown(self):
        r = self.reserve()
        with self.transaction() as (ledger, _):
            self.assertIsNone(
                ledger.claim(r, b" " + self.request, self.fence, now=NOW)
            )
        self.assertEqual(self.rows()[0]["status"], "UNKNOWN")

    def test_stale_claim_fence_becomes_unknown(self):
        r = self.reserve()
        with self.transaction() as (ledger, _):
            self.assertIsNone(
                ledger.claim(
                    r,
                    self.request,
                    replace(self.fence, owner_sha256="5" * 64),
                    now=NOW,
                )
            )
        self.assertEqual(self.rows()[0]["status"], "UNKNOWN")

    def test_source_id_only_change_is_stale_accounting_not_current(self):
        claim = self.claim()
        changed_source = SOURCE | {"source_id": "catalog:different"}
        changed = replace(
            self.fence, source_identity_sha256=digest(changed_source)
        )
        self.assertEqual(self.observe(claim, current_fence=changed), "UNKNOWN")
        self.assertTrue(self.rows()[0]["observation"])
        with self.assertRaises(AppError):
            self.reserve(fence(2), now=NOW + 2)

    def test_full_source_identity_required_for_reservation(self):
        changed = replace(
            self.fence,
            source_identity_sha256=digest(
                SOURCE | {"source_id": "catalog:different"}
            ),
        )
        with self.assertRaises(AppError):
            self.reserve(changed)

    def test_expired_claim_and_reserve(self):
        with self.assertRaises(AppError):
            self.reserve(now=NOW + 80)
        r = self.reserve()
        self.assertIsNone(self.claim(r, now=NOW + 80))
        self.assertEqual(self.rows()[0]["status"], "UNKNOWN")

    def test_stale_late_and_expired_observation_retains_usage(self):
        for kind in ("stale", "late", "expired", "rollback-clock"):
            with self.subTest(kind=kind):
                # Independent database per case, never a production reset.
                self.path = Path(self.temp.name) / (kind + ".sqlite3")
                c = self.claim()
                kwargs = (
                    {"current_fence": fence(2)}
                    if kind == "stale"
                    else {
                        "now": {
                            "late": NOW + 20,
                            "expired": NOW + 80,
                            "rollback-clock": NOW - 1,
                        }[kind]
                    }
                )
                self.assertEqual(self.observe(c, **kwargs), "UNKNOWN")
                self.assertTrue(self.rows()[0]["observation"])
                with self.assertRaises(AppError):
                    self.reserve(fence(3), now=NOW + 2)

    def test_missing_invalid_accounting_commits_unknown(self):
        cases = []
        for field, value in [
            ("input_tokens", True),
            ("input_tokens", -1),
            ("input_tokens", CONTEXT_TOKENS + 1),
            ("output_tokens", OUTPUT_TOKENS + 1),
            ("output_tokens", 1.0),
            ("total_tokens", 0),
            ("total_tokens", MAX_INTEGER + 1),
            ("input_tokens_details", {}),
            ("input_tokens_details", {"cached_tokens": 1}),
            ("input_tokens_details", {"cached_tokens": False}),
            (
                "input_tokens_details",
                {"cached_tokens": 0, "cache_write_tokens": 1},
            ),
            ("output_tokens_details", {"reasoning_tokens": 1}),
        ]:
            body = envelope()
            body["usage"][field] = value
            cases.append(body)
        cases += [
            envelope(CONTEXT_TOKENS, 1),
            envelope(usage=None),
            envelope(model="other"),
            envelope(service_tier="priority"),
            envelope(object="chat"),
            envelope(id="bad"),
        ]
        for index, body in enumerate(cases):
            with self.subTest(index=index):
                self.path = Path(self.temp.name) / f"invalid-{index}.sqlite3"
                c = self.claim()
                self.assertEqual(self.observe(c, body), "UNKNOWN")
                self.assertEqual(self.rows()[0]["observation"], "")
                # Later valid accounting is retained, but cannot clear UNKNOWN.
                self.assertEqual(self.observe(c), "UNKNOWN")
                self.assertTrue(self.rows()[0]["observation"])
                with self.assertRaises(AppError):
                    self.reserve(fence(2))

    def test_parser_accepts_context_edge_and_rejects_bool_details(self):
        result = parse_accounting(
            canonical(
                envelope(CONTEXT_TOKENS - OUTPUT_TOKENS, OUTPUT_TOKENS)
            ).encode(),
            self.policy,
        )
        self.assertEqual(json.loads(result)["total_tokens"], CONTEXT_TOKENS)
        self.assertIsInstance(
            parse_accounting(
                canonical(envelope(CONTEXT_TOKENS, 0)).encode(), self.policy
            ),
            str,
        )
        self.assertIsInstance(
            parse_accounting(canonical(envelope(0, 0)).encode(), self.policy),
            str,
        )

    def test_cache_write_details_must_be_compatible_zero_integers(self):
        body = envelope()
        details = body["usage"]["input_tokens_details"]
        details.update(
            cache_write_tokens=0,
            cache_write_tokens_details={
                "ttl_30m_tokens": 0,
                "ttl_12h_tokens": 0,
            },
        )
        self.assertIsInstance(
            parse_accounting(canonical(body).encode(), self.policy), str
        )
        for key, value in [
            ("ttl_30m_tokens", 1),
            ("ttl_12h_tokens", True),
            ("ttl_12h_tokens", -1),
            ("ttl_30m_tokens", 0.0),
        ]:
            changed = json.loads(canonical(body))
            changed["usage"]["input_tokens_details"][
                "cache_write_tokens_details"
            ][key] = value
            with (
                self.subTest(key=key, value=value),
                self.assertRaises(AppError),
            ):
                parse_accounting(canonical(changed).encode(), self.policy)
        for nested in [
            None,
            {},
            {"ttl_30m_tokens": 0},
            {"ttl_30m_tokens": 0, "ttl_12h_tokens": 0, "extra": 0},
        ]:
            details["cache_write_tokens_details"] = nested
            with self.assertRaises(AppError):
                parse_accounting(canonical(body).encode(), self.policy)

    def test_wrong_claim_and_host_exchange_leave_row_unchanged(self):
        c = self.claim()
        before = self.rows()
        for changed in [
            replace(c, claim_token="a" * 64),
            replace(c, expires_at=True),
            replace(
                c, reservation=replace(c.reservation, ledger_sha256="a" * 64)
            ),
            replace(
                c, reservation=replace(c.reservation, request_sha256="b" * 64)
            ),
            replace(
                c, reservation=replace(c.reservation, reserved_micro_usd=1)
            ),
        ]:
            with self.assertRaises(AppError):
                self.observe(changed)
            self.assertEqual(self.rows(), before)
        for kwargs in [
            dict(runtime_sha256="a" * 64),
            dict(request_sha256="a" * 64),
            dict(request_id="Bearer secret"),
            dict(current_fence={}),
        ]:
            with self.assertRaises(AppError):
                self.observe(c, **kwargs)
            self.assertEqual(self.rows(), before)

    def test_duplicate_observation_and_provider_replay(self):
        c = self.claim()
        self.observe(c)
        before = self.rows()
        with self.assertRaises(AppError):
            self.observe(c)
        self.assertEqual(self.rows(), before)
        f = fence(2)
        with self.transaction() as (ledger, _):
            r = ledger.reserve(self.request, f, now=NOW + 2)
            c2 = ledger.claim(r, self.request, f, now=NOW + 2)
        self.assertEqual(
            self.observe(
                c2, current_fence=f, now=NOW + 3, request_id="req_new"
            ),
            "UNKNOWN",
        )

    def test_pre_send_failure_never_refunds(self):
        r = self.reserve()
        with self.transaction() as (ledger, _):
            ledger.mark_unknown(r)
        with self.assertRaises(AppError):
            self.reserve(fence(2))
        self.assertEqual(
            json.loads(self.rows()[0]["reservation"])["input_tokens"],
            CONTEXT_TOKENS,
        )

    def test_atomic_rollback_with_owner_analysis(self):
        with self.transaction() as (_, connection):
            connection.execute("CREATE TABLE analysis_fixture (id TEXT)")
        with self.assertRaises(RuntimeError):
            with self.transaction() as (ledger, connection):
                connection.execute(
                    "INSERT INTO analysis_fixture VALUES ('analysis')"
                )
                ledger.reserve(self.request, self.fence, now=NOW)
                raise RuntimeError("owner rollback")
        self.assertEqual(self.rows(), [])
        with self.transaction() as (_, connection):
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM analysis_fixture"
                ).fetchone()[0],
                0,
            )

    def test_recovery_after_reserved_and_claimed_commits(self):
        for state in ("RESERVED", "CLAIMED"):
            self.path = Path(self.temp.name) / (state + ".sqlite3")
            r = self.reserve()
            c = self.claim(r) if state == "CLAIMED" else None
            with self.transaction() as (_, connection):
                recover_context_capacity(connection)
            self.assertEqual(self.rows()[0]["status"], "UNKNOWN")
            with self.assertRaises(AppError):
                self.reserve(fence(2))
            if c:
                self.assertEqual(self.observe(c), "UNKNOWN")
                self.assertTrue(self.rows()[0]["observation"])

    def test_subprocess_crash_after_commit_boundaries(self):
        setup = """
import os,sqlite3,sys
from tests.test_context_capacity import *
c=sqlite3.connect(sys.argv[1],isolation_level=None)
p=policy(); a=authorization(p)
c.execute('BEGIN IMMEDIATE'); l=TransactionContextCapacityLedger(c,p,a)
r=l.reserve(request(),fence(),now=NOW); c.commit()
if sys.argv[2] == 'reserve': os._exit(41)
c.execute('BEGIN IMMEDIATE'); l.claim(r,request(),fence(),now=NOW); c.commit()
os._exit(42)
"""
        for state, expected in [("reserve", 41), ("claim", 42)]:
            self.path = Path(self.temp.name) / f"crash-{state}.sqlite3"
            run = subprocess.run(
                [sys.executable, "-c", setup, str(self.path), state],
                capture_output=True,
                timeout=10,
            )
            self.assertEqual(run.returncode, expected, run.stderr.decode())
            with self.transaction() as (_, connection):
                recover_context_capacity(connection)
            self.assertEqual(self.rows()[0]["status"], "UNKNOWN")

    def test_cross_connection_concurrent_claim_only_one_wins(self):
        r = self.reserve()
        gate = threading.Barrier(3)
        outcomes = []

        def worker():
            gate.wait()
            try:
                outcomes.append(self.claim(r))
            except AppError:
                outcomes.append("blocked")

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        gate.wait()
        for thread in threads:
            thread.join(10)
            self.assertFalse(thread.is_alive())
        self.assertEqual(
            sum(type(value) is ContextClaim for value in outcomes), 1
        )
        self.assertEqual(outcomes.count("blocked"), 1)

    def test_cross_connection_concurrent_reserve_only_one_wins(self):
        # Initialize identity before racing the reservations.
        with self.transaction():
            pass
        gate = threading.Barrier(3)
        outcomes = []

        def worker(generation):
            gate.wait()
            try:
                self.reserve(fence(generation))
                outcomes.append("reserved")
            except AppError:
                outcomes.append("blocked")

        threads = [threading.Thread(target=worker, args=(i,)) for i in (1, 2)]
        for thread in threads:
            thread.start()
        gate.wait()
        for thread in threads:
            thread.join(10)
        self.assertCountEqual(outcomes, ["reserved", "blocked"])

    def test_no_network_environment_credentials_or_old_ledger_changes(self):
        with self.transaction() as (_, connection):
            connection.execute("CREATE TABLE budget_operations (status TEXT)")
            connection.execute(
                "INSERT INTO budget_operations VALUES ('UNKNOWN')"
            )
        with (
            patch(
                "socket.create_connection",
                side_effect=AssertionError("network"),
            ),
            patch.dict(os.environ, {"OPENAI_API_KEY": "must-not-be-read"}),
            patch("os.getenv", side_effect=AssertionError("ambient config")),
        ):
            c = self.claim()
            self.observe(c)
        with self.transaction() as (_, connection):
            self.assertEqual(
                connection.execute(
                    "SELECT status FROM budget_operations"
                ).fetchone()[0],
                "UNKNOWN",
            )
            persisted = canonical(
                connection.execute(
                    "SELECT document FROM context_capacity_identity"
                ).fetchall()
            ) + canonical(self.rows())
        self.assertNotIn("must-not-be-read", persisted)
        self.assertNotIn("not valid proposal JSON", persisted)
        self.assertNotIn(SOURCE["text"], persisted)
        self.assertNotIn("req_fabricated", persisted)

    def test_fence_scalar_validation(self):
        for changes in [
            dict(source_revision=True),
            dict(generation=0),
            dict(owner_sha256="owner"),
            dict(generation=MAX_INTEGER + 1),
        ]:
            with self.assertRaises(AppError):
                replace(self.fence, **changes)
        self.assertEqual(EVIDENCE_REVISION, self.policy.evidence_revision)
        self.assertEqual(len(asdict(self.fence)), 7)


if __name__ == "__main__":
    unittest.main()
