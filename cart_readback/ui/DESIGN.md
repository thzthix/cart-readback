# CartReadback / a buying desk, not a storefront pitch

Owner: Chloe | AI Design/Frontend (`import_buyer_interface`). Imported under real issue #5 and branch `feat/5-buyer-review-ui` on 2026-11-03 UTC. Original local design work CR-003 predates this issue; it was not a GitHub issue. This preserves the pre-existing CartReadback layout, not newly invented feature history. Prior SessionClose/Closeout screens are archival references, not shipped.

## D01 — The job and strongest objection

Help a buyer review one already-chosen keyboard against one or two explicitly selected conditions: key layout and included cable. The buyer—not a model—decides whether to keep a mismatch or continue without an established fact. The current app is entirely synthetic. No genuine model inference, PayPal request, real purchase, customer adoption, or saved-time result is claimed.

The strongest alternative is a good product table. It appears first, with all six layouts, included cables, and item prices. A selected product’s complete original description is available immediately without entering conditions or running analysis. The evidence readback uses that identical source; it is not given privileged facts. The UI is not an experiment showing that AI is better. Preparation, preference input, review, correction, and completion effort still need a legitimate comparison with actual participants.

## D02 — Sources → decisions

Inspected 2026-11-02 UTC unless noted. These are source-informed choices, not proof of our app’s usability or conversion performance.

| Source | What it contributes | Applied decision / limit |
| --- | --- | --- |
| [getdesign.md](https://getdesign.md/) | A reusable document should connect visual tokens, components, and rationale. | This file is the design contract. No commercial kit, brand analysis, fonts, imagery, or third-party component code was copied. The site’s marketing claims are not our evidence. |
| [W3C supported-choice pattern](https://www.w3.org/WAI/WCAG2/supplemental/patterns/o7p03-supported-choice/) | Explain changed conditions, exclusions, and consequences beside a choice. It is supplemental guidance, not a conformance standard. | Per-condition match/conflict/unknown words, exact quotes, separate unchecked acknowledgements, and a clear warning when reviewed information changes. No disability information is collected. |
| [Baymard included-accessory research](https://baymard.com/research-articles/included-accessories-image) | Its observed participants sometimes inferred included items from imagery and struggled to find inclusion information. | A strong included-cable column precedes the readback. “Not stated” is distinct from explicit exclusion. A pictured cable is never treated as included. This research also supports the non-AI alternative; its historical statistics are not presented as ours. |
| [GOV.UK check answers](https://design-system.service.gov.uk/patterns/check-answers/) | Review the actual submitted information before a consequential action. | An exact SKU/quantity/USD amount/conditions/source-version summary precedes confirmation. Editing before order creation revokes consent. Order approval and final capture intent remain separate. No GOV.UK styling or component code is reused. |
| Prior non-generic design research (local archival SessionClose design notes; not imported) | Practitioner critiques favor specific content hierarchy and meaningful states over interchangeable landing-page decoration. | A continuous editorial workspace, small numbered sections, actual table rows and original descriptions. No hero pitch, gradient, card grid, testimonials, decorative AI symbol, invented metric, or stock-photo shopping story. Those critiques are opinion, not controlled evidence. |
| Buyer problem research (local archival brainstorm-buyers-10.md), CartReadback section; not imported | A wrong key layout is a plausible concrete mistake, not proven demand for this solution. | UK QWERTY, German QWERTZ, and US QWERTY are distinct typed conditions. ANSI/ISO geometry is not silently converted to a language/keycap layout. |

## D03 — Visual contract

An editorial review sheet: warm paper, dark ink, restrained forest actions, serif only for the task title and original text. The catalog is a table, not six sales cards. Rules and whitespace group content. The source/readback are neighboring columns on wide screens; after that, one continuous order summary. No shadows, gradients, remote assets, icon library, motion, or web font dependency.

Tokens in `styles.css`: paper `#f8f7f2`, near-white `#fffefa`, ink `#242a27`, muted `#565d56`, divider `#d0d1c6`, control border `#757d72`, action `#274d3a`, match wash `#eaf0e8`, warning `#76500d` on `#fff1d4`, conflict `#963728` on `#fff0eb`, focus `#005fcc`. System body 16px/1.55. Title 32–48px Georgia; source 18–19px Georgia. Metadata 12–13px system/monospace. Section title 20–22px. ISO currency and tabular numbers stay visible.

Native controls target 44–46px comfortable hit areas. A radio selects an exact SKU; no product or condition is preselected. Borders, text, and explicit labels distinguish states, not color alone. At 800px evidence and order columns stack; at 480px conditions stack. At 320px the comparison table keeps readable columns in a separately labelled horizontal scroll region; the rest is intended to fit the viewport. Long hashes/source text wrap. These are implemented responsive rules, **not visually verified 320px behavior**.

`check.py` calculates token contrast from sRGB; it does not certify rendered contrast, typography, controls, focus placement, or WCAG compliance. Native keyboard navigation, screen readers, zoom, and focus visibility still need browser inspection.

## D04 — Truth labels and interaction boundaries

- Persistent “Fixture mode · sample shop”; source says synthetic, readback says scripted/not AI, order says fixture/no PayPal/no money. `FEATURE_FLAGS.live=false`; a non-fixture bootstrap, model, or payment response blocks the UI.
- All product/model strings use `textContent`/text nodes. Exact spans use Unicode code points with `Array.from`, not UTF-16 offsets. Source identity and quotes are checked before display. Quote validity does not prove semantic correctness.
- Unknown/conflict each has an individual initially unchecked acknowledgement. Acknowledging an unknown never changes it into a match. Changing an acknowledgement clears the final review checkbox.
- Changing SKU/conditions before an order exists immediately hides the old review and clears consent. Server revision, review ID, source-bound fingerprint, and confirmation are submitted; the browser never sends price/currency/merchant authority.
- Fixture create → explicit simulated buyer approval → explicit server recheck → fresh unchecked final capture intent → fixture capture are separate actions. No automatic redirect, simulated provider window, SDK, or external payment link exists.
- A 15-second request timeout or any uncertain mutation response pauses further mutations until bootstrap retrieves the authoritative state. No automatic POST replay. Only random per-review create/capture UUIDs persist in `sessionStorage`; CSRF/owner credentials and source text do not. Repeated action keys survive tab reload. Server durable operation uniqueness remains the actual duplicate-operation guard.
- After any order exists, inputs stay locked. Pending/unknown offers only the same-order reconciliation path; completed has no new-order shortcut. A stale pre-order review is discarded locally while preserving typed inputs for explicit fresh analysis. A stale **existing order** is retained as a labelled previous reviewed version: no edit, confirm, create, verify, or capture; unresolved operations may still be reconciled. This v1 has no cancellation/new-checkout flow.
- An invalid model proposal can have no confirmable fingerprint. It renders “analysis blocked,” never a successful fallback; pre-order reanalysis is still available.

## D05 — Historical local verification, not this import-head evidence

The following records pre-issue local source work. It is retained as provenance,
not a current pass or review. Fresh exact-artifact checks, counts and separate
review for issue #5 belong in the draft PR and import ledger. No old receipt
certifies this revision.

Run `python cart_readback/ui/check.py` from the project root (or any directory with the full path). No installation, paid call, external service, or browser automation is used by the checks.

- Node syntax checks for actual app and pure client module.
- Static markup checks: unique IDs, existing explicit label targets, no inline event handlers, only local script/style resources; no HTML interpolation/eval in app/core source.
- 20 pure core tests: money types/currency, fixture flags, six unique SKUs, typed key layouts, Unicode/forged spans, same-source/version/amount checks, result coverage, independent unknown/conflict acknowledgements, immutable statuses, stale/order lock, merged ranges, persistent operation keys, null blocked-analysis fingerprint, and stale-order read-only validation.
- 1 minimal fake-DOM application test: six rows/no inferred selections, non-AI source access before analysis, stale consent invalidation, blocked-analysis and stale-preorder recovery, explicit order flow, repeated-click guard, reload restoration, stale-postorder same-order reconciliation, and transport-error pause. This executes the real `app.mjs` but **is not a browser, renderer, or accessibility tree**.
- 3 real local HTTP/client-contract tests against an ephemeral temporary SQLite-backed fixture server: actual UI/MIME/CSP; full explicit fixture workflow and restored same order; unknown/conflict acknowledgement. This is not a rendered browser E2E test or real PayPal/model integration.
- Python check-script compilation passed. The first Ruff attempt found no executable on PATH. Ryan subsequently supplied the project-pinned, already-installed `/tmp/cartreadback-lint-0.14.3/bin/ruff` (0.14.3). Its import-order/format finding in the owned `ui/check.py` was corrected; Ruff check and format-check then passed, followed by a fresh complete 24-check UI aggregate. No dependencies were installed by this UI task.
- Browser inspection remains blocked: prior HTTP loopback browser attempts in the parent workspace were connection-refused. A direct CUA `file://` attempt for this screen was rejected by the browser URL security policy (only http/https allowed). That path was stopped without a workaround. No screenshots, visual rating, native keyboard pass, mobile pass, or WCAG certification is claimed.

## D06 — Handoff acceptance / not done

Contract: `../API_CONTRACT.md` C01–C08, including codepoint spans, per-condition exact acknowledgement sets, server revision, UUID operation keys, stale source and existing-order freeze. The pre-existing implementation was local-only before this import. Issue #5 and its numbered branch cover the import and subsequent review changes, not retroactive review of original work. The dependent draft PR targets server branch `feat/3-fixture-server`, exact base `d2781cf7f603d83b552c9cd84371544357589bdd` (draft PR #4), not merged main. Actual head and review evidence are verified separately. No deployment, model inference, PayPal sandbox call, credential access or payment is established.

Before any externally usable build: inspect actual desktop/320px rendering, keyboard-only order, screen-reader labels/errors/source links, text zoom and long content; independently rerun final revision; then separately authorize/configure genuine model and sandbox adapters. A model/sandbox flag is not implemented functionality. Do not remove fixture labels merely to make a demonstration look complete.
