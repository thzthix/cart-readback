"""Same-store immutable corpus grants, paired operations and frozen results."""

import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from cartreadback_app.analysis_history import legacy_analysis_history_guard
from cartreadback_app.context_capacity import initialize_context_capacity
from cartreadback_app.gemini_capacity import (
    MAX_INPUT_TOKENS,
    MAX_INTEGER,
    OUTPUT_TOKENS,
    GeminiReservation,
    TransactionGeminiCapacityLedger,
    gemini_database_identity,
    initialize_gemini_capacity,
    initialize_gemini_database,
)
from cartreadback_app.gemini_corpus import blocked
from cartreadback_app.responses_adapter import _validate_results
from cartreadback_app.storage import Store
from cartreadback_app.validation import (
    canonical,
    digest,
    integer,
    object_fields,
    text_hash,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS gemini_corpus_identity (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    document TEXT NOT NULL, frozen TEXT NOT NULL DEFAULT '',
    frozen_sha256 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS gemini_corpus_requests (
    ordinal INTEGER PRIMARY KEY, mapping TEXT NOT NULL,
    operation_id TEXT UNIQUE, result TEXT NOT NULL DEFAULT '',
    result_sha256 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS gemini_corpus_observation_commits (
    ordinal INTEGER PRIMARY KEY, document TEXT NOT NULL, sha256 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gemini_corpus_completion_receipts (
    ordinal INTEGER PRIMARY KEY, document TEXT NOT NULL, sha256 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gemini_corpus_invalidation (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    document TEXT NOT NULL, sha256 TEXT NOT NULL
);
"""
PREDICTIONS_SCHEMA = "gemini-frozen-corpus-results-v2"
AUDIT_SCHEMA = "gemini-frozen-corpus-audit-only-v1"
_HISTORY_TABLES = (
    "catalog",
    "sessions",
    "reviews",
    "confirmations",
    "orders",
    "operations",
    "analysis_operations",
    "events",
    "budget_identity",
    "budget_operations",
    "analysis_preflights",
    "context_capacity_identity",
    "context_capacity_operations",
    "gemini_capacity_identity",
    "gemini_capacity_operations",
    "gemini_database_identity",
)


def database_file_identity(path) -> str:
    """Bind path, device and inode; never recreate or rotate an approved store."""
    path = Path(path).resolve(strict=True)
    info = path.stat()
    return digest(
        {"path": str(path), "device": info.st_dev, "inode": info.st_ino}
    )


class ExistingCorpusStore(Store):
    """Use the existing DB and existing service lock, without seeding catalog."""

    def __init__(self, path, file_identity=None):
        """Retain a physical existing database, never invoke Store's creator."""
        self.path = Path(path).resolve(strict=True)
        self.file_identity = file_identity or database_file_identity(self.path)

    def connect(self):
        """Use mode=rw and recheck identity so races cannot create a fresh DB."""
        if database_file_identity(self.path) != self.file_identity:
            raise blocked()
        connection = sqlite3.connect(
            self.path.as_uri() + "?mode=rw",
            uri=True,
            timeout=5,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection


def commit_observation(store, deadline, observe):
    """Bound SQLite lock waits, not OS/fsync latency; measure actual COMMIT return.

    The callback writes only provisional accounting/candidates. A successful
    commit does not itself accept semantics. Any exception is reconciled against
    durable rows by the caller, never assumed to mean rollback succeeded.
    """
    connection = store.connect()
    try:
        connection.execute(
            f"PRAGMA busy_timeout={min(5000, int(deadline.remaining() * 1000))}"
        )
        connection.execute("BEGIN IMMEDIATE")
        deadline.remaining()
        state = observe(connection)
        connection.execute(
            f"PRAGMA busy_timeout={min(5000, int(deadline.remaining() * 1000))}"
        )
        deadline.remaining()
        connection.commit()
        returned_at = time.monotonic()
        disposition = "TIMELY" if returned_at < deadline.expires_at else "LATE"
        return state, disposition
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.close()


def _protocol_rows(connection):
    return connection.execute(
        "SELECT r.*,c.status,c.observation,c.reservation FROM gemini_corpus_requests r "
        "LEFT JOIN gemini_corpus_capacity_operations c "
        "ON c.operation_id=r.operation_id ORDER BY r.ordinal"
    ).fetchall()


def _candidate_binding(record_sha256, request, row):
    item = request["mapping"][row["ordinal"]]
    if (
        row["mapping"] != canonical(item)
        or row["status"] not in ("KNOWN", "UNKNOWN")
        or not row["operation_id"]
        or not row["result"]
        or text_hash(row["result"]) != row["result_sha256"]
    ):
        raise blocked()
    return {
        "approved_record_sha256": record_sha256,
        "ordinal": row["ordinal"],
        "case_id": item["case_id"],
        "operation_id": row["operation_id"],
        "request_sha256": item["request_sha256"],
        "runtime_sha256": request["runtime_sha256"],
        "accounting_state": row["status"],
        "candidate_sha256": row["result_sha256"],
        "accounting_sha256": text_hash(row["observation"]),
    }


def completion_state(connection, record_sha256, request):
    """Verify append-only markers, receipts and terminal invalidation both ways.

    Missing receipts are returned for crash recovery, never accepted as timely.
    This check needs no credential, current window, prompt or runtime code match.
    """
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    if not {
        "gemini_corpus_observation_commits",
        "gemini_corpus_completion_receipts",
        "gemini_corpus_invalidation",
    }.issubset(tables):
        raise blocked()
    rows = _protocol_rows(connection)
    if len(rows) != len(request["mapping"]):
        raise blocked()
    markers = {
        row["ordinal"]: row
        for row in connection.execute(
            "SELECT * FROM gemini_corpus_observation_commits"
        )
    }
    receipts = {
        row["ordinal"]: row
        for row in connection.execute(
            "SELECT * FROM gemini_corpus_completion_receipts"
        )
    }
    if (set(markers) | set(receipts)) - set(range(len(rows))):
        raise blocked()
    verified = {}
    missing = []
    for index, row in enumerate(rows):
        if row["ordinal"] != index or row["mapping"] != canonical(
            request["mapping"][index]
        ):
            raise blocked()
        marker = markers.get(index)
        receipt = receipts.get(index)
        if not (marker or receipt or row["status"] == "KNOWN"):
            continue
        binding = _candidate_binding(record_sha256, request, row)
        if marker:
            expected = {"schema": "gemini-provisional-commit-v1", **binding}
            if marker["document"] != canonical(expected) or marker[
                "sha256"
            ] != digest(expected):
                raise blocked()
        if receipt is None:
            missing.append(index)
            continue
        value = json.loads(receipt["document"])
        disposition = value.get("disposition")
        if disposition not in ("TIMELY", "LATE", "UNCONFIRMED") or (
            disposition != "UNCONFIRMED" and marker is None
        ):
            raise blocked()
        expected = {
            "schema": "gemini-completion-receipt-v1",
            **binding,
            "observation_commit_sha256": marker["sha256"] if marker else None,
            "disposition": disposition,
        }
        if receipt["document"] != canonical(expected) or receipt[
            "sha256"
        ] != digest(expected):
            raise blocked()
        verified[index] = expected
    invalid = connection.execute(
        "SELECT document,sha256 FROM gemini_corpus_invalidation WHERE singleton=1"
    ).fetchone()
    terminal = [
        value for value in verified.values() if value["disposition"] != "TIMELY"
    ]
    invalidation = None
    if invalid:
        invalidation = json.loads(invalid["document"])
        match = next(
            (
                value
                for value in terminal
                if digest(value) == invalidation.get("receipt_sha256")
            ),
            None,
        )
        expected = _invalidation_value(record_sha256, match) if match else None
        if (
            expected is None
            or invalid["document"] != canonical(expected)
            or invalid["sha256"] != digest(expected)
        ):
            raise blocked()
    elif terminal:
        raise blocked()
    return verified, invalidation, missing


def _invalidation_value(record_sha256, receipt):
    return {
        "schema": "gemini-corpus-invalidation-v1",
        "approved_record_sha256": record_sha256,
        "scoring_eligible": False,
        "reason": receipt["disposition"],
        "ordinal": receipt["ordinal"],
        "operation_id": receipt["operation_id"],
        "receipt_sha256": digest(receipt),
    }


def stage_observation(connection, runtime, ordinal):
    """Atomically mark a candidate provisional in its accounting transaction."""
    if not connection.in_transaction:
        raise blocked()
    row = _protocol_rows(connection)[ordinal]
    value = {
        "schema": "gemini-provisional-commit-v1",
        **_candidate_binding(runtime.record_sha256, runtime.request, row),
    }
    connection.execute(
        "INSERT INTO gemini_corpus_observation_commits VALUES(?,?,?)",
        (ordinal, canonical(value), digest(value)),
    )


def seal_completion(connection, runtime, ordinal, disposition):
    """Append a measured commit fact; late/unconfirmed facts invalidate all cases."""
    if not connection.in_transaction:
        raise blocked()
    receipts, invalidation, missing = completion_state(
        connection, runtime.record_sha256, runtime.request
    )
    if (
        ordinal in receipts
        or ordinal not in missing
        or disposition not in ("TIMELY", "LATE", "UNCONFIRMED")
    ):
        raise blocked()
    row = _protocol_rows(connection)[ordinal]
    marker = connection.execute(
        "SELECT sha256 FROM gemini_corpus_observation_commits WHERE ordinal=?",
        (ordinal,),
    ).fetchone()
    if disposition != "UNCONFIRMED" and (
        marker is None or invalidation is not None
    ):
        raise blocked()
    value = {
        "schema": "gemini-completion-receipt-v1",
        **_candidate_binding(runtime.record_sha256, runtime.request, row),
        "observation_commit_sha256": marker[0] if marker else None,
        "disposition": disposition,
    }
    connection.execute(
        "INSERT INTO gemini_corpus_completion_receipts VALUES(?,?,?)",
        (ordinal, canonical(value), digest(value)),
    )
    if disposition != "TIMELY" and invalidation is None:
        terminal = _invalidation_value(runtime.record_sha256, value)
        connection.execute(
            "INSERT INTO gemini_corpus_invalidation VALUES(1,?,?)",
            (canonical(terminal), digest(terminal)),
        )
    completion_state(connection, runtime.record_sha256, runtime.request)


def invalidated(connection, runtime):
    """Return validated terminal state, including runs invalidated during recovery."""
    return (
        completion_state(connection, runtime.record_sha256, runtime.request)[1]
        is not None
    )


def prepare_database(connection, owner):
    """Initialize empty admission schemas only; never activate a corpus grant."""
    if not connection.execute(
        "SELECT 1 FROM sessions WHERE sid=?", (owner,)
    ).fetchone():
        raise blocked()
    database_id = initialize_gemini_database(connection)
    initialize_context_capacity(connection)
    initialize_gemini_capacity(connection)
    legacy_analysis_history_guard(connection)
    return database_id


def history_snapshot(connection) -> str:
    """Hash stored legacy records, including owner/catalog/fixture mutations."""
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    return digest(
        {
            name: sorted(
                canonical(dict(row))
                for row in connection.execute(f"SELECT * FROM {name}")
            )
            if name in tables
            else None
            for name in _HISTORY_TABLES
        }
    )


def prior_totals(connection) -> tuple[int, int, int, int]:
    """Count permanent historical reservations, rejecting malformed or paid rows."""
    reservations = []
    for table in ("context_capacity_operations", "gemini_capacity_operations"):
        for row in connection.execute(
            f"SELECT operation_id,reservation FROM {table}"
        ):
            value = json.loads(row["reservation"])
            if value["operation_id"] != row["operation_id"]:
                raise blocked()
            reservations.append(value)
    reservations.extend(
        dict(row)
        for row in connection.execute(
            "SELECT input_tokens,output_tokens,reserved_micro_usd FROM budget_operations"
        )
    )
    totals = [len(reservations), 0, 0, 0]
    for value in reservations:
        for index, name in enumerate(
            ("input_tokens", "output_tokens", "reserved_micro_usd"), 1
        ):
            integer(value[name], name, 0, MAX_INTEGER)
            totals[index] += value[name]
            integer(totals[index], name, 0, MAX_INTEGER)
    if totals[3] != 0:
        raise blocked()
    return tuple(totals)


def check_baseline(connection, runtime):
    """Recompute shared history on every admission/guard/result transition."""
    request = runtime.request
    legacy_analysis_history_guard(connection)
    if (
        gemini_database_identity(connection) != request["database_id"]
        or history_snapshot(connection) != request["baseline_sha256"]
        or list(prior_totals(connection)) != request["prior_totals"]
    ):
        raise blocked()


class CorpusCapacityLedger(TransactionGeminiCapacityLedger):
    """Reuse all conservative mechanics under a separate immutable grant."""

    _prefix = "gemini_corpus"

    def _approved_tuple(self, fence, request_sha256, operation_id):
        row = self._connection.execute(
            "SELECT document FROM gemini_corpus_identity WHERE singleton=1"
        ).fetchone()
        if row is None:
            raise blocked()
        request = json.loads(row[0])["request"]
        receipts, invalidation, missing = completion_state(
            self._connection, text_hash(row[0]), request
        )
        if invalidation or missing:
            raise blocked()
        for previous in range(fence.generation - 1):
            if receipts.get(previous, {}).get("disposition") != "TIMELY":
                raise blocked()
        legacy_analysis_history_guard(self._connection)
        if history_snapshot(self._connection) != request["baseline_sha256"]:
            raise blocked()
        ordinal = fence.generation - 1
        integer(ordinal, "ordinal", 0, len(request["mapping"]) - 1)
        item = request["mapping"][ordinal]
        stored = self._connection.execute(
            "SELECT mapping,operation_id FROM gemini_corpus_requests WHERE ordinal=?",
            (ordinal,),
        ).fetchone()
        if (
            stored is None
            or stored[0] != canonical(item)
            or stored[1] != operation_id
            or fence.runtime_sha256 != request["runtime_sha256"]
            or fence.owner_sha256 != request["owner_sha256"]
            or fence.source_sha256 != item["source_sha256"]
            or fence.source_identity_sha256 != item["source_identity_sha256"]
            or fence.source_revision != item["source_revision"]
            or fence.conditions_sha256 != item["conditions_sha256"]
            or request_sha256 != item["request_sha256"]
        ):
            raise blocked()

    def reserve(self, request, fence, *, now):
        """Enforce exact corpus membership even below the executable wrapper."""
        self._approved_tuple(fence, text_hash(request.decode("utf-8")), None)
        if self._connection.execute(
            "SELECT 1 FROM gemini_corpus_requests r LEFT JOIN gemini_corpus_capacity_operations c ON c.operation_id=r.operation_id WHERE r.ordinal<? AND (r.operation_id IS NULL OR c.status!='KNOWN' OR r.result='') LIMIT 1",
            (fence.generation - 1,),
        ).fetchone():
            raise blocked()
        return super().reserve(request, fence, now=now)

    def claim(self, reservation, request, current_fence, *, now):
        """Require the persisted ordered mapping before claiming once."""
        self._approved_tuple(
            current_fence, reservation.request_sha256, reservation.operation_id
        )
        return super().claim(reservation, request, current_fence, now=now)

    def validate_claim(self, claim, request, current_fence, *, now):
        """Revalidate exact finite membership at each network/secret guard."""
        self._approved_tuple(
            current_fence,
            claim.reservation.request_sha256,
            claim.reservation.operation_id,
        )
        return super().validate_claim(claim, request, current_fence, now=now)

    def observe(self, claim, envelope, **kwargs):
        """Reject a tuple-swapped observation, preserving the original claim."""
        self._approved_tuple(
            kwargs["current_fence"],
            kwargs["request_sha256"],
            claim.reservation.operation_id,
        )
        return super().observe(claim, envelope, **kwargs)

    def _prior_totals(self):
        return prior_totals(self._connection)


def _initialize(connection):
    for statement in _SCHEMA.split(";"):
        if statement.strip():
            connection.execute(statement)


def activate(connection, record, runtime, now):
    """Atomically bind exact authority, historical consumption and ordered rows."""
    runtime.require(now)
    check_baseline(connection, runtime)
    _initialize(connection)
    document = canonical(record)
    if text_hash(document) != runtime.record_sha256:
        raise blocked()
    row = connection.execute(
        "SELECT document FROM gemini_corpus_identity WHERE singleton=1"
    ).fetchone()
    if row is None:
        if connection.execute(
            "SELECT 1 FROM gemini_corpus_requests LIMIT 1"
        ).fetchone():
            raise blocked()
        totals = prior_totals(connection)
        auth = runtime.authorization
        # The new total includes all old permanent reservations, not a renewal.
        count = len(runtime.request["mapping"])
        if (
            totals[0] + count > auth.max_calls
            or totals[1] + count * MAX_INPUT_TOKENS
            > auth.max_total_input_tokens
            or totals[2] + count * OUTPUT_TOKENS > auth.max_total_output_tokens
        ):
            raise blocked()
        connection.execute(
            "INSERT INTO gemini_corpus_identity(singleton,document) VALUES(1,?)",
            (document,),
        )
        for item in runtime.request["mapping"]:
            connection.execute(
                "INSERT INTO gemini_corpus_requests(ordinal,mapping) VALUES(?,?)",
                (item["ordinal"], canonical(item)),
            )
    elif row[0] != document:
        raise blocked()
    ledger = CorpusCapacityLedger(
        connection, runtime.policy, runtime.authorization
    )
    paired_rows(connection, runtime)
    return ledger


def ledger_for(connection, runtime, now, *, fresh=True):
    """Require original stored authority before using the immutable ledger."""
    row = connection.execute(
        "SELECT document,frozen FROM gemini_corpus_identity WHERE singleton=1"
    ).fetchone()
    if (
        row is None
        or text_hash(row["document"]) != runtime.record_sha256
        or row["frozen"]
    ):
        raise blocked()
    if fresh:
        runtime.require(now)
        check_baseline(connection, runtime)
    return CorpusCapacityLedger(
        connection, runtime.policy, runtime.authorization
    )


def paired_rows(connection, runtime):
    """Validate both directions and the exact operation/result prefix."""
    rows = connection.execute(
        "SELECT r.*,c.reservation,c.status,c.observation,c.fence_sha256,c.response_id_sha256,c.request_id_sha256 FROM gemini_corpus_requests r LEFT JOIN gemini_corpus_capacity_operations c ON c.operation_id=r.operation_id ORDER BY r.ordinal"
    ).fetchall()
    mapping = runtime.request["mapping"]
    if (
        len(rows) != len(mapping)
        or connection.execute(
            "SELECT 1 FROM gemini_corpus_capacity_operations c LEFT JOIN gemini_corpus_requests r ON r.operation_id=c.operation_id WHERE r.ordinal IS NULL LIMIT 1"
        ).fetchone()
    ):
        raise blocked()
    stopped = False
    for index, row in enumerate(rows):
        if row["ordinal"] != index or row["mapping"] != canonical(
            mapping[index]
        ):
            raise blocked()
        if row["operation_id"] is None:
            if (
                row["result"]
                or row["result_sha256"]
                or row["status"] is not None
            ):
                raise blocked()
            stopped = True
            continue
        if stopped or row["status"] not in (
            "RESERVED",
            "CLAIMED",
            "KNOWN",
            "UNKNOWN",
        ):
            raise blocked()
        reservation = GeminiReservation(**json.loads(row["reservation"]))
        if (
            reservation.operation_id != row["operation_id"]
            or reservation.input_tokens != MAX_INPUT_TOKENS
            or reservation.output_tokens != OUTPUT_TOKENS
            or reservation.reserved_micro_usd != 0
            or reservation.request_sha256 != mapping[index]["request_sha256"]
            or reservation.fence_sha256 != digest(runtime.fence(index).__dict__)
            or row["fence_sha256"] != reservation.fence_sha256
            or reservation.ledger_sha256
            != text_hash(
                CorpusCapacityLedger(
                    connection, runtime.policy, runtime.authorization
                ).identity
            )
        ):
            raise blocked()
        if row["status"] != "KNOWN":
            stopped = True
        if row["status"] == "KNOWN" and (
            not row["result"] or not row["observation"]
        ):
            raise blocked()
        if row["observation"]:
            accounting = json.loads(row["observation"])
            if (
                accounting.get("request_sha256") != reservation.request_sha256
                or accounting.get("runtime_sha256")
                != runtime.authorization.runtime_sha256
                or accounting.get("response_id_sha256")
                != row["response_id_sha256"]
                or accounting.get("request_id_sha256")
                != row["request_id_sha256"]
                or accounting.get("model") != runtime.config.model
                or accounting.get("estimated_micro_usd_at_adopted_rates") != 0
                or (
                    row["status"] == "KNOWN"
                    and accounting.get("accounting_contract")
                    != "no-explicit-profile-conflict"
                )
            ):
                raise blocked()
            integer(
                accounting["input_tokens"], "input_tokens", 0, MAX_INPUT_TOKENS
            )
            integer(
                accounting["output_tokens"], "output_tokens", 0, OUTPUT_TOKENS
            )
            if (
                accounting["total_tokens"]
                != accounting["input_tokens"] + accounting["output_tokens"]
            ):
                raise blocked()
        if row["result"]:
            result = json.loads(row["result"])
            object_fields(
                result,
                {
                    "ordinal",
                    "case_id",
                    "condition_ids",
                    "request_sha256",
                    "operation_id",
                    "accounting_state",
                    "outcome",
                    "error_code",
                    "results",
                },
            )
            if (
                text_hash(row["result"]) != row["result_sha256"]
                or result["condition_ids"] != mapping[index]["condition_ids"]
            ):
                raise blocked()
            if result["outcome"] == "predicted":
                case, _ = runtime.exact_case(index)
                if (
                    result["error_code"]
                    or _validate_results(
                        case["source"],
                        case["conditions"],
                        {"results": result["results"]},
                    )
                    != result["results"]
                ):
                    raise blocked()
            elif result["results"] is not None or result["error_code"] not in {
                "MODEL_OUTCOME_UNKNOWN",
                "MODEL_REFUSED",
                "MODEL_INCOMPLETE",
                "MODEL_UNAVAILABLE",
                "INVALID_PROPOSAL",
            }:
                raise blocked()
            if (
                result["ordinal"] != index
                or result["case_id"] != mapping[index]["case_id"]
                or result["request_sha256"] != reservation.request_sha256
                or result["operation_id"] != reservation.operation_id
                or result["accounting_state"] != row["status"]
                or (
                    row["status"] == "KNOWN"
                    and result["outcome"] not in ("predicted", "failed")
                )
                or (
                    row["status"] == "UNKNOWN"
                    and result["outcome"] != "unknown"
                )
                or row["status"] in ("RESERVED", "CLAIMED")
            ):
                raise blocked()
    completion_state(connection, runtime.record_sha256, runtime.request)
    return rows


def result_value(runtime, ordinal, operation_id, state, code, results=None):
    """Build an exact case-keyed result without gold, source copies or secrets."""
    item = runtime.request["mapping"][ordinal]
    return {
        "ordinal": ordinal,
        "case_id": item["case_id"],
        "condition_ids": item["condition_ids"],
        "request_sha256": item["request_sha256"],
        "operation_id": operation_id,
        "accounting_state": state,
        "outcome": "unknown"
        if state == "UNKNOWN"
        else "failed"
        if code
        else "predicted",
        "error_code": code,
        "results": results,
    }


def attach_result(
    connection, runtime, ordinal, operation_id, state, code, results=None
):
    """Attach exactly once in the same transaction as the accounting observation."""
    value = result_value(runtime, ordinal, operation_id, state, code, results)
    changed = connection.execute(
        "UPDATE gemini_corpus_requests SET result=?,result_sha256=? WHERE ordinal=? AND operation_id=? AND result=''",
        (canonical(value), digest(value), ordinal, operation_id),
    ).rowcount
    if changed != 1:
        raise blocked()


def recover(connection, runtime):
    """Retain crash reservations UNKNOWN; never replay or clear uncertainty."""
    _initialize(connection)
    rows = paired_rows(connection, runtime)
    _, _, missing = completion_state(
        connection, runtime.record_sha256, runtime.request
    )
    for ordinal in missing:
        seal_completion(connection, runtime, ordinal, "UNCONFIRMED")
    ledger = ledger_for(connection, runtime, 0, fresh=False)
    for row in rows:
        if row["status"] in ("RESERVED", "CLAIMED"):
            ledger.mark_unknown(
                GeminiReservation(**json.loads(row["reservation"]))
            )
            attach_result(
                connection,
                runtime,
                row["ordinal"],
                row["operation_id"],
                "UNKNOWN",
                "MODEL_OUTCOME_UNKNOWN",
            )
        elif row["status"] == "UNKNOWN" and not row["result"]:
            attach_result(
                connection,
                runtime,
                row["ordinal"],
                row["operation_id"],
                "UNKNOWN",
                "MODEL_OUTCOME_UNKNOWN",
            )


def freeze(connection, runtime):
    """Commit canonical result bytes before any separate scoring or file export."""
    row = connection.execute(
        "SELECT frozen,frozen_sha256 FROM gemini_corpus_identity WHERE singleton=1"
    ).fetchone()
    receipts, invalidation, missing = completion_state(
        connection, runtime.record_sha256, runtime.request
    )
    if missing:
        raise blocked()
    if row["frozen"]:
        return _verified_frozen(connection, audit_only=invalidation is not None)
    rows = paired_rows(connection, runtime)
    if any(row["status"] in ("RESERVED", "CLAIMED") for row in rows):
        raise blocked()
    unknown = any(row["status"] == "UNKNOWN" for row in rows)
    if not (unknown or invalidation) and any(
        row["operation_id"] is None for row in rows
    ):
        raise blocked()
    cases = []
    for row in rows:
        if row["result"]:
            cases.append(json.loads(row["result"]))
        else:
            item = runtime.request["mapping"][row["ordinal"]]
            cases.append(
                {
                    "ordinal": row["ordinal"],
                    "case_id": item["case_id"],
                    "condition_ids": item["condition_ids"],
                    "request_sha256": item["request_sha256"],
                    "operation_id": None,
                    "accounting_state": "NOT_RUN",
                    "outcome": "not_run",
                    "error_code": "PRIOR_OUTCOME_UNKNOWN",
                    "results": None,
                }
            )
    value = {
        "schema": PREDICTIONS_SCHEMA,
        "completion_receipts": list(receipts.values()),
        "receipt_hashes": [digest(receipt) for receipt in receipts.values()],
        "corpus_sha256": runtime.request["corpus_sha256"],
        "mapping": runtime.request["mapping"],
        "mapping_sha256": runtime.request["mapping_sha256"],
        "approved_record_sha256": runtime.record_sha256,
        "runtime_sha256": runtime.authorization.runtime_sha256,
        "baseline_sha256": runtime.request["baseline_sha256"],
        "evidence_kind": runtime.evidence_kind,
        "prior_totals": runtime.request["prior_totals"],
        "capacity_identity_sha256": text_hash(
            CorpusCapacityLedger(
                connection, runtime.policy, runtime.authorization
            ).identity
        ),
        "reservations": [
            json.loads(row["reservation"]) for row in rows if row["reservation"]
        ],
        "accounting": [
            json.loads(row["observation"]) if row["observation"] else None
            for row in rows
        ],
        "stopped_on_unknown": unknown,
        "cases": cases,
    }
    if invalidation:
        value.pop("cases")
        value.update(
            {
                "schema": AUDIT_SCHEMA,
                "scoring_eligible": False,
                "invalidation": invalidation,
                "invalidation_sha256": digest(invalidation),
                "audit_operations": [
                    {
                        "ordinal": row["ordinal"],
                        "operation_id": row["operation_id"],
                        "accounting_state": row["status"] or "NOT_RUN",
                        "candidate_sha256": row["result_sha256"] or None,
                    }
                    for row in rows
                ],
            }
        )
    frozen = canonical(value) + "\n"
    connection.execute(
        "UPDATE gemini_corpus_identity SET frozen=?,frozen_sha256=? WHERE singleton=1 AND frozen=''",
        (frozen, text_hash(frozen)),
    )
    return frozen.encode()


def _verified_frozen(connection, *, audit_only=False):
    row = connection.execute(
        "SELECT document,frozen,frozen_sha256 FROM gemini_corpus_identity WHERE singleton=1"
    ).fetchone()
    if (
        row is None
        or not row["frozen"]
        or text_hash(row["frozen"]) != row["frozen_sha256"]
    ):
        raise blocked()
    frozen_raw = row["frozen"].encode()
    record = json.loads(row["document"])
    receipts, invalidation, missing = completion_state(
        connection, text_hash(row["document"]), record["request"]
    )
    value = json.loads(row["frozen"])
    common_fields = {
        "schema",
        "completion_receipts",
        "receipt_hashes",
        "corpus_sha256",
        "mapping",
        "mapping_sha256",
        "approved_record_sha256",
        "runtime_sha256",
        "baseline_sha256",
        "evidence_kind",
        "prior_totals",
        "capacity_identity_sha256",
        "reservations",
        "accounting",
        "stopped_on_unknown",
    }
    object_fields(
        value,
        common_fields
        | (
            {
                "scoring_eligible",
                "invalidation",
                "invalidation_sha256",
                "audit_operations",
            }
            if audit_only
            else {"cases"}
        ),
    )
    rows = _protocol_rows(connection)
    for name in (
        "corpus_sha256",
        "mapping_sha256",
        "runtime_sha256",
        "baseline_sha256",
        "prior_totals",
        "evidence_kind",
    ):
        if value[name] != record["request"][name]:
            raise blocked()
    capacity = connection.execute(
        "SELECT document FROM gemini_corpus_capacity_identity WHERE singleton=1"
    ).fetchone()
    if (
        capacity is None
        or value["capacity_identity_sha256"] != text_hash(capacity[0])
        or value["reservations"]
        != [
            json.loads(row["reservation"]) for row in rows if row["reservation"]
        ]
        or value["accounting"]
        != [
            json.loads(row["observation"]) if row["observation"] else None
            for row in rows
        ]
        or value["stopped_on_unknown"]
        != any(row["status"] == "UNKNOWN" for row in rows)
    ):
        raise blocked()
    if (
        missing
        or value.get("schema")
        != (AUDIT_SCHEMA if audit_only else PREDICTIONS_SCHEMA)
        or bool(invalidation) != audit_only
        or value.get("approved_record_sha256") != text_hash(row["document"])
        or value.get("completion_receipts") != list(receipts.values())
        or value.get("receipt_hashes")
        != [digest(receipt) for receipt in receipts.values()]
        or value.get("mapping") != record["request"]["mapping"]
    ):
        raise blocked()
    if audit_only:
        if (
            value.get("scoring_eligible") is not False
            or "cases" in value
            or value.get("invalidation") != invalidation
            or value.get("invalidation_sha256") != digest(invalidation)
            or value.get("audit_operations")
            != [
                {
                    "ordinal": row["ordinal"],
                    "operation_id": row["operation_id"],
                    "accounting_state": row["status"] or "NOT_RUN",
                    "candidate_sha256": row["result_sha256"] or None,
                }
                for row in rows
            ]
        ):
            raise blocked()
    else:
        cases = value.get("cases")
        rows = _protocol_rows(connection)
        if not isinstance(cases, list) or len(cases) != len(rows):
            raise blocked()
        for index, case in enumerate(cases):
            row = rows[index]
            if (
                row["status"] == "KNOWN"
                and receipts.get(index, {}).get("disposition") != "TIMELY"
            ):
                raise blocked()
            if row["result"] and case != json.loads(row["result"]):
                raise blocked()
            if not row["result"] and (
                case.get("outcome") != "not_run"
                or case.get("results") is not None
            ):
                raise blocked()
    return frozen_raw


def read_frozen(db, *, audit_only=False) -> bytes:
    """Export only the requested versioned contract; old/unsealed artifacts fail.

    Normal prediction export refuses invalidated runs. Audit-only export contains
    no case predictions and is deliberately a different schema and CLI command.
    """
    path = Path(db).resolve(strict=True)
    with closing(
        sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    ) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("BEGIN")
        return _verified_frozen(connection, audit_only=audit_only)
