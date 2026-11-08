"""Invented development inputs/fake transport only; no semantic assets or gold."""

import copy
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cartreadback_app.analysis_history import reject_active_corpus
from cartreadback_app.gemini_capacity import MAX_INPUT_TOKENS, OUTPUT_TOKENS
from cartreadback_app.gemini_client import CURRENT_MODEL, GeminiConfig
from cartreadback_app.gemini_corpus import (
    APPROVAL_SCHEMA,
    CORPUS_SCHEMA,
    parse_corpus,
)
from cartreadback_app.gemini_corpus_credentials import CorpusPipes
from cartreadback_app.gemini_corpus_ledger import (
    activate,
    ledger_for,
    read_frozen,
)
from cartreadback_app.gemini_runtime import (
    CredentialBinding,
    FabricatedTransportBinding,
)
from cartreadback_app.inference_config import PromptBundle
from cartreadback_app.storage import Store
from cartreadback_app.validation import AppError, canonical, digest, text_hash

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/run_gemini_corpus.py"
spec = importlib.util.spec_from_file_location("corpus_runner", SCRIPT)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
# Invented mechanics-only template, not copied from shipped prompts or an eval.
BUNDLE = PromptBundle(
    "Invented offline test instructions.",
    "INPUT={{request_json}};SCHEMA={{output_schema_json}};END",
    '{"type":"object"}',
    '{"prompt_version":"invented-test"}',
)
NOW = 1_800_000_000


def corpus_document(count=2):
    cases = []
    for index in range(count):
        source = {
            "source_id": "development/source",
            "revision": 1,
            "text": f"Invented specimen {index}. No product facts supplied.",
        }
        source["sha256"] = text_hash(source["text"])
        cases.append(
            {
                "case_id": f"development/{index}",
                "source": source,
                "conditions": [
                    {
                        "condition_id": "opaque/선택",
                        "kind": "layout",
                        "value": "UK_QWERTY",
                    }
                ],
            }
        )
    return {"schema": CORPUS_SCHEMA, "cases": cases}


def host_plan(count=2):
    return {
        "binding": {
            "project": "invented",
            "credential_version": "v1",
            "host_revision": "test",
        },
        "config": {
            "model": CURRENT_MODEL,
            "expected_model_version": CURRENT_MODEL,
            "response_language": "en",
        },
        "policy": {
            "valid_from": NOW - 1,
            "expires_at": NOW + 100,
            "model": CURRENT_MODEL,
            "expected_model_version": CURRENT_MODEL,
            "max_input_tokens": MAX_INPUT_TOKENS,
            "input_rate_micro_usd_per_million": 0,
            "output_rate_micro_usd_per_million": 0,
            "project": "invented",
            "tier": "free",
            "eligibility_record_sha256": "a" * 64,
            "pricing_record_sha256": "b" * 64,
            "admission_mode": "externally-verified-free-tier",
            "host_decision_record_sha256": "c" * 64,
        },
        "binding_record_sha256": "d" * 64,
        "pricing_adoption_record_sha256": "b" * 64,
        "installation_revision": "invented",
        "timeout_seconds": 2.0,
        "limits": {
            "valid_from": NOW - 1,
            "expires_at": NOW + 100,
            "max_calls": count,
            "max_total_input_tokens": count * MAX_INPUT_TOKENS,
            "max_total_output_tokens": count * OUTPUT_TOKENS,
            "max_micro_usd": 0,
            "admission_mode": "externally-verified-free-tier",
        },
    }


class Response:
    status = 200
    version = 11

    def __init__(self, body):
        self.body = body
        self.offset = 0

    def getheaders(self):
        return [
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(self.body))),
        ]

    def read1(self, amount):
        part = self.body[self.offset : self.offset + amount]
        self.offset += len(part)
        return part

    def close(self):
        pass


class Connection:
    def __init__(self, harness):
        self.harness = harness
        self.sock = self

    def set_debuglevel(self, level):
        pass

    def connect(self):
        self.harness.connects += 1

    def settimeout(self, value):
        pass

    def request(self, method, path, body, headers, encode_chunked):
        self.harness.calls.append(body)
        # Assert synthetic key without retaining it in logs/artifacts.
        if headers["x-goog-api-key"] != "invented-test-key":
            raise AssertionError("wrong synthetic key")
        if self.harness.on_request:
            self.harness.on_request()

    def getresponse(self):
        index = len(self.harness.calls) - 1
        result = {
            "condition_id": "opaque/선택",
            "status": "unknown",
            "explanation": "Invented development response.",
            "evidence": [],
        }
        envelope = {
            "modelVersion": CURRENT_MODEL,
            "responseId": f"invented-{index}",
            "usageMetadata": {
                "promptTokenCount": 10,
                "candidatesTokenCount": 5,
                "thoughtsTokenCount": 0,
                "totalTokenCount": 15,
            },
            "candidates": [
                {
                    "finishReason": "STOP",
                    "content": {
                        "role": "model",
                        "parts": [{"text": canonical({"results": [result]})}],
                    },
                }
            ],
        }
        if index == self.harness.unknown_at:
            envelope.pop("usageMetadata")
        if index == self.harness.refusal_at:
            envelope["promptFeedback"] = {"blockReason": "SAFETY"}
        return Response(canonical(envelope).encode())

    def close(self):
        pass


class CorpusTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.db = self.root / "existing.sqlite3"
        self.store = Store(self.db)
        self.owner = self.store.session(None)[0]["sid"]
        self.calls = []
        self.connects = 0
        self.on_request = None
        self.unknown_at = self.refusal_at = -1
        self.transport = FabricatedTransportBinding(
            lambda *a, **kw: Connection(self)
        )
        for module in (
            "cartreadback_app.gemini_client",
            "cartreadback_app.gemini_capacity",
        ):
            mocked = patch(module + ".load_bundle", return_value=BUNDLE)
            mocked.start()
            self.addCleanup(mocked.stop)
        for target in (
            "socket.create_connection",
            "http.client.HTTPSConnection",
        ):
            mocked = patch(
                target, side_effect=AssertionError("Real network forbidden")
            )
            mocked.start()
            self.addCleanup(mocked.stop)
        self.raw = canonical(corpus_document()).encode()

    def disclosure(self, **kwargs):
        return runner.prepare(
            self.db,
            self.owner,
            self.raw,
            kwargs.pop("plan", host_plan()),
            transport=self.transport,
            **kwargs,
        )

    def approval(self, request=None):
        request = request or self.disclosure()
        return {
            "schema": APPROVAL_SCHEMA,
            "approval_reference": "invented-offline-decision",
            "request_sha256": digest(request),
            "request": request,
        }

    def descriptors(self, ordinals=(0, 1)):
        result = {}
        for ordinal in ordinals:
            read, write = os.pipe()
            os.write(write, b"invented-test-key")
            os.close(write)
            result[ordinal] = read
        return result

    def execute(self, record=None, descriptors=None, **kwargs):
        return runner.run(
            self.db,
            self.owner,
            self.raw,
            record or self.approval(),
            self.descriptors() if descriptors is None else descriptors,
            transport=self.transport,
            clock=lambda: NOW,
            **kwargs,
        )

    def runtime(self, record):
        return runner._runtime(record, self.raw, self.owner, self.transport)

    def reserve(self, record, ordinal=0, claim=False):
        runtime = self.runtime(record)
        with self.store.transaction() as connection:
            ledger = activate(connection, record, runtime, NOW)
            _, prepared = runtime.exact_case(ordinal)
            reservation = ledger.reserve(
                prepared.body, runtime.fence(ordinal), now=NOW
            )
            connection.execute(
                "UPDATE gemini_corpus_requests SET operation_id=? WHERE ordinal=?",
                (reservation.operation_id, ordinal),
            )
        if claim:
            with self.store.transaction() as connection:
                ledger = ledger_for(connection, runtime, NOW)
                return ledger.claim(
                    reservation, prepared.body, runtime.fence(ordinal), now=NOW
                )
        return reservation

    def test_prepare_is_offline_and_not_authority(self):
        request = self.disclosure()
        self.assertEqual([], self.calls)
        self.assertEqual(0, self.connects)
        self.assertEqual(2, len(request["mapping"]))
        with self.store.transaction() as connection:
            reject_active_corpus(connection)
            self.assertIsNone(
                connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='gemini_corpus_identity'"
                ).fetchone()
            )
        self.assertEqual(corpus_document(), request["corpus"])
        self.assertNotIn("catalog", request)

    def test_exact_raw_hash_and_owned_values(self):
        a = parse_corpus(
            self.raw, GeminiConfig(CURRENT_MODEL, model=CURRENT_MODEL)
        )
        b = parse_corpus(
            self.raw + b"\n", GeminiConfig(CURRENT_MODEL, model=CURRENT_MODEL)
        )
        self.assertNotEqual(a.sha256, b.sha256)
        self.assertEqual(a.mapping, b.mapping)
        changed = a.cases
        changed[0]["source"]["text"] = "mutated"
        self.assertEqual(corpus_document()["cases"], a.cases)

    def test_parser_rejects_malformed_duplicate_extra_and_gold(self):
        invalid = [
            b"\xff",
            b'{"schema":"x","schema":"y"}',
            b'{"cases":NaN}',
            b"[]",
        ]
        doc = corpus_document()
        for key in ("gold", "labels", "results", "prompt", "catalog", "sku_id"):
            changed = copy.deepcopy(doc)
            changed[key] = []
            invalid.append(canonical(changed).encode())
        changed = copy.deepcopy(doc)
        changed["cases"][1]["case_id"] = changed["cases"][0]["case_id"]
        invalid.append(canonical(changed).encode())
        for raw in invalid:
            with self.subTest(raw=raw[:40]), self.assertRaises(AppError):
                parse_corpus(
                    raw, GeminiConfig(CURRENT_MODEL, model=CURRENT_MODEL)
                )

    def test_opaque_ids_and_safe_revision_bounds(self):
        for field, invalid in (
            ("case_id", "a" * 161),
            ("case_id", "x\x7f"),
            ("case_id", ""),
        ):
            doc = corpus_document()
            doc["cases"][0][field] = invalid
            with self.assertRaises(AppError):
                parse_corpus(
                    canonical(doc).encode(),
                    GeminiConfig(CURRENT_MODEL, model=CURRENT_MODEL),
                )
        for value in (True, 0, 2**53, 1.5):
            doc = corpus_document()
            doc["cases"][0]["source"]["revision"] = value
            with self.assertRaises(AppError):
                parse_corpus(
                    canonical(doc).encode(),
                    GeminiConfig(CURRENT_MODEL, model=CURRENT_MODEL),
                )
        # Repeated source/condition IDs across cases are explicitly legal.
        self.assertEqual(
            2,
            len(
                parse_corpus(
                    self.raw, GeminiConfig(CURRENT_MODEL, model=CURRENT_MODEL)
                ).cases
            ),
        )

    def test_success_real_wire_seam_and_frozen_integrity(self):
        record = self.approval()
        frozen = self.execute(record)
        value = json.loads(frozen)
        self.assertEqual(2, len(self.calls))
        self.assertEqual(
            ["predicted", "predicted"], [r["outcome"] for r in value["cases"]]
        )
        self.assertEqual("fabricated-offline", value["evidence_kind"])
        self.assertEqual(frozen, read_frozen(self.db))
        self.assertEqual(
            2 * MAX_INPUT_TOKENS,
            sum(r["input_tokens"] for r in value["reservations"]),
        )
        with self.assertRaises(AppError):
            self.execute(record, descriptors={})
        self.assertEqual(2, len(self.calls))

    def test_unknown_stops_before_next_case_and_never_retries(self):
        self.unknown_at = 0
        record = self.approval()
        frozen = self.execute(record)
        value = json.loads(frozen)
        self.assertEqual(
            ["unknown", "not_run"], [r["outcome"] for r in value["cases"]]
        )
        self.assertEqual(1, len(self.calls))
        with self.assertRaises(AppError):
            self.execute(record, descriptors={})
        with self.store.transaction() as connection:
            with self.assertRaises(AppError):
                reject_active_corpus(connection)

    def test_known_refusal_is_frozen_failure_and_can_continue(self):
        self.refusal_at = 0
        value = json.loads(self.execute())
        self.assertEqual(
            ["failed", "predicted"], [r["outcome"] for r in value["cases"]]
        )
        self.assertEqual("MODEL_REFUSED", value["cases"][0]["error_code"])

    def test_reserved_and_claimed_crashes_recover_unknown(self):
        record = self.approval()
        self.reserve(record, claim=True)
        value = json.loads(self.execute(record, descriptors={}))
        self.assertEqual(
            ["unknown", "not_run"], [r["outcome"] for r in value["cases"]]
        )
        self.assertEqual([], self.calls)

    def test_reserved_crash_recovery(self):
        record = self.approval()
        self.reserve(record)
        value = json.loads(self.execute(record, descriptors={}))
        self.assertTrue(value["stopped_on_unknown"])
        self.assertEqual([], self.calls)

    def test_resume_only_needs_remaining_pipe(self):
        record = self.approval()
        runtime = self.runtime(record)
        with self.store.transaction() as connection:
            activate(connection, record, runtime, NOW)
        pipes = CorpusPipes(
            self.descriptors((0,)), [0], runtime.binding, runtime.record_sha256
        )
        try:
            self.assertEqual(
                "KNOWN",
                runner._execute(self.store, runtime, 0, pipes, lambda: NOW),
            )
        finally:
            pipes.close()
        value = json.loads(
            self.execute(record, descriptors=self.descriptors((1,)))
        )
        self.assertEqual(2, len(self.calls))
        self.assertEqual(
            ["predicted", "predicted"], [r["outcome"] for r in value["cases"]]
        )

    def test_changed_raw_owner_mapping_and_runtime_block_before_io(self):
        record = self.approval()
        for change in ("raw", "mapping", "owner", "source"):
            changed = copy.deepcopy(record)
            raw = self.raw
            owner = self.owner
            if change == "raw":
                raw += b"\n"
            elif change == "mapping":
                changed["request"]["mapping"].reverse()
            elif change == "owner":
                owner = "different_owner"
            else:
                changed["request"]["corpus"]["cases"][0]["source"][
                    "revision"
                ] += 1
            changed["request_sha256"] = digest(changed["request"])
            with self.subTest(change=change), self.assertRaises(AppError):
                runner.run(
                    self.db,
                    owner,
                    raw,
                    changed,
                    {},
                    transport=self.transport,
                    clock=lambda: NOW,
                )
        self.assertEqual([], self.calls)

    def test_changed_session_revision_blocks_continuation(self):
        record = self.approval()
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE sessions SET revision=revision+1 WHERE sid=?",
                (self.owner,),
            )
        with self.assertRaises(AppError):
            self.execute(record, descriptors={})
        self.assertEqual([], self.calls)

    def test_zero_rates_and_zero_ceiling_are_exact(self):
        for group, key, value in (
            ("limits", "max_micro_usd", 1),
            ("limits", "max_micro_usd", False),
            ("policy", "input_rate_micro_usd_per_million", 1),
            ("policy", "output_rate_micro_usd_per_million", 1),
            ("limits", "max_calls", True),
        ):
            plan = host_plan()
            plan[group][key] = value
            with (
                self.subTest(key=key, value=value),
                self.assertRaises(AppError),
            ):
                self.disclosure(plan=plan)

    def test_scope_and_source_code_drift_before_secret(self):
        record = self.approval()
        with patch(
            "cartreadback_app.gemini_corpus.source_identity",
            return_value="f" * 64,
        ):
            with self.assertRaises(AppError):
                self.execute(record, descriptors={})
        self.assertEqual([], self.calls)

    def test_expired_authority_blocks(self):
        record = self.approval()
        with self.assertRaises(AppError):
            runner.run(
                self.db,
                self.owner,
                self.raw,
                record,
                {},
                transport=self.transport,
                clock=lambda: NOW + 100,
            )
        self.assertEqual([], self.calls)

    def test_different_authority_cannot_replace_activated_grant(self):
        record = self.approval()
        runtime = self.runtime(record)
        with self.store.transaction() as connection:
            activate(connection, record, runtime, NOW)
        changed = copy.deepcopy(record)
        changed["request"]["plan"]["limits"]["max_calls"] = 3
        changed["request_sha256"] = digest(changed["request"])
        with self.assertRaises(AppError):
            self.execute(changed, descriptors={})

    def test_no_pipe_or_duplicate_inode_alias_before_reserve(self):
        record = self.approval()
        read, write = os.pipe()
        os.close(write)
        alias = os.dup(read)
        with self.assertRaises(AppError):
            self.execute(record, descriptors={0: read, 1: alias})
        with self.store.transaction() as connection:
            self.assertEqual(
                0,
                connection.execute(
                    "SELECT count(*) FROM gemini_corpus_capacity_operations"
                ).fetchone()[0],
            )
        for fd in (read, alias):
            with self.assertRaises(OSError):
                os.fstat(fd)

    def test_file_write_pipe_public_mode_and_wrong_scope_rejected(self):
        binding = CredentialBinding("invented", "v1", "test")
        for kind in ("file", "write", "public"):
            if kind == "file":
                fd = os.open(
                    self.root / "ordinary", os.O_CREAT | os.O_RDONLY, 0o600
                )
            else:
                read, write = os.pipe()
                fd, other = (write, read) if kind == "write" else (read, write)
                os.close(other)
                if kind == "public":
                    os.fchmod(fd, 0o644)
            with self.subTest(kind=kind), self.assertRaises(AppError):
                CorpusPipes({0: fd}, [0], binding, "a" * 64)
        pipes = CorpusPipes(self.descriptors((0,)), [0], binding, "a" * 64)
        try:
            with self.assertRaises(AppError):
                pipes.handle(0, "b" * 64)
        finally:
            pipes.close()

    def test_same_store_process_lock_excludes_parallel_runner(self):
        record = self.approval()
        lease = self.store.acquire_service()
        try:
            with self.assertRaises(AppError):
                self.execute(record, descriptors={})
        finally:
            lease.close()
        self.assertEqual([], self.calls)

    def test_freeze_then_export_failure_is_reexport_only(self):
        frozen = self.execute()
        destination = self.root / "existing.json"
        destination.write_bytes(b"partial old artifact")
        with self.assertRaises(FileExistsError):
            runner.publish(frozen, destination)
        self.assertEqual(b"partial old artifact", destination.read_bytes())
        new = self.root / "new.json"
        runner.publish(read_frozen(self.db), new)
        self.assertEqual(frozen, new.read_bytes())
        self.assertEqual(0o600, new.stat().st_mode & 0o777)
        self.assertEqual([], list(self.root.glob(".corpus-export-*")))

    def test_frozen_tampering_is_detected(self):
        self.execute()
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE gemini_corpus_identity SET frozen=frozen || ' '"
            )
        with self.assertRaises(AppError):
            read_frozen(self.db)

    def test_orphan_legacy_operations_block(self):
        self.disclosure()
        with self.store.transaction() as connection:
            connection.execute(
                "INSERT INTO budget_operations(operation_id,request_sha256,input_tokens,output_tokens,reserved_micro_usd,status) VALUES('orphan',?,1,1,0,'KNOWN')",
                ("a" * 64,),
            )
        with self.assertRaises(AppError):
            self.disclosure()
        self.assertEqual([], self.calls)

    def test_cli_has_no_gold_interface(self):
        with self.assertRaises(SystemExit) as caught:
            runner.main(
                [
                    "prepare",
                    "--db",
                    "unused",
                    "--output",
                    "unused",
                    "--owner-file",
                    "unused",
                    "--corpus",
                    "unused",
                    "--host-plan",
                    "unused",
                    "--gold",
                    "not-opened",
                ]
            )
        self.assertEqual(2, caught.exception.code)
        self.assertEqual([], self.calls)

    def legacy_gemini(self):
        from cartreadback_app.gemini_capacity import (
            GeminiCapacityPolicy,
            GeminiFence,
            HostGeminiAuthorization,
            TransactionGeminiCapacityLedger,
            gemini_database_identity,
        )
        from cartreadback_app.gemini_client import GeminiClient

        self.disclosure()
        adopted = GeminiCapacityPolicy(**host_plan(10)["policy"])
        source = corpus_document()["cases"][0]["source"]
        choices = corpus_document()["cases"][0]["conditions"]
        prepared = GeminiClient(
            GeminiConfig(CURRENT_MODEL, model=CURRENT_MODEL)
        ).prepare(source, choices)
        fence = GeminiFence(
            "5" * 64,
            text_hash(self.owner),
            source["sha256"],
            digest(source),
            1,
            digest(choices),
            1,
        )
        with self.store.transaction() as connection:
            auth = HostGeminiAuthorization(
                database_id=gemini_database_identity(connection),
                provenance_sha256="3" * 64,
                data_scope_sha256="4" * 64,
                runtime_sha256="5" * 64,
                policy_sha256=text_hash(adopted.identity),
                **host_plan(10)["limits"],
            )
            ledger = TransactionGeminiCapacityLedger(connection, adopted, auth)
            reservation = ledger.reserve(prepared.body, fence, now=NOW)
            claim = ledger.claim(reservation, prepared.body, fence, now=NOW)
            legacy_envelope = json.loads(Connection(self).getresponse().body)
            legacy_envelope["usageMetadata"] = {
                "promptTokenCount": 10,
                "candidatesTokenCount": 5,
                "totalTokenCount": 15,
            }
            legacy_envelope["responseId"] = "legacy-invented"
            state = ledger.observe(
                claim,
                canonical(legacy_envelope).encode(),
                request_sha256=prepared.request_sha256,
                runtime_sha256="5" * 64,
                request_id="legacy-fabricated",
                current_fence=fence,
                now=NOW,
            )
            self.assertEqual("KNOWN", state)
            self.add_analysis_pair(connection, reservation.operation_id)
        return adopted, auth, prepared, fence, reservation

    def add_analysis_pair(self, connection, operation_id):
        review = "invented-review-" + operation_id
        connection.execute(
            "INSERT INTO reviews VALUES(?,?,?,?)",
            (review, self.owner, "0" * 64, "{}"),
        )
        connection.execute(
            "INSERT INTO analysis_operations(operation_id,sid,review_id,input_document,input_hash,checkout_hash,reserved_revision,is_fixture,status,reserved_at,observation,strategy) VALUES(?,?,?,?,?,?,0,0,'SUCCEEDED','invented','{}','gemini-capacity-v1')",
            (operation_id, self.owner, review, "{}", text_hash("{}"), "0" * 64),
        )

    def test_prior_known_reservation_counts_against_total_not_new_allowance(
        self,
    ):
        self.legacy_gemini()
        too_small = self.approval(self.disclosure(plan=host_plan(2)))
        with self.assertRaises(AppError):
            self.execute(too_small, descriptors={})
        record = self.approval(self.disclosure(plan=host_plan(3)))
        frozen = json.loads(self.execute(record))
        self.assertEqual(
            [1, MAX_INPUT_TOKENS, OUTPUT_TOKENS, 0], frozen["prior_totals"]
        )
        self.assertEqual(2, len(self.calls))
        with self.store.transaction() as connection:
            self.assertEqual(
                1,
                connection.execute(
                    "SELECT count(*) FROM gemini_capacity_operations"
                ).fetchone()[0],
            )
            self.assertEqual(
                2,
                connection.execute(
                    "SELECT count(*) FROM gemini_corpus_capacity_operations"
                ).fetchone()[0],
            )

    def test_whole_corpus_token_shortfall_is_blocked_before_any_reservation(
        self,
    ):
        for field, value in (
            ("max_calls", 1),
            ("max_total_input_tokens", MAX_INPUT_TOKENS),
            ("max_total_output_tokens", OUTPUT_TOKENS),
        ):
            plan = host_plan()
            plan["limits"][field] = value
            record = self.approval(self.disclosure(plan=plan))
            with self.subTest(field=field), self.assertRaises(AppError):
                self.execute(record, descriptors={})
        self.assertEqual([], self.calls)

    def test_all_legacy_gemini_unknown_and_orphan_states_block(self):
        _, _, _, _, reservation = self.legacy_gemini()
        for status in ("RESERVED", "CLAIMED", "UNKNOWN"):
            with self.store.transaction() as connection:
                connection.execute(
                    "UPDATE gemini_capacity_operations SET status=?", (status,)
                )
            with self.subTest(status=status), self.assertRaises(AppError):
                self.disclosure(plan=host_plan(3))
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE gemini_capacity_operations SET status='KNOWN'"
            )
            connection.execute(
                "DELETE FROM analysis_operations WHERE operation_id=?",
                (reservation.operation_id,),
            )
        with self.assertRaises(AppError):
            self.disclosure(plan=host_plan(3))

    def test_analysis_unknown_and_missing_reverse_pair_block(self):
        _, _, _, _, reservation = self.legacy_gemini()
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE analysis_operations SET status='UNKNOWN'"
            )
        with self.assertRaises(AppError):
            self.disclosure(plan=host_plan(3))
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE analysis_operations SET status='SUCCEEDED'"
            )
            connection.execute(
                "DELETE FROM gemini_capacity_operations WHERE operation_id=?",
                (reservation.operation_id,),
            )
        with self.assertRaises(AppError):
            self.disclosure(plan=host_plan(3))

    def test_unresolved_preflight_blocks(self):
        self.disclosure()
        with self.store.transaction() as connection:
            connection.execute(
                "INSERT INTO analysis_preflights(preflight_id,sid,input_document,input_hash,status,created_at) VALUES('invented',?,'{}',?,'UNKNOWN','invented')",
                (self.owner, text_hash("{}")),
            )
        with self.assertRaises(AppError):
            self.disclosure()

    def test_old_nonzero_spend_cannot_be_migrated_to_zero(self):
        self.legacy_gemini()
        with self.store.transaction() as connection:
            row = connection.execute(
                "SELECT reservation FROM gemini_capacity_operations"
            ).fetchone()
            value = json.loads(row[0])
            value["reserved_micro_usd"] = 1
            connection.execute(
                "UPDATE gemini_capacity_operations SET reservation=?",
                (canonical(value),),
            )
        with self.assertRaises(AppError):
            self.disclosure(plan=host_plan(3))

    def test_direct_capacity_tuple_swap_and_skipped_ordinal_block(self):
        record = self.approval()
        runtime = self.runtime(record)
        with self.store.transaction() as connection:
            ledger = activate(connection, record, runtime, NOW)
            _, first = runtime.exact_case(0)
            _, second = runtime.exact_case(1)
            with self.assertRaises(AppError):
                ledger.reserve(first.body, runtime.fence(1), now=NOW)
            with self.assertRaises(AppError):
                ledger.reserve(second.body, runtime.fence(1), now=NOW)
            self.assertEqual(
                0,
                connection.execute(
                    "SELECT count(*) FROM gemini_corpus_capacity_operations"
                ).fetchone()[0],
            )

    def test_duplicate_claim_cannot_borrow_again(self):
        record = self.approval()
        claim = self.reserve(record, claim=True)
        runtime = self.runtime(record)
        with self.store.transaction() as connection:
            ledger = ledger_for(connection, runtime, NOW)
            _, prepared = runtime.exact_case(0)
            with self.assertRaises(AppError):
                ledger.claim(
                    claim.reservation, prepared.body, runtime.fence(0), now=NOW
                )
        self.assertEqual([], self.calls)

    def test_result_hash_and_operation_pair_tamper_block_freeze(self):
        record = self.approval()
        runtime = self.runtime(record)
        with self.store.transaction() as connection:
            activate(connection, record, runtime, NOW)
        pipes = CorpusPipes(
            self.descriptors((0,)), [0], runtime.binding, runtime.record_sha256
        )
        try:
            self.assertEqual(
                "KNOWN",
                runner._execute(self.store, runtime, 0, pipes, lambda: NOW),
            )
        finally:
            pipes.close()
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE gemini_corpus_requests SET result=result || ' ' WHERE ordinal=0"
            )
        with self.assertRaises(AppError):
            self.execute(record, descriptors=self.descriptors((1,)))
        self.assertEqual(1, len(self.calls))

    def test_transport_failure_keeps_reservation_and_closes_unused_pipes(self):
        self.on_request = lambda: (_ for _ in ()).throw(
            OSError("invented fault")
        )
        descriptors = self.descriptors()
        value = json.loads(self.execute(descriptors=descriptors))
        self.assertEqual(
            ["unknown", "not_run"], [r["outcome"] for r in value["cases"]]
        )
        for fd in descriptors.values():
            with self.assertRaises(OSError):
                os.fstat(fd)

    def test_early_raw_rejection_closes_owned_unused_pipes(self):
        record = self.approval()
        descriptors = self.descriptors()
        with self.assertRaises(AppError):
            runner.run(
                self.db,
                self.owner,
                self.raw + b"\n",
                record,
                descriptors,
                transport=self.transport,
                clock=lambda: NOW,
            )
        for fd in descriptors.values():
            with self.assertRaises(OSError):
                os.fstat(fd)
        self.assertEqual([], self.calls)

    def test_crashed_claim_recovery_does_not_need_fresh_window_or_pipes(self):
        record = self.approval()
        self.reserve(record, claim=True)
        frozen = runner.run(
            self.db,
            self.owner,
            self.raw,
            record,
            {},
            transport=self.transport,
            clock=lambda: NOW + 1000,
        )
        self.assertTrue(json.loads(frozen)["stopped_on_unknown"])
        self.assertEqual([], self.calls)

    def test_all_observed_crash_before_freeze_needs_no_new_pipes(self):
        record = self.approval()
        runtime = self.runtime(record)
        with self.store.transaction() as connection:
            activate(connection, record, runtime, NOW)
        pipes = CorpusPipes(
            self.descriptors(), [0, 1], runtime.binding, runtime.record_sha256
        )
        try:
            for ordinal in (0, 1):
                self.assertEqual(
                    "KNOWN",
                    runner._execute(
                        self.store, runtime, ordinal, pipes, lambda: NOW
                    ),
                )
        finally:
            pipes.close()
        frozen = self.execute(record, descriptors={})
        self.assertEqual(2, len(self.calls))
        self.assertEqual(frozen, read_frozen(self.db))

    def test_changed_baseline_during_exchange_stops_next_request(self):
        def change():
            with self.store.transaction() as connection:
                connection.execute("UPDATE sessions SET revision=revision+1")

        self.on_request = change
        frozen = json.loads(self.execute())
        self.assertTrue(frozen["stopped_on_unknown"])
        self.assertEqual(1, len(self.calls))

    def test_pipe_privacy_rechecked_before_borrow_and_single_use(self):
        import time

        from cartreadback_app.responses_adapter import Deadline

        binding = CredentialBinding("invented", "v1", "test")
        descriptors = self.descriptors((0,))
        pipes = CorpusPipes(descriptors, [0], binding, "a" * 64)
        handle = pipes.handle(0, "a" * 64)
        try:
            os.fchmod(descriptors[0], 0o644)
            with self.assertRaises(AppError):
                handle.borrow(
                    expected_binding=binding,
                    deadline=Deadline(time.monotonic() + 1, 1, 1),
                )
            os.fchmod(descriptors[0], 0o600)
            self.assertEqual(
                "invented-test-key",
                handle.borrow(
                    expected_binding=binding,
                    deadline=Deadline(time.monotonic() + 1, 1, 1),
                ),
            )
            with self.assertRaises(AppError):
                handle.borrow(
                    expected_binding=binding,
                    deadline=Deadline(time.monotonic() + 1, 1, 1),
                )
        finally:
            pipes.close()

    def test_legacy_and_corpus_activation_are_transactionally_exclusive(self):
        import threading
        from dataclasses import replace

        from cartreadback_app.gemini_capacity import (
            TransactionGeminiCapacityLedger,
        )

        adopted, auth, prepared, fence, _ = self.legacy_gemini()
        record = self.approval(self.disclosure(plan=host_plan(3)))
        runtime = self.runtime(record)
        barrier = threading.Barrier(2)
        outcomes = []

        def corpus_action():
            barrier.wait()
            try:
                with self.store.transaction() as connection:
                    activate(connection, record, runtime, NOW)
                outcomes.append("corpus")
            except AppError:
                outcomes.append("corpus-blocked")

        def legacy_action():
            barrier.wait()
            try:
                with self.store.transaction() as connection:
                    ledger = TransactionGeminiCapacityLedger(
                        connection, adopted, auth
                    )
                    ledger.reserve(
                        prepared.body, replace(fence, generation=2), now=NOW
                    )
                outcomes.append("legacy")
            except AppError:
                outcomes.append("legacy-blocked")

        threads = [
            threading.Thread(target=corpus_action),
            threading.Thread(target=legacy_action),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(
            1, len([x for x in outcomes if not x.endswith("-blocked")])
        )
        self.assertEqual([], self.calls)

    def child_exit(self, action, expected):
        pid = os.fork()
        if pid == 0:
            try:
                action()
            except BaseException:
                os._exit(91)
            os._exit(92)
        _, status = os.waitpid(pid, 0)
        self.assertEqual(expected, os.waitstatus_to_exitcode(status))

    def test_real_process_exit_after_dispatch_retains_claim(self):
        record = self.approval()

        def child():
            self.on_request = lambda: os._exit(31)
            self.execute(record)

        self.child_exit(child, 31)
        with self.store.transaction() as connection:
            self.assertEqual(
                "CLAIMED",
                connection.execute(
                    "SELECT status FROM gemini_corpus_capacity_operations"
                ).fetchone()[0],
            )
        frozen = self.execute(record, descriptors={})
        self.assertTrue(json.loads(frozen)["stopped_on_unknown"])
        self.assertEqual([], self.calls)

    def test_real_process_exit_after_observation_before_freeze(self):
        record = self.approval()

        def child():
            with patch.object(
                runner, "freeze", side_effect=lambda *args: os._exit(32)
            ):
                self.execute(record)

        self.child_exit(child, 32)
        frozen = self.execute(record, descriptors={})
        self.assertEqual(
            ["predicted", "predicted"],
            [r["outcome"] for r in json.loads(frozen)["cases"]],
        )
        self.assertEqual([], self.calls)

    def test_real_export_crash_before_link_reexports_frozen_bytes(self):
        frozen = self.execute()
        target = self.root / "crashed-export.json"

        def child():
            with patch.object(os, "link", side_effect=lambda *a: os._exit(33)):
                runner.publish(frozen, target)

        self.child_exit(child, 33)
        self.assertFalse(target.exists())
        self.assertTrue(list(self.root.glob(".corpus-export-*")))
        runner.publish(read_frozen(self.db), target)
        self.assertEqual(frozen, target.read_bytes())
        self.assertEqual(2, len(self.calls))

    def test_exact_handle_cannot_be_relabelled_to_other_ordinal(self):
        from dataclasses import replace

        record = self.approval()
        runtime = self.runtime(record)
        pipes = CorpusPipes(
            self.descriptors((0,)), [0], runtime.binding, runtime.record_sha256
        )
        try:
            wrong = replace(
                runtime,
                credential_handle=pipes.handle(0, runtime.record_sha256),
                ordinal=1,
            )
            with self.assertRaises(AppError):
                wrong.require(NOW)
        finally:
            pipes.close()

    def test_independent_review_slow_cleanup_cannot_accept_late_results(self):
        import time

        plan = host_plan()
        plan["timeout_seconds"] = 1.0
        record = self.approval(self.disclosure(plan=plan))
        started = time.monotonic()
        with patch.object(
            Connection, "close", lambda connection: time.sleep(1.4)
        ):
            frozen = runner.run(
                self.db,
                self.owner,
                self.raw,
                record,
                self.descriptors(),
                transport=self.transport,
                clock=lambda: NOW + (time.monotonic() - started),
            )
        self.assertEqual(
            ["unknown", "not_run"],
            [r["outcome"] for r in json.loads(frozen)["cases"]],
        )
        self.assertEqual(1, len(self.calls))

    def test_independent_review_lock_failure_closes_owned_pipes(self):
        record = self.approval()
        descriptors = self.descriptors()
        lease = self.store.acquire_service()
        try:
            with self.assertRaises(AppError):
                self.execute(record, descriptors=descriptors)
            for fd in descriptors.values():
                with self.assertRaises(OSError):
                    os.fstat(fd)
        finally:
            lease.close()

    def test_independent_review_lease_held_until_cleanup_actually_ends(self):
        import threading
        import time

        plan = host_plan()
        plan["timeout_seconds"] = 0.5
        record = self.approval(self.disclosure(plan=plan))
        entered = threading.Event()
        release = threading.Event()
        errors = []

        def cleanup(connection):
            entered.set()
            if not release.wait(5):
                raise TimeoutError("invented cleanup")

        def work():
            try:
                self.execute(record)
            except BaseException as error:
                errors.append(type(error).__name__)

        with patch.object(Connection, "close", cleanup):
            thread = threading.Thread(target=work)
            thread.start()
            try:
                self.assertTrue(entered.wait(5))
                time.sleep(0.6)
                self.assertTrue(thread.is_alive())
                with self.assertRaises(AppError):
                    self.store.acquire_service()
            finally:
                release.set()
                thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual([], errors)
        lease = self.store.acquire_service()
        lease.close()

    def test_fixture_after_prior_smoke_and_activation_is_preserved_but_stales_corpus(
        self,
    ):
        from cartreadback_app.service import Service

        self.legacy_gemini()
        record = self.approval(self.disclosure(plan=host_plan(3)))
        runtime = self.runtime(record)
        with self.store.transaction() as connection:
            activate(connection, record, runtime, NOW)
        service = Service(self.store)
        try:
            result = service.mutate(
                self.owner,
                "analyze",
                {
                    "expected_revision": 0,
                    "sku_id": "KB-UK-C2C",
                    "conditions": [{"kind": "layout", "value": "UK_QWERTY"}],
                },
            )
            self.assertEqual("REVIEW_REQUIRED", result["checkout"]["state"])
        finally:
            service.close()
        with self.assertRaises(AppError):
            self.execute(record, descriptors={})
        self.assertEqual([], self.calls)

    def test_other_legacy_ledgers_cannot_hide_unknown_orphans(self):
        self.disclosure()
        for table in ("budget_operations", "context_capacity_operations"):
            with self.store.transaction() as connection:
                if table == "budget_operations":
                    connection.execute(
                        "INSERT INTO budget_operations(operation_id,request_sha256,input_tokens,output_tokens,reserved_micro_usd,status) VALUES('invented-orphan',?,1,1,0,'UNKNOWN')",
                        ("a" * 64,),
                    )
                else:
                    connection.execute(
                        "INSERT INTO context_capacity_operations(operation_id,reservation,fence_sha256,status) VALUES('invented-orphan','{}',?,'UNKNOWN')",
                        ("a" * 64,),
                    )
            with self.subTest(table=table), self.assertRaises(AppError):
                self.disclosure()
            with self.store.transaction() as connection:
                connection.execute(
                    f"DELETE FROM {table} WHERE operation_id='invented-orphan'"
                )

    def test_changed_model_policy_window_and_prior_snapshot_stale_approval(
        self,
    ):
        record = self.approval()
        for target, key, value in (
            ("config", "expected_model_version", CURRENT_MODEL + "-new"),
            ("policy", "host_decision_record_sha256", "e" * 64),
            ("limits", "expires_at", NOW + 99),
        ):
            changed = copy.deepcopy(record)
            changed["request"]["plan"][target][key] = value
            # A changed external record cannot reuse the old request checksum.
            with self.subTest(target=target), self.assertRaises(AppError):
                self.execute(changed, descriptors={})
        self.assertEqual([], self.calls)

    def test_normalized_accounting_tuple_tampering_blocks_freeze(self):
        record = self.approval()
        runtime = self.runtime(record)
        with self.store.transaction() as connection:
            activate(connection, record, runtime, NOW)
        pipes = CorpusPipes(
            self.descriptors((0,)), [0], runtime.binding, runtime.record_sha256
        )
        try:
            self.assertEqual(
                "KNOWN",
                runner._execute(self.store, runtime, 0, pipes, lambda: NOW),
            )
        finally:
            pipes.close()
        with self.store.transaction() as connection:
            raw = connection.execute(
                "SELECT observation FROM gemini_corpus_capacity_operations"
            ).fetchone()[0]
            value = json.loads(raw)
            value["request_sha256"] = "f" * 64
            connection.execute(
                "UPDATE gemini_corpus_capacity_operations SET observation=?",
                (canonical(value),),
            )
        with self.assertRaises(AppError):
            self.execute(record, descriptors=self.descriptors((1,)))
        self.assertEqual(1, len(self.calls))

    def test_review_v2_deadline_after_observation_lock_wait(self):
        import threading
        import time

        plan = host_plan()
        plan["timeout_seconds"] = 1.5
        record = self.approval(self.disclosure(plan=plan))
        started = time.monotonic()
        held = threading.Event()
        workers = []
        faults = []

        def writer():
            try:
                with self.store.transaction():
                    held.set()
                    time.sleep(2.0)
            except BaseException as error:
                faults.append(type(error).__name__)

        def cleanup(connection):
            if not workers:
                thread = threading.Thread(target=writer)
                workers.append(thread)
                thread.start()
                if not held.wait(5):
                    raise AssertionError("invented writer did not start")

        try:
            with patch.object(Connection, "close", cleanup):
                frozen = runner.run(
                    self.db,
                    self.owner,
                    self.raw,
                    record,
                    self.descriptors(),
                    transport=self.transport,
                    clock=lambda: NOW + time.monotonic() - started,
                )
        finally:
            for thread in workers:
                thread.join(5)
        self.assertEqual([], faults)
        self.assertEqual(
            ["unknown", "not_run"],
            [item["outcome"] for item in json.loads(frozen)["cases"]],
        )
        self.assertEqual(1, len(self.calls))

    def test_review_v2_constructor_failure_never_double_closes_reused_fd(self):
        import threading

        record = self.approval()
        read, write = os.pipe()
        os.close(write)
        alias = os.dup(read)
        freed = threading.Event()
        resume = threading.Event()
        faults = []
        reused = []
        original_close = CorpusPipes.close

        def close(owner):
            original_close(owner)
            freed.set()
            if not resume.wait(5):
                raise AssertionError("invented scheduling barrier timeout")

        def attempt():
            try:
                self.execute(record, descriptors={0: read, 1: alias})
            except AppError:
                pass
            except BaseException as error:
                faults.append(type(error).__name__)

        with patch.object(CorpusPipes, "close", close):
            thread = threading.Thread(target=attempt)
            thread.start()
            try:
                self.assertTrue(freed.wait(5))
                descriptor = os.open(
                    self.root / "unrelated-resource",
                    os.O_CREAT | os.O_RDWR,
                    0o600,
                )
                reused.append(descriptor)
                self.assertIn(descriptor, (read, alias))
                resume.set()
                thread.join(5)
                self.assertFalse(thread.is_alive())
                self.assertEqual([], faults)
                os.fstat(descriptor)
            finally:
                resume.set()
                thread.join(5)
                for descriptor in reused:
                    try:
                        os.close(descriptor)
                    except OSError:
                        pass

    def test_review_v3_commit_reader_wait_cannot_accept_late_completion(self):
        import threading
        import time

        plan = host_plan()
        plan["timeout_seconds"] = 1.5
        record = self.approval(self.disclosure(plan=plan))
        started = time.monotonic()
        held = threading.Event()
        workers = []
        faults = []
        original = runner.attach_result

        def reader():
            connection = self.store.connect()
            try:
                connection.execute("BEGIN")
                connection.execute(
                    "SELECT ordinal FROM gemini_corpus_requests"
                ).fetchall()
                held.set()
                time.sleep(2.0)
                connection.rollback()
            except BaseException as error:
                faults.append(type(error).__name__)
            finally:
                connection.close()

        def attach(*args, **kwargs):
            result = original(*args, **kwargs)
            if not workers:
                thread = threading.Thread(target=reader)
                workers.append(thread)
                thread.start()
                if not held.wait(5):
                    raise AssertionError("invented reader did not start")
            return result

        try:
            with patch.object(runner, "attach_result", attach):
                frozen = runner.run(
                    self.db,
                    self.owner,
                    self.raw,
                    record,
                    self.descriptors(),
                    transport=self.transport,
                    clock=lambda: NOW + time.monotonic() - started,
                )
        finally:
            for thread in workers:
                thread.join(5)
        self.assertEqual([], faults)
        self.assertEqual(
            ["unknown", "not_run"],
            [item["outcome"] for item in json.loads(frozen)["cases"]],
        )
        self.assertEqual(1, len(self.calls))

    def commit_return_patch(self, action, target=0, phase="observation"):
        """Wrap only the target observation COMMIT, never provider transport."""
        original = runner.ExistingCorpusStore.connect
        fired = []

        class WrappedConnection:
            def __init__(self, connection):
                self.connection = connection

            def __getattr__(self, name):
                return getattr(self.connection, name)

            def commit(self):
                tables = self.connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='gemini_corpus_observation_commits'"
                ).fetchone()
                pending = (
                    tables
                    and self.connection.execute(
                        "SELECT 1 FROM gemini_corpus_observation_commits m LEFT JOIN gemini_corpus_completion_receipts r ON r.ordinal=m.ordinal WHERE m.ordinal=? AND r.ordinal IS NULL",
                        (target,),
                    ).fetchone()
                )
                if tables and phase == "seal":
                    pending = self.connection.execute(
                        "SELECT 1 FROM gemini_corpus_completion_receipts WHERE ordinal=?",
                        (target,),
                    ).fetchone()
                self.connection.commit()
                if pending and not fired:
                    fired.append(True)
                    action()

        return patch.object(
            runner.ExistingCorpusStore,
            "connect",
            lambda store: WrappedConnection(original(store)),
        )

    def assert_audit_only(self, frozen, reason):
        value = json.loads(frozen)
        self.assertEqual("gemini-frozen-corpus-audit-only-v1", value["schema"])
        self.assertIs(value["scoring_eligible"], False)
        self.assertEqual(reason, value["invalidation"]["reason"])
        self.assertNotIn("cases", value)
        self.assertNotIn('"results":', frozen.decode())
        with self.assertRaises(AppError):
            read_frozen(self.db)
        self.assertEqual(frozen, read_frozen(self.db, audit_only=True))
        return value

    def test_v4_successful_late_commit_invalidates_entire_prefix(self):
        import time

        self.raw = canonical(corpus_document(3)).encode()
        plan = host_plan(3)
        plan["timeout_seconds"] = 0.8
        record = self.approval(self.disclosure(plan=plan))
        with self.commit_return_patch(lambda: time.sleep(1.0), target=1):
            frozen = self.execute(
                record, descriptors=self.descriptors((0, 1, 2))
            )
        value = self.assert_audit_only(frozen, "LATE")
        self.assertEqual(
            ["TIMELY", "LATE"],
            [r["disposition"] for r in value["completion_receipts"]],
        )
        self.assertEqual(
            ["KNOWN", "KNOWN", "NOT_RUN"],
            [r["accounting_state"] for r in value["audit_operations"]],
        )
        self.assertEqual(2, len(self.calls))
        with self.store.transaction() as connection:
            candidates = connection.execute(
                "SELECT result FROM gemini_corpus_requests WHERE result!=''"
            ).fetchall()
            self.assertEqual(
                ["predicted", "predicted"],
                [json.loads(r[0])["outcome"] for r in candidates],
            )
        with self.assertRaises(AppError):
            self.execute(record, descriptors={})
        self.assertEqual(2, len(self.calls))

    def test_v4_ambiguous_commit_preserves_known_and_invalidates(self):
        def uncertain():
            raise OSError("invented post-commit uncertainty")

        record = self.approval()
        with self.commit_return_patch(uncertain):
            frozen = self.execute(record)
        value = self.assert_audit_only(frozen, "UNCONFIRMED")
        self.assertEqual(
            ["KNOWN", "NOT_RUN"],
            [r["accounting_state"] for r in value["audit_operations"]],
        )
        self.assertEqual(1, len(self.calls))

    def test_v4_process_exit_after_commit_before_seal_invalidates(self):
        record = self.approval()

        def child():
            with patch.object(
                runner,
                "seal_completion",
                side_effect=lambda *args: os._exit(41),
            ):
                self.execute(record)

        self.child_exit(child, 41)
        with self.store.transaction() as connection:
            self.assertEqual(
                "KNOWN",
                connection.execute(
                    "SELECT status FROM gemini_corpus_capacity_operations"
                ).fetchone()[0],
            )
            self.assertEqual(
                0,
                connection.execute(
                    "SELECT count(*) FROM gemini_corpus_completion_receipts"
                ).fetchone()[0],
            )
        frozen = runner.run(
            self.db,
            self.owner,
            self.raw,
            record,
            {},
            transport=self.transport,
            clock=lambda: NOW + 1000,
        )
        self.assert_audit_only(frozen, "UNCONFIRMED")
        self.assertEqual([], self.calls)

    def test_v4_process_exit_after_timely_seal_resumes_only_suffix(self):
        record = self.approval()
        original = runner._execute

        def child():
            def execute(*args, **kwargs):
                original(*args, **kwargs)
                os._exit(42)

            with patch.object(runner, "_execute", execute):
                self.execute(record)

        self.child_exit(child, 42)
        # Child used invented response ID 0; the suffix must use a different ID.
        self.calls.append(b"prior child request, no credentials")
        frozen = self.execute(record, descriptors=self.descriptors((1,)))
        self.assertEqual(
            ["predicted", "predicted"],
            [r["outcome"] for r in json.loads(frozen)["cases"]],
        )
        self.assertEqual(2, len(self.calls))

    def test_v4_delayed_seal_records_past_timely_commit_without_renewal(self):
        import time

        self.raw = canonical(corpus_document(1)).encode()
        plan = host_plan(1)
        plan["timeout_seconds"] = 0.8
        record = self.approval(self.disclosure(plan=plan))
        original = runner.seal_completion

        def delayed(*args, **kwargs):
            time.sleep(1.0)
            return original(*args, **kwargs)

        with patch.object(runner, "seal_completion", delayed):
            value = json.loads(
                self.execute(record, descriptors=self.descriptors((0,)))
            )
        self.assertEqual(
            "TIMELY", value["completion_receipts"][0]["disposition"]
        )
        self.assertEqual("predicted", value["cases"][0]["outcome"])
        self.assertEqual(1, len(self.calls))

    def unsealed_prefix(self, record):
        with patch.object(
            runner,
            "seal_completion",
            side_effect=RuntimeError("invented seal failure"),
        ):
            with self.assertRaises(RuntimeError):
                self.execute(record)

    def test_v4_missing_receipt_blocks_direct_reserve_freeze_and_guard(self):
        from cartreadback_app.gemini_corpus_ledger import CorpusCapacityLedger

        record = self.approval()
        runtime = self.runtime(record)
        self.unsealed_prefix(record)
        with self.store.transaction() as connection:
            ledger = CorpusCapacityLedger(
                connection, runtime.policy, runtime.authorization
            )
            _, prepared = runtime.exact_case(1)
            with self.assertRaises(AppError):
                ledger.reserve(prepared.body, runtime.fence(1), now=NOW)
            with self.assertRaises(AppError):
                ledger._approved_tuple(
                    runtime.fence(1), prepared.request_sha256, None
                )
            with self.assertRaises(AppError):
                runner.freeze(connection, runtime)
        self.assertEqual(1, len(self.calls))

    def test_v4_old_unsealed_candidates_are_never_grandfathered(self):
        record = self.approval()
        self.unsealed_prefix(record)
        with self.store.transaction() as connection:
            connection.execute("DELETE FROM gemini_corpus_observation_commits")
        frozen = self.execute(record, descriptors={})
        value = self.assert_audit_only(frozen, "UNCONFIRMED")
        self.assertIsNone(
            value["completion_receipts"][0]["observation_commit_sha256"]
        )
        self.assertEqual(1, len(self.calls))

    def test_v4_receipt_tamper_duplicate_orphan_and_missing_rejected(self):
        import sqlite3

        record = self.approval()
        runtime = self.runtime(record)
        self.execute(record)
        with self.store.transaction() as connection:
            original = connection.execute(
                "SELECT document,sha256 FROM gemini_corpus_completion_receipts WHERE ordinal=0"
            ).fetchone()
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO gemini_corpus_completion_receipts VALUES(0,?,?)",
                    tuple(original),
                )
            with self.assertRaises(AppError):
                runner.seal_completion(connection, runtime, 0, "TIMELY")
        for field in (
            "approved_record_sha256",
            "request_sha256",
            "runtime_sha256",
            "candidate_sha256",
            "accounting_sha256",
            "operation_id",
            "ordinal",
        ):
            with self.subTest(field=field):
                value = json.loads(original[0])
                value[field] = 1 if field == "ordinal" else "bad"
                with self.store.transaction() as connection:
                    connection.execute(
                        "UPDATE gemini_corpus_completion_receipts SET document=?,sha256=? WHERE ordinal=0",
                        (canonical(value), digest(value)),
                    )
                with self.assertRaises(AppError):
                    read_frozen(self.db)
                with self.store.transaction() as connection:
                    connection.execute(
                        "UPDATE gemini_corpus_completion_receipts SET document=?,sha256=? WHERE ordinal=0",
                        tuple(original),
                    )
        with self.store.transaction() as connection:
            connection.execute(
                "INSERT INTO gemini_corpus_completion_receipts VALUES(5,?,?)",
                tuple(original),
            )
        with self.assertRaises(AppError):
            read_frozen(self.db)
        with self.store.transaction() as connection:
            connection.execute(
                "DELETE FROM gemini_corpus_completion_receipts WHERE ordinal IN (0,5)"
            )
        with self.assertRaises(AppError):
            read_frozen(self.db)
        with self.store.transaction() as connection:
            with self.assertRaises(AppError):
                runner.freeze(connection, runtime)

    def test_v4_old_frozen_schema_rejected_even_with_valid_byte_hash(self):
        frozen = json.loads(self.execute())
        frozen["schema"] = "gemini-frozen-corpus-results-v1"
        raw = canonical(frozen) + "\n"
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE gemini_corpus_identity SET frozen=?,frozen_sha256=?",
                (raw, text_hash(raw)),
            )
        with self.assertRaises(AppError):
            read_frozen(self.db)
        with self.assertRaises(AppError):
            read_frozen(self.db, audit_only=True)

    def test_v4_normal_cli_export_refuses_audit_only_artifact(self):
        def uncertain():
            raise OSError("invented commit uncertainty")

        with self.commit_return_patch(uncertain):
            frozen = self.execute()
        target = self.root / "predictions.json"
        audit = self.root / "audit.json"
        self.assertEqual(
            1,
            runner.main(
                ["export", "--db", str(self.db), "--output", str(target)]
            ),
        )
        self.assertFalse(target.exists())
        self.assertEqual(
            0,
            runner.main(
                ["export-audit", "--db", str(self.db), "--output", str(audit)]
            ),
        )
        self.assertEqual(frozen, audit.read_bytes())

    def test_v4_expiry_while_sealing_cannot_dispatch_suffix(self):
        now = [NOW]
        record = self.approval()
        original = runner.seal_completion

        def expired(*args, **kwargs):
            original(*args, **kwargs)
            now[0] = NOW + 1000

        with patch.object(runner, "seal_completion", expired):
            frozen = runner.run(
                self.db,
                self.owner,
                self.raw,
                record,
                self.descriptors(),
                transport=self.transport,
                clock=lambda: now[0],
            )
        self.assert_audit_only(frozen, "EXPIRED")
        self.assertEqual(1, len(self.calls))
        with self.store.transaction() as connection:
            receipt = json.loads(
                connection.execute(
                    "SELECT document FROM gemini_corpus_completion_receipts"
                ).fetchone()[0]
            )
            self.assertEqual("TIMELY", receipt["disposition"])
            self.assertIsNone(
                connection.execute(
                    "SELECT operation_id FROM gemini_corpus_requests WHERE ordinal=1"
                ).fetchone()[0]
            )
        with self.assertRaises(AppError):
            runner.run(
                self.db,
                self.owner,
                self.raw,
                record,
                {},
                transport=self.transport,
                clock=lambda: now[0],
            )
        self.assertEqual(1, len(self.calls))

    def test_v4_crash_during_seal_transaction_cannot_restore_timely(self):
        record = self.approval()
        original = runner.seal_completion

        def child():
            def interrupted(*args, **kwargs):
                original(*args, **kwargs)
                os._exit(43)

            with patch.object(runner, "seal_completion", interrupted):
                self.execute(record)

        self.child_exit(child, 43)
        frozen = self.execute(record, descriptors={})
        self.assert_audit_only(frozen, "UNCONFIRMED")
        self.assertEqual([], self.calls)

    def test_v4_terminal_invalidation_blocks_direct_ledger_admission(self):
        from cartreadback_app.gemini_corpus_ledger import CorpusCapacityLedger

        record = self.approval()
        runtime = self.runtime(record)

        def uncertain():
            raise OSError("invented commit uncertainty")

        with (
            self.commit_return_patch(uncertain),
            patch.object(
                runner,
                "freeze",
                side_effect=RuntimeError("invented freeze interruption"),
            ),
        ):
            with self.assertRaises(RuntimeError):
                self.execute(record)
        with self.store.transaction() as connection:
            ledger = CorpusCapacityLedger(
                connection, runtime.policy, runtime.authorization
            )
            _, prepared = runtime.exact_case(1)
            with self.assertRaises(AppError):
                ledger.reserve(prepared.body, runtime.fence(1), now=NOW)
        self.assert_audit_only(
            self.execute(record, descriptors={}), "UNCONFIRMED"
        )
        self.assertEqual(1, len(self.calls))

    def test_v4_late_unknown_commit_is_audit_only_too(self):
        import time

        self.unknown_at = 0
        plan = host_plan()
        plan["timeout_seconds"] = 0.8
        record = self.approval(self.disclosure(plan=plan))
        with self.commit_return_patch(lambda: time.sleep(1.0)):
            frozen = self.execute(record)
        value = self.assert_audit_only(frozen, "LATE")
        self.assertEqual(
            "UNKNOWN", value["audit_operations"][0]["accounting_state"]
        )
        self.assertEqual(1, len(self.calls))

    def test_v4_audit_export_rejects_prediction_fields_even_with_new_hash(self):
        def uncertain():
            raise OSError("invented commit uncertainty")

        with self.commit_return_patch(uncertain):
            original = self.execute()
        for key in ("cases", "results"):
            value = json.loads(original)
            value[key] = [{"status": "invented prediction must not export"}]
            raw = canonical(value) + "\n"
            with self.store.transaction() as connection:
                connection.execute(
                    "UPDATE gemini_corpus_identity SET frozen=?,frozen_sha256=?",
                    (raw, text_hash(raw)),
                )
            with self.assertRaises(AppError):
                read_frozen(self.db, audit_only=True)

    def test_v4_missing_protocol_table_never_grandfathers_frozen_results(self):
        self.execute()
        with self.store.transaction() as connection:
            connection.execute("DROP TABLE gemini_corpus_completion_receipts")
        with self.assertRaises(AppError):
            read_frozen(self.db)

    def test_v4_normal_run_cli_does_not_publish_audit_as_predictions(self):
        def uncertain():
            raise OSError("invented commit uncertainty")

        record = self.approval()
        with self.commit_return_patch(uncertain):
            frozen = self.execute(record)
        owner = self.root / "invented-owner"
        corpus = self.root / "invented-input.json"
        approval = self.root / "invented-approval.json"
        output = self.root / "must-not-publish-predictions.json"
        owner.write_text(self.owner)
        corpus.write_bytes(self.raw)
        approval.write_text(canonical(record))
        with patch.object(runner, "run", return_value=frozen):
            self.assertEqual(
                1,
                runner.main(
                    [
                        "run",
                        "--db",
                        str(self.db),
                        "--owner-file",
                        str(owner),
                        "--corpus",
                        str(corpus),
                        "--approved-record",
                        str(approval),
                        "--output",
                        str(output),
                    ]
                ),
            )
        self.assertFalse(output.exists())

    def test_v5_expiry_after_durable_timely_prefix_freezes_terminal_audit(self):
        now = [NOW]
        record = self.approval()
        with self.commit_return_patch(
            lambda: now.__setitem__(0, NOW + 1000), phase="seal"
        ):
            frozen = runner.run(
                self.db,
                self.owner,
                self.raw,
                record,
                self.descriptors(),
                transport=self.transport,
                clock=lambda: now[0],
            )
        value = self.assert_audit_only(frozen, "EXPIRED")
        self.assertEqual(1, len(self.calls))
        self.assertEqual(
            ["KNOWN", "NOT_RUN"],
            [r["accounting_state"] for r in value["audit_operations"]],
        )
        self.assertEqual(
            ["TIMELY"], [r["disposition"] for r in value["completion_receipts"]]
        )
        self.assertEqual(
            value["receipt_hashes"], value["invalidation"]["receipt_hashes"]
        )
        self.assertEqual([1], value["invalidation"]["not_run_ordinals"])
        with self.store.transaction() as connection:
            self.assertEqual(
                "predicted",
                json.loads(
                    connection.execute(
                        "SELECT result FROM gemini_corpus_requests WHERE ordinal=0"
                    ).fetchone()[0]
                )["outcome"],
            )
            self.assertEqual(
                1,
                connection.execute(
                    "SELECT count(*) FROM gemini_corpus_capacity_operations"
                ).fetchone()[0],
            )
        with self.assertRaises(AppError):
            runner.run(
                self.db,
                self.owner,
                self.raw,
                record,
                {},
                transport=self.transport,
                clock=lambda: now[0],
            )
        self.assertEqual(frozen, read_frozen(self.db, audit_only=True))

    def test_v5_expired_restart_finalizes_without_any_new_pipe(self):
        record = self.approval()
        original = runner._execute

        def interrupted(*args, **kwargs):
            original(*args, **kwargs)
            raise KeyboardInterrupt(
                "invented process interruption after durable seal"
            )

        with patch.object(runner, "_execute", interrupted):
            with self.assertRaises(KeyboardInterrupt):
                self.execute(record)
        with self.store.transaction() as connection:
            self.assertEqual(
                "",
                connection.execute(
                    "SELECT frozen FROM gemini_corpus_identity"
                ).fetchone()[0],
            )
        frozen = runner.run(
            self.db,
            self.owner,
            self.raw,
            record,
            {},
            transport=self.transport,
            clock=lambda: NOW + 1000,
        )
        self.assert_audit_only(frozen, "EXPIRED")
        self.assertEqual(1, len(self.calls))

    def test_v5_expiry_is_exact_terminal_append_not_new_authority(self):
        from cartreadback_app.gemini_corpus_ledger import CorpusCapacityLedger

        record = self.approval()
        runtime = self.runtime(record)
        original = runner._execute

        def interrupted(*args, **kwargs):
            original(*args, **kwargs)
            raise KeyboardInterrupt("invented interruption")

        with patch.object(runner, "_execute", interrupted):
            with self.assertRaises(KeyboardInterrupt):
                self.execute(record)
        expires_at = record["request"]["plan"]["limits"]["expires_at"]
        with self.store.transaction() as connection:
            candidate = tuple(
                connection.execute(
                    "SELECT result,result_sha256 FROM gemini_corpus_requests WHERE ordinal=0"
                ).fetchone()
            )
            receipt = tuple(
                connection.execute(
                    "SELECT document,sha256 FROM gemini_corpus_completion_receipts WHERE ordinal=0"
                ).fetchone()
            )
            identity = connection.execute(
                "SELECT document FROM gemini_corpus_identity"
            ).fetchone()[0]
            self.assertFalse(
                runner.expire_incomplete(
                    connection, runtime, expires_at - 0.001
                )
            )
            self.assertTrue(
                runner.expire_incomplete(connection, runtime, expires_at)
            )
            self.assertTrue(
                runner.expire_incomplete(connection, runtime, expires_at + 1)
            )
            self.assertEqual(
                1,
                connection.execute(
                    "SELECT count(*) FROM gemini_corpus_invalidation"
                ).fetchone()[0],
            )
            self.assertEqual(
                candidate,
                tuple(
                    connection.execute(
                        "SELECT result,result_sha256 FROM gemini_corpus_requests WHERE ordinal=0"
                    ).fetchone()
                ),
            )
            self.assertEqual(
                receipt,
                tuple(
                    connection.execute(
                        "SELECT document,sha256 FROM gemini_corpus_completion_receipts WHERE ordinal=0"
                    ).fetchone()
                ),
            )
            self.assertEqual(
                identity,
                connection.execute(
                    "SELECT document FROM gemini_corpus_identity"
                ).fetchone()[0],
            )
            ledger = CorpusCapacityLedger(
                connection, runtime.policy, runtime.authorization
            )
            _, prepared = runtime.exact_case(1)
            with self.assertRaises(AppError):
                ledger.reserve(prepared.body, runtime.fence(1), now=NOW)
            frozen = runner.freeze(connection, runtime)
        self.assert_audit_only(frozen, "EXPIRED")
        self.assertEqual(1, len(self.calls))

    def test_v5_not_run_case_identity_mismatch_is_rejected_on_export(self):
        self.unknown_at = 0
        frozen = json.loads(self.execute())
        frozen["cases"][1]["case_id"] = "unrelated/invented-case"
        changed = canonical(frozen) + "\n"
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE gemini_corpus_identity SET frozen=?,frozen_sha256=?",
                (changed, text_hash(changed)),
            )
        with self.assertRaises(AppError):
            read_frozen(self.db)

    def test_v5_entire_not_run_placeholder_and_source_mapping_are_exact(self):
        # Deliberate local corruption with recomputed hashes tests contract
        # validation, not protection from an attacker controlling the database.
        self.unknown_at = 0
        original = json.loads(self.execute())
        changes = {
            "ordinal": 7,
            "case_id": "invented/wrong",
            "condition_ids": ["wrong"],
            "request_sha256": "f" * 64,
            "operation_id": "invented-other",
            "accounting_state": "KNOWN",
            "outcome": "predicted",
            "error_code": "OTHER",
            "results": [],
            "extra": True,
        }
        for field, changed_value in changes.items():
            with self.subTest(field=field):
                value = copy.deepcopy(original)
                value["cases"][1][field] = changed_value
                changed = canonical(value) + "\n"
                with self.store.transaction() as connection:
                    connection.execute(
                        "UPDATE gemini_corpus_identity SET frozen=?,frozen_sha256=?",
                        (changed, text_hash(changed)),
                    )
                with self.assertRaises(AppError):
                    read_frozen(self.db)
        value = copy.deepcopy(original)
        value["mapping"][1]["source_identity_sha256"] = "e" * 64
        changed = canonical(value) + "\n"
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE gemini_corpus_identity SET frozen=?,frozen_sha256=?",
                (changed, text_hash(changed)),
            )
        with self.assertRaises(AppError):
            read_frozen(self.db)

    def test_v5_expired_audit_identity_tampering_is_rejected(self):
        now = [NOW]
        record = self.approval()
        with self.commit_return_patch(
            lambda: now.__setitem__(0, NOW + 1000), phase="seal"
        ):
            runner.run(
                self.db,
                self.owner,
                self.raw,
                record,
                self.descriptors(),
                transport=self.transport,
                clock=lambda: now[0],
            )
        with self.store.transaction() as connection:
            original = json.loads(
                connection.execute(
                    "SELECT document FROM gemini_corpus_invalidation"
                ).fetchone()[0]
            )
        for field, changed in (
            ("observed_at", NOW),
            ("completed_prefix_length", 0),
            ("receipt_hashes", []),
            ("not_run_ordinals", [0, 1]),
            ("approved_record_sha256", "f" * 64),
        ):
            with self.subTest(field=field):
                value = copy.deepcopy(original)
                value[field] = changed
                with self.store.transaction() as connection:
                    connection.execute(
                        "UPDATE gemini_corpus_invalidation SET document=?,sha256=?",
                        (canonical(value), digest(value)),
                    )
                with self.assertRaises(AppError):
                    read_frozen(self.db, audit_only=True)
