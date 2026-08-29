# Objective Function — Source of Truth

This document is the single definition of what the Growth Decision Engine
optimizes. Any change here must be reflected in the Phase 2 decision engine
code and in the Phase 6 audit trail's "reason" field — they should never
drift apart.

## The formula

For a given basket and a given candidate action (a specific upsell, a
specific cross-sell, or no action), the engine computes:

    expected_incremental_contribution =
        P(accept | offer, customer, basket)
        x (incremental_basket_value x margin_proxy)
        - expected_downside

The engine evaluates every candidate action this way and picks whichever
scores highest. "No action" is always one of the candidates, not a
fallback used only when nothing else qualifies — see below.

## Term by term

**P(accept | offer, customer, basket)** — the probability this specific
customer accepts this specific offer, given their current basket. This
comes from the Phase 2 acceptance model, trained on dunnhumby's basket,
demographic, and campaign/coupon history.

**incremental_basket_value** — the extra revenue the offer would add if
accepted. For a cross-sell, this is the added item's price. For an
upsell (swapping a cheaper item for a pricier one in the same
sub-commodity), this is the price difference, not the full price of the
new item.

**margin_proxy** — none of the three datasets (dunnhumby, Olist, UCI
Online Retail II) contain true cost-of-goods data, so contribution margin
cannot be computed exactly. Starting placeholder: a flat 30% assumed
margin across all categories, applied uniformly. This is a placeholder,
not a researched figure. Whatever is chosen, the dashboard (Phase 7) must
label every contribution-margin figure as based on an assumed proxy, not
real COGS.

**expected_downside** — a penalty representing the risk that presenting
an offer at all causes some fraction of customers to abandon the basket
(interruption/friction cost), separate from whether the specific offer is
accepted. This is the least-grounded term in the formula.

## "No action" as a first-class candidate

No action always scores exactly 0 (no incremental value, no downside). It
is scored on the same footing as every upsell/cross-sell candidate and
the engine's decision is simply the argmax across the full candidate set,
including 0. This is deliberate: the whole point of the project is that
the agent can decide silence is the best move, not that it always finds
some offer to make.

## Status

Placeholder values (30% margin proxy, fixed abandonment constant) are
Phase 0 defaults so the rest of the build isn't blocked. They are meant
to be revisited, not treated as final.

## Phase 2 exit criterion, checked against the plan

The build plan's own exit line for this phase: "given any basket, the
engine returns a ranked decision with an attached expected-value score
and the specific reason behind it (which rule fired, what the
acceptance probability was, what the margin proxy contributed)". The
first two were always true; the margin proxy's dollar contribution
was not spelled out in the reason text until this round.
objective.py now has an explain(p_accept, incremental_value) function
alongside score() (same constants, so they can't drift apart) and
engine.py appends its output to every cross-sell and upsell reason,
e.g. "49% accept x ($8.44 incremental x 30% margin proxy) - $0.20
downside = $1.033 expected value". Verified end to end on real
decisions after adding it.

The plan's Phase 2 text also states "logistic regression is
deliberately the right choice here, not a heavier model" as a blanket
rule for both models in this phase. That assumption was tested, not
just carried forward: it holds for the acceptance model (logistic
0.6525 AUC vs gbm 0.6664, a small gap not worth losing interpretability
over) but does not hold for the upsell propensity model (logistic
0.6016 vs gbm 0.6801, a large gap). This is a deliberate, evidence-based
deviation from the plan's original text for one of the two models, not
an oversight — see the model comparison section above for the numbers
that drove it.

## Phase 2 implementation notes

Concrete placeholder values used in src/decision_engine/objective.py:

- margin_proxy = 0.30 (flat, as above)
- expected_downside = 0.20 (20 cents per offer shown, flat). Revised
  from an initial 0.10 guess after sweeping the constant against the
  real distribution of candidates' raw expected margin
  (P(accept) x incremental_value x margin_proxy, before downside) on a
  500-basket sample: median raw margin $0.26, 25th percentile $0.16,
  75th percentile $0.45 (src/decision_engine/tune_downside.py). At 0.20
  the engine chose no_action on roughly a third of baskets under the
  first-pass models, filtering out weak candidates while leaving the
  stronger ones untouched. Still an assumption about interruption cost,
  not derived from a real cost measurement. Revisit once Phase 5's
  experiment gives a real abandonment signal.

P(accept) comes from two different sources depending on action type,
and this split is itself a Phase 2 simplification worth flagging:

- Cross-sell: models/acceptance_model.joblib, trained on the top-300
  affinity rules by lift as the training set (real co-purchase behavior
  as the label, dunnhumby has no logged offer-shown/offer-accepted
  event). Feature set: confidence, lift, avg_basket_value,
  coupon_redemption_count, has_demographic, has_campaign_exposure,
  income_desc, household_size_desc.
- Upsell: hybrid. The price-ratio penalty (bigger step = lower
  probability) stays a hand-set curve, there is no data linking a
  specific price jump to an accept/reject outcome. The household
  personalization term, models/upsell_propensity_model.joblib, predicts
  whether a household tends to buy the top-tier or bottom-tier product
  within a sub_commodity_desc (population-median price split, not the
  household's own history, to avoid circularity).

## Model choice: logistic regression vs gradient boosting

Both models were originally logistic regression, picked for
interpretability. That choice was never actually tested against a
heavier model, so it was a default, not a verified decision.
src/decision_engine/train_acceptance_model.py and
src/decision_engine/train_upsell_model.py now both support
HistGradientBoostingClassifier (sklearn's histogram-based gradient
boosting, chosen over the older GradientBoostingClassifier for speed
and over XGBoost/LightGBM to avoid a new dependency) alongside logistic
regression, fit on an identical preprocessing pipeline and train/test
split, so the comparison isolates the model class rather than the
preprocessing.

**Results (300k-row sample, run by the user, 2026-08-29):**

| model | upsell propensity AUC | upsell log_loss | acceptance AUC | acceptance log_loss |
|---|---|---|---|---|
| baseline (single strongest raw feature) | 0.5799 (trade_up_rate_other alone) | - | 0.6261 (rule confidence alone) | - |
| logistic regression | 0.6016 | 0.6633 | 0.6525 | 0.5189 |
| gradient boosting (HistGBM) | 0.6801 | 0.6348 | 0.6664 | 0.5131 |

Two different verdicts, not one:

- **Upsell propensity: gradient boosting wins by a real margin** (+7.85
  AUC points over logistic, +10 points over the single-feature
  baseline, vs logistic's own +2.2 over that same baseline). Logistic
  regression is barely beating one raw feature used alone, which means
  it isn't meaningfully using its other 9 features, most likely because
  the real structure here is interaction-heavy (does trade_up_rate_other
  matter more when same_manufacturer_as_usual is true? does
  national_brand_rate_other cut the other way for private-label loyal
  households? see the SHAP example below, it does). That is exactly the
  kind of relationship a linear model cannot represent without someone
  hand-adding interaction terms, and gradient boosting finds it
  automatically. models/upsell_propensity_model.joblib should be gbm.
- **Cross-sell acceptance: gradient boosting wins, but marginally**
  (+1.4 AUC points, +0.006 log_loss). Logistic regression already
  captures most of the usable signal here (+2.6 points over the
  confidence-alone baseline, a much bigger jump off baseline than the
  upsell model's logistic managed). The feature set is smaller and less
  interaction-heavy (rule confidence/lift are already aggregate
  statistics, not raw behavioral signals), so there's less for a
  heavier model to find. A 1.4-point gap on this sample size is a real
  but small effect, not obviously worth giving up clean linear
  coefficients for. models/acceptance_model.joblib should stay
  logistic.

Save both accordingly:

    python3 src/decision_engine/train_upsell_model.py --model gbm --save
    python3 src/decision_engine/train_acceptance_model.py --model logistic --save

engine.py loads whatever is saved at each path and works with either
model type without any code changes — both expose predict_proba the
same way.

## Explainability: SHAP, implemented for the upsell model's real gap

Before deciding whether to spend effort here, this was tested
empirically rather than assumed: shap.Explainer(clf, background)
auto-dispatches to shap.TreeExplainer for HistGradientBoostingClassifier
and shap.LinearExplainer for LogisticRegression, both verified to run
in under 5ms per decision (single-row) once built, with additivity
confirmed (base_value + sum(shap_values), passed through a sigmoid,
reproduces predict_proba exactly). Given that cost is negligible and
the code path is identical for both model types, engine.py now computes
a real per-decision SHAP attribution for every candidate it scores (not
a static template), aggregating one-hot dummy columns back to their
original feature name so the output reads as "same_manufacturer_as_usual
(+0.27), trade_up_rate_other (+0.19)" rather than per-dummy-column
noise. This is exposed both in the reason text and as a structured
feature_attribution list on every candidate, ready for the Phase 6
audit trail to log directly rather than only a prose string.

One real example pulled while testing this (upsell model, gbm): for one
candidate, same_manufacturer_as_usual contributed +0.27 to the trade-up
prediction (by far the largest driver), trade_up_rate_other +0.19,
but national_brand_rate_other pulled the other way at -0.16 for that
same household. A linear model forces every feature to have one fixed
direction across all households; the tree model let national brand
loyalty cut against trade-up propensity for this specific household
while trade_up_rate_other pushed the other way, which is the concrete
form of the "complex relations a linear model can't capture" concern
that motivated trying gradient boosting in the first place.

This was implemented for both models (not just upsell) since the
per-decision cost turned out to be uniformly cheap regardless of model
type; skipping it for the model that stayed logistic would have meant
one code path with real per-decision numbers and another with a static
label, which is a worse audit trail than doing it consistently.

Cost/latency note: SHAP roughly doubles the per-candidate scoring cost.
Measured on real baskets: ~130ms per basket decision (candidate
generation + scoring + attribution for every candidate, cross-sell and
upsell combined), against a background sample of 100 synthetic rows
built once at import time from data already loaded by engine.py (no new
heavy file reads). This is fine for offline validation and a live demo
loop; if this decision engine is ever moved into a tight low-latency
request path, this is the number to watch, not the AUC.

## Upsell feature fixes (this round)

Two problems in the first-pass upsell model were fixed before comparing
model classes, since comparing logistic regression against gradient
boosting on a weak feature set would not have been a meaningful test of
either the features or the models:

1. **Brand-blind candidate selection.** upsell_tiers.py picked the
   closest pricier product in the same sub_commodity_desc with no
   regard for manufacturer. dunnhumby's brand field is only a binary
   National/Private flag, not a specific brand name (verified before
   writing the fix: 1,849,560 National vs 746,172 Private rows, zero
   nulls) — it could never have supported real brand matching.
   manufacturer (6,476 distinct values, zero nulls) is the field that
   identifies a specific maker. upsell_tiers.py now tries a
   same-manufacturer match within the price band first, falling back to
   any manufacturer only if none exists in-band; 71.4% of the 85,028
   products with an upsell target now get a same-manufacturer upgrade.

2. **Missing features.** The original upsell propensity model used only
   generic household features (avg_basket_value, coupon_redemption_count,
   demographic/campaign flags, income, household size), with nothing
   that distinguished "this household trades up in general" from "this
   household is loyal to one manufacturer and this candidate either
   matches that loyalty or doesn't." Two features were added:
   - trade_up_rate_other / national_brand_rate_other: the household's
     top-tier and National-brand purchase rate across every OTHER
     sub_commodity (this one excluded), Bayesian-smoothed toward the
     population rate (SMOOTHING_K=10) for households with thin history
     outside one category. Leave-out at training time so the model
     can't learn a trivial identity mapping; full household history at
     inference (household_brand_stats.py), since no label is being
     derived at inference time.
   - same_manufacturer_as_usual: whether a purchase's manufacturer was
     the household's dominant manufacturer in that sub_commodity,
     computed leave-one-transaction-out at training time (this
     manufacturer's count minus one, compared against the best
     remaining manufacturer — not just the plain historical majority,
     which would leak for households with very few purchases in that
     sub_commodity). At inference this is evaluated per upsell
     candidate against the household's full-history dominant
     manufacturer (household_subcommodity_manufacturer.parquet), since
     it depends on which specific product is being offered, not just
     the household.

   See src/decision_engine/upsell_training_data.py and
   src/decision_engine/household_brand_stats.py.

**Verified direction, corrected from the original assumption:**
same_manufacturer_as_usual was added on the assumption that manufacturer
loyalty would predict a higher trade-up rate (comfortable with the
brand, easier upsell). Checked directly against the real label on
100,000 rows: it's the opposite. mean top_tier rate is 47.7% when the
purchase is a DIFFERENT manufacturer from the household's usual one,
vs 40.0% when it matches (correlation -0.064, same sign as the trained
model's per-decision SHAP attributions). The likely mechanism: being
loyal to one manufacturer in a sub_commodity mostly captures habitual,
repeat-buy-the-same-cheap-thing behavior, not brand affinity that
extends upward — trading up more often coincides with reaching for a
manufacturer the household doesn't already buy by habit. The feature is
still genuinely useful (it shows up as a top-2 SHAP driver on a large
share of real decisions, comparable in effect size to
national_brand_rate_other), just not in the direction the name and the
original write-up implied. Left in with the corrected sign understood,
not removed — the model already learned the real relationship from
data regardless of what the docstring assumed; this correction is to
the narrative, not the code.
