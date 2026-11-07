"""Unselected context-capacity accounting, without transport or billing proof.

This host-only primitive does not authorize genuine dispatch. Reference prices
are not adopted project prices. The caller owns the SQLite transaction and lock;
the context service bridge composes it without rewriting prior UNKNOWN history.
"""

import hashlib
import json
import re
import secrets
import sqlite3
from dataclasses import asdict, dataclass
from uuid import uuid4

from cartreadback_app.inference_config import MODEL, load_bundle
from cartreadback_app.provider_json import strict_provider_json
from cartreadback_app.responses_http import valid_request_id
from cartreadback_app.validation import (
    AppError,
    canonical,
    conditions,
    digest,
    integer,
    object_fields,
    string,
    text_hash,
)

VERSION = "context-capacity-v1"
EVIDENCE_REVISION = "2026-11-03-luna-standard-context-v1"
EVIDENCE_SHA256 = (
    "ab42b7b87825982e33c564c080270221c029ed21488d4348883f971b3d42e82d"
)
CONTEXT_TOKENS = 1_050_000
OUTPUT_TOKENS = 2048
MAX_INTEGER = 2**53 - 1
_TERMINAL_RESPONSE_STATES = ("completed", "failed", "cancelled", "incomplete")
_SCHEMA = """
CREATE TABLE IF NOT EXISTS context_capacity_identity (
    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
    document TEXT NOT NULL, last_seen INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS context_capacity_operations (
    operation_id TEXT PRIMARY KEY, reservation TEXT NOT NULL,
    fence_sha256 TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK(status IN ('RESERVED','CLAIMED','KNOWN','UNKNOWN')),
    claim_token TEXT NOT NULL DEFAULT '', observation TEXT NOT NULL DEFAULT '',
    claim_deadline INTEGER NOT NULL DEFAULT 0,
    response_id_sha256 TEXT NOT NULL DEFAULT '',
    request_id_sha256 TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS unique_context_capacity_response
ON context_capacity_operations(response_id_sha256) WHERE response_id_sha256 != '';
CREATE UNIQUE INDEX IF NOT EXISTS unique_context_capacity_request_id
ON context_capacity_operations(request_id_sha256) WHERE request_id_sha256 != '';
CREATE UNIQUE INDEX IF NOT EXISTS single_context_capacity_pending
ON context_capacity_operations((1)) WHERE status IN ('RESERVED', 'CLAIMED');
"""


def _error() -> AppError:
    return AppError(
        "CONTEXT_CAPACITY_BLOCKED", "Context capacity unavailable.", 503
    )


def _int(value: object, maximum: int = MAX_INTEGER, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
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
class ContextCapacityPolicy:
    """Immutable reference evidence, never external project/billing proof.

    Both supported profiles remain unselected. A regional reference calculation
    does not verify regional billing. A genuine binding gate is still missing.
    Evidence and host windows are bounded to at most one day, not self-renewing.
    """

    valid_from: int
    expires_at: int
    reference_profile: str = "global-standard"
    evidence_revision: str = EVIDENCE_REVISION

    def __post_init__(self) -> None:
        """Accept only the reviewed immutable reference profiles and window."""
        _window(self.valid_from, self.expires_at)
        if (
            type(self.reference_profile) is not str
            or self.reference_profile
            not in ("global-standard", "regional-standard-plus-10-percent")
            or type(self.evidence_revision) is not str
            or self.evidence_revision != EVIDENCE_REVISION
        ):
            raise _error()

    @property
    def rates(self) -> tuple[int, int]:
        """Return maximum long-context uncached reference component rates."""
        return (
            (200_000, 750_000)
            if self.reference_profile == "global-standard"
            else (220_000, 825_000)
        )

    def estimate(self, input_tokens: int, output_tokens: int) -> int:
        """Compute a conservative estimate, not an invoice or refunded balance."""
        _int(input_tokens, CONTEXT_TOKENS)
        _int(output_tokens, OUTPUT_TOKENS)
        return sum(
            charge_micro_usd(tokens, rate)
            for tokens, rate in zip(
                (input_tokens, output_tokens), self.rates, strict=True
            )
        )

    @property
    def identity(self) -> str:
        """Bind reviewed settings and explicit missing external-binding gates."""
        bundle = load_bundle()
        return canonical(
            {
                "version": VERSION,
                **asdict(self),
                "evidence_sha256": EVIDENCE_SHA256,
                "model": MODEL,
                "service_tier": "default",
                "context_tokens": CONTEXT_TOKENS,
                "max_output_tokens": OUTPUT_TOKENS,
                "rates_micro_usd_per_million": self.rates,
                "currency": "USD",
                "prompt_manifest_sha256": text_hash(bundle.manifest_json),
                "request_profile": "shipped-one-shot-text-explicit-no-cache-v1",
                "claim_timeout_seconds": 20,
                "billing_scope": "unselected",
                "remaining_gates": [
                    "verified-account-project-credential-and-billing-binding",
                    "bounded-live-data-call-spend-authorization",
                    "reviewed-genuine-transport-and-controlled-observations",
                ],
            }
        )


@dataclass(frozen=True)
class HostCapacityAuthorization:
    """Bounded host provenance for local admission; not external authorization.

    Hash references identify nonsecret reviewed records, never keys or hashes of
    credentials. No browser deserializer, account ID or verification flag exists.
    """

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

    def __post_init__(self) -> None:
        """Reject unbounded allowances and mutable or malformed references."""
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
            self.max_micro_usd,
        ):
            _int(value, minimum=1)


@dataclass(frozen=True)
class ContextFence:
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
class ContextReservation:
    """Permanent capacity attached to exact bytes, fence and host identity."""

    operation_id: str
    request_sha256: str
    fence_sha256: str
    ledger_sha256: str
    input_tokens: int
    output_tokens: int
    reserved_micro_usd: int


@dataclass(frozen=True)
class ContextClaim:
    """Single local claim, never a credential or permission to transmit data."""

    reservation: ContextReservation
    claim_token: str
    expires_at: int


def _request_hash(request: bytes, fence: ContextFence) -> str:
    """Check exact shipped text profile and host source binding without count."""
    if type(fence) is not ContextFence:
        raise _error()
    raw = strict_provider_json(request, max_bytes=65_536, max_depth=32)
    bundle = load_bundle()
    try:
        messages = raw["input"]
        if type(messages) is not list or len(messages) != 1:
            raise _error()
        message = object_fields(messages[0], {"role", "content"})
        content = message["content"]
        if type(content) is not list or len(content) != 1:
            raise _error()
        text = object_fields(content[0], {"type", "text"})["text"]
        if type(text) is not str:
            raise _error()
        before, rest = bundle.user_template.split("{{request_json}}")
        middle, after = rest.split("{{output_schema_json}}")
        suffix = middle + bundle.wire_schema_json + after
        if not text.startswith(before) or not text.endswith(suffix):
            raise _error()
        request_text = text[len(before) : -len(suffix)]
        inputs = strict_provider_json(
            request_text.encode("utf-8"), max_bytes=65_536, max_depth=8
        )
        object_fields(inputs, {"source", "conditions", "response_language"})
        source = object_fields(
            inputs["source"], {"source_id", "revision", "sha256", "text"}
        )
        string(source["source_id"], "source_id")
        string(source["text"], "source_text", 16000, multiline=True)
        integer(source["revision"], "source_revision", 1, MAX_INTEGER)
        choices = inputs["conditions"]
        if type(choices) is not list or not 1 <= len(choices) <= 2:
            raise _error()
        ids, values = [], []
        for item in choices:
            object_fields(item, {"condition_id", "kind", "value"})
            ids.append(string(item["condition_id"], "condition_id"))
            values.append({"kind": item["kind"], "value": item["value"]})
        conditions(values)
        if (
            len(set(ids)) != len(ids)
            or inputs["response_language"] not in ("en", "ko")
            or request_text != canonical(inputs)
            or source["sha256"] != text_hash(source["text"])
            or source["sha256"] != fence.source_sha256
            or digest(source) != fence.source_identity_sha256
            or source["revision"] != fence.source_revision
            or digest(choices) != fence.conditions_sha256
        ):
            raise _error()
        expected = {
            "model": MODEL,
            "service_tier": "default",
            "instructions": bundle.system,
            "input": [
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": text}],
                }
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "cartreadback_proposal_v1",
                    "strict": True,
                    "schema": json.loads(bundle.wire_schema_json),
                }
            },
            "reasoning": {"effort": "none"},
            "tools": [],
            "prompt_cache_options": {"mode": "explicit"},
            "store": False,
            "background": False,
            "stream": False,
            "max_output_tokens": OUTPUT_TOKENS,
        }
        # Compare serialized values for strict bool/int distinctions and fields.
        if canonical(raw) != canonical(expected):
            raise _error()
    except (KeyError, TypeError, ValueError, UnicodeError) as error:
        raise _error() from error
    return hashlib.sha256(request).hexdigest()


def _profile_conflict(raw: dict) -> bool:
    # Only explicit provider-level activity is considered here, not whether the
    # proposal text or semantic output shape is acceptable. Absence is not proof
    # against hidden vendor violations, and this does not estimate tool charges.
    if "tool_usage" in raw and (
        type(raw["tool_usage"]) is not dict or bool(raw["tool_usage"])
    ):
        return True
    if "background" in raw and raw["background"] is not False:
        return True
    if "tools" in raw and (type(raw["tools"]) is not list or raw["tools"]):
        return True
    if "output" in raw:
        if type(raw["output"]) is not list:
            return True
        for item in raw["output"]:
            if (
                type(item) is not dict
                or type(item.get("type")) is not str
                or item["type"] not in ("message", "reasoning")
            ):
                return True
    return False


def parse_accounting(envelope: bytes, policy: ContextCapacityPolicy) -> str:
    """Parse accounting before semantic acceptance; never return proposal text.

    Missing details and unknown usage categories fail closed. A malformed or
    stale semantic proposal may still have independently valid usage. Full output
    usage includes invisible tokens, not a count of the visible result string.
    """
    if type(policy) is not ContextCapacityPolicy:
        raise _error()
    raw = strict_provider_json(envelope, max_bytes=131_072, max_depth=32)
    if raw.get("model") != MODEL or raw.get("service_tier") != "default":
        raise _error()
    if raw.get("object") != "response":
        raise _error()
    response_status = raw.get("status")
    if type(response_status) is not str or response_status not in (
        *_TERMINAL_RESPONSE_STATES,
        "queued",
        "in_progress",
    ):
        raise _error()
    response_id = raw.get("id")
    if type(response_id) is not str or not re.fullmatch(
        r"resp_[A-Za-z0-9_-]{1,96}", response_id
    ):
        raise _error()
    usage = object_fields(
        raw.get("usage"),
        {
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "input_tokens_details",
            "output_tokens_details",
        },
    )
    incoming = _int(usage["input_tokens"], CONTEXT_TOKENS)
    outgoing = _int(usage["output_tokens"], OUTPUT_TOKENS)
    total = _int(usage["total_tokens"], CONTEXT_TOKENS)
    cache = usage["input_tokens_details"]
    if (
        type(cache) is not dict
        or "cached_tokens" not in cache
        or set(cache)
        - {"cached_tokens", "cache_write_tokens", "cache_write_tokens_details"}
    ):
        raise _error()
    if (
        "cache_write_tokens" in cache
        and _int(cache["cache_write_tokens"], CONTEXT_TOKENS) != 0
    ):
        raise _error()
    if "cache_write_tokens_details" in cache:
        details = object_fields(
            cache["cache_write_tokens_details"],
            {"ttl_30m_tokens", "ttl_12h_tokens"},
        )
        if "cache_write_tokens" not in cache or any(
            _int(value, CONTEXT_TOKENS) != 0 for value in details.values()
        ):
            raise _error()
    reasoning = object_fields(
        usage["output_tokens_details"], {"reasoning_tokens"}
    )
    if (
        incoming + outgoing != total
        or _int(cache["cached_tokens"], CONTEXT_TOKENS) != 0
        or _int(reasoning["reasoning_tokens"], OUTPUT_TOKENS) != 0
    ):
        raise _error()
    return canonical(
        {
            "response_id_sha256": text_hash(response_id),
            "response_status": response_status,
            "usage_finality": (
                "terminal-model-usage"
                if response_status in _TERMINAL_RESPONSE_STATES
                else "provisional-model-usage"
            ),
            "accounting_contract": (
                "unsupported-provider-activity"
                if _profile_conflict(raw)
                else "no-explicit-profile-conflict"
            ),
            "model": MODEL,
            "service_tier": "default",
            "input_tokens": incoming,
            "output_tokens": outgoing,
            "total_tokens": total,
            "estimated_micro_usd_at_reference_max_rates": policy.estimate(
                incoming, outgoing
            ),
            "cost_basis": "unselected-reference-not-vendor-charge",
        }
    )


def initialize_context_capacity(connection: sqlite3.Connection) -> None:
    """Initialize schema without requiring any current installation or approval."""
    if not connection.in_transaction:
        raise _error()
    for statement in _SCHEMA.split(";"):
        if statement.strip():
            connection.execute(statement)


def context_ledger_from_document(connection, document: str):
    """Restore the original immutable ledger for recovery and late accounting."""
    try:
        raw = json.loads(document)
        stored = raw["policy"]
        policy = ContextCapacityPolicy(
            stored["valid_from"],
            stored["expires_at"],
            stored["reference_profile"],
            stored["evidence_revision"],
        )
        authorization = HostCapacityAuthorization(**raw["host_authorization"])
        ledger = TransactionContextCapacityLedger(
            connection, policy, authorization
        )
        if ledger.identity != document:
            raise _error()
        return ledger
    except (ValueError, TypeError, KeyError) as error:
        raise _error() from error


def recover_context_capacity(connection: sqlite3.Connection) -> None:
    """Fence pending work UNKNOWN in the exclusive owner's startup transaction.

    This is not a cancellation or retry. The owner must initialize the ledger
    first, hold its process lock, and commit recovery before accepting work.
    """
    if not connection.in_transaction:
        raise _error()
    connection.execute(
        "UPDATE context_capacity_operations SET status = 'UNKNOWN' "
        "WHERE status IN ('RESERVED', 'CLAIMED')"
    )


class TransactionContextCapacityLedger:
    """Short caller-owned transactions for atomic analysis/capacity integration.

    Default service selection remains off. Callers serialize current host state
    with reserve/claim/observe, keep the same database and immutable identity,
    own startup recovery and commit before any outside work. No network callback
    is accepted. Returned claims confer only local accounting identity.
    """

    def __init__(
        self,
        connection: sqlite3.Connection,
        policy: ContextCapacityPolicy,
        authorization: HostCapacityAuthorization,
    ) -> None:
        """Bind an active host transaction without committing or recovering it."""
        if (
            not connection.in_transaction
            or type(policy) is not ContextCapacityPolicy
            or type(authorization) is not HostCapacityAuthorization
            or authorization.policy_sha256 != text_hash(policy.identity)
            or authorization.valid_from < policy.valid_from
            or authorization.expires_at > policy.expires_at
        ):
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
        initialize_context_capacity(connection)
        row = connection.execute(
            "SELECT document FROM context_capacity_identity WHERE singleton = 1"
        ).fetchone()
        if row is None:
            connection.execute(
                "INSERT INTO context_capacity_identity VALUES (1, ?, 0)",
                (self._identity,),
            )
        elif row[0] != self._identity:
            raise _error()

    @property
    def identity(self) -> str:
        """Return the private immutable record for original-policy observation."""
        return self._identity

    @property
    def policy(self) -> ContextCapacityPolicy:
        """Return the original immutable policy for independent classification."""
        return self._policy

    def _transaction(self) -> sqlite3.Connection:
        connection = self._connection
        if not connection.in_transaction:
            raise _error()
        row = connection.execute(
            "SELECT document FROM context_capacity_identity WHERE singleton = 1"
        ).fetchone()
        if row is None or row[0] != self._identity:
            raise _error()
        return connection

    def _fresh(self, now: int) -> bool:
        _int(now)
        connection = self._transaction()
        last = connection.execute(
            "SELECT last_seen FROM context_capacity_identity WHERE singleton = 1"
        ).fetchone()[0]
        connection.execute(
            "UPDATE context_capacity_identity SET last_seen = ? WHERE singleton = 1",
            (max(last, now),),
        )
        return (
            last <= now
            and self._authorization.valid_from
            <= now
            < self._authorization.expires_at
        )

    def reserve(
        self, request: bytes, fence: ContextFence, *, now: int
    ) -> ContextReservation:
        """Reserve C input plus M output permanently, without fabricating count."""
        request_sha = _request_hash(request, fence)
        auth = self._authorization
        connection = self._transaction()
        if fence.runtime_sha256 != auth.runtime_sha256 or not self._fresh(now):
            raise _error()
        rows = connection.execute(
            "SELECT reservation, status FROM context_capacity_operations"
        ).fetchall()
        cost = self._policy.estimate(CONTEXT_TOKENS, OUTPUT_TOKENS)
        # All reservations use the same immutable policy; KNOWN never refunds.
        count = len(rows) + 1
        if (
            any(row[1] != "KNOWN" for row in rows)
            or count > auth.max_calls
            or count * CONTEXT_TOKENS > auth.max_total_input_tokens
            or count * OUTPUT_TOKENS > auth.max_total_output_tokens
            or count * cost > auth.max_micro_usd
        ):
            raise _error()
        reservation = ContextReservation(
            str(uuid4()),
            request_sha,
            digest(asdict(fence)),
            text_hash(self._identity),
            CONTEXT_TOKENS,
            OUTPUT_TOKENS,
            cost,
        )
        if connection.execute(
            "SELECT 1 FROM context_capacity_operations WHERE fence_sha256 = ?",
            (reservation.fence_sha256,),
        ).fetchone():
            raise _error()
        connection.execute(
            "INSERT INTO context_capacity_operations (operation_id, reservation, fence_sha256, status) VALUES (?, ?, ?, 'RESERVED')",
            (
                reservation.operation_id,
                canonical(asdict(reservation)),
                reservation.fence_sha256,
            ),
        )
        return reservation

    def _row(self, reservation: ContextReservation) -> tuple:
        if type(reservation) is not ContextReservation:
            raise _error()
        row = (
            self._transaction()
            .execute(
                "SELECT reservation, status, claim_token, observation, claim_deadline FROM context_capacity_operations WHERE operation_id = ?",
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
        reservation: ContextReservation,
        request: bytes,
        current_fence: ContextFence,
        *,
        now: int,
    ) -> ContextClaim | None:
        """Claim once, or retain stale/expired pre-send capacity as UNKNOWN.

        A None result must be committed, not rolled back and retried. Current
        fence must come from host state held under the same transaction lock.
        """
        row = self._row(reservation)
        if row[1] != "RESERVED":
            raise _error()
        _int(now)
        try:
            matches = (
                _request_hash(request, current_fence)
                == reservation.request_sha256
                and digest(asdict(current_fence)) == reservation.fence_sha256
            )
        except AppError:
            matches = False
        fresh = self._fresh(now)
        if not matches or not fresh:
            self._transaction().execute(
                "UPDATE context_capacity_operations SET status = 'UNKNOWN' WHERE operation_id = ? AND status = 'RESERVED'",
                (reservation.operation_id,),
            )
            return None
        token = secrets.token_hex(32)
        deadline = min(now + 20, self._authorization.expires_at)
        self._transaction().execute(
            "UPDATE context_capacity_operations SET status = 'CLAIMED', claim_token = ?, claim_deadline = ? WHERE operation_id = ? AND status = 'RESERVED'",
            (token, deadline, reservation.operation_id),
        )
        return ContextClaim(reservation, token, deadline)

    def _claimed(self, claim: ContextClaim) -> tuple:
        if type(claim) is not ContextClaim:
            raise _error()
        row = self._row(claim.reservation)
        if (
            row[1] not in ("CLAIMED", "UNKNOWN")
            or not row[2]
            or row[2] != claim.claim_token
            or type(claim.expires_at) is not int
            or row[4] != claim.expires_at
        ):
            raise _error()
        return row

    def observe(
        self,
        claim: ContextClaim,
        envelope: bytes,
        *,
        request_sha256: str,
        runtime_sha256: str,
        request_id: str,
        current_fence: ContextFence,
        now: int,
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
            or type(current_fence) is not ContextFence
            or not valid_request_id(request_id)
            or row[3]
        ):
            raise _error()
        fresh = self._fresh(now)
        try:
            accounting = json.loads(parse_accounting(envelope, self._policy))
            if (
                self._transaction()
                .execute(
                    "SELECT 1 FROM context_capacity_operations WHERE response_id_sha256 = ? OR request_id_sha256 = ?",
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
            "UPDATE context_capacity_operations SET status = ?, observation = ?, response_id_sha256 = ?, request_id_sha256 = ? WHERE operation_id = ? AND claim_token = ? AND observation = '' AND status IN ('CLAIMED','UNKNOWN')",
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

    def mark_unknown(self, reservation: ContextReservation) -> None:
        """Retain full pre-send/failure/timeout capacity with no retry or refund."""
        row = self._row(reservation)
        if row[1] not in ("RESERVED", "CLAIMED", "UNKNOWN"):
            raise _error()
        self._transaction().execute(
            "UPDATE context_capacity_operations SET status = 'UNKNOWN' WHERE operation_id = ?",
            (reservation.operation_id,),
        )
