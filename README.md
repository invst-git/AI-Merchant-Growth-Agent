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

## Phase 4 (Razorpay Test Mode integration): not started

Turns an accepted offer into a real, verifiable Test Mode transaction.
Per the plan: create a Razorpay Order via the Orders API for the final
basket amount in paise (basket metadata in receipt/notes), made
through the official Razorpay MCP Server's tools (create_order,
create_payment_link, fetch_payment, capture), not hand-rolled REST
calls. Standard Checkout completes against the mock bank/UPI page,
returns razorpay_order_id/razorpay_payment_id/razorpay_signature; the
server verifies that signature with HMAC-SHA256 before treating the
payment as legitimate, then captures (or confirms auto-capture) and
fetches to confirm final status. One webhook listener for
payment.captured, verifying the x-razorpay-signature header. A second,
deliberate path uses the "failure@razorpay" mock UPI identifier to
force a decline, handled gracefully: a clear message, no half-updated
cart or order state, a logged failed attempt in the audit trail. A
spend cap enforced here is the concrete "bounded" mechanism. Phase
ends with one successful and one deliberately failed Test Mode
payment, both traceable back to the specific agent decision that
triggered them. Guardrail: borrow only the concept of a signed,
bounded authorization record for the audit log, not the AP2
specification itself, and stay entirely in Test Mode, no Live Mode
keys anywhere near this build.

Before any code: a Razorpay Test Mode account and Test API keys
(that's real account setup, the user's to do), and a decision on
hosted vs self-hosted Docker for the official Razorpay MCP Server.
