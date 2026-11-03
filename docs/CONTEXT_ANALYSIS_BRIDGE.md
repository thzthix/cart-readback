# Context-capacity service bridge

Issue #39 adds one host-selected vertical analysis path, not a live enable flag.
The default server, CLI, fixture payments, frozen assets and blocked counted-plan
identity are unchanged. The distinct GenuineResponsesAdapter has no unadmitted
propose shortcut and does not subclass OfflineResponsesAdapter. Shared extraction
is limited to pure exact text request construction and pure proposal helpers.

## Host boundary and unresolved proof

ContextAnalysisRuntime is a frozen host-only container for InstalledProviderContext.
The installation owns an exact transport binding; an optional compatibility factory
must be that same selected callable. An unrelated replacement is unavailable and
stales the private review identity without executing either factory. Default
construction has no installation or factory; resolve_installed_context always denies. No HTTP, query, environment or config-file
loader supplies authority. Trusted Python is not a sandbox: these records carry
externally established facts and do not establish their truth themselves.

ProviderTransportBinding selects only the shipped unselected stdlib constructor,
with a bounded externally established nonsecret installation revision. It accepts
no arbitrary factory. FabricatedTransportBinding owns an explicitly fake callable
and automatically assigns a new nonsecret installation generation. Ordinary
construction or dataclasses.replace creates a fresh generation even with the same
factory, so old authorization cannot silently carry over. It cannot be paired
with provider evidence. The same immutable binding can continue across Service
restart in one host process; reconstruction of an arbitrary fake factory across
processes is not claimed to preserve a verified installation. Generation records
freshness, not external proof. Trusted Python can subvert its own objects and is
not sandboxed here.

Both bindings include fixed implementation versions and observed shipped wrapper
and transport source hashes in execution identity before authorization. No callable
repr, captures, token bytes or secret derivatives are hashed. Changing selected
mechanics requires matching new authority, and an old review remains stale even
if the host separately authorizes the new transport. These records do not supply
the absent external provisioner or establish actual network readiness.

CredentialBinding names nonsecret organization, project, credential version and
host revision. An opaque provisioner handle must expose that binding and enforce
borrow(expected_binding, deadline). A bare token callback cannot fill this seam.
Exact CredentialBinding type is checked before equality; hostile property faults
are sanitized. Checks occur before connection construction, before retrieval and before POST
headers are created. Tests use an explicitly fabricated handle and fake token,
never any actual credential. No key or derivative is persisted.

ApprovedDataScope allowlists full catalog hashes (including source ID, exact text,
revision, money and baseline), exact owner hashes, and actual typed condition
values. Matching a scope name is insufficient. ContextFence binds complete source
identity, source bytes/revision, owner, condition IDs/order, runtime and generation.
Service CAS additionally binds the entire catalog, review, configuration, revision,
prepared request bytes and absence of an order.

Identity ordering is acyclic: exact execution/assets/request/route/host binding;
observed Python implementation/full version and OpenSSL build/version facts;
independent reference policy; external binding/pricing record references plus
bounded host authorization/data scope; ledger identity; private review metadata.
Hashes bind records and are not attestations. The external pricing-adoption record
does not modify the policy's explicit unselected-reference cost basis. No supported
secure provisioning, actual applicable pricing, bounded live approval or genuine
provider observation currently exists for this application.

## Transactions and late work

Startup holds the existing process lease, initializes context tables without a
current policy/approval, classifies supported legacy fixture/offline pairings, and
recovers pending analysis and context rows UNKNOWN in one transaction. Orphan
owners do not prevent recovery. Unsupported legacy or bidirectional ledger orphan
history blocks subsequent admission; no history deletion/reset/new namespace is
provided.

Reserve holds a short write transaction while validating owner/revision, concrete
scope, runtime and all unresolved history. It stores paired analysis/capacity with
one operation ID, original policy/authorization identity, and exact byte/fence
hashes; no input count preflight runs. A single claim token is then written to
both rows in one transaction. Stale/expired claims commit UNKNOWN, rather than
raising inside the transaction and rolling that fault back. No connection or
credential retrieval occurs until that transaction commits.

The exchange runs outside SQLite. Runtime, framing and billing-profile validity
are classified before semantics. On a protocol fault, mark_unknown precedes
ledger.observe so independently supported usage cannot accidentally settle KNOWN.
Accounting and proposal CAS commit together. Refusal/incomplete/malformed prose
can retain terminal KNOWN accounting but cannot create a confirmable review.
Queued/in-progress or unsupported tool/background/cache/model/tier evidence stays
UNKNOWN under the unchanged v4 accounting semantics.

A watchdog commits UNKNOWN and returns a blocked review. The worker retains a
separate service activity until it actually exits, so close and replacement
services cannot release/acquire the DB lease while late accounting remains alive.
Matching late accounting uses the original reserved policy/authorization, appends
once, never refunds/reopens/attaches success, and remains UNKNOWN. A persistence
failure rolls back the complete observation transaction; startup conservatively
recovers unfinished rows. This is not hard network cancellation. A process crash
can lose an uncommitted observation; it never authorizes replay.

## Transport and request IDs

The host-bound ScopedHTTPSTransport shares the reviewed fixed-origin HTTPS parser:
api.openai.com:443, POST /v1/responses, certificate/hostname validation, TLS 1.2
minimum, HTTP/1.1, explicit direct or PythonAnywhere CONNECT route, bounded headers
and response bytes. No ambient proxy, retry, redirect, refresh or fallback is used.
Organization/project headers come only from the installed binding. Deadlines are
bounded by the committed claim and approval using precise finite UTC and one
monotonic deadline, including gate overhead. Integer ledger timestamps never
extend the transport deadline by rounding. The committed claim wall expiry is
carried into transport and rechecked before credential borrow and immediately
before POST, so a forward wall-clock step cannot rely on a still-live monotonic
budget or the later approval expiry. The concrete stdlib constructor is
unselected and has not opened any actual socket in bridge tests.

The official [API overview](https://developers.openai.com/api/reference/overview)
describes organization/project headers and an opaque x-request-id for debugging;
it does not promise a req_ prefix grammar. Transport and ledger therefore share
one local supported subset, ASCII [A-Za-z0-9_-] of length 1–256. This is a defensive
local support limit, not a universal provider contract or proof of authenticity.
Unsupported formats fail closed. Raw request IDs and private installation records
never enter public API metadata. Actual DNS/TLS/proxy/provider compatibility remains
unverified; fake connections exercise configured mechanics only.

## Public truth and checks

API C12 separates configured execution_kind/dispatch_available from historical
owned attempt/accounting/evidence_kind. Attempt means committed dispatch claim,
not a proven network send. Fabricated accounting is labelled fabricated-offline,
never actual provider success. Reference usage estimates are not invoices. The
initial composition allows only fixture payments; buyer consent and baseline
remain unchanged. UI preserves uncertain/historical outcomes through provider
changes rather than implying current connection or overwriting them with success.

Focused tests live in tests/test_context_service.py and accompanying boundary
regressions. Run the full README aggregate plus the dedicated C12 loopback driver
when present. Exact artifact manifests and command receipts are recorded by the
implementation/review handoff, not inferred from this document. Structural tests,
quote validation and fabricated observations do not establish model truth or
buyer value. The same-source table may remain the simpler and better solution.
