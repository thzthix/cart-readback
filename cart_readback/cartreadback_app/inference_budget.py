"""Durable offline budget prerequisite, with no counter, price or live dispatch.

All counts and rates are explicitly injected trusted test data. This module is
usable inside the offline service transaction but does not authorize spending
or read secrets.
Reserved capacity is never refunded, even after known usage or pre-send failure.
"""

import hashlib
import json
import re
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid4

from cartreadback_app.provider_json import strict_provider_json
from cartreadback_app.validation import AppError, canonical, digest

_VERSION = "offline-budget-v1"
_MAX = 2**53 - 1
BUDGET_SCHEMA = """
CREATE TABLE IF NOT EXISTS budget_identity (
    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
    document TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS budget_operations (
    operation_id TEXT PRIMARY KEY,
    request_sha256 TEXT NOT NULL, input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL, reserved_micro_usd INTEGER NOT NULL,
    status TEXT NOT NULL, claim_token TEXT NOT NULL DEFAULT '',
    observation TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS single_budget_pending
ON budget_operations((1)) WHERE status IN ('RESERVED', 'DISPATCHED');
"""


def _error() -> AppError:
    return AppError(
        "MODEL_BUDGET_EXCEEDED", "Offline budget unavailable or exhausted.", 503
    )


def _number(value: object, maximum: int = _MAX) -> bool:
    return type(value) is int and 0 < value <= maximum


def _label(value: object) -> bool:
    return type(value) is str and bool(
        re.fullmatch(r"[A-Za-z0-9_.:-]{1,96}", value)
    )


def _sha(value: object) -> bool:
    return type(value) is str and bool(re.fullmatch(r"[a-f0-9]{64}", value))


def request_hash(request: bytes) -> str:
    """Hash exact bounded request bytes, never a reserialized approximation."""
    if type(request) is not bytes or not 0 < len(request) <= 65_536:
        raise _error()
    return hashlib.sha256(request).hexdigest()


@dataclass(frozen=True)
class OfflineBudgetPolicy:
    """Explicit synthetic USD rates/limits and host-owned dispatch identity.

    Rates are integer micro-USD per million tokens, charging all input as uncached
    and all reserved output at its full rate. No real rate, discount or provider
    accuracy is inferred. A new policy cannot replace the identity of an old DB.
    """

    model: str
    price_revision: str
    counter_revision: str
    dispatch_config_sha256: str
    scope_id: str
    input_micro_usd_per_million: int
    output_micro_usd_per_million: int
    max_calls: int
    max_input_tokens: int
    max_output_tokens: int
    max_total_input_tokens: int
    max_total_output_tokens: int
    max_micro_usd: int
    service_tier: str = "default"
    execution_mode: str = "offline-injected-only"

    def __post_init__(self) -> None:
        """Reject unknown identity, free rates, booleans and unbounded limits."""
        if (
            not all(
                _label(value)
                for value in (
                    self.model,
                    self.price_revision,
                    self.counter_revision,
                    self.scope_id,
                )
            )
            or not _sha(self.dispatch_config_sha256)
            or self.service_tier != "default"
            or self.execution_mode != "offline-injected-only"
            or not all(
                _number(value)
                for value in (
                    self.input_micro_usd_per_million,
                    self.output_micro_usd_per_million,
                    self.max_total_input_tokens,
                    self.max_total_output_tokens,
                    self.max_micro_usd,
                )
            )
            or not _number(self.max_calls, 64)
            or not _number(self.max_input_tokens, 1_000_000)
            or not _number(self.max_output_tokens, 8192)
            or self.max_input_tokens > self.max_total_input_tokens
            or self.max_output_tokens > self.max_total_output_tokens
        ):
            raise _error()

    @property
    def identity(self) -> str:
        """Return immutable nonsecret policy identity for durable comparison."""
        return canonical(
            {"version": _VERSION, "currency": "USD", **asdict(self)}
        )

    def cost(self, input_tokens: int, output_tokens: int) -> int:
        """Round each positive token charge upward using integer arithmetic."""
        if any(
            type(value) is not int or not 0 <= value <= _MAX
            for value in (input_tokens, output_tokens)
        ):
            raise _error()
        return sum(
            (tokens * rate + 999_999) // 1_000_000
            for tokens, rate in (
                (input_tokens, self.input_micro_usd_per_million),
                (output_tokens, self.output_micro_usd_per_million),
            )
        )


@dataclass(frozen=True)
class OfflineInputCount:
    """Trusted fabricated count bound to exact bytes/model/counter revision."""

    request_sha256: str
    model: str
    counter_revision: str
    input_tokens: int


@dataclass(frozen=True)
class BudgetClaim:
    """Single-dispatch identity, not a credential or an authorization to spend."""

    operation_id: str
    request_sha256: str
    policy_sha256: str
    claim_token: str


def _ensure_policy(
    connection: sqlite3.Connection, policy: OfflineBudgetPolicy
) -> None:
    if type(policy) is not OfflineBudgetPolicy or not connection.in_transaction:
        raise _error()
    for statement in BUDGET_SCHEMA.split(";"):
        if statement.strip():
            connection.execute(statement)
    row = connection.execute(
        "SELECT document FROM budget_identity WHERE singleton = 1"
    ).fetchone()
    if row is None:
        connection.execute(
            "INSERT INTO budget_identity VALUES (1, ?)", (policy.identity,)
        )
    elif row[0] != policy.identity:
        raise _error()


def recover_budget(connection: sqlite3.Connection) -> None:
    """Mark pending capacity UNKNOWN inside its owner's startup transaction."""
    if not connection.in_transaction:
        raise _error()
    connection.execute(
        "UPDATE budget_operations SET status = 'UNKNOWN' "
        "WHERE status IN ('RESERVED', 'DISPATCHED')"
    )


def policy_from_identity(document: str) -> OfflineBudgetPolicy:
    """Reconstruct only an exact supported, nonsecret reserved policy document."""
    try:
        values = json.loads(document)
        if values.pop("version") != _VERSION or values.pop("currency") != "USD":
            raise _error()
        policy = OfflineBudgetPolicy(**values)
        if policy.identity != document:
            raise _error()
        return policy
    except (ValueError, TypeError, AttributeError, KeyError) as error:
        raise _error() from error


def validate_input_count(
    request: bytes, count: OfflineInputCount, policy: OfflineBudgetPolicy
) -> int:
    """Validate exact trusted count binding; return conservative synthetic cost."""
    if type(policy) is not OfflineBudgetPolicy:
        raise _error()
    sha = request_hash(request)
    payload = strict_provider_json(request, max_bytes=65_536, max_depth=32)
    if (
        type(count) is not OfflineInputCount
        or count.request_sha256 != sha
        or count.model != policy.model
        or count.counter_revision != policy.counter_revision
        or not _number(count.input_tokens, policy.max_input_tokens)
        or payload.get("model") != policy.model
        or payload.get("service_tier") != policy.service_tier
        or type(payload.get("max_output_tokens")) is not int
        or payload["max_output_tokens"] != policy.max_output_tokens
    ):
        raise _error()
    return policy.cost(count.input_tokens, policy.max_output_tokens)


class _BudgetOperations:
    """Share operations across standalone and owner-managed transactions."""

    def reserve(self, request: bytes, count: OfflineInputCount) -> str:
        """Commit worst-case capacity for exactly one explicitly counted payload."""
        sha = request_hash(request)
        policy = self._policy
        cost = validate_input_count(request, count, policy)
        with self._transaction() as connection:
            rows = connection.execute(
                "SELECT * FROM budget_operations"
            ).fetchall()
            if (
                len(rows) >= policy.max_calls
                or any(row["status"] != "KNOWN" for row in rows)
                or sum(row["input_tokens"] for row in rows) + count.input_tokens
                > policy.max_total_input_tokens
                or sum(row["output_tokens"] for row in rows)
                + policy.max_output_tokens
                > policy.max_total_output_tokens
                or sum(row["reserved_micro_usd"] for row in rows) + cost
                > policy.max_micro_usd
            ):
                raise _error()
            operation_id = str(uuid4())
            connection.execute(
                "INSERT INTO budget_operations(operation_id, request_sha256, "
                "input_tokens, output_tokens, reserved_micro_usd, status) "
                "VALUES (?, ?, ?, ?, ?, 'RESERVED')",
                (
                    operation_id,
                    sha,
                    count.input_tokens,
                    policy.max_output_tokens,
                    cost,
                ),
            )
        return operation_id

    def claim(self, operation_id: str, request: bytes) -> BudgetClaim:
        """Commit one claim before returning; duplicate or changed bytes fail."""
        sha = request_hash(request)
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM budget_operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if (
                row is None
                or row["status"] != "RESERVED"
                or row["request_sha256"] != sha
            ):
                raise _error()
            token = secrets.token_hex(32)
            connection.execute(
                "UPDATE budget_operations SET status = 'DISPATCHED', claim_token = ? "
                "WHERE operation_id = ?",
                (token, operation_id),
            )
        return BudgetClaim(
            operation_id, sha, digest(json.loads(self._policy.identity)), token
        )

    def settle(
        self,
        claim: BudgetClaim,
        *,
        model: str,
        service_tier: str,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int,
    ) -> None:
        """Record known bounded usage or retain UNKNOWN, with no capacity refund.

        Wrong claim identity cannot change another operation. A matching claim
        with invalid usage/model/tier makes that operation durably UNKNOWN before
        raising. Missing outcomes must use mark_unknown or restart recovery.
        """
        invalid = False
        with self._transaction() as connection:
            row = self._claimed(connection, claim)
            valid_counts = all(
                type(value) is int and 0 <= value <= _MAX
                for value in (input_tokens, output_tokens, total_tokens)
            )
            if (
                not valid_counts
                or input_tokens > row["input_tokens"]
                or output_tokens > row["output_tokens"]
                or input_tokens + output_tokens != total_tokens
                or model != self._policy.model
                or service_tier != self._policy.service_tier
            ):
                invalid = True
                status, observation = "UNKNOWN", ""
            else:
                status = "KNOWN"
                observation = canonical(
                    {
                        "model": model,
                        "service_tier": service_tier,
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "total_tokens": total_tokens,
                        "cost_is_synthetic": True,
                        "is_real_charge": False,
                        "actual_micro_usd": self._policy.cost(
                            input_tokens, output_tokens
                        ),
                    }
                )
            connection.execute(
                "UPDATE budget_operations SET status = ?, observation = ? "
                "WHERE operation_id = ?",
                (status, observation, claim.operation_id),
            )
        if invalid:
            raise _error()

    def _claimed(self, connection, claim):
        if type(claim) is not BudgetClaim:
            raise _error()
        row = connection.execute(
            "SELECT * FROM budget_operations WHERE operation_id = ?",
            (claim.operation_id,),
        ).fetchone()
        if (
            row is None
            or row["status"] != "DISPATCHED"
            or row["request_sha256"] != claim.request_sha256
            or claim.policy_sha256 != digest(json.loads(self._policy.identity))
            or row["claim_token"] != claim.claim_token
        ):
            raise _error()
        return row

    def mark_unknown(self, claim: BudgetClaim) -> None:
        """Durably stop admission after ambiguity, without retry or reset."""
        with self._transaction() as connection:
            self._claimed(connection, claim)
            connection.execute(
                "UPDATE budget_operations SET status = 'UNKNOWN' WHERE operation_id = ?",
                (claim.operation_id,),
            )

    def abandon_reservation(
        self, operation_id: str, request_sha256: str
    ) -> None:
        """Keep an undispatched stale reservation as UNKNOWN, never release it."""
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM budget_operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if (
                row is None
                or row["status"] != "RESERVED"
                or row["request_sha256"] != request_sha256
            ):
                raise _error()
            connection.execute(
                "UPDATE budget_operations SET status = 'UNKNOWN' WHERE operation_id = ?",
                (operation_id,),
            )


class OfflineBudgetLedger(_BudgetOperations):
    """Own one private, exclusive SQLite budget ledger for offline tests.

    Opening recovers any pending reservation as UNKNOWN, never free or retried.
    Identity and committed history are database-wide, independent of sessions.
    A caller must retain the same DB and policy; deleting/copying DBs or supplying
    false counts/rates defeats this trusted seam and is not a recovery workflow.
    """

    def __init__(self, path: str | Path, policy: OfflineBudgetPolicy) -> None:
        """Lock before recovery; never open network connections or load prices."""
        if type(policy) is not OfflineBudgetPolicy:
            raise _error()
        self._path = Path(path).resolve()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._policy = policy
        self._mutex = threading.Lock()
        self._closed = False
        self._lease = self._path.with_suffix(
            self._path.suffix + ".budget-lock"
        ).open("a+b")
        try:
            # This offline prerequisite currently supports POSIX ownership only.
            import fcntl

            fcntl.flock(self._lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self._transaction() as connection:
                _ensure_policy(connection, policy)
                recover_budget(connection)
        except BaseException:
            self._lease.close()
            raise

    @contextmanager
    def _transaction(self):
        with self._mutex:
            if self._closed:
                raise _error()
            connection = sqlite3.connect(self._path, isolation_level=None)
            connection.row_factory = sqlite3.Row
            try:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
            finally:
                connection.close()

    def close(self) -> None:
        """Release this owner; a replacement recovers unresolved work as UNKNOWN."""
        with self._mutex:
            self._closed = True
            self._lease.close()


class TransactionBudgetLedger(_BudgetOperations):
    """Budget operations sharing an existing owner's exact SQLite transaction.

    This does not acquire a lease, commit, roll back or recover. The service owns
    those responsibilities. Settlement errors must be caught inside the outer
    transaction if the caller wants an UNKNOWN update to commit before raising.
    """

    def __init__(
        self, connection: sqlite3.Connection, policy: OfflineBudgetPolicy
    ) -> None:
        """Bind an already-open owner transaction and persisted policy identity."""
        _ensure_policy(connection, policy)
        self._connection = connection
        self._policy = policy

    @contextmanager
    def _transaction(self):
        if not self._connection.in_transaction:
            raise _error()
        yield self._connection
