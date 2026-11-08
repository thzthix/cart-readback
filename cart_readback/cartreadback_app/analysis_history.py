"""Shared admission integrity, preserving historical uncertainty across paths."""

from cartreadback_app.context_runtime import blocked
from cartreadback_app.validation import text_hash


def reject_active_corpus(connection):
    """Deny legacy model admission after a finite corpus grant is activated."""
    if (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='gemini_corpus_identity'"
        ).fetchone()
        and connection.execute(
            "SELECT 1 FROM gemini_corpus_identity LIMIT 1"
        ).fetchone()
    ):
        raise blocked()


def legacy_analysis_history_guard(connection, current_preflight_id=None):
    """Validate both directions of all pre-corpus analysis history."""
    # Pair both directions. A new strategy or current installation cannot
    # discard orphan/unknown history in any of the shared admission ledgers.
    rows = connection.execute(
        "SELECT a.*, b.operation_id AS budget_id, c.operation_id AS context_id, g.operation_id AS gemini_id FROM analysis_operations a LEFT JOIN budget_operations b ON b.operation_id = a.operation_id LEFT JOIN context_capacity_operations c ON c.operation_id = a.operation_id LEFT JOIN gemini_capacity_operations g ON g.operation_id = a.operation_id"
    ).fetchall()
    for row in rows:
        strategy = row["strategy"]
        if not connection.execute(
            "SELECT 1 FROM sessions WHERE sid = ?", (row["sid"],)
        ).fetchone():
            raise blocked()
        if strategy == "fixture":
            valid = (
                row["is_fixture"] == 1
                and not row["budget_id"]
                and not row["context_id"]
                and not row["gemini_id"]
            )
        elif strategy == "offline-count-v1":
            valid = (
                row["is_fixture"] == 0
                and row["budget_id"]
                and not row["context_id"]
                and not row["gemini_id"]
            )
        elif strategy == "context-capacity-v1":
            valid = (
                row["is_fixture"] == 0
                and row["context_id"]
                and not row["budget_id"]
                and not row["gemini_id"]
            )
        elif strategy == "gemini-capacity-v1":
            valid = (
                row["is_fixture"] == 0
                and row["gemini_id"]
                and not row["budget_id"]
                and not row["context_id"]
            )
        else:
            valid = False
        if (
            not valid
            or text_hash(row["input_document"]) != row["input_hash"]
            or row["status"]
            not in {
                "RESERVED",
                "DISPATCHED",
                "SUCCEEDED",
                "BLOCKED",
                "STALE",
                "UNKNOWN",
            }
        ):
            raise blocked()
        if not connection.execute(
            "SELECT 1 FROM reviews WHERE review_id = ? AND sid = ?",
            (row["review_id"], row["sid"]),
        ).fetchone():
            raise blocked()
        if strategy != "fixture" and row["status"] in {
            "UNKNOWN",
            "RESERVED",
            "DISPATCHED",
        }:
            raise blocked()
    for table, strategy in (
        ("budget_operations", "offline-count-v1"),
        ("context_capacity_operations", "context-capacity-v1"),
        ("gemini_capacity_operations", "gemini-capacity-v1"),
    ):
        if connection.execute(
            f"SELECT 1 FROM {table} b LEFT JOIN analysis_operations a ON a.operation_id = b.operation_id WHERE a.operation_id IS NULL OR a.strategy != ? OR b.status != 'KNOWN' OR a.status NOT IN ('SUCCEEDED','BLOCKED','STALE') OR a.observation = '' LIMIT 1",
            (strategy,),
        ).fetchone():
            raise blocked()
    if connection.execute(
        "SELECT 1 FROM analysis_preflights p LEFT JOIN analysis_operations a ON a.operation_id = p.analysis_operation_id WHERE p.status NOT IN ('PREPARED','COUNTING','UNKNOWN','USED','BLOCKED','STALE') OR NOT EXISTS (SELECT 1 FROM sessions s WHERE s.sid = p.sid) OR p.status = 'UNKNOWN' OR (p.status IN ('PREPARED', 'COUNTING') AND p.preflight_id != ?) OR (p.status = 'USED' AND (a.operation_id IS NULL OR a.strategy != 'offline-count-v1')) LIMIT 1",
        (current_preflight_id or "",),
    ).fetchone():
        raise blocked()
