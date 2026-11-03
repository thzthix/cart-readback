# PayPal HTTPS/OAuth groundwork — issue #30

Base: main `0f458bf08a29ceee2263df6f4304f5446762c125`. This adds an isolated
standard-library exchange core, tested only with fabricated in-memory credentials
and fake connections. **No genuine OAuth, PayPal call, account/credential access,
payment or TLS connection occurred. PayPal remains UNCONNECTED.**

`SandboxHttpsTransport()` has neither a credential source nor connection factory
by default and refuses to send. No app/CLI provider factory, credential loader,
live-enable setting or genuine provider mode is added. The marked network-capable
core is rejected by `OfflinePayPalSandboxAdapter`: actual networking must not hide
behind an offline badge. Tests alone use a clearly test-only bridge whose supplied
factory creates fake connection/socket/response objects. Injected Python remains
trusted code, not an I/O sandbox.

## Prepared exchange and configuration

An explicitly supplied future factory could construct a direct stdlib
HTTPSConnection only for `api-m.sandbox.paypal.com:443`. The shipped constructor
is unselected; tests replace HTTPSConnection and forbid socket creation. TLS uses
the verified system trust store, required certificate validation, hostname checks
and TLS 1.2 minimum. No arbitrary host, custom context/CA, disable-verification,
tunnel or debug-output option is exposed by the core. System trust is not PayPal
certificate pinning and may include locally installed trust roots.

Before credential-source or factory work, reject nonempty case-insensitive
`*_proxy` environment settings, including HTTP_PROXY/NO_PROXY, and discovered
system proxies. Proxy-discovery errors reject. SSL_CERT_FILE/DIR overrides also
reject; configuration values are never echoed. Detection is conservative and
platform dependent: urllib proxy discovery does not prove that every operating
system proxy mechanism is absent. A configured proxy is refused, never silently
bypassed. **PythonAnywhere free hosting requires an outbound proxy and is not
supported by this direct-only groundwork.** Proxy support needs separate review.

Each accepted send performs at most one OAuth token exchange and one Orders
exchange. OAuth is a fixed POST to `/v1/oauth2/token`, Basic authorization in the
header and exact `grant_type=client_credentials` form bytes. Orders use only
validated create/get/capture paths, the exact supplied canonical body and
server-owned UUIDv4 request ID for POST. Caller Authorization, Host and extra
headers cannot cross this seam. No retries, redirects, refresh-and-replay on 401,
live endpoint, response-link following or connection reuse are implemented.

Only bounded ASCII client IDs/secrets supported by the conservative Basic-input
validator are accepted. Token JSON must have a bounded Bearer token, finite
positive integer lifetime (bool rejected) and bounded scope metadata. Scope does
not grant authority to call anything. A monotonic expiry starts before the token
request and subtracts one second of safety margin; unusably short tokens reject
before Orders. Both exchanges share the caller deadline, limited further by token
expiry. A fresh token is requested for each send: no token cache, refresh or stored
credential is added. This sacrifices call volume/latency to keep lifecycle small;
a future acceptance run must authorize the OAuth exchanges too.

The configuration digest includes fixed route, public credential-reference
identity, timeout policy and resource limits. It excludes credential/token values.
A genuine provider factory must bind that identity into durable dispatch and use
a truthful genuine mode; this change does not implement that live gate.

## Resource and redaction policy

- Request JSON is capped at 64 KiB and depth 16. OAuth response is capped at
  8 KiB/depth 8; Orders body is capped at 64 KiB for existing normalization.
- Require one canonical Content-Length and identity encoding; reject transfer
  encoding, duplicate headers, malformed/overlong length, compressed bodies,
  unsupported media type/charset, short bodies and bytes a reader exposes beyond
  the declared frame. Stdlib hides bytes outside Content-Length; read(1) cannot
  prove upstream trailing-byte absence. Mandatory close/no reuse avoids treating
  those bytes as another response. Chunked responses reject; real PayPal
  interoperability remains untested.
- Validate at most 32 headers / 8 KiB aggregate after the HTTP parser returns.
  This is not a preallocation bound: stdlib header/interim parsing has its own
  version-dependent limits before this check. No universal slow-drip/header
  memory guarantee is claimed.
- TLS/connect, request, response and body calls receive remaining per-call waits.
  A daemon worker imposes a caller-visible overall timeout and single flight.
  Timeout, failed startup or uncertain exchange poisons that instance; a late
  result is never reused and cannot open another dispatch right.
- A timed-out worker may still be blocked in DNS, TLS, header or socket work.
  Python thread timeout does not prove cancellation or timely socket cleanup.
  A retained socket reference handles stdlib's Connection: close detachment while
  the response owns its makefile. Once the frame is fully consumed, stdlib may
  release that final descriptor reference; no socket option is changed after its
  closure, and its EOF read is immediate. No reconnect or replay occurs.
  Responses and connections close in the worker's finally path when it returns;
  failed close becomes unknown. Hard cancellation/resource reclamation remains
  a mandatory live-enable gate.
- Credential/token object representations, transport and response representations
  hide values. Errors are fixed sanitized ambiguity, without raw exception chain,
  headers or response bodies. No logs or persistence are added. Python memory and
  arbitrary caller serialization cannot be claimed securely zeroized/redacted.

## Offline evidence and unchanged authority

Focused checks: `python -m unittest discover -s tests -p test_paypal_https.py -v`
from `cart_readback/`. Tests forbid socket creation; the direct constructor is
mocked. Fake TLS settings, proxy refusal before synthetic credential access,
OAuth/request bytes, headers/framing/size failures, 401/3xx without replay,
resource errors, expiry/deadline poisoning and adapter rejection are exercised.
Fake HTTPS/OAuth also passes through the existing owned durable payment lifecycle;
I/O probes verify no application SQLite write transaction is held, and synthetic
credential/token markers do not enter the operation ledger.

Service, Store, API/UI, buyer returns, default fixture selection, model/budget
logic, existing deterministic authority checks and frozen artifacts are unchanged.
Existing UNKNOWN retains the same provider order and single dispatch identity.
No provider response fact is invented to satisfy verification. The final check
receipt and separate fixed-artifact review must bind exact source hashes; these
instructions are not themselves a successful test or provider observation.

## Sources and next genuine gate

Reviewed read-only 2026-11-03 UTC:
[PayPal authentication](https://developer.paypal.com/api/rest/authentication),
[PayPal requests](https://developer.paypal.com/api/make-api-requests/),
[OAuth response rules](https://www.rfc-editor.org/rfc/rfc6749.html#section-5.1),
[Python SSL defaults](https://docs.python.org/3/library/ssl.html#security-considerations),
[Python HTTP client](https://docs.python.org/3.11/library/http.client.html) and
[proxy behavior](https://docs.python.org/3.11/library/urllib.request.html).
These informed mapping and defensive choices; they do not establish acceptance.

Before genuine execution, separately authorize the exact sandbox merchant/app,
secure credential provisioning and destination, bounded OAuth/Orders operations
and synthetic data. Add a genuine capability/provider factory with durable config
identity, reviewed network cancellation/DNS/header/proxy controls and truthful UI
labels. Then verify real TLS, credential/token behavior, response framing and
complete returned payee/items/reference/snapshot/capture facts. If PayPal omits
required evidence, remain unknown rather than substitute the request. Only then
can an authorized buyer approval → server recheck → fresh capture-confirmation
run establish that limited sandbox lifecycle. No account/legal setup, credential
transmission, real transaction, spending or deployment follows from this code.
