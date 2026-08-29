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

## Next: Phase 3 (agent layer and agent-readable catalogue)

Per the build plan: one thin, agent-readable catalogue endpoint (plain
JSON — product id, price, availability, attributes, declared
complements/alternatives, current offers, a checkout-capability
marker), queryable in natural language. A Merchant Agent behind it
that interprets a buyer request, picks the base product from the
catalogue, calls this decision engine (decide()) for the growth
decision, and presents whatever it returns (including no action) for
accept/decline. A minimal Buyer Agent alongside it (one tool: query the
catalogue in natural language) so the demo is agent-to-agent, not a
human clicking a UI. Cart state tracked as an explicit before/after
pair from here on, for the Phase 7 dashboard. No money moves yet —
that's Phase 4. Guardrail: no OAuth delegated-auth flows, no
cryptographic mandates, no .well-known discovery stack, no full ACP/UCP
conformance attempt — the one correctly-shaped JSON endpoint is the
entire buyer-readiness commitment.
