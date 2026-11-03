# Genuine runtime identity, issue #35

Status: **pure identity/fencing primitive; every capability remains blocked**.
Source base: `ab2a97f4ead67509d1aef4bb295b180714c3a085`. The existing service,
CLI, offline adapters, durable records and provider labels are unchanged.

## Implemented boundary

[`GenuineRuntimeIdentity`](../cart_readback/cartreadback_app/genuine_runtime.py)
is a separate immutable value, not a renamed or subclassed offline configuration.
Construction accepts only the reviewed language (`en`/`ko`) and planned route
(`direct`/`pythonanywhere`). It reads and verifies the shipped prompt/schema
assets, then snapshots a canonical nonsecret document. It does not construct a
network connection, retrieve credentials, inspect environment variables, price
a call or admit an operation.

The document binds both fixed provider endpoints, accepted model, prompt and
schema hashes, the complete planned text-only generation contract, route, TLS,
HTTP/JSON parser policy, limits, deadlines, no retry/redirect/fallback, and the
actual Python and OpenSSL versions. Separate count, credential-binding, pricing,
authorization and runtime revisions participate in the same digest. These are
planned requirements, **not claims that a genuine transport already enforces
them**. Existing offline adapters are neither wrapped nor selected.

`metadata` returns a deep copy. `require_same_identity(saved_digest)` rejects a
missing, malformed or mismatched plan fingerprint. Consumers should construct a
fresh identity at a later review boundary and compare it with the saved review;
an old object is a snapshot, not an automatic detector of files changed afterward.
This closes the pure review/fencing identity step for later integration without
pretending to provide an executable runtime factory.

The immutable `capability` result has `available=False` and seven specific
blockers. Its `require_dispatch()` always raises `COUNT_CONTRACT_UNRESOLVED`.
Neither a matching digest nor a supported route changes that result. There is
no send, count, adapter, credential callback, factory callback, live flag or
fallback interface. Frozen dataclasses protect ordinary use, not hostile code
that already executes inside the process.

## Evidence that is deliberately absent

Account, project and credential-binding references are null. No constructor
parameter accepts an account name, project label, token hash, claimed verification
or approval Boolean. A source label cannot attest to a real billing destination.
Secret values and their derivatives are not accepted as identity material.
Future verified nonsecret references require a separately reviewed trusted
binding/provisioning boundary; this module does not implement that boundary.

Pricing and bounded count/generation authorization references are also null.
No synthetic rates or published reference price become an adopted policy.
Durable admission, genuine transport and deployment verification are absent.
The fingerprint is a **plan identity**, not an exact per-operation request hash:
generation/count body hashes remain null until later authorized request work.
An identity change is never permission to reset prior UNKNOWN or spent capacity.

For this counted plan, the [existing design gates](GENUINE_PROVIDER_RUNTIME.md)
remain blocking. Theo's
2026-11-03 source review confirmed that the count reference and the generated
[official SDK parameters at a fixed revision](https://github.com/openai/openai-python/blob/f6e8480f9a5b2a4d02b17a1da54a1e57964bc312/src/openai/types/responses/input_token_count_params.py)
do not define count handling for six fields in our generation body:
`service_tier`, `max_output_tokens`, `prompt_cache_options`, `store`, `background`
and `stream`. This module records those gaps. It does not strip the fields,
construct a six-field projection or claim equivalence from two hashes.

The documented [count response](https://github.com/openai/openai-python/blob/f6e8480f9a5b2a4d02b17a1da54a1e57964bc312/src/openai/types/responses/input_token_count_response.py)
contains an object marker and input-token count, not model/project/tier
attestation. No real count request or paired generation observation has run.
Count billing is unresolved too. Genuine dispatch remains denied independently
of whether the pure identity regression passes.

An equivalent count is not claimed to be mandatory for every possible future
runtime. A distinct, separately reviewed strategy could reserve a conservative
whole-context capacity bound without counting. That would need its own model
limit evidence, maximum applicable pricing, bounded authorization and durable
accounting policy. It must not fabricate `OfflineInputCount`, relabel the current
counted plan or clear UNKNOWN history. No such policy is adopted or implemented
in this issue; this module's counted-plan capability remains blocked.

## Offline checks and remaining integration

Run the focused suite from `cart_readback/`:

```sh
python -m unittest discover -s tests -p 'test_genuine_runtime.py' -v
```

Tests cover immutable copies, strict enums and unsupported override parameters,
sanitized failures, changed route/language/revision/host fingerprints, shipped
asset mismatch, denial before network construction, no ambient secret lookup,
absent evidence and the fixed request settings versus the existing offline
builder. These checks do not establish provider acceptance, TLS behavior in a
deployed environment, account binding, count equivalence or model quality.

Use all applicable README aggregate checks on the final changed tree. A later
integration issue must supply actual verified binding, resolved counting or a
separately reviewed conservative usage bound, priced bounded authorization,
durable admission, genuine transport and truthful
API/UI selection. No caller-supplied label/Boolean can turn this implementation
into that integration. No credentials, real API requests, costs, PayPal actions,
deployment or submission are included here.
