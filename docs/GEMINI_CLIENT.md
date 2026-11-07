# Gemini generateContent client, not yet connected

The owner selected an existing Gemini key. The OpenAI Responses request and
runtime cannot accept that key: Gemini uses a different endpoint, authentication,
request schema and response/usage envelope. This change adds a concrete Gemini
client and HTTPS implementation, without claiming a successful provider call.
No Service, HTTP or CLI path imports or selects these modules. The default app
remains fixture-only. There is no key loader, installer or supported live runner.

## Implemented contract

`GeminiClient` prepares canonical UTF-8 text-only requests using the exact verified
v2 evidence system/user prompt and schema. The sole endpoint is
`https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent`.
One candidate, 2,048 maximum output tokens, JSON schema and thinking budget zero
are explicit. No tools, grounding, files, history, explicit cache or retry is
requested. The exact expected returned model version is required configuration;
an alias echo is not proof of a pinned checkpoint, account or billing tier.
Current model availability and account eligibility still need verification.

Responses require one model-role text-only STOP candidate, a bounded provider
response identity, exact expected model version, valid JSON, ordered conditions,
and exact code-point evidence spans. No Markdown repair, fallback or conversion
of technical failures to successful unknown results occurs. Required input,
candidate and total usage counters must be nonnegative integers with consistent
sum. Nonzero thinking/cache/tool/unknown token counters and non-text token details
are unsupported and fail closed. Structural validation does not establish that
a quote entails a semantic conclusion or that the usage reflects a bill.

`GeminiHTTPTransport` is synchronous and one-shot, including after a failure.
It fixes direct verified TLS to the Google host and sends the existing key only
in `x-goog-api-key`, after connection. It uses the previously reviewed strict
HTTP/1.1 status/header/chunk parser, JSON/framing checks and bounded body reads
under one shared deadline. It does not use ambient proxies, redirects, reconnect,
retries, environment credentials, logging, credential caches or hidden workers.
No connection factory is selected by default. Cleanup completion does not prove
remote cancellation or zero charges. The caller retains all operation ownership
and records ambiguity even when no usable proposal is returned.

Three explicit trusted host callbacks are required: a connection factory, a
credential borrower, and an I/O claim guard. The guard runs before connection
construction/connect, credential activity, POST and each read. Those callbacks
are **not an authorization system**, secure provisioner, identity attestation,
or spending cap. A borrower must check its exact approved credential binding.
A guard must recheck the durably committed exact request/data/owner/runtime,
call/token/spend reservation and authorization expiry. The client intentionally
has no `propose` method and is not a supported `Service` InferenceAdapter.
Constructing another transport never replenishes external capacity.

## Remaining connection gates

1. Obtain a supported secure route to the owner's existing key, verify its
   Google account/project and current model/tier/pricing. Do not paste a key into
   chat or commit it. Creation of a new key is not an automatic fallback.
2. Obtain required action-time approval for credential transmission/provisioning
   and any persistent access. Select a concrete synthetic catalog/data scope,
   owner, finite generation attempts, input/output limits and maximum spend.
   A billing-cap notification alone grants none of this authority.
3. Add and separately review genuine Gemini Service/HTTP/UI composition with a
   durable shared call/token/spend ledger, identity/freshness fences, timeout and
   restart UNKNOWN behavior. Do not reuse OpenAI pricing or falsely label a
   fabricated transport as provider evidence. Keep PayPal and inference authority
   independent. No payment action is enabled by this client.
4. With those gates satisfied, run a bounded provider acceptance test, retain
   sanitized actual observations and usage, then test source-backed semantics
   and buyer benefit against the same-source table. These stages have not run.

## Evidence and sources

All tests use fabricated envelopes, in-memory wires and synthetic credentials;
focused tests prohibit real sockets/default TLS construction. Passing them proves
local request/parser/transport behavior, not Google schema acceptance, TLS
reachability, quota, account mapping, billing, model quality or user benefit.

Official references consulted November 7, 2026:
- https://ai.google.dev/api/generate-content
- https://ai.google.dev/gemini-api/docs/structured-output
- https://ai.google.dev/gemini-api/docs/thinking
- https://ai.google.dev/gemini-api/docs/pricing

The web reader returned unsupported-content-type errors for direct documentation
fetches; indexed official API excerpts confirmed generateContent,
responseJsonSchema, modelVersion and responseId. No live API/schema or current
price was verified. No vendor SDK/dependency, frozen prompt, payment source,
database migration, persistent credential or runtime default was changed.
