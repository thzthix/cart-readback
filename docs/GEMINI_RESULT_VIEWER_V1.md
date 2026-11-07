# Gemini host-result viewer v1

Issue #52 defines `gemini-host-result-viewer-v1`. This addendum supersedes only
C13's prohibition on serving Gemini results, for the explicit host launcher below.
The frozen API_CONTRACT, prompt preflight, prompts, corpus, gold and scorer remain
unchanged. Ordinary LocalServer, fixture CLI, buyer UI and context UI are unchanged.
This is a separate review-only page, not a Gemini selector for the ordinary UI.

## Host action and lifetime

The trusted-host Python `view(db, owner_file, record, credential_fd, opener,
port=0)` interface in `scripts/run_gemini_analysis.py` shares the original run
validation/construction and exact single `Service.mutate(..., "analyze", ...)`
with `run`. It requires the same externally reviewed v2 record, prepared existing
DB/file identity, original owner, exact SKU/conditions, runtime, policy, key
binding, finite call/token/spend bounds and inherited private pipe. It creates no
approval, account fact, key or replacement owner. Free-tier facts and no-paid
fallback still require the external verification described in GEMINI_SERVICE.
The existing prepare/run CLI is unchanged. There is no default browser opener,
subprocess/shell launcher, credential discovery or live activation CLI.

The host must explicitly authorize both the provider action and a trusted local
browser opener before invoking this interface. The injected opener receives a
private loopback URL directly and must return promptly, without logging,
persisting, echoing or forwarding it to another service. The URL is never
returned or printed by this launcher. Tests inject fabricated openers only.
This implementation does not itself authorize or execute an actual browser
launch, existing-key setup or Google call during development.

The bound server starts serving before the injected opener is called, so a
synchronous opener may immediately fetch the page. Shutdown stops and joins the
server worker and all request handlers before releasing Service ownership.
The original Service/store/owner/runtime stays alive from that one analyze through
viewer shutdown. No runtime is reconstructed after CLI closure: the approval is
bound to its pre-execution revision. Opener failure, construction failure,
interrupt and server errors exit through server close and synchronous Service
cleanup. A watchdog is not cancellation; the lease is retained until the actual
provider/observation worker exits. Pending/UNKNOWN history is never renewed,
refunded, replaced or replayed. An expired/stale result remains nonactionable.
Restarting the launcher with the old pre-execution record fails revision checks.

## Private bounded browser handoff

The server binds literal IPv4 loopback on one ephemeral port. The host opener
receives `/viewer#launch=<ONE_USE_CAPABILITY_PLACEHOLDER>`, never the actual owner,
key or approval record. The launch capability has 32 random bytes, lives only in
server memory, expires after at most 60 monotonic seconds and can be consumed once.
The sole CSP-hashed first inline script captures it in a closure and immediately
calls history.replaceState before importing any module or fetching any asset.
Malformed paths, query/fragment syntax or history failure cannot trigger a fetch.
The HTML response uses no-referrer, no-store, same-origin resource policy and a
restricted CSP without unsafe-inline. There are no remote assets, storage APIs,
service workers, preloads or analytics.

The browser sends only the ephemeral launch capability in a bounded JSON POST to
`/gemini-viewer/api/redeem`. Exact Host, Origin and browser-supplied
Sec-Fetch-Site=same-origin are mandatory. Content type, single bounded
Content-Length, no Transfer-Encoding, exact JSON fields, duplicate keys and
cookies are checked before an atomic consume. A race has one winner; duplicate,
expired, incorrect or interrupted redemption never retries or renews access.

Redemption mints an independent random **viewer-only** capability, not the Service
owner. Cookie: `cr_viewer`, HttpOnly, SameSite=Strict,
Path=/gemini-viewer/api, Max-Age at most 600 seconds, plus the same nonrenewing
server-monotonic deadline and one server lifetime. The owner stays in trusted
host memory. Cookies are not port-scoped: another loopback service on the same
host/path could receive this limited viewer token, but it grants no Service
mutation/owner authority there. A hostile local process, browser extension or
compromised trusted host is outside this local-demo security boundary.

Fragment removal reduces subsequent history/referrer/request exposure; it cannot
prove that the initial URL never entered browser history, crash restore, the
trusted opener, OS argument handling or extensions. Complete browser nonstorage
is not guaranteed. Native browser behavior and keyboard/rendering remain untested.
If this residual exposure is unacceptable, do not launch the viewer. Do not print
or attach its URL as a fallback.

## Closed HTTP surface and public evidence

Only the allowlisted viewer HTML/modules and authenticated GET/HEAD
`/gemini-viewer/api/bootstrap` are served. Bootstrap requires the existing
viewer capability and same-origin Fetch Metadata. It never calls Store.session,
initializes an owner or reveals an actual owner-derived CSRF token. The response
explicitly projects public envelope fields, the original approved single catalog
item and the retained public checkout. New selected SKUs, conditions, policy,
approval, pricing, quota, keys or runtime cannot be supplied from the browser.
Every ordinary analyze, confirm, refresh, order, approval, return, verification,
reconcile, capture and unsupported method is rejected before Service mutation.
No order/consent controls exist. Reload reads only; it neither replays nor renews.

The separate UI requires exact Gemini provider/model/prompt/adapter/validator,
strategy, execution-kind and accounting fields. The descriptor includes the
configured model and expected returned version, explicitly labeled configuration.
The public checkout's model_version is the configured model identifier, not a raw
returned wire version. Actual wire modelVersion is not publicly reported here.
Wrong providers, historical fixture metadata, contradictory fabricated/provider
labels, known without usage and UNKNOWN with accepted snapshots are blocked.
Expired historical provider observations remain historical observations, never
reclassified as fixtures or treated as fresh consent.

Configured dispatch/network availability is not an observed send, approval,
quota, account eligibility, actual zero charge or correctness result. A durable
claim is not proof that a POST reached Google. Fabricated usage is never a provider
observation. Known accounting is not semantic truth or an invoice; UNKNOWN stays
UNKNOWN. Payments remain fixture-only and PayPal remains unconnected. The viewer
uses the identical-source baseline and quotations, with plain-text rendering.

## Offline checks and limits

Run backend discovery, `node --test ui/viewer.test.mjs`, and
`python ui/viewer_http_check.py`, in addition to all existing integrated checks.
Tests use synthetic host records/credentials and fabricated transport only. The
loopback suite exercises redemption races, malformed requests, denial before
Service/owner creation, privacy projection, expiry and unchanged single dispatch.
The Node/HTTP check consumes the actual server envelope and renders a fake DOM;
it is not native browser evidence. No real key, Google/OpenAI call, billing/quota,
model quality, PayPal, hosted Actions, deployment or contest claim is established.
