# Genuine Responses runtime: design gates, issue #33

Status: **architecture only; genuine inference remains UNCONNECTED**.
Reviewed source base: `eea8372a03be873ef2c3cc1ca6564118e02bb234`,
tree `7959270ca4c026e09c2ef21efe31236408f61425`. This note adds no client,
factory, credentials, live-enable setting, runtime behavior or deployment.
It does not authorize data transmission or spending. PayPal remains a separate
integration and authorization boundary.

## Decision and strongest objection

Do not install `http.client.HTTPSConnection` behind the existing offline adapter
and call that genuine integration. A concrete connection factory is a small part
of the remaining work. Identity, count equivalence, durable accounting, explicit
authorization and truthful API/UI modes must be reviewed together before any
genuine dispatch. Finding a credential or setting a Boolean cannot supply those
properties.

Defer the proposed pure count-request projection implementation. It would be
deterministic, but the available documentation does not settle whether omitted
generation settings are count-neutral. Two hashes prove which bytes were used,
not that one payload safely counts the other. Adding an unused preparer now
would risk producing false readiness rather than closing the critical gap.

The product counterexample also remains: the good structured table over the
same source may be easier and safer for buyers. Provider connectivity does not
establish useful semantics, demand or an advantage over that baseline.

## Observed barriers in the current source

These are code observations at the base above, not executed integration results:

- [InferenceConfig](../cart_readback/cartreadback_app/inference_config.py) accepts
  only `offline-injected-only`. Its config hash covers reviewed model/prompt/
  parser/request settings, but not the concrete transport, account or project.
- [The service](../cart_readback/cartreadback_app/service.py) requires the exact
  offline adapter and budget classes in `_configured_budget()`. The budget binds
  that adapter config hash. `provider_contract()` only exposes fixture or
  injected-offline analysis and always reports `network_enabled: false`.
- [The HTTPS seam](../cart_readback/cartreadback_app/responses_http.py) has no
  default factory or credential loader. Its separate transport hash is not part
  of the service dispatch identity. It only permits `/v1/responses`, not the
  input-count endpoint. TLS/proxy behavior is still offline-tested groundwork.
- [Count preflight](../cart_readback/cartreadback_app/count_preflight.py) runs a
  trusted fabricated counter outside SQLite with a durable claim. There is no
  genuine count client, response parser or verified request equivalence.
- [The budget](../cart_readback/cartreadback_app/inference_budget.py) uses
  explicitly synthetic rates and counts. Its `actual_micro_usd` field is marked
  `cost_is_synthetic: true` and `is_real_charge: false`; it is not a vendor bill.
- [The CLI](../cart_readback/cartreadback_app/__main__.py) selects the fixture
  service only. A genuine analysis mode requires separately reviewed API and
  frontend behavior; a changed backend label alone is insufficient.

The current conservative reservation/claim/observation/UNKNOWN history must be
preserved. Replacing an adapter, changing labels, starting a new session or
deleting/copying the database is not recovery or renewed spending authority.

## Proposed genuine-factory contract

This is a future design, not an interface shipped by this issue.

1. **Host-owned identity.** Define a distinct genuine runtime configuration.
   Bind model and accepted model IDs, tier, language, prompts/schema/parser,
   exact request settings, count serialization revision, pricing revision,
   bounded authorization scope, deployment/runtime version and both fixed
   endpoint paths. Include count/generation transport versions, route/TLS/parser
   policy and verified account/project scope in one durable dispatch identity.
   A caller-supplied scope label is not proof of the actual billing destination.
2. **Credential separation.** Obtain credentials only through an approved secure
   workflow with a confirmed destination and least privilege. Keep secret values,
   their derivatives and callbacks out of public metadata, model inputs, proposal
   text, operation documents, logs and GitHub artifacts. Use nonsecret verified
   credential-binding metadata for scope/rotation; never hash a bearer token as
   public identity. Rebinding must stale old reviews and cannot reset history.
3. **Default denied.** Keep existing fixture/offline constructors unchanged.
   Introduce an explicit genuine adapter/runtime path rather than subclassing or
   relabelling the exact offline classes. No browser/API parameter or ambient
   environment flag alone may grant spending authority. No offline fallback
   may disguise a failed genuine call as success.
4. **Fixed transport.** A reviewed stdlib factory constructs without I/O. Only a
   durably admitted operation may connect. Preserve fixed origin/path allowlists,
   certificate and hostname checks, explicit direct or approved CONNECT route,
   strict bounded parsing, disabled debug output, no redirects and no automatic
   retry or alternate-route fallback. Add an explicit count path if reviewed;
   do not turn the current generation-only transport into an arbitrary URL client.
5. **Separate count and generation admission.** Before a count connection or
   secret retrieval, validate bounded count-call/data/runtime/price authorization
   and commit a durable count intent/claim. A prior token count is not required
   for that count operation. Before a generation connection or secret retrieval,
   additionally validate the count bound to the exact generation bytes and commit
   the worst-case generation reservation. Keep the current
   TLS-before-bearer callback sequence for both operations. A successful close is
   not proof of remote cancellation. Genuine-environment DNS/TLS/proxy/parser
   behavior requires separate evidence, including the exact deployment Python
   version and any private parser hooks. Both operations preserve UNKNOWN rather
   than retrying or resetting history after ambiguity.

## Count equivalence is a blocking evidence question

The [token-counting guide](https://developers.openai.com/api/docs/guides/token-counting)
recommends the generation payload and notes reasoning/caching-dependent counting.
The [count reference](https://developers.openai.com/api/reference/resources/responses/subresources/input_tokens/methods/count)
lists model, instructions, input, structured text, reasoning and tools, but does
not list several current generation fields, including service tier, maximum
output tokens and top-level cache options. Nested cache descriptions still refer
to request cache options. This is an ambiguity, not proof that the endpoint
accepts, rejects or ignores the omitted settings.

Do not silently strip settings, tokenize only visible text, guess from characters,
or use fabricated `OfflineInputCount` as genuine evidence. Before implementing a
client, resolve a complete supported count payload and its relation to the exact
generation bytes. Any projection needs a versioned explicit field rule, strict
types/shapes, the exact reviewed schema, immutable bodies and hashes for both
requests. Preserve token-affecting settings and account/model provenance.
Unsupported tools, history, files, images, additional fields and cache breakpoints
must fail closed for this narrow text-only scope.

Even accepted count requests do not alone establish a safe bound on actual
generation usage. Separately authorized paired observations must compare counted
and returned usage under identical reviewed settings. On uncertainty or excess
usage, retain UNKNOWN and deny another generation attempt.

## Authorization, pricing and durable accounting

Authorize a specific provider/project, approved input-data category and bounded
count/generation calls, per-call and aggregate input/output tokens, USD ceiling
and validity window before genuine use. Approving key creation does not approve
paid calls. Count operations also need bounded scope and verified billing
behavior; absence of generation is not evidence that counting is free.

The [model page](https://developers.openai.com/api/docs/models/gpt-6-luna) and
[pricing page](https://developers.openai.com/api/docs/pricing), checked
2026-11-03 UTC, list GPT-6 Luna Standard short-context text input at $0.10 and
output at $0.50 per million tokens. These are reference observations, not adopted
runtime rates or proof this project has model access. Tier, context, regional
processing, cache writes and future revisions can change cost. Verify the exact
applicable rates again before adopting an immutable genuine policy.

The [cache guide](https://developers.openai.com/api/docs/guides/prompt-caching)
documents that explicit mode without breakpoints uses no prompt cache or cache
writes. Preserve that exact narrow setting when relying on ordinary uncached
input pricing. A different caching policy needs different accounting and review.

Reuse the existing short-transaction intent/claim/CAS structure, not an external
call inside SQLite. Bind count and generation to the same verified runtime
identity and exact frozen source/config/policy/owner state. Commit worst-case
capacity before dispatch. Persist known usage even when the proposal is stale or
invalid where independently validated accounting is available. Timeout, refusal,
malformed response, missing accounting, crash or late result must never become
zero-cost success. Do not refund capacity or replay POSTs after ambiguity.

Separate synthetic calculations, genuine usage-based estimates and actual vendor
charges in the schema. Token arithmetic is not an invoice or an account-wide
vendor-enforced billing cap. A real policy cannot overwrite an old synthetic
identity to manufacture a fresh allowance. Migration and any unknown-accounting
reconciliation need explicit reviewed decisions; history stays intact.

## Truthful modes and staged acceptance

Expose analysis and payment modes independently. Future genuine analysis with
fixture payments must say exactly that; it cannot imply PayPal connectivity or
real-money readiness. The API/notice/UI must distinguish configured capability,
attempted network work and observed outcomes. Unsupported or inconsistent mode
combinations must remain blocked, not be coerced to fixture/offline.

Implement later issues in this dependency order:

1. Resolve the supported count request/equivalence contract and fixed assets.
2. Add immutable genuine runtime/account/transport identity with default-denied
   factory construction and adversarial offline tests, without selecting it.
3. Add genuine count/usage parsers, priced authorization and durable admission,
   preserving old UNKNOWN history and reviewing migration explicitly.
4. Add the explicit opt-in launcher and truthful API/UI contract with fixture
   payment isolation. Re-run all integrated checks on its exact final tree.
5. Only after secure provisioning and bounded call/data/spend approval, run
   controlled real count/generation, failure/timeout and restart observations.
   Record real request identities/usage safely. Stop on UNKNOWN; no repeated
   paid probe or database reset to conceal an inconclusive outcome.
6. Run fresh semantic evaluation and buyer comparison with the good same-source
   table. Schema validity and exact spans do not establish semantic truth.

Acceptance tests must cover changed route/project/credential binding, count/body
mismatch, stale source/config/authorization, duplicate/concurrent claims,
restart after every commit boundary, timeouts/late workers, excess/missing usage,
secret redaction, and false or unsupported provider modes. Separate offline
reproducers from authorized real observations in every report.

## Evidence boundary for this issue

This is source inspection and documentation research only. No credentials were
read or created, no count/generation request was sent, no costs incurred, and no
runtime or UI check was run for this note. Secure key provisioning is a separate
pending gate; this issue supplies neither a manual secret workaround nor a
working integration. All future application changes still require the repository
issue/branch/draft-PR/separate-review flow and exact-revision checks.

## Issue #39: executable bridge, still no supported live installation

The context-capacity alternative is now wired through the service's reservation,
claim, exchange, independent accounting and proposal compare-and-set. It does not
resolve or select the earlier counted-plan identity in `genuine_runtime.py`.
The default CLI remains fixture-only. The only executed provider-shaped evidence
for this bridge is fabricated host records/handles and fake HTTPS connections.

A trusted external provisioner would have to establish binding, pricing adoption,
concrete data/owner scope and bounded approval before installing the host context.
No supported provisioner/resolver presently supplies those facts. A Python record,
metadata hash, opaque handle or caller label is not proof. The unselected stdlib
constructor supplies mechanics only, not missing authorization or environment
readiness. The installation now owns an exact transport binding: the fixed shipped
provider constructor or a separately identified fabricated factory. Fake factory
replacement receives a fresh nonsecret generation and cannot reuse old approval
or masquerade as provider evidence. These are identity/freshness checks, not an
attestation or arbitrary Python sandbox. No actual key, endpoint call or live activation is part of this change.

See [the service bridge and limits](CONTEXT_ANALYSIS_BRIDGE.md) and API C12 for
exact lifecycle, history, public metadata and the independent-observation contract.
Reference-price arithmetic stays labelled unselected reference estimation, not
adopted project prices or actual charges, even when a separate adoption record is
carried through the host seam.
