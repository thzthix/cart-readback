# Responses HTTPS mechanics: offline prerequisite, issue #20

Initial base: `e3549540595ec4da2d90fe1650ea1e4d87d0d405`. Final combined base:
`c82aeaaf2bbb8fda341c023e6f1c7b9153061c7e`, after issue #19's reviewed buyer
return flow. This slice adds only
`cart_readback/cartreadback_app/responses_http.py`, its fabricated tests and this
document. The application, CLI, WSGI, current inference configuration, payment
adapters and durable operation ledger are unchanged. No genuine model request,
credential access, account change, paid use or deployment has occurred here.

## What exists

`InjectedHTTPSTransport` implements the existing `ResponsesTransport` seam with
an explicitly provided connection factory and credential callback. There is **no
default network factory**, environment/secret loader, live-enable option, runner
or application wiring. Constructing the object does not invoke either callback.
The shipped tests supply only fake connections and a clearly synthetic token,
and fail if a real socket/default HTTPS factory is used. Trusted injected Python
code is not sandboxed; a future caller could supply unsafe code, so injection
alone is never a security or authorization boundary.

The immutable route configuration supports only direct TLS to `api.openai.com`
port 443, or HTTP CONNECT through exactly `proxy.server:3128` to that same TLS
destination. Ambient proxy variables are ignored. There is no automatic direct
fallback when the proxy refuses or is unavailable. The endpoint must equal
`https://api.openai.com/v1/responses` byte for byte. No caller-supplied host,
port, path, query, fragment, redirect or provider URL is dispatched.

The factory receives a fresh default certificate-verifying SSL context with
hostname checks, a TLS 1.2 minimum and HTTP/1.1 ALPN. Its contract is the standard
library `HTTPSConnection`, including TLS/SNI after CONNECT, honoring the supplied
strict response class, and no I/O during construction. An actual stdlib response
that bypasses the selected parser is rejected. Debug output is disabled; automatic
reconnection is disabled. Only after explicit connect/TLS completes is the
credential callback evaluated. The bearer value cannot contain whitespace,
control characters or HTTP-header injection, and is never put in CONNECT.
The context uses normal system CA trust; this is not certificate pinning or a
claim that the host's trust store is uncompromised. No TLS/proxy bypass exists.

There is one POST, with the exact adapter-produced bytes, fixed JSON/identity
encoding headers, explicit byte length and connection-close preference. No
retries, credential refresh or fallback occur. Raw response headers, error bodies,
credentials and exception text are not persisted or logged by this module.
Only a bounded ASCII request ID survives header validation. Non-200 responses,
including redirects, are closed without reading their bodies or following links.

## Bounded consumption and uncertainty

The request is limited to 64 KiB. A narrow response subclass validates exact
HTTP/1.1 status and raw CRLF-terminated header lines before stdlib normalization,
admitting at most 64 fields and 16 KiB of raw header bytes with smaller per-field
bounds. This does not bound TLS, socket or buffered-reader allocation to 16 KiB.
Folded/malformed/unterminated headers, duplicate relevant headers, ambiguous
length/transfer framing, compressed or non-JSON bodies, unsupported HTTP versions
and malformed request IDs fail closed. Plain chunked and close-delimited HTTP/1.1
JSON responses are supported without decompression. Chunk sizes must be bounded
plain hexadecimal with exact CRLF data/final terminators; chunk extensions and
trailers are intentionally unsupported and rejected rather than discarded.
Body reads are at most 8 KiB, with a 128 KiB total limit and an extra-byte probe.
An explicit Content-Length must agree with bytes actually consumed.

Connect uses the adapter's shared deadline/connect bound. Write, response-header
and body phases refresh the socket inactivity timeout from the same remaining
deadline, then check the absolute deadline after returning. The existing adapter
watchdog bounds the caller's overall wait. DNS, a malicious slow header/chunk
framing peer, OS calls and trusted callbacks cannot be forcibly interrupted by
Python socket timeouts alone. A timed-out worker can remain alive until its call
returns. These offline tests do not prove TCP cancellation, real proxy/TLS
behavior, a hard process-wide memory cap or zero provider charges.

The caller must consume or explicitly close every returned WireResponse, even
when iteration never starts. Exhaustion, generator cancellation and explicit
close close the response and connection best effort and release the local slot.
KeyboardInterrupt/SystemExit also perform cleanup before propagating. An
unfinished close or any transport/response failure permanently blocks that
transport instance. Cleanup failure also blocks reuse; closing is not proof of
remote cancellation. A second concurrent exchange is rejected without another
factory/credential call. There is no queue. Replacing a transport must never be
used to bypass the service's durable UNKNOWN breaker or admission history.

No error becomes zero-token or zero-dollar success. The existing service records
dispatched failures lacking validated observation/accounting as UNKNOWN and
blocks further nonfixture work across restart. Known usage still comes only
from a strictly validated observation, not a transport guess. See
[analysis dispatch](ANALYSIS_DISPATCH.md). This slice changes none of that logic.

## Mandatory gates before genuine use

The transport's nonsecret metadata has a route/version/config hash, but the
current `OfflineResponsesAdapter` and service do **not** incorporate that hash
into their immutable dispatch identity. Their configuration intentionally remains
`offline-injected-only`. A future implementation must fence every transport,
account/project and dispatch-relevant setting in the same reservation and review
identity, rather than injecting a real factory behind an offline label. Any
provider-mode envelope reporting `network_enabled: false` must remain restricted
to genuinely offline factories. No runtime network mode is introduced here.

The following are still mandatory, separately authorized and reviewed:

- Approved data and bounded call/input-token/output-token/USD authorization.
- Exact current model/service-tier availability and pricing, with a durable
  conservative pre-dispatch token/cost reservation and known/UNKNOWN accounting.
  The existing attempt count is **not a spending cap**. An unpriced model, tier,
  unknown count or unknown charge must fail closed. No price or tier is guessed
  or selected by this slice.
- Secure, per-action-approved credential provisioning/use with least privilege,
  no public secret exposure and no persistent-access setup by inference.
- Reviewed concrete factory/runtime integration, truthful mode metadata and
  unchanged deterministic consent/payment boundaries. No secret may enter model
  source/conditions, application bootstrap, proposal text or durable public data.
- Explicitly authorized real TLS/proxy/provider schema and usage validation,
  including failure/timeout/restart evidence, plus fresh semantic evaluation and
  buyer comparison with the good same-source table.

Do not wire this class into the existing default server or deployment to skip
these gates. It is offline-tested transport preparation, not a working AI
integration, provider acceptance, cost guarantee or permission to spend.

## Reproduction and primary references

From `cart_readback/`, run
`python -m unittest discover -s tests -p 'test_responses_http.py' -v`.
The complete README checks must also run on the final assembled revision;
component passes do not certify another checkout or an integrated PR head.
Tests use manufactured HTTP responses, not observed vendor responses. No API
request, real credential, DNS/TLS handshake or PythonAnywhere proxy request is
made. The existing adapter's fabricated envelope test proves only local seam
compatibility, not current API schema acceptance or genuine model output.
Raw-wire regressions also exercise the actual stdlib HTTP parser over a fake
socket, including malformed status/header/chunk framing and connection-close
detachment. The narrow parser uses private http.client chunk-reading hooks;
it must be rechecked on the exact deployment Python version before any genuine
factory is permitted. Current observed receipts identify the Python version used,
not a claim that all supported interpreter versions were tested.

Reviewed 2026-11-03 UTC:

- [Python 3.11 HTTPSConnection and CONNECT](https://docs.python.org/3.11/library/http.client.html)
- [Python 3.11 SSL context defaults and checks](https://docs.python.org/3.11/library/ssl.html)
- [PythonAnywhere free-account proxy restrictions](https://help.pythonanywhere.com/pages/403ForbiddenError)

These primary references inform mechanics, not an integration result. Actual
allowlist availability and deployment/runtime behavior must be verified in the
authorized target environment without bypassing an access denial.
