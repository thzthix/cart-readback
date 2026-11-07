# Gemini generateContent client, not yet connected

The owner selected an existing Gemini key. The OpenAI Responses request and
runtime cannot accept that key: Gemini uses a different endpoint,
authentication, request schema and response/usage envelope. This change adds a
concrete Gemini client and HTTPS implementation, without claiming a successful
provider call. No Service, HTTP or CLI path imports or selects these modules.
The default app remains fixture-only. There is no key loader, installer or
supported live runner.

## Implemented contract

`GeminiClient` prepares canonical UTF-8 text-only requests using the exact
verified v2 evidence system/user prompt and schema. Two exact endpoints are
allowlisted, one for the explicitly selected model: -
`https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent`
-
`https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent`

One candidate, 2,048 maximum output tokens and JSON schema are explicit. Legacy
2.5 uses `thinkingBudget: 0`. Current 3.5 uses `thinkingLevel: MINIMAL`, which
does not promise zero thoughts. There is no model fallback or automatic
migration. No tools, grounding, files, history, explicit cache or retry is
requested. The exact expected returned model version is required configuration;
an alias echo is not proof of a pinned checkpoint, account or billing tier.
Current account/model eligibility still needs verification. Indexed official
notices restrict 2.5 to prior active 2.5 users; an old key/project alone is not
proof. Current official indexed model documentation recommends 3.5 Flash-Lite.
Selecting 3.5 requires both its explicit model and expected returned version;
there is no live default. The config and verified bundle are read-only.

Responses require one model-role final text STOP candidate, a bounded provider
response identity, exact expected model version, valid JSON, ordered
conditions, and exact code-point evidence spans. An optional standard-base64
`thoughtSignature` may accompany that final text; it is bounded, validated and
discarded, never persisted/replayed or treated as authority. A missing/False
`thought` marker is supported; actual thought content is rejected. Multiple
parts and tools remain unsupported. No Markdown repair, fallback or conversion
of technical failures to successful unknown results occurs. Required input,
candidate and total usage counters and optional thoughts must be nonnegative
integers with consistent sum. Output observation includes both candidate and
thinking tokens and is capped by the requested output limit. Nonzero thoughts
fail for the 2.5 zero-thinking contract. Nonzero cache/tool or unknown token
counters, contradictory details and non-text token details fail closed. Empty
or zero TEXT cache/tool detail lists may describe zero usage. Structural
validation does not establish that a quote entails a semantic conclusion or
that the usage reflects a bill.

`GeminiHTTPTransport` is synchronous and one-shot, including after a failure.
It fixes direct verified TLS to the Google host and sends the existing key only
in `x-goog-api-key`, after connection. It uses the previously reviewed strict
HTTP/1.1 status/header/chunk parser, JSON/framing checks and bounded body reads
under one shared deadline. A bounded buffering wrapper refreshes the host guard
and remaining socket timeout before every raw receive, including status/header
and chunk framing reads. TLS context creation ignores `SSLKEYLOGFILE`; session
key logging is explicitly disabled. It does not use ambient proxies, redirects,
reconnect, retries, environment credentials, logging, credential caches or
hidden workers. No connection factory is selected by default. Both response and
connection cleanup are attempted even if closing one raises an interruption.
Native DNS, connect, TLS/send and cleanup are synchronous and have no hard
cancellation proof; their actual platform timing requires separate validation.
A late result is rejected, and service ownership must last until the worker
truly exits. Cleanup completion does not prove remote cancellation or zero
charges. The caller retains all operation ownership and records ambiguity even
when no usable proposal is returned.

Three explicit trusted host callbacks are required: a connection factory, a
credential borrower, and an I/O claim guard. The guard must return `None` on
success and raise to deny; every other return value, including `False`, is
rejected. The guard runs before connection construction/connect, credential
activity, POST and each read. Those callbacks are **not an authorization
system**, secure provisioner, identity attestation, or spending cap. A borrower
must check its exact approved credential binding. A guard must recheck the
durably committed exact request/data/owner/runtime, call/token/spend
reservation and authorization expiry. The client intentionally has no `propose`
method and is not a supported `Service` InferenceAdapter. Constructing another
transport never replenishes external capacity.

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
focused tests prohibit real sockets/default TLS construction. Passing them
proves local request/parser/transport behavior, not Google schema acceptance,
TLS reachability, quota, account mapping, billing, model quality or user
benefit.

Official references consulted November 7, 2026: -
https://ai.google.dev/api/generate-content -
https://googleapis.github.io/js-genai/release_docs/interfaces/types.Part.html -
https://ai.google.dev/gemini-api/docs/structured-output -
https://ai.google.dev/gemini-api/docs/thinking -
https://ai.google.dev/gemini-api/docs/pricing

The web reader returned unsupported-content-type errors for direct
documentation fetches; indexed official API excerpts confirmed generateContent,
responseJsonSchema, modelVersion, responseId and thought-inclusive total
tokens. Current indexed 3.5 model/thinking pages support structured outputs and
MINIMAL thinking without a zero-thinking guarantee. Sources also include: -
https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite -
https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash-lite -
https://ai.google.dev/gemini-api/docs/deprecations -
https://ai.google.dev/gemini-api/docs/generate-content/thinking

No live API/schema or current price was verified. No vendor SDK/dependency,
frozen prompt, payment source, database migration, persistent credential or
runtime default was changed.
