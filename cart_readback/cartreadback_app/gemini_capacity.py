"""Gemini-specific permanent capacity accounting, without billing proof.

This host-only primitive requires explicit project-specific adopted rates and
capacity provenance. It cannot establish their external truth. The caller owns
the SQLite transaction and lock, and preserves prior UNKNOWN history.
"""

import hashlib
import json
import math
import re
import secrets
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid4

from cartreadback_app.gemini_client import (
    GeminiClient,
    GeminiConfig,
    classify_gemini_usage,
)
from cartreadback_app.inference_config import load_bundle
from cartreadback_app.provider_json import strict_provider_json
from cartreadback_app.validation import (
    AppError,
    canonical,
    digest,
    object_fields,
    text_hash,
)

VERSION = "gemini-capacity-v2"
PAID_MODE = "paid"
FREE_MODE = "externally-verified-free-tier"
MAX_INPUT_TOKENS = 1_048_576
OUTPUT_TOKENS = 2048
MAX_INTEGER = 2**53 - 1
_TERMINAL_RESPONSE_STATES = ("completed",)
_SCHEMA = """
CREATE TABLE IF NOT EXISTS gemini_capacity_identity (
    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
    document TEXT NOT NULL, last_seen REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS gemini_capacity_operations (
    operation_id TEXT PRIMARY KEY, reservation TEXT NOT NULL,
    fence_sha256 TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK(status IN ('RESERVED','CLAIMED','KNOWN','UNKNOWN')),
    claim_token TEXT NOT NULL DEFAULT '', observation TEXT NOT NULL DEFAULT '',
    claim_deadline REAL NOT NULL DEFAULT 0,
    response_id_sha256 TEXT NOT NULL DEFAULT '',
    request_id_sha256 TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS unique_gemini_capacity_response
ON gemini_capacity_operations(response_id_sha256) WHERE response_id_sha256 != '';
CREATE UNIQUE INDEX IF NOT EXISTS unique_gemini_capacity_request_id
ON gemini_capacity_operations(request_id_sha256) WHERE request_id_sha256 != '';
CREATE UNIQUE INDEX IF NOT EXISTS single_gemini_capacity_pending
ON gemini_capacity_operations((1)) WHERE status IN ('RESERVED', 'CLAIMED');
"""


def _error() -> AppError:
    return AppError(
        "GEMINI_CAPACITY_BLOCKED", "Gemini capacity unavailable.", 503
    )


def _int(value: object, maximum: int = MAX_INTEGER, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise _error()
    return value


def _mode(value: object) -> None:
    if type(value) is not str or value not in (PAID_MODE, FREE_MODE):
        raise _error()


def _time(value: object) -> float:
    if (
        type(value) not in (int, float)
        or not math.isfinite(value)
        or not 0 <= value <= MAX_INTEGER
    ):
        raise _error()
    return value


def _sha(value: object) -> str:
    if type(value) is not str or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise _error()
    return value


def _window(start: int, end: int) -> None:
    _int(start)
    _int(end)
    if not 0 < end - start <= 86400:
        raise _error()


def charge_micro_usd(tokens: int, rate: int) -> int:
    """Round a component upward; reject bools, negatives and storage overflow."""
    _int(tokens)
    _int(rate, minimum=1)
    return _int((tokens * rate + 999_999) // 1_000_000)


@dataclass(frozen=True)
class GeminiCapacityPolicy:
    """Externally adopted project rates and capacity, not verified by this code."""

    valid_from: int
    expires_at: int
    model: str
    expected_model_version: str
    max_input_tokens: int
    input_rate_micro_usd_per_million: int
    output_rate_micro_usd_per_million: int
    project: str
    tier: str
    eligibility_record_sha256: str
    pricing_record_sha256: str
    admission_mode: str
    host_decision_record_sha256: str

    def __post_init__(self) -> None:
        """Require explicit paid rates or externally established free-tier facts."""
        _window(self.valid_from, self.expires_at)
        GeminiConfig(self.expected_model_version, model=self.model)
        _int(self.max_input_tokens, MAX_INPUT_TOKENS, MAX_INPUT_TOKENS)
        _mode(self.admission_mode)
        for rate in self.rates:
            _int(rate, minimum=0 if self.admission_mode == FREE_MODE else 1)
        if self.admission_mode == FREE_MODE:
            if self.tier != "free" or self.rates != (0, 0):
                raise _error()
        elif self.tier != "paid":
            raise _error()
        for value in (self.project, self.tier):
            if (
                type(value) is not str
                or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) is None
            ):
                raise _error()
        _sha(self.eligibility_record_sha256)
        _sha(self.pricing_record_sha256)
        _sha(self.host_decision_record_sha256)

    @property
    def rates(self) -> tuple[int, int]:
        """Return adopted uncached input and thought-inclusive output rates."""
        return (
            self.input_rate_micro_usd_per_million,
            self.output_rate_micro_usd_per_million,
        )

    def estimate(self, input_tokens: int, output_tokens: int) -> int:
        """Round both components upward, without asserting a provider invoice."""
        _int(input_tokens, self.max_input_tokens)
        _int(output_tokens, OUTPUT_TOKENS)
        if self.admission_mode == FREE_MODE:
            return 0
        return _int(
            sum(
                charge_micro_usd(tokens, rate)
                for tokens, rate in zip(
                    (input_tokens, output_tokens), self.rates, strict=True
                )
            )
        )

    @property
    def identity(self) -> str:
        """Bind the exact adopted policy and shared prompt asset revision."""
        return canonical(
            {
                "version": VERSION,
                **asdict(self),
                "max_output_tokens": OUTPUT_TOKENS,
                "currency": "USD",
                "prompt_manifest_sha256": text_hash(
                    load_bundle().manifest_json
                ),
                "cost_basis": "host-adopted-rates-not-vendor-charge",
            }
        )


@dataclass(frozen=True)
class HostGeminiAuthorization:
    """Bounded host provenance for local admission; not external authorization.

    Hash references identify nonsecret reviewed records, never keys or hashes of
    credentials. No browser deserializer, account ID or verification flag exists.
    """

    database_id: str
    provenance_sha256: str
    data_scope_sha256: str
    runtime_sha256: str
    policy_sha256: str
    valid_from: int
    expires_at: int
    max_calls: int
    max_total_input_tokens: int
    max_total_output_tokens: int
    max_micro_usd: int
    admission_mode: str

    def __post_init__(self) -> None:
        """Reject unbounded allowances and mutable or malformed references."""
        _sha(self.database_id)
        for value in (
            self.provenance_sha256,
            self.data_scope_sha256,
            self.runtime_sha256,
            self.policy_sha256,
        ):
            _sha(value)
        _window(self.valid_from, self.expires_at)
        _int(self.max_calls, 64, 1)
        for value in (
            self.max_total_input_tokens,
            self.max_total_output_tokens,
        ):
            _int(value, minimum=1)
        _mode(self.admission_mode)
        if self.admission_mode == FREE_MODE:
            _int(self.max_micro_usd, maximum=0)
        else:
            _int(self.max_micro_usd, minimum=1)


@dataclass(frozen=True)
class GeminiFence:
    """Exact host-owned source, owner and generation snapshot, not model echo."""

    runtime_sha256: str
    owner_sha256: str
    source_sha256: str
    source_identity_sha256: str
    source_revision: int
    conditions_sha256: str
    generation: int

    def __post_init__(self) -> None:
        """Validate every scalar before recording immutable fence identity."""
        for value in (
            self.runtime_sha256,
            self.owner_sha256,
            self.source_sha256,
            self.source_identity_sha256,
            self.conditions_sha256,
        ):
            _sha(value)
        _int(self.source_revision, minimum=1)
        _int(self.generation, minimum=1)


@dataclass(frozen=True)
class GeminiReservation:
    """Permanent capacity attached to exact bytes, fence and host identity."""

    operation_id: str
    request_sha256: str
    fence_sha256: str
    ledger_sha256: str
    input_tokens: int
    output_tokens: int
    reserved_micro_usd: int


@dataclass(frozen=True)
class GeminiClaim:
    """Single local claim, never a credential or permission to transmit data."""

    reservation: GeminiReservation
    claim_token: str
    expires_at: float


def _request_hash(
    request: bytes, fence: GeminiFence, policy: GeminiCapacityPolicy
) -> str:
    """Rebuild exact Gemini request bytes and verify the owned input fence."""
    if type(fence) is not GeminiFence:
        raise _error()
    try:
        raw = strict_provider_json(request, max_bytes=65_536, max_depth=32)
        text = raw["contents"][0]["parts"][0]["text"]
        bundle = load_bundle()
        before, rest = bundle.user_template.split("{{request_json}}")
        middle, after = rest.split("{{output_schema_json}}")
        suffix = middle + bundle.wire_schema_json + after
        if (
            type(text) is not str
            or not text.startswith(before)
            or not text.endswith(suffix)
        ):
            raise _error()
        inputs = strict_provider_json(
            text[len(before) : -len(suffix)].encode("utf-8"),
            max_bytes=65_536,
            max_depth=8,
        )
        fields = {"source", "conditions", "response_language"}
        if "evidence_span_hints" in inputs:
            fields.add("evidence_span_hints")
        object_fields(inputs, fields)
        # Optional hints are host-derived data, not trusted caller authority.
        # The unchanged exact reconstruction below rejects any tampering.
        source, choices = inputs["source"], inputs["conditions"]
        config = GeminiConfig(
            policy.expected_model_version,
            inputs["response_language"],
            policy.model,
        )
        rebuilt = GeminiClient(config).prepare(source, choices)
        if (
            request != rebuilt.body
            or source["sha256"] != fence.source_sha256
            or digest(source) != fence.source_identity_sha256
            or source["revision"] != fence.source_revision
            or digest(choices) != fence.conditions_sha256
        ):
            raise _error()
        return hashlib.sha256(request).hexdigest()
    except Exception:
        raise _error() from None


def parse_accounting(envelope: bytes, policy: GeminiCapacityPolicy) -> str:
    """Retain bounded usage independently of refused or malformed proposals."""
    if type(policy) is not GeminiCapacityPolicy:
        raise _error()
    try:
        accounting = asdict(
            classify_gemini_usage(
                envelope,
                GeminiConfig(policy.expected_model_version, model=policy.model),
            )
        )
        _int(accounting["input_tokens"], policy.max_input_tokens)
        accounting.update(
            {
                "estimated_micro_usd_at_adopted_rates": policy.estimate(
                    accounting["input_tokens"], accounting["output_tokens"]
                ),
                "cost_basis": "host-adopted-rates-not-vendor-charge",
            }
        )
        return canonical(accounting)
    except Exception:
        raise _error() from None


def _database_location(connection: sqlite3.Connection) -> tuple[str, int, int]:
    row = next(
        (
            row
            for row in connection.execute("PRAGMA database_list")
            if row[1] == "main"
        ),
        None,
    )
    if row is None or not row[2]:
        raise _error()
    path = Path(row[2]).resolve(strict=True)
    stat = path.stat()
    return text_hash(str(path)), stat.st_dev, stat.st_ino


def initialize_gemini_database(connection: sqlite3.Connection) -> str:
    """Explicit offline prepare only: bind this existing store to a random ID."""
    if (
        not connection.in_transaction
        or not connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sessions'"
        ).fetchone()
    ):
        raise _error()
    connection.execute(
        "CREATE TABLE IF NOT EXISTS gemini_database_identity (singleton INTEGER PRIMARY KEY CHECK(singleton=1), database_id TEXT NOT NULL, path_sha256 TEXT NOT NULL, device INTEGER NOT NULL, inode INTEGER NOT NULL)"
    )
    if (
        connection.execute(
            "SELECT database_id FROM gemini_database_identity WHERE singleton=1"
        ).fetchone()
        is None
    ):
        connection.execute(
            "INSERT INTO gemini_database_identity VALUES (1, ?, ?, ?, ?)",
            (secrets.token_hex(32), *_database_location(connection)),
        )
    return gemini_database_identity(connection)


def gemini_database_identity(connection: sqlite3.Connection) -> str:
    """Read the exact prepared physical store identity; never recreate it."""
    try:
        row = connection.execute(
            "SELECT database_id,path_sha256,device,inode FROM gemini_database_identity WHERE singleton=1"
        ).fetchone()
        if row is None or tuple(row[1:]) != _database_location(connection):
            raise _error()
        return _sha(row[0])
    except (sqlite3.Error, OSError, TypeError, IndexError):
        raise _error() from None


def initialize_gemini_capacity(connection: sqlite3.Connection) -> None:
    """Initialize schema without requiring any current installation or approval."""
    if not connection.in_transaction:
        raise _error()
    for statement in _SCHEMA.split(";"):
        if statement.strip():
            connection.execute(statement)


def gemini_ledger_from_document(connection, document: str):
    """Restore the original immutable ledger for recovery and late accounting."""
    try:
        raw = json.loads(document)
        stored = raw["policy"]
        policy = GeminiCapacityPolicy(
            **{
                key: stored[key]
                for key in GeminiCapacityPolicy.__dataclass_fields__
            }
        )
        authorization = HostGeminiAuthorization(**raw["host_authorization"])
        ledger = TransactionGeminiCapacityLedger(
            connection, policy, authorization
        )
        if ledger.identity != document:
            raise _error()
        return ledger
    except (ValueError, TypeError, KeyError) as error:
        raise _error() from error


def recover_gemini_capacity(connection: sqlite3.Connection) -> None:
    """Fence pending work UNKNOWN in the exclusive owner's startup transaction.

    This is not a cancellation or retry. The owner must initialize the ledger
    first, hold its process lock, and commit recovery before accepting work.
    """
    if not connection.in_transaction:
        raise _error()
    connection.execute(
        "UPDATE gemini_capacity_operations SET status = 'UNKNOWN' "
        "WHERE status IN ('RESERVED', 'CLAIMED')"
    )


class TransactionGeminiCapacityLedger:
    """Short caller-owned transactions for atomic analysis/capacity integration.

    Default service selection remains off. Callers serialize current host state
    with reserve/claim/observe, keep the same database and immutable identity,
    own startup recovery and commit before any outside work. No network callback
    is accepted. Returned claims confer only local accounting identity.
    """

    def __init__(
        self,
        connection: sqlite3.Connection,
        policy: GeminiCapacityPolicy,
        authorization: HostGeminiAuthorization,
    ) -> None:
        """Bind an active host transaction without committing or recovering it."""
        if (
            not connection.in_transaction
            or type(policy) is not GeminiCapacityPolicy
            or type(authorization) is not HostGeminiAuthorization
            or authorization.admission_mode != policy.admission_mode
            or authorization.policy_sha256 != text_hash(policy.identity)
            or authorization.valid_from < policy.valid_from
            or authorization.expires_at > policy.expires_at
        ):
            raise _error()
        if gemini_database_identity(connection) != authorization.database_id:
            raise _error()
        self._connection = connection
        self._policy = policy
        self._authorization = authorization
        self._identity = canonical(
            {
                "policy": json.loads(policy.identity),
                "host_authorization": asdict(authorization),
            }
        )
        initialize_gemini_capacity(connection)
        row = connection.execute(
            "SELECT document FROM gemini_capacity_identity WHERE singleton = 1"
        ).fetchone()
        if row is None:
            if connection.execute(
                "SELECT 1 FROM gemini_capacity_operations LIMIT 1"
            ).fetchone():
                raise _error()
            connection.execute(
                "INSERT INTO gemini_capacity_identity VALUES (1, ?, 0)",
                (self._identity,),
            )
        elif row[0] != self._identity:
            raise _error()

    @property
    def policy(self) -> GeminiCapacityPolicy:
        """Return the original immutable adopted policy for classification."""
        return self._policy

    def validate_claim(
        self, claim, request, current_fence, *, now: float
    ) -> bool:
        """Check one committed claim and checkpoint time in a short transaction.

        A false result must be committed and fenced UNKNOWN by the caller.
        This method never performs I/O or authorizes a replacement claim.
        """
        row = self._claimed(claim)
        fresh = self._fresh(now)
        try:
            return (
                row[1] == "CLAIMED"
                and fresh
                and now < claim.expires_at
                and _request_hash(request, current_fence, self._policy)
                == claim.reservation.request_sha256
                and digest(asdict(current_fence))
                == claim.reservation.fence_sha256
            )
        except AppError:
            return False

    @property
    def identity(self) -> str:
        """Return the private immutable record for original-policy observation."""
        return self._identity

    def _transaction(self) -> sqlite3.Connection:
        connection = self._connection
        if (
            gemini_database_identity(connection)
            != self._authorization.database_id
        ):
            raise _error()
        if not connection.in_transaction:
            raise _error()
        row = connection.execute(
            "SELECT document FROM gemini_capacity_identity WHERE singleton = 1"
        ).fetchone()
        if row is None or row[0] != self._identity:
            raise _error()
        return connection

    def _fresh(self, now: float) -> bool:
        _time(now)
        connection = self._transaction()
        last = connection.execute(
            "SELECT last_seen FROM gemini_capacity_identity WHERE singleton = 1"
        ).fetchone()[0]
        connection.execute(
            "UPDATE gemini_capacity_identity SET last_seen = ? WHERE singleton = 1",
            (max(last, now),),
        )
        return (
            last <= now
            and self._authorization.valid_from
            <= now
            < self._authorization.expires_at
        )

    def reserve(
        self, request: bytes, fence: GeminiFence, *, now: float
    ) -> GeminiReservation:
        """Reserve C input plus M output permanently, without fabricating count."""
        request_sha = _request_hash(request, fence, self._policy)
        auth = self._authorization
        connection = self._transaction()
        if fence.runtime_sha256 != auth.runtime_sha256 or not self._fresh(now):
            raise _error()
        rows = connection.execute(
            "SELECT reservation, status FROM gemini_capacity_operations"
        ).fetchall()
        cost = self._policy.estimate(
            self._policy.max_input_tokens, OUTPUT_TOKENS
        )
        # All reservations use the same immutable policy; KNOWN never refunds.
        count = len(rows) + 1
        if (
            any(row[1] != "KNOWN" for row in rows)
            or count > auth.max_calls
            or count * self._policy.max_input_tokens
            > auth.max_total_input_tokens
            or count * OUTPUT_TOKENS > auth.max_total_output_tokens
            or count * cost > auth.max_micro_usd
        ):
            raise _error()
        reservation = GeminiReservation(
            str(uuid4()),
            request_sha,
            digest(asdict(fence)),
            text_hash(self._identity),
            self._policy.max_input_tokens,
            OUTPUT_TOKENS,
            cost,
        )
        if connection.execute(
            "SELECT 1 FROM gemini_capacity_operations WHERE fence_sha256 = ?",
            (reservation.fence_sha256,),
        ).fetchone():
            raise _error()
        connection.execute(
            "INSERT INTO gemini_capacity_operations (operation_id, reservation, fence_sha256, status) VALUES (?, ?, ?, 'RESERVED')",
            (
                reservation.operation_id,
                canonical(asdict(reservation)),
                reservation.fence_sha256,
            ),
        )
        return reservation

    def _row(self, reservation: GeminiReservation) -> tuple:
        if type(reservation) is not GeminiReservation:
            raise _error()
        row = (
            self._transaction()
            .execute(
                "SELECT reservation, status, claim_token, observation, claim_deadline FROM gemini_capacity_operations WHERE operation_id = ?",
                (reservation.operation_id,),
            )
            .fetchone()
        )
        if (
            row is None
            or row[0] != canonical(asdict(reservation))
            or reservation.ledger_sha256 != text_hash(self._identity)
        ):
            raise _error()
        return row

    def claim(
        self,
        reservation: GeminiReservation,
        request: bytes,
        current_fence: GeminiFence,
        *,
        now: float,
    ) -> GeminiClaim | None:
        """Claim once, or retain stale/expired pre-send capacity as UNKNOWN.

        A None result must be committed, not rolled back and retried. Current
        fence must come from host state held under the same transaction lock.
        """
        row = self._row(reservation)
        if row[1] != "RESERVED":
            raise _error()
        _time(now)
        try:
            matches = (
                _request_hash(request, current_fence, self._policy)
                == reservation.request_sha256
                and digest(asdict(current_fence)) == reservation.fence_sha256
            )
        except AppError:
            matches = False
        fresh = self._fresh(now)
        if not matches or not fresh:
            self._transaction().execute(
                "UPDATE gemini_capacity_operations SET status = 'UNKNOWN' WHERE operation_id = ? AND status = 'RESERVED'",
                (reservation.operation_id,),
            )
            return None
        token = secrets.token_hex(32)
        deadline = min(now + 20, self._authorization.expires_at)
        self._transaction().execute(
            "UPDATE gemini_capacity_operations SET status = 'CLAIMED', claim_token = ?, claim_deadline = ? WHERE operation_id = ? AND status = 'RESERVED'",
            (token, deadline, reservation.operation_id),
        )
        return GeminiClaim(reservation, token, deadline)

    def _claimed(self, claim: GeminiClaim) -> tuple:
        if type(claim) is not GeminiClaim:
            raise _error()
        row = self._row(claim.reservation)
        if (
            row[1] not in ("CLAIMED", "UNKNOWN")
            or not row[2]
            or row[2] != claim.claim_token
            or type(claim.expires_at) not in (int, float)
            or row[4] != claim.expires_at
        ):
            raise _error()
        return row

    def observe(
        self,
        claim: GeminiClaim,
        envelope: bytes,
        *,
        request_sha256: str,
        runtime_sha256: str,
        request_id: str,
        current_fence: GeminiFence,
        now: float,
    ) -> str:
        """Record independently valid accounting; return KNOWN or UNKNOWN.

        Wrong host exchange identity cannot change this operation. A matching
        invalid response becomes UNKNOWN without raising, so an outer exception
        does not accidentally roll back that fault. Late/stale/recovered valid
        accounting is recorded once, but cannot clear UNKNOWN or accept prose.
        """
        row = self._claimed(claim)
        if (
            request_sha256 != claim.reservation.request_sha256
            or runtime_sha256 != self._authorization.runtime_sha256
            or type(current_fence) is not GeminiFence
            or type(request_id) is not str
            or re.fullmatch(r"[A-Za-z0-9_-]{1,256}", request_id) is None
            or row[3]
        ):
            raise _error()
        fresh = self._fresh(now)
        try:
            accounting = json.loads(parse_accounting(envelope, self._policy))
            if (
                self._transaction()
                .execute(
                    "SELECT 1 FROM gemini_capacity_operations WHERE response_id_sha256 = ? OR request_id_sha256 = ?",
                    (accounting["response_id_sha256"], text_hash(request_id)),
                )
                .fetchone()
            ):
                raise _error()
        except AppError:
            observation = ""
            status = "UNKNOWN"
        else:
            accounting.update(
                {
                    "request_sha256": request_sha256,
                    "runtime_sha256": runtime_sha256,
                    "request_id_sha256": text_hash(request_id),
                    "observed_at": now,
                }
            )
            observation = canonical(accounting)
            status = (
                "KNOWN"
                if row[1] == "CLAIMED"
                and accounting["response_status"] in _TERMINAL_RESPONSE_STATES
                and accounting["accounting_contract"]
                == "no-explicit-profile-conflict"
                and fresh
                and now < claim.expires_at
                and digest(asdict(current_fence))
                == claim.reservation.fence_sha256
                else "UNKNOWN"
            )
        self._transaction().execute(
            "UPDATE gemini_capacity_operations SET status = ?, observation = ?, response_id_sha256 = ?, request_id_sha256 = ? WHERE operation_id = ? AND claim_token = ? AND observation = '' AND status IN ('CLAIMED','UNKNOWN')",
            (
                status,
                observation,
                accounting["response_id_sha256"] if observation else "",
                text_hash(request_id) if observation else "",
                claim.reservation.operation_id,
                claim.claim_token,
            ),
        )
        return status

    def mark_unknown(self, reservation: GeminiReservation) -> None:
        """Retain full pre-send/failure/timeout capacity with no retry or refund."""
        row = self._row(reservation)
        if row[1] not in ("RESERVED", "CLAIMED", "UNKNOWN"):
            raise _error()
        self._transaction().execute(
            "UPDATE gemini_capacity_operations SET status = 'UNKNOWN' WHERE operation_id = ?",
            (reservation.operation_id,),
        )
