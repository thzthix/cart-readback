# CartReadback project brief

## Buyer outcome
Help a buyer check the keyboard SKU they already selected against one or two
requirements they already have, before checkout: language layout and an included
cable. First scope: one merchant, six synthetic keyboard SKUs, one item/order,
integer USD cents. This is not a shopping/recommendation chatbot, arbitrary-shop
connector, price search, compatibility guarantee or inference from product photos.

An ISO physical shape does not establish UK QWERTY or German QWERTZ. A cable being
pictured, compatible, optional or supported does not establish that it is included.
Missing/contradictory facts remain unknown; acknowledgement does not create facts.

## Baseline and strongest objection
A good structured option-and-included-items table may solve the same problem more
simply. Use exactly the same source material for that table and the readback.
Include preparation, requirement entry, reading, correction and completion effort
when comparing them. Extra buyer input and AI prose may make the flow worse.
Customer demand, merchant willingness and net AI benefit are hypotheses, not
findings. Do not fabricate studies, testimonials or time-saving claims.

## Intended flow and authority
1. Select one SKU and at most two explicit typed requirements.
2. Propose match/conflict/unknown with exact source quotations, treating source
   text as untrusted data rather than instructions. Do not infer missing facts.
3. Deterministic code validates source/SKU/revision/condition identity, schema and
   codepoint spans. Structural validity does not establish semantic correctness.
4. The buyer explicitly confirms the reviewed snapshot and separately acknowledges
   every conflict or unknown. Changing source, price, requirements or model/prompt
   identity invalidates old consent; acknowledgement preserves uncertainty.
5. Server-owned facts drive order creation, separate simulated approval, requery
   verification and explicit final capture. Browser GET/return never captures;
   neither browser money nor model suggestions authorize a transaction.
6. Persist operation identities. Timeout/restart ambiguity stays PAYMENT_UNKNOWN;
   query the same known order without retrying a new payment or hiding history.
   After creation, v1 has no cancel/restart/new-order escape flow.

The normative wire boundary is [API v1](cart_readback/API_CONTRACT.md). The design
is a small Python/SQLite modular monolith with a same-origin vanilla UI, not a
runtime debate team. Amount/quantity/currency/owner checks remain outside a model.

## Current stage and evidence
This tree combines the issue-first imports of pre-existing local fixture server,
buyer UI and offline evaluation artifacts. It uses synthetic catalog data, a
deterministic proposal test double and fake payment provider, not genuine AI
inference or PayPal calls. Component reviews do not certify later changes; run
fresh exact-revision integration checks and preserve original provenance.

An app-external uncontrolled native-agent pilot later used a synthetic evaluation
set. The exposed set is regression material, not fresh hidden holdout. No prompt
performance winner, complete human validation or app integration is established.
Actual application model integration/fresh semantic evaluation, PayPal sandbox
lifecycle/recovery, rendered browser/native-keyboard flows and real buyer value
remain unverified. If the table is easier or AI makes unsupported confident claims,
narrow or stop the AI path rather than weaken the baseline.

## Repository and release boundaries
The private repository exists at thzthix/cart-readback. This issue-first scaffold
import is not retroactive GitHub review of earlier local work. Keep original
import provenance and disclose material AI assistance in PR descriptions without
AI-authorship or coauthor commit trailers. AI names label responsibilities, not
separate humans/accounts.

The user authorized private repository code/issue/branch/PR work and separately
authorized merging the current reviewed project PRs. Formal approval, auto-merge,
public visibility, open-source licensing, account or credential access, costs,
legal acceptance, live payments, deployment and contest submission retain their
separate gates. Never use fixture success as evidence of
real integration or publish a working-integration claim from simulated footage.
