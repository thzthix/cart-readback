# Offline buyer approval and return preparation

This is an offline prerequisite, not a connected PayPal checkout. Default CLI
behavior is unchanged: six synthetic SKUs, scripted analysis and fixture payment.
There is no credential lookup, provider switch, OAuth flow, genuine network
transport, spending or deployment. No new dependency is needed.

## Buyer-facing behavior

Analysis and payment mode are shown separately. Injected fabricated PayPal wire
uses the `paypal-sandbox-offline` identity; it cannot impersonate a fixture or real
PayPal. A validated fabricated approval URL may be displayed as inert text, never
as an external link. Fixture approval remains available only to fixture payments.

An injected callback preparation can be exercised with fabricated provider data.
The landing removes its query before bootstrap, restores the existing owner and
offers a deliberate same-order return recheck. Neither page visitation nor the
word `approved` authorizes capture. A fully verified APPROVED provider observation
is required, followed by fresh unchecked final capture intent. Cancellation only
records the buyer return; it cannot assert remote cancellation or create another
order. Refresh/history never replays the return or final capture decision.

## Boundaries

- Exact literal-loopback callback origin; no arbitrary callback or redirect URL.
- Random one-use state, hash and 20-minute expiry bound to the durable owned
  checkout and existing wire operation. Raw state stays out of public envelopes
  and audit observations. The private wire ledger necessarily holds callback URLs.
- Read-only static GET/HEAD return route. No owner-cookie lookup, session creation,
  provider GET, state consumption or monetary action during landing.
- Normal same-origin JSON POST, existing HttpOnly Strict owner cookie, exact CSRF,
  revision/snapshot and current source/configuration checks. No permission bypass.
- Provider GET outside SQLite transactions, followed by a fresh binding check.
  Duplicate concurrent returns cannot commit twice; mismatches and uncertainty
  retain the same order. No automatic create/capture replay, void, refund or reset.
- Distinct provider modes are offline host descriptors, not proof arbitrary
  injected executable code cannot open a network socket. No network-capable
  injection is selected by the server/CLI. A future enabled provider factory needs
  explicit authority and a separately reviewed mode/capability/budget contract.

Exact API details and transition rules are in [C11](../cart_readback/API_CONTRACT.md#c11--offline-buyer-return-and-independent-provider-modes).
The pre-existing payment ledger/crash design remains in [PAYMENT_DISPATCH.md](PAYMENT_DISPATCH.md).

## Local evidence commands

From `cart_readback/`, run the backend and independent suites, `python ui/check.py`,
`node --test review/test_independent_ui.mjs`, compilation, pinned Ruff and the four
HTTP smoke modes listed in README. `tests/test_buyer_return.py` adds direct
service and actual loopback HTTP checks. `ui/return.test.mjs` covers volatile
callback parsing/history and nonnavigation with a minimal fake DOM.

These commands are checks to execute, not a claim they passed. Exact artifact
hashes, observed results and independent review belong in the PR/review receipt.
C11 changes the contract dependency hash, so PREFLIGHT.json and its SHA256SUMS
entry are regenerated with the documented preflight command. This is a receipt
migration only; prompt/corpus/gold/scorer bytes are unchanged.
Native browser rendering/accessibility, real PayPal payload/return behavior,
merchant acceptance, account security, genuine model integration, customer value,
application CI and production deployment remain separate unverified gates.

## Documentation reference

The mapping follows PayPal's documented
[Orders integration](https://developer.paypal.com/whats-an-order/) and
[full integration example](https://developer.paypal.com/checkout/put-it-all-together/),
inspected 2026-11-03 UTC. The offline request uses the documented experience
context fields and a separate merchant review/capture decision. Documentation
inspection is not provider acceptance evidence. App-switch and JS SDK flows are
not implemented or claimed by these static callback preparations.
