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
