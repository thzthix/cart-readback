"""Input-only finite Gemini corpus contract and immutable host runtime.

These records identify externally established facts; they cannot establish Free
eligibility, permission to disclose data, or provider availability. No gold,
scorer, catalog insertion, credential discovery or default network path exists.
"""

import hashlib
import json
import unicodedata
from dataclasses import dataclass, field, fields
from pathlib import Path

from cartreadback_app.gemini_capacity import (
    FREE_MODE,
    MAX_INTEGER,
    GeminiCapacityPolicy,
    GeminiFence,
    HostGeminiAuthorization,
)
from cartreadback_app.gemini_client import GeminiClient, GeminiConfig
from cartreadback_app.gemini_runtime import (
    CredentialBinding,
    FabricatedTransportBinding,
    ProviderTransportBinding,
    execution_identity,
    host_provenance,
)
from cartreadback_app.genuine_gemini import GenuineGeminiAdapter
from cartreadback_app.provider_json import strict_provider_json
from cartreadback_app.validation import (
    AppError,
    canonical,
    digest,
    integer,
    object_fields,
    string,
    text_hash,
)

CORPUS_SCHEMA = "gemini-input-corpus-v1"
REQUEST_SCHEMA = "gemini-corpus-disclosure-v1"
APPROVAL_SCHEMA = "gemini-corpus-approved-host-record-v1"
MAX_CORPUS_BYTES = 4_194_304
PLAN_FIELDS = {
    "binding",
    "config",
    "policy",
    "binding_record_sha256",
    "pricing_adoption_record_sha256",
    "installation_revision",
    "timeout_seconds",
    "limits",
}
REQUEST_FIELDS = {
    "schema",
    "plan",
    "corpus_sha256",
    "corpus",
    "mapping",
    "mapping_sha256",
    "runtime_sha256",
    "database_id",
    "database_file_sha256",
    "owner_sha256",
    "baseline_sha256",
    "prior_totals",
    "evidence_kind",
}


def blocked() -> AppError:
    """Return a sanitized error without source, keys or host record details."""
    return AppError("GEMINI_CORPUS_BLOCKED", "Finite corpus unavailable.", 503)


def owned_json(raw: bytes, maximum: int = MAX_CORPUS_BYTES) -> dict:
    """Parse one bounded owned byte value, rejecting duplicates and extras later."""
    if type(raw) is not bytes:
        raise blocked()
    return strict_provider_json(raw, max_bytes=maximum, max_depth=16)


def _identifier(value):
    string(value, "identifier")
    if any(unicodedata.category(char) == "Cc" for char in value):
        raise blocked()
    return value


@dataclass(frozen=True)
class Corpus:
    """Owned immutable bytes and strings, with no nested mutable aliases."""

    raw: bytes
    document_json: str
    mapping_json: str

    @property
    def sha256(self) -> str:
        """Identify exact input bytes, including harmless whitespace changes."""
        return hashlib.sha256(self.raw).hexdigest()

    @property
    def cases(self) -> list[dict]:
        """Return isolated copies of the ordered input-only cases."""
        return json.loads(self.document_json)["cases"]

    @property
    def mapping(self) -> list[dict]:
        """Return isolated exact request-to-case/condition tuples."""
        return json.loads(self.mapping_json)


def parse_corpus(raw: bytes, config: GeminiConfig) -> Corpus:
    """Validate invented or separately authorized inputs, never score them."""
    document = owned_json(raw)
    object_fields(document, {"schema", "cases"})
    cases = document["cases"]
    if (
        document["schema"] != CORPUS_SCHEMA
        or type(cases) is not list
        or not 1 <= len(cases) <= 64
    ):
        raise blocked()
    client = GeminiClient(config)
    seen = set()
    mapping = []
    for ordinal, case in enumerate(cases):
        object_fields(case, {"case_id", "source", "conditions"})
        case_id = _identifier(case["case_id"])
        if case_id in seen:
            raise blocked()
        seen.add(case_id)
        source, choices = case["source"], case["conditions"]
        prepared = client.prepare(source, choices)
        _identifier(source["source_id"])
        integer(source["revision"], "revision", 1, MAX_INTEGER)
        for condition in choices:
            _identifier(condition["condition_id"])
        mapping.append(
            {
                "ordinal": ordinal,
                "case_id": case_id,
                "source_id": source["source_id"],
                "source_revision": source["revision"],
                "source_sha256": source["sha256"],
                "source_identity_sha256": digest(source),
                "condition_ids": [item["condition_id"] for item in choices],
                "conditions_sha256": digest(choices),
                "request_sha256": prepared.request_sha256,
            }
        )
    return Corpus(raw, canonical(document), canonical(mapping))


def plan_parts(plan: dict, transport=None):
    """Validate complete Free-only host settings without resolving credentials."""
    object_fields(plan, PLAN_FIELDS)
    object_fields(
        plan["binding"], {item.name for item in fields(CredentialBinding)}
    )
    object_fields(
        plan["config"], {"model", "expected_model_version", "response_language"}
    )
    object_fields(
        plan["policy"], {item.name for item in fields(GeminiCapacityPolicy)}
    )
    object_fields(
        plan["limits"],
        {
            "valid_from",
            "expires_at",
            "max_calls",
            "max_total_input_tokens",
            "max_total_output_tokens",
            "max_micro_usd",
            "admission_mode",
        },
    )
    binding = CredentialBinding(**plan["binding"])
    config = GeminiConfig(**plan["config"])
    policy = GeminiCapacityPolicy(**plan["policy"])
    if (
        policy.admission_mode != FREE_MODE
        or policy.rates != (0, 0)
        or plan["limits"]["admission_mode"] != FREE_MODE
        or type(plan["limits"]["max_micro_usd"]) is not int
        or plan["limits"]["max_micro_usd"] != 0
        or plan["pricing_adoption_record_sha256"]
        != policy.pricing_record_sha256
    ):
        raise blocked()
    provider = ProviderTransportBinding(plan["installation_revision"])
    selected = provider if transport is None else transport
    if type(selected) not in (
        ProviderTransportBinding,
        FabricatedTransportBinding,
    ):
        raise blocked()
    if type(selected) is ProviderTransportBinding and selected != provider:
        raise blocked()
    execution_identity(
        binding,
        config,
        plan["timeout_seconds"],
        transport=selected,
        policy=policy,
    )
    return binding, config, policy, selected


def source_identity() -> str:
    """Bind all app Python bytes and both host runners, not only transport files."""
    root = Path(__file__).resolve().parent
    paths = sorted(root.glob("*.py")) + [
        root.parent / "scripts" / name
        for name in ("run_gemini_analysis.py", "run_gemini_corpus.py")
    ]
    return digest(
        {
            str(path.relative_to(root.parent)): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in paths
        }
    )


def corpus_execution_identity(plan: dict, transport=None) -> str:
    """Include every corpus/credential/ledger/shared-guard execution byte."""
    binding, config, policy, selected = plan_parts(plan, transport)
    return digest(
        {
            "contract": REQUEST_SCHEMA,
            "source_sha256": source_identity(),
            "runtime_sha256": execution_identity(
                binding,
                config,
                plan["timeout_seconds"],
                transport=selected,
                policy=policy,
            ),
        }
    )


def approved_request(record: dict) -> dict:
    """Recognize only a distinct corpus record, never a smoke approval."""
    # Snapshot caller objects immediately; no mutable alias becomes authority.
    record = owned_json(canonical(record).encode())
    object_fields(
        record, {"schema", "approval_reference", "request_sha256", "request"}
    )
    if record["schema"] != APPROVAL_SCHEMA or record[
        "request_sha256"
    ] != digest(record["request"]):
        raise blocked()
    _identifier(record["approval_reference"])
    request = record["request"]
    object_fields(request, REQUEST_FIELDS)
    if request["schema"] != REQUEST_SCHEMA:
        raise blocked()
    return request


@dataclass(frozen=True)
class CorpusRuntime:
    """Immutable finite authority with exact per-request membership checks."""

    request_json: str
    record_sha256: str
    transport: object
    credential_handle: object = field(default=None, repr=False, compare=False)
    ordinal: int = -1

    @property
    def request(self):
        """Return a fresh disclosure copy, not a mutable internal reference."""
        return json.loads(self.request_json)

    @property
    def installed(self):
        """Expose the trusted record shape used by the existing adapter."""
        return self

    @property
    def binding(self):
        """Return the exact nonsecret host credential scope."""
        return CredentialBinding(**self.request["plan"]["binding"])

    @property
    def config(self):
        """Return the unchanged Gemini configuration contract."""
        return GeminiConfig(**self.request["plan"]["config"])

    @property
    def policy(self):
        """Return the explicit zero-rate policy."""
        return GeminiCapacityPolicy(**self.request["plan"]["policy"])

    @property
    def evidence_kind(self):
        """Distinguish fabricated mechanics from shipped provider transport."""
        return self.transport.metadata["kind"]

    @property
    def timeout_seconds(self):
        """Return the approved wall/monotonic timeout ceiling."""
        return self.request["plan"]["timeout_seconds"]

    @property
    def execution_sha256(self):
        """Recompute code/runtime identity at every guarded transition."""
        return corpus_execution_identity(self.request["plan"], self.transport)

    @property
    def connection_factory(self):
        """Select exactly the recorded transport, without opening it."""
        return self.transport.factory

    @property
    def authorization(self):
        """Reuse existing finite capacity scalar validation under distinct scope."""
        request = self.request
        plan = request["plan"]
        return HostGeminiAuthorization(
            database_id=request["database_id"],
            provenance_sha256=host_provenance(
                plan["binding_record_sha256"],
                plan["pricing_adoption_record_sha256"],
                self.evidence_kind,
                policy=self.policy,
            ),
            data_scope_sha256=digest(
                {
                    "contract": REQUEST_SCHEMA,
                    "disclosure": request,
                    "approved_record_sha256": self.record_sha256,
                }
            ),
            runtime_sha256=request["runtime_sha256"],
            policy_sha256=text_hash(self.policy.identity),
            **plan["limits"],
        )

    def require(self, now):
        """Reject stale source/model/window or inconsistent host facts."""
        request = self.request
        plan_parts(request["plan"], self.transport)
        auth = self.authorization
        handle = self.credential_handle
        if handle is not None and (
            getattr(handle, "binding", None) != self.binding
            or getattr(handle, "ordinal", None) != self.ordinal
            or getattr(handle, "grant_sha256", None) != self.record_sha256
        ):
            raise blocked()
        if (
            request["runtime_sha256"] != self.execution_sha256
            or request["evidence_kind"] != self.evidence_kind
            or auth.valid_from < self.policy.valid_from
            or auth.expires_at > self.policy.expires_at
            or type(now) not in (int, float)
            or not auth.valid_from <= now < auth.expires_at
        ):
            raise blocked()
        return self

    def exact_case(self, ordinal, *, body=None):
        """Check the full ordered tuple, never a Cartesian product of allowlists."""
        request = self.request
        integer(ordinal, "ordinal", 0, len(request["mapping"]) - 1)
        case = request["corpus"]["cases"][ordinal]
        prepared = GeminiClient(self.config).prepare(
            case["source"], case["conditions"]
        )
        corpus = parse_corpus(
            canonical(request["corpus"]).encode(), self.config
        )
        if (
            corpus.mapping != request["mapping"]
            or digest(request["mapping"]) != request["mapping_sha256"]
            or (body is not None and body != prepared.body)
        ):
            raise blocked()
        return case, prepared

    def fence(self, ordinal):
        """Bind the case ordinal, owner and source/condition identities."""
        case, _ = self.exact_case(ordinal)
        source = case["source"]
        return GeminiFence(
            self.authorization.runtime_sha256,
            self.request["owner_sha256"],
            source["sha256"],
            digest(source),
            source["revision"],
            digest(case["conditions"]),
            ordinal + 1,
        )


class CorpusGeminiAdapter(GenuineGeminiAdapter):
    """Reuse genuine exchange/classification without broadening smoke scope."""

    def __init__(self, runtime: CorpusRuntime, clock):
        """Require the distinct corpus runtime; no Service admission is implied."""
        if type(runtime) is not CorpusRuntime:
            raise blocked()
        self.runtime = runtime
        self.clock = clock
