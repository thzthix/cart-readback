"""Same-store immutable corpus grants, paired operations and frozen results."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from cartreadback_app.analysis_history import legacy_analysis_history_guard
from cartreadback_app.context_capacity import initialize_context_capacity
from cartreadback_app.gemini_capacity import (
    MAX_INTEGER,
    GeminiReservation,
    TransactionGeminiCapacityLedger,
    gemini_database_identity,
    initialize_gemini_capacity,
    initialize_gemini_database,
)
from cartreadback_app.gemini_corpus import blocked
from cartreadback_app.storage import Store
from cartreadback_app.validation import canonical, digest, integer, text_hash

_SCHEMA = """
CREATE TABLE IF NOT EXISTS gemini_corpus_identity (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    document TEXT NOT NULL, frozen TEXT NOT NULL DEFAULT '',
    frozen_sha256 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS gemini_corpus_requests (
    ordinal INTEGER PRIMARY KEY, mapping TEXT NOT NULL,
    operation_id TEXT UNIQUE, result TEXT NOT NULL DEFAULT ''
);
"""
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
        if (
            totals[0] >= auth.max_calls
            or totals[1] >= auth.max_total_input_tokens
            or totals[2] >= auth.max_total_output_tokens
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
        "SELECT r.*,c.reservation,c.status,c.observation,c.fence_sha256 FROM gemini_corpus_requests r LEFT JOIN gemini_corpus_capacity_operations c ON c.operation_id=r.operation_id ORDER BY r.ordinal"
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
            if row["result"] or row["status"] is not None:
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
        if row["result"]:
            result = json.loads(row["result"])
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
        "UPDATE gemini_corpus_requests SET result=? WHERE ordinal=? AND operation_id=? AND result=''",
        (canonical(value), ordinal, operation_id),
    ).rowcount
    if changed != 1:
        raise blocked()


def recover(connection, runtime):
    """Retain crash reservations UNKNOWN; never replay or clear uncertainty."""
    rows = paired_rows(connection, runtime)
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
    if row["frozen"]:
        if text_hash(row["frozen"]) != row["frozen_sha256"]:
            raise blocked()
        return row["frozen"].encode()
    rows = paired_rows(connection, runtime)
    if any(row["status"] in ("RESERVED", "CLAIMED") for row in rows):
        raise blocked()
    unknown = any(row["status"] == "UNKNOWN" for row in rows)
    if not unknown and any(row["operation_id"] is None for row in rows):
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
        "schema": "gemini-frozen-corpus-results-v1",
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
    frozen = canonical(value) + "\n"
    connection.execute(
        "UPDATE gemini_corpus_identity SET frozen=?,frozen_sha256=? WHERE singleton=1 AND frozen=''",
        (frozen, text_hash(frozen)),
    )
    return frozen.encode()


def read_frozen(db) -> bytes:
    """Read and verify authoritative frozen bytes without runtime or credentials."""
    path = Path(db).resolve(strict=True)
    with closing(
        sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    ) as connection:
        row = connection.execute(
            "SELECT frozen,frozen_sha256 FROM gemini_corpus_identity WHERE singleton=1"
        ).fetchone()
        if row is None or not row[0] or text_hash(row[0]) != row[1]:
            raise blocked()
        return row[0].encode()
