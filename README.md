# AI Merchant Growth Agent

Razorpay AI Buildathon, Track 01. Full context and the phase-by-phase
build plan are in AI_Merchant_Growth_Agent_Build_Plan.md.

## Status: Phase 2 done. Next up: Phase 3 (agent layer).

## Repo layout

- docs/objective_function.md: the formula the decision engine optimizes,
  including margin-proxy, abandonment-risk, and upsell-heuristic
  placeholders, and the logistic-vs-gradient-boosting model comparison,
  all flagged explicitly.
- docs/audit_schema.md: the field contract for every logged transaction.
- docs/data_dictionary.md: fields and stats for all three datasets.
- mcp/: Razorpay MCP Server setup. See mcp/README.md.
- scripts/: Phase 0 setup scripts (Razorpay connectivity check, MCP auth
  header helper).
- data_prep/: dataset download and preprocessing (UCI direct download,
  Kaggle download for dunnhumby and Olist). All three are done.
- src/decision_engine/: the Phase 2 pipeline, run in this order:
  affinity_rules.py, upsell_tiers.py, household_features.py,
  household_brand_stats.py, upsell_training_data.py,
  representative_products.py, then the two training scripts
  (train_acceptance_model.py, train_upsell_model.py — each supports
  --model logistic / gbm / compare, see below), then engine.py
  (importable, decide(household_key, basket_product_ids)) and
  validate.py (offline sanity check).
- src/catalogue/, src/cart/, src/payments/, src/audit/, src/experiment/,
  src/dashboard/: placeholders for later phases.
- models/: trained artifacts from src/decision_engine (gitignored,
  regenerate by rerunning the scripts above).
- data/raw/, data/processed/: all three datasets downloaded and cleaned.

## Setup

1. pip install -r requirements.txt
2. cp .env.example .env and fill in Razorpay Test Mode keys and Kaggle
   API credentials.
3. python scripts/test_razorpay_connection.py to confirm Razorpay.
4. bash data_prep/download_kaggle.sh, then run the three
   data_prep/preprocess_*.py scripts.
5. Run the src/decision_engine scripts in the order listed above,
   ending with the two training commands below.

## Data status

- UCI Online Retail II: done. 805,549 clean rows.
- dunnhumby Complete Journey: done. 2,595,732 rows, 2,500 households,
  276,484 baskets, 92,339 products.
- Olist Brazilian E-Commerce: done. 112,650 rows, 98,666 orders.

## Decision engine status (Phase 2)

- 2,018 cross-sell affinity rules mined at the commodity level (lift >=
  1.5). Top rules are intuitive: pasta/pasta sauce, cheese/deli meats,
  peppers/onions.
- Upsell price tiers rebuilt to be manufacturer-aware: for each of the
  85,028 products with an upsell target, the closest pricier product in
  the same sub_commodity is picked from the same manufacturer first
  (71.4% of targets), falling back to any manufacturer only if no
  in-band same-manufacturer option exists. The original version ignored
  manufacturer entirely; dunnhumby's brand field turned out to be only
  a binary National/Private flag, not a specific brand name, so it
  could never have supported real brand matching (verified before
  building the fix).
- Upsell training features expanded: trade_up_rate_other,
  national_brand_rate_other (household's leave-out top-tier / National
  brand rate), and same_manufacturer_as_usual (leave-one-out, was this
  purchase's manufacturer the household's dominant one in that
  sub_commodity), added to the existing household features. See
  docs/objective_function.md for the full rationale and the leave-out
  construction.
- Both the cross-sell acceptance model and the upsell propensity model
  now support logistic regression or gradient boosting
  (HistGradientBoostingClassifier), trained on an identical
  preprocessing pipeline for a fair comparison. Logistic regression was
  the original choice for interpretability but was never actually
  tested against a heavier model until now.
- Model comparison done (300k-row sample, run by the user, 2026-08-29):
  upsell propensity, logistic 0.6016 AUC vs gradient boosting 0.6801 AUC
  (+7.85 points, a real interaction effect a linear model can't
  represent, gbm kept); cross-sell acceptance, logistic 0.6525 AUC vs
  gradient boosting 0.6664 AUC (+1.4 points, small enough that logistic
  stays for its clean coefficients). Save both:

      python src/decision_engine/train_upsell_model.py --model gbm --save
      python src/decision_engine/train_acceptance_model.py --model logistic --save

  Full numbers and reasoning in docs/objective_function.md.
- Per-decision explainability (SHAP) added to engine.py for both
  models, verified empirically to be sub-5ms per decision regardless of
  model type (shap.Explainer auto-dispatches to TreeExplainer or
  LinearExplainer). Every candidate now carries a feature_attribution
  list (top contributing features, aggregated back from one-hot dummies
  to real feature names) alongside its reason text, ready for the
  Phase 6 audit trail. Adds roughly 130ms per basket decision on top of
  candidate scoring, worth watching if this ever sits in a low-latency
  path, not a concern for offline validation or the demo.
- expected_downside tuned from 0.10 to 0.20 by sweeping against the real
  distribution of candidates' raw expected margin on a 500-basket
  sample (median $0.26, 25th percentile $0.16). See
  src/decision_engine/tune_downside.py and docs/objective_function.md.
- Offline validation (src/decision_engine/validate.py), final numbers
  on the real trained models (gbm upsell, logistic acceptance), 500
  held-out baskets: 39.2% cross_sell, 30.6% upsell, 30.2% no_action.
  no_action is a real, substantial fraction of outcomes, not a
  theoretical option.
- Reason text now spells out the margin proxy's dollar contribution
  explicitly (objective.py's new explain() function), matching the
  build plan's own Phase 2 exit line word for word: "which rule fired,
  what the acceptance probability was, what the margin proxy
  contributed."
- One assumption caught and corrected by verification: same_manufacturer_as_usual
  was expected to predict a HIGHER trade-up rate (brand comfort). The
  real data says the opposite (47.7% vs 40.0% top-tier rate, non-loyal
  vs loyal) — manufacturer consistency mostly captures habitual
  repeat-buying, not brand affinity that extends upward. Feature kept
  (it's a real, useful signal), narrative in docs/objective_function.md
  corrected to match what the data actually shows.
- Phase 2 exit criterion (from the build plan): "given any basket, the
  engine returns a ranked decision with an attached expected-value
  score and the specific reason behind it" — verified true on 500 real
  baskets. Phase 2 is done.

## Phase 3 (agent layer and agent-readable catalogue): DONE

Verified directly against the build plan's own exit line: "a scripted
natural-language request produces a correct catalogue match, a growth
decision from the engine (with at least one rehearsed run that
resolves to no action, to prove the policy isn't just an always-upsell
reflex), and an updated cart, all without any money changing hands
yet."

Architecture: LangGraph (StateGraph orchestration, create_react_agent
for each agent's own tool-use loop) against the raw Anthropic API via
langchain-anthropic, not the Claude Agent SDK. Model id
`claude-sonnet-5`, verified against the docs before hardcoding it,
configurable via ANTHROPIC_MODEL.

- src/catalogue/catalogue.py: the catalogue's data layer. Filters out
  637 non-product rows (unclassified NO COMMODITY/SUBCOMMODITY rows,
  FUEL, coupon-bookkeeping pseudo-categories, bottle deposits) verified
  against the real category list first. 91,357 real products remain.
  search(query) does token-overlap matching against category/
  subcommodity TEXT only, which cannot resolve a bare product_id (see
  the bug in run 2 below).
- src/catalogue/catalogue_api.py: the one thin agent-readable
  catalogue endpoint the plan asks for, plain FastAPI, two routes
  (/catalogue/search, /catalogue/product/{id}), tested via TestClient.
- src/agents/tools.py: query_catalogue, get_product, and
  get_growth_decision as LangChain tools. get_growth_decision wraps
  engine.decide() with zero duplicated logic; get_product wraps
  catalogue.build_entry() directly, added after run 2's bug.
- src/agents/buyer_agent.py: one tool only (query_catalogue), per the
  plan's spec. Plain-text prompt (no markdown, no emoji, no
  exclamation points) after run 1 showed sales-pitch tone leaking in.
- src/agents/merchant_agent.py: three tools (query_catalogue,
  get_product, get_growth_decision). Told never to invent a product,
  price, or offer, to state no_action plainly, and to call get_product
  first for any buyer-stated product_id, since query_catalogue only
  matches text and can't confirm a bare id. Also plain-text, no
  markdown, no emoji, no sales tone, since the reply is a logged
  record for the dashboard, not a chat message.
- src/agents/demo_graph.py: the top-level LangGraph StateGraph,
  buyer -> merchant -> resolve. resolve_node is a seeded random draw
  against p_accept to produce a cart-before/cart-after diff and an
  accept/decline outcome, explicitly a Phase 3 placeholder only, not
  Phase 5's real experiment engine. Handles no_action and a missing
  decision without crashing. Takes --household-key/--intent/--seed.

**Live runs, all verified against real data (5 total, real API calls,
user's own key):**

1. household_key=1, "spaghetti for dinner tonight": worked end to
   end, cross_sell to Beef accepted, but the merchant reply had
   emoji, markdown bold, and sales-pitch language (fixed by tightening
   both prompts).
2. Same scenario rerun: a real bug surfaced. The merchant agent said
   product_id 5995213 "does not exist in our catalogue," which is
   false, confirmed directly against catalogue.build_entry(5995213).
   Root cause: query_catalogue only matches category/subcommodity
   TEXT, never a numeric product_id, and a text search for "spaghetti"
   doesn't surface 5995213 because its real category is Hispanic/
   authentic pasta. The merchant agent had no tool that could confirm
   a bare product_id the buyer already named, and correctly refused to
   guess rather than fabricate a match. Fixed with the get_product
   tool and the prompt sequencing above.
3. household_key=500, "I need toothpaste": fully accurate. Toothpaste
   (7085339, $0.69) confirmed, cross_sell to fluid milk (995242)
   offered at 47% co-purchase rate, 1.9 lift, 40% p_accept, $0.028
   expected value, all checked against real data. Offer accepted.
4. household_key=1200, "I want orange juice": fully accurate. Orange
   juice (1905462, $0.89) confirmed, cross_sell to Cold Cereal
   (1054262) offered at 29% co-purchase rate, 3.2x lift, 31% p_accept,
   $0.009 expected value, all checked against real data. Offer
   declined.
5. household_key=1, "I need cigarettes": the genuine no_action run
   the exit line asks for. Cigarettes (1015476, $2.00) confirmed, an
   upsell to 1091997 ($2.36) was evaluated and rejected because its
   expected value came out negative (-$0.14), so no offer was made.
   Reran engine.decide(1, [1015476]) directly and confirmed the exact
   same expected value (-0.1424..., rounds to -$0.14) and both product
   ids/prices, matching the merchant's reply precisely. This is an
   engine-level no_action, the upsell was evaluated and rejected on
   its own merits, not a tool failure, which is exactly what the exit
   line is checking for.

All three exit-line conditions hold (catalogue match, growth decision
including a verified no_action, updated cart) with no money changing
hands anywhere in this phase. Guardrail respected: no OAuth
delegated-auth flows, no cryptographic mandates, no .well-known
discovery stack, no full ACP/UCP conformance attempt, one JSON
endpoint only.

Left open, not blocking, revisit around Phase 7/8: whether the Buyer
Agent's intent per demo run should be scripted/fixed for the pitch
rehearsal or left open-ended.

## Phase 4 (Razorpay Test Mode integration): DONE

Architecture, matching the plan's own emphasis that Razorpay calls go
through its MCP server's tools rather than hand-rolled REST calls: split
between what an LLM agent decides and what deterministic Python decides,
same reasoning as resolve_node's accept/decline draw not being an LLM
call. The Checkout Agent (LLM, one tool, mirrors the Buyer Agent's
single-tool shape) creates the Razorpay order once the cart is
finalized, since the plan specifically wants that call to visibly come
from the agent. Verifying the signature, confirming/capturing the
payment, and handling the webhook are deterministic code, not agent
decisions, since those are correctness and security critical.

Verified live before any of this was written: connected to Razorpay's
hosted MCP server (https://mcp.razorpay.com/mcp, streamable HTTP, HTTP
Basic auth from your real Test Mode keys) and created a real order
(order_TViNm65ZU16X3E) to confirm auth, transport, and response shape,
rather than assuming from the docs. Confirmed Standard Checkout itself
requires a browser (checkout.js), not something any backend script can
finish alone, against two separate Razorpay doc pages. Confirmed
Razorpay's own minimum order amount is 100 paise (from the live
create_order tool schema, not just the docs).

Files:
- src/payments/razorpay_mcp.py: connects to the hosted MCP server,
  unwraps its content-block responses into JSON. Found and fixed a real
  bug here while testing: an MCP tool error (e.g. fetch_payment on a
  nonexistent id) comes back as a plain error string, not JSON, which
  crashed the naive version with a JSONDecodeError. Now raises a typed
  RazorpayMCPError instead, caught everywhere Razorpay calls happen so a
  bad id or a transient failure fails gracefully rather than crashing.
- src/payments/checkout.py: prices a finalized cart from the real
  catalogue (never from anything the agent says), converts to paise,
  applies Razorpay's 100-paise floor and a 50,000-paise (INR 500) spend
  cap. Verified against real product prices, including baskets small
  enough to need the floor.
- src/payments/audit.py: append-only JSON-lines log at
  data/audit_log.jsonl, fields matching docs/audit_schema.md's payment
  section. Every order creation, checkout verification, and webhook
  event gets a record.
- src/agents/tools.py: added create_checkout_order (async, since it's
  the first tool that calls out over the network rather than running
  in-process; verified directly that an MCP-backed tool with no sync
  entry point raises NotImplementedError on .invoke()). Never lets the
  agent name a price, same principle as get_product never letting it
  invent one.
- src/agents/checkout_agent.py: the Checkout Agent, one tool
  (create_checkout_order), given the household_key and the exact
  finalized basket_product_ids, replies with the order confirmation and
  checkout link.
- src/payments/checkout_api.py: a small FastAPI app serving the actual
  checkout.js page for one order, plus /checkout/verify (signature
  check via the razorpay SDK's own HMAC-SHA256 utility, then
  fetch_payment/capture_payment through the MCP tools, deterministic,
  not agent-driven), /checkout/failed (the deliberate-decline path),
  and /webhooks/razorpay (payment.captured, verifies
  x-razorpay-signature). Tested with real signed payloads I generated
  myself, both correct and tampered, and with a synthetic
  payment.captured webhook body, all handled correctly including the
  graceful-failure path for a nonexistent payment id.
- src/agents/demo_graph.py: added a checkout node after resolve
  (runs regardless of whether the offer was accepted, declined, or
  no_action, since the base product always needs paying for). The graph
  now runs via ainvoke instead of invoke, since checkout_node's tool has
  no sync path.

What I verified myself, since none of it costs your API credits or
needs a browser: the MCP connection and every tool schema against the
live server, checkout.basket_amount_paise's math against real prices,
the full create_checkout_order tool end to end (created two more real,
harmless Test Mode orders in your dashboard under receipts starting
"claude_verify_" and "demo-1-", both status "created", never paid),
and every checkout_api.py route via FastAPI's TestClient with
synthetic but correctly-signed payloads.

What still needs you, and why: completing an actual Standard Checkout
requires a browser, confirmed against Razorpay's own docs, no backend
code can substitute for it. To close this phase per the plan's own exit
line ("one successful and one deliberately failed Test Mode payment,
both fully traceable back to the specific agent decision that triggered
them"), run the demo twice and complete checkout in the browser each
time. Setup:

    # terminal 1, from the repo root
    uvicorn src.payments.checkout_api:app --port 8001 --app-dir .

    # terminal 2, from the repo root
    python src/agents/demo_graph.py --household-key 1 --intent "I need cigarettes"

The script prints a checkout_url. Open it, pay with UPI ID
success@razorpay for the successful rehearsal, then run the command
again and use failure@razorpay for the deliberately failed one. Report
back what the page shows and what data/audit_log.jsonl contains
afterward, same as every other live run so far, that's what I can't
verify without you running it.

Real run against your account (household_key=1, cigarettes, order
order_TVidaR2Vb8itTd, 200 paise): a card payment failed with Razorpay's
own real decline ("International cards are not supported"), logged
correctly with no corrupted state, then a second attempt on the same
order captured successfully. Both are genuine, both are traceable to
this order/decision, so Phase 4's exit line (one successful, one
failed, both traceable, both handled gracefully) is substantively met,
even though the failure wasn't the deliberate failure@razorpay path.
Why: UPI never appeared as a payment method in checkout. Verified
against Razorpay's own docs (config-payment-methods page), UPI's
visibility is controlled by what's enabled for the account in the
Dashboard, not by anything checkout.js can force, and that enable/
disable toggle only lives in Live Mode, not Test Mode. Likely an
account-activation-level gap, not a code issue. Card-based testing
sidesteps it entirely and is arguably a cleaner deliberate-failure
mechanism anyway: Razorpay's own domestic test card (4111 1111 1111
1111, any future expiry, any CVV) leads to a confirmation screen with
explicit Success/Failure buttons. checkout_api.py's page now shows
both options.

Open, not blocking: the webhook listener is built and unit-tested with
a synthetic signed payload, but Razorpay can't actually reach it
without a public URL. Making it fire for real needs a tunnel (ngrok or
similar) pointed at port 8001, that tunnel's URL registered as a
webhook in the Razorpay Dashboard, and the webhook secret it gives you
set as RAZORPAY_WEBHOOK_SECRET in .env. Not done yet since it's a real
account/infrastructure decision, not mine to make unasked.

### Setting up the webhook (zrok)

Razorpay blocks ngrok's free-tier domains for webhook registration; zrok
works. Steps:

    # terminal 3, after the checkout_api server (terminal 1) is running
    zrok share public localhost:8001

Copy the https URL zrok prints. In the Razorpay Dashboard: Settings ->
Webhooks -> Add New Webhook, URL = `<that zrok url>/webhooks/razorpay`,
event = `payment.captured`. Razorpay shows you a webhook secret when you
save it, put that in `.env` as `RAZORPAY_WEBHOOK_SECRET` (replacing the
empty placeholder).

zrok's public share URL is ephemeral by default, it changes if you stop
and restart `zrok share`, so the Dashboard's webhook URL needs updating
if that happens. Leave the zrok terminal running for the length of a
demo session rather than restarting it between runs.

To confirm it's actually working: run a demo end to end, complete a
successful payment in the browser, then check data/audit_log.jsonl for
a `webhook_payment_captured` event (a second, independent confirmation
of the same payment, arriving from Razorpay's servers rather than the
browser callback).

### Two more real bugs found from live runs

- **Duplicate failure logging**: two separate runs both logged the same
  failed payment_id twice, a few seconds apart, identical reason each
  time. Razorpay's checkout.js appears to fire `payment.failed` more
  than once for a single failed attempt. Fixed with a dedup guard in
  `audit.log_payment_event`: it now checks the immediately preceding
  log line and skips writing a near-identical one (same event,
  payment_id, status, failure_reason) within 30 seconds.
- **A rejected webhook logged nothing**: both failure branches in
  `/webhooks/razorpay` (missing secret, bad signature) used to return
  an HTTP error without writing an audit record, so a misconfigured
  webhook was invisible in `data/audit_log.jsonl`. Fixed: both branches
  now log a `webhook_rejected` event with the reason before responding.
  Most likely explanation for a webhook that doesn't show up at all:
  `RAZORPAY_WEBHOOK_SECRET` is read from `.env` once, at process
  startup. If you added it to `.env` after already starting
  `uvicorn src.payments.checkout_api:app`, that process is still
  running with the old empty value. Restart it after any `.env`
  change. Razorpay's own Dashboard (Settings -> Webhooks -> click the
  webhook -> Delivery attempts) is the authoritative place to check
  whether it even tried to reach your URL and what response it got.

### Third bug: webhook path mismatch (found from real zrok delivery logs)

The uvicorn access log showed every incoming webhook POST hitting
`/webhook/razorpay` (singular) while the route was defined as
`/webhooks/razorpay` (plural), a plain 404 on every attempt, invisible
in the audit log because the request never reached the handler at all.
zrok and Razorpay's delivery were both working correctly; only the
final path segment was wrong (whatever was typed into the Dashboard's
webhook URL). Fixed by registering both spellings on the same handler,
so a Dashboard URL using either one now works. Verified against a real
signed synthetic payload on both paths, and confirmed the dedup guard
(see above) correctly treats a repeat delivery of the same event as one
log entry, not two.

Webhook confirmed working live: after the path-mismatch fix, a real
successful payment produced a `webhook_payment_captured` entry in
`data/audit_log.jsonl`, independently confirming the payment via
Razorpay's own server-to-server delivery rather than only the browser
callback. Phase 4 is closed.

## Phase 5 (Control vs Agent experiment): DONE

Full results, methodology, and every number: `docs/phase5_results.md`.
Summary here.

A data-grounded simulator (`src/experiment/`) replays real dunnhumby
households and real dunnhumby baskets through two policies: Control
(base basket, no intervention) and Agent (the real Phase 2 decision
engine, no-action included as a candidate on equal footing with every
offer). No LLM-simulated shopper anywhere in this phase, no synthetic
basket, no fabricated price — every household, basket, and product
price is a real observed value.

Confirmatory result, n=9,399 real baskets per arm (sample size set by a
Monte Carlo power simulation on real pilot data, not an arbitrary round
number — see the results doc for how an initial n=1,500 draw came back
non-significant by chance and was reported rather than discarded):

- Mann-Whitney U (agent order value > control order value): p=9.37e-6.
- Incremental revenue/session: +$1.62 (+6.12%), 95% bootstrap CI
  [$0.58, $2.67].
- Attach rate 25.2%. Uplift/Qini analysis: the engine's own targeting
  beats random targeting at the same rate by 29.5%, answering the
  plan's question of whether the targeting itself is doing work.

A real bug was found and fixed along the way: `engine.py`'s SHAP
explainer could crash on certain real households
(`shap.utils._exceptions.ExplainerError: Additivity check failed`), a
known SHAP + HistGradientBoostingClassifier quirk affecting the
already-"done" Phase 2/3/4 code path (`get_growth_decision`'s default
`explain_drivers=True`). Fixed with SHAP's own suggested
`check_additivity=False` fallback, verified against 201 real baskets
(the original 200 plus the found failure): zero crashes, and
`explain_drivers=False` (the fast path added this phase for bulk
simulation) produces identical decisions to `explain_drivers=True`,
just without the explanation — 87ms vs 170ms per decision.

Evidence tiers (repeated from the results doc because it matters):
this offline replay is tier (a), empirically validated; the one live
Razorpay transaction from Phase 4 is tier (b), demonstrated; a real
merchant A/B test remains tier (c), future validation, not claimed to
exist.

## Phase 6 (Audit trail, bounding, gating): DONE

Full schema: `docs/audit_schema.md`. Summary here.

**Explainable, end to end:** every node in the demo graph now logs its
part of the audit trail (`src/audit/audit_log.py`) — intent, decision
(with the engine's own plain-English reason, never hand-written), the
explicit accept/decline gate, and the cart diff — all keyed by one
`request_id` per run. Payment events (Phase 4) are bridged in via a
`checkout_order_linked` event written the instant a real order exists.
`src/audit/trace.py <request_id>` reconstructs any transaction start to
finish from `data/audit_log.jsonl` alone — verified structurally on real
households/baskets across a genuine no_action, an accepted upsell, a
signature-verification failure, and an abandoned checkout (the browser's
modal-dismissed case, which Phase 4 never actually logged — fixed here
with a new `/checkout/abandoned` endpoint).

**Bounded, as two enforced rules, not a slogan:**
1. Spend cap (Phase 4, unchanged) — re-confirmed still enforced at both
   order creation and capture time.
2. Catalogue-declared SKUs only (`src/decision_engine/bounding.py`, new).
   Checked against 1,000 real baskets before writing this: 31% of the
   engine's own real chosen offers referenced a product outside the
   catalogue's declared complements/alternatives for that basket (the
   engine ranks up to 15 cross-sell candidates to find the best one;
   the catalogue only declares the top 3 by lift). Now enforced inside
   `get_growth_decision` itself — an out-of-bounds winner is replaced
   with `no_action` and the rejection is recorded, never silently
   dropped. Re-verified on the same 1,000 baskets: zero violations
   remain.

**Gated:** `resolve_node` is the explicit accept step — `checkout_node`
is structurally unreachable before it in the graph's linear edges, and
it now logs a `gate` event on every path before returning, so nothing
charges silently and it's independently auditable, not just true by
accident of wiring order.

One honest caveat carried over into `docs/audit_schema.md`: Phase 5's
replay calls `engine.decide()` directly (for speed at thousands of
sessions) and isn't subject to the new catalogue bound, so a live
deployment's realized uplift would be somewhat below Phase 5's reported
number once bounding vetoes the ~31% of top-ranked offers that fall
outside the catalogue's declared surface. Not re-run here — out of
scope for what Phase 6 itself asks for, flagged for whoever picks up
Phase 7/8 or a future bounded re-run.

## Phase 7 (Dashboard and demo assembly): DONE (build), rehearsal pending

Two views, one dashboard, reading live off `data/audit_log.jsonl` and
`data/experiment/*.parquet` on every request — nothing on this page is
hand-curated. Run it with:

```
uvicorn src.dashboard.dashboard_api:app --port 8002 --app-dir .
```

then open `http://localhost:8002`.

Visual language: a sidebar-nav layout (Views, Filters, a live Results
list, Quick Links, an Evidence Tiers box, all in a left sidebar) in
Inter with a light, minimalist palette — built to a second reference
screenshot the user supplied partway through this phase, which
superseded an earlier minimalist "Workspace" reference used for the
first pass. The user asked for that layout specifically "with the font
inter, and minimalistic light colors" (not the dark-navy the reference
itself used), so the structure follows the reference and the palette
follows the instruction.

**Transactions view** centers the agent's decision, not a flat
before/after listing: a numbered 1 → 2 → 3 flow — Original Basket
(Observed) → Agent Decision (the real catalogue-priced product, the
model's own reason text headlined then expandable in full, expected
accept probability, expected incremental value) → Customer Outcome
(accepted/declined/no-offer, payment captured/failed/abandoned/pending,
basket after) — plus a Transaction Summary card and an expandable raw
audit trail (`src/audit/trace.py`'s own reconstruction, unmodified). A
genuine `no_action` and a Phase 6 bound-rejected offer render as
distinct, honest states (the latter badged "BOUNDED", decision type
"Offer Blocked (Bounded)"), never hidden or treated as errors. The
sidebar adds real filtering (outcome, decision type, payment status,
household/order-id search, date range — all client-side against the
already-fetched transaction list, no extra round-trips) and four Quick
Links (Audit Logs, Engine Decisions, Raw Data / Parquet, Documentation)
that open a modal reading real files live: the audit log tail, decision
events only, `data/experiment/*.parquet`'s real row counts (via
`pyarrow.parquet.ParquetFile(...).metadata.num_rows`, not a full read),
and the repo's real docs with their real descriptions.

The real audit log now holds one genuine traceable transaction (request_id
`866da2ea-...`, household 2375) from the user's own real `demo_graph.py`
run, alongside 4 legacy Phase 4 payment-only lines that predate
request_id and so can't be traced per-transaction. It's a valuable one:
the engine's real top-ranked candidate (cross_sell to a soft-drinks
product) was correctly bound-rejected by the Phase 6 catalogue rule
(soft drinks isn't a declared complement for peanut butter) and replaced
with `no_action` — live proof the guardrail fires for real, not just in
a unit test.

**Aggregate view** reads Phase 5's output live (`src/dashboard/aggregate.py`
reruns the same Mann-Whitney test and bootstrap CIs `stats_module.py`
used, straight off the archived parquet files) as five KPI cards (AOV
split, attach rate split, incremental revenue/session, incremental
contribution margin/session, Mann-Whitney significance), a targeting
curve with its own case-resampling bootstrap 95% CI band (resample
sessions with replacement, re-rank each resample by its own expected
value, recompute the running-mean curve, percentile the band across
resamples — a k-floor near the low end avoids the wild single-session
variance a literal k=1 point would show), a "Smart targeting vs. random"
card headlining +29.5% at the engine's own real targeting rate, and a
real order-value density distribution (agent vs. control, $0–$200 binned
plus overflow). Every money or lift figure carries an explicit "TEST
MODE · OFFLINE REPLAY" badge — deliberately, so "incremental
revenue/session" is never confused with "revenue generated" (this is an
offline replay's incremental AOV, not a live production result, and the
dashboard says so everywhere the number appears, not once at the top).

All charts are hand-rolled inline SVG (polylines/polygons for the CI
band and density curves) — zero external JS chart libraries, so the
page works offline in front of a judge; only Google Fonts (Inter) is
loaded externally, with a full system-font fallback stack if that fetch
is ever blocked.

Verified structurally (FastAPI `TestClient`, real Phase 5 parquet
files, zero LLM/Razorpay calls) against every endpoint, including the
new `/api/raw/*` routes and the real `866da2ea` transaction, plus a full
visual QA pass in a headless browser: the built page was staged into
the cloud sandbox with fresh fixtures (the one real transaction, plus
four synthetic-but-clearly-labeled `TESTPHASE7` scenarios covering
accepted/declined/no-action/bound-rejected — visual QA fixtures only,
never written to the real audit log) and screenshotted through every
view, filter, and modal with the sandbox's pre-installed headless
Chromium via Playwright. That pass caught and fixed two real bugs: the
`.view` class had no `display:none` rule, so the inactive view stayed
in the DOM and rendered stacked underneath the active one instead of
being hidden; and the outcome badge showed "ACCEPTED" for a plain
`no_action` session whose payment happened to complete, which is
misleading since nothing was ever offered — it now shows "COMPLETED"
for that case and reserves "ACCEPTED" for an offer that was actually
accepted.

**Files:** `src/dashboard/aggregate.py` (live Phase 5 computation, now
including the targeting-curve bootstrap and the order-value
distribution), `src/dashboard/dashboard_api.py` (FastAPI:
`/api/transactions`, `/api/transactions/{request_id}`,
`/api/audit/{request_id}`, `/api/aggregate`, `/api/raw/audit-log`,
`/api/raw/decisions`, `/api/raw/parquet-files`, `/api/raw/docs`),
`src/dashboard/static/index.html` (single-page frontend, no external
dependencies besides the Inter font — self-contained so it works
offline in front of a judge).

**Rehearsal still pending:** the plan's own exit line for this phase —
the scripted demo sequence (`docs/demo_script.md`) run start to finish
twice in a row with no manual data patching — needs real API calls and
a real browser completing real Test Mode payments, so it's the user's
step, not something built or run here. `docs/demo_script.md` has the
exact commands, talking points, and two concrete household/intent pairs
(found by calling the real decision engine directly, free) verified to
produce an accepted cross-sell and a structurally guaranteed no_action.
