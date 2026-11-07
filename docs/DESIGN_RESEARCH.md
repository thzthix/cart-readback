# Design research and implementation map

Issue #56. Audited against main `dd988f01ad7704f5ac4467ad9d625ca8b002baa8`
on 2026-11-07 UTC. This is a fresh source check and a bounded correction, not
retroactive proof that earlier work was complete or user-tested.

## What existed and what was missing

`cart_readback/ui/DESIGN.md` already linked getdesign.md, defined the paper/ink/
forest tokens and mapped several research sources to the buyer UI. README already
linked that contract. `index.html`, `styles.css` and `app.mjs` implemented a table,
original descriptions, evidence columns and explicit transaction states.

The non-generic-design research was cited only as unimported local archival
notes. There was no root DESIGN.md entry point. More importantly, the separate
Gemini `/viewer` page had no stylesheet or visual connection to that system.
Its read-only/privacy boundary was implemented, but its visual design was not.
Issue #56 adds this source trail, the root entry point and the viewer treatment.
The ordinary checkout UI and all provider/payment gates stay unchanged.

## Sources, decisions and limits

All links below were read through the available web research tool in this audit.
These are short source-informed design decisions, not copied components or claims
of measured improvement in CartReadback.

| Source and evidence kind | Decision | Where to inspect |
| --- | --- | --- |
| [getdesign.md](https://getdesign.md/) and its [maintainer repository](https://github.com/VoltAgent/awesome-design-md), a third-party collection | Keep colors, typography, layout, components and rationale in an explicit reusable contract. No commercial kit, installer, brand assets or catalog file was imported. | Root `DESIGN.md`; `ui/DESIGN.md` D02–D04; paper/ink/forest tokens in both surfaces. |
| [NN/G AI prototyping evaluation](https://www.nngroup.com/articles/ai-prototyping/), the authors' heuristic evaluation of a real redesign task | Specify task, domain, hierarchy and interrupted states instead of asking for a vague “premium AI app.” Their evaluation is not a benchmark of this app or current model quality. | Typed SKU/layout/cable conditions, same-source baseline, retained blocked/UNKNOWN states and review tests. |
| [NN/G UX-context design](https://www.nngroup.com/articles/ux-context-design/), practitioner guidance | Curate product-specific knowledge and constraints alongside visual tokens. No invented interviews or persona validation. | Project brief, root design entry point and this implementation map. |
| [GOV.UK check answers](https://design-system.service.gov.uk/patterns/check-answers/), first-party design-system guidance | Let people inspect actual values before a consequential action. The separate viewer stays inspection-only; it must not acquire confirm/pay controls. | Buyer snapshot in `app.mjs`; original selection/source and retained results in `viewer.mjs`. |
| [Baymard included-accessory research](https://baymard.com/research-articles/included-accessories-image), the authors' product-page study | Surface included cable information and distinguish unstated from excluded. Pictures and compatibility do not establish inclusion. This also supports the non-AI table alternative. | Baseline table and original description; viewer baseline; `unknown` labels. No source statistic is claimed as our result. |
| [W3C reflow explanation](https://www.w3.org/WAI/WCAG22/Understanding/reflow.html), informative explanation of a standard | Fit prose and controls at 320 CSS px. A genuine comparison table may scroll within a labelled region; ordinary text must wrap. | Buyer `.table-wrap`; both surfaces' narrow media rules; viewer `minmax(0,1fr)` columns and `overflow-wrap:anywhere`. This is not a conformance pass. |
| [W3C minimum target explanation](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html), informative explanation | Existing buyer controls use generous 44–46px labels/buttons. The AA minimum is generally 24px with exceptions, not 44px. No fake controls are added to the viewer. | Buyer `.check-label`, `.product-label`, buttons; viewer no action controls. |
| [Slopless](https://slopless.design/) and [Design Slop](https://github.com/wpgaurav/design-slop), first-person practitioner critiques, not controlled research | Remove interchangeable decoration, nested card soup, unsupported proof and screenshot-only happy paths. Judge task fit, clear states and accessibility, not whether a font “looks AI.” | Continuous review sheet, real product/source text, thin rules, word-labelled outcomes and recovery tests. No skill/installer was executed. |

getdesign.md's brand pages explicitly describe independent analyses, not brand
endorsement. The collection references Google's Stitch format; Google's linked
page returned no readable content in this audit, so this record does not claim an
independent verification of that specification or official Google certification.
No brand-clone styling is the target.

## Concrete viewer changes

- Same warm paper `#f8f7f2`, ink `#242a27`, forest `#274d3a`, Georgia task/source
  type and system body as the existing buyer contract.
- The original selected item and same-source baseline precede neighboring original
  words and retained results. At 800px and below they become one column.
- Match/conflict/unknown keep explicit words plus distinct restrained color.
  Long source identifiers and quotes wrap. Source newlines remain visible.
- Configured model/dispatch, fabricated/provider accounting, stale history,
  UNKNOWN, possible inference charges and PayPal disconnection remain explicit.
- No action, remote asset, web font, image, animation, storage or third-party
  dependency was added. The existing first script stays byte-for-byte unchanged.
  One inline style is authorized by its exact CSP SHA-256, without unsafe-inline
  or style-src self. No CSS request can precede launch-fragment removal.

## Verification and remaining objection

The snapshot's 142 files were checked against GitHub Git-blob SHA identities
before edits. Focused checks and independent review are recorded against the final
PR head, not inferred from the prior import receipts. Text/HTTP/fake-DOM tests do
not establish rendering, native focus, screen-reader behavior or usability.

Actual rendering was attempted, not passed. Installed Chromium exited during
startup with `socket() failed: Operation not permitted`, including after the
approved environment escalation. The supported cloud browser could not reach the
loopback fixture server (`net::ERR_CONNECTION_REFUSED`). No screenshot was produced
and no file-URL, public hosting, tunnel or security-setting workaround was used.
Thus wide/320px rendering, keyboard-only flow, zoom, screen readers and human
preference remain unverified. The strongest remaining objection is the missing
rendered check of the new viewer, followed by whether this adds buyer value over
the good table. No aesthetic score or “AI smell removed” success is asserted.

To continue: use the documented authorized local fixture workflow on a computer
whose browser can reach its own loopback service, then inspect 1440px/320px,
long text, source/history navigation and keyboard focus. The Gemini private viewer
must retain its existing authorized host opener and one-call lifetime; design QA
does not authorize a real model call or access to a launch capability.
