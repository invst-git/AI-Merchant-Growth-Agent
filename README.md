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

      python3 src/decision_engine/train_upsell_model.py --model gbm --save
      python3 src/decision_engine/train_acceptance_model.py --model logistic --save

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
    python3 src/agents/demo_graph.py --household-key 1 --intent "I need cigarettes"

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
