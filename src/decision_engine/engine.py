"""Phase 2: the growth decision engine.

Given a household and its current basket, generates cross-sell and
upsell candidates, scores every candidate plus no_action through the
objective function, and returns the winner with a plain-English reason.
Field names in the returned decision dict match docs/audit_schema.md.

Upsell propensity features:

trade_up_rate / national_brand_rate come from household_brand_stats.py
(full household history, no label being derived here so no leave-out
needed). same_manufacturer_as_usual is computed per candidate below,
since it depends on which specific upsell product is being scored, not
just the household. All three are passed under the same column names
the model was trained on (see upsell_training_data.py) even though the
training-time versions were leave-out and these are full-history: same
statistic, different scope, same feature slot.

Both acceptance_model.joblib and upsell_propensity_model.joblib can
hold either a logistic regression or a HistGradientBoostingClassifier
pipeline (see train_acceptance_model.py / train_upsell_model.py). Both
expose predict_proba the same way so no branching is needed there.

Per-decision explainability: verified empirically (not assumed) that
shap.Explainer(clf, background) auto-dispatches to LinearExplainer for
logistic regression and TreeExplainer for HistGradientBoostingClassifier,
both sub-5ms per call, so one code path covers whichever model type is
saved. One-hot columns are aggregated back to their original feature
name so the attribution is per real feature, not per dummy column.
"""

import math
import os

# joblib's loky backend tries to shell out to count physical CPU cores;
# that subprocess call fails on Windows (WinError 2) and prints a scary
# multi-line UserWarning + traceback on every run, even though joblib
# falls back to logical core count fine on its own. Set this before
# joblib is imported (loky's core-count probe is a lazy one-time check,
# cached at first use) so the fallback happens silently instead.
os.environ.setdefault("LOKY_MAX_CPU_COUNT", str(os.cpu_count() or 4))

import joblib
import numpy as np
import pandas as pd
import shap

from objective import explain, score

MODELS_DIR = "models"

RULES = pd.read_parquet(f"{MODELS_DIR}/affinity_rules.parquet")
UPSELL_TIERS = pd.read_parquet(f"{MODELS_DIR}/upsell_tiers.parquet").set_index("product_id")
REPRESENTATIVE = pd.read_parquet(f"{MODELS_DIR}/representative_products.parquet").set_index("commodity_desc")
PRODUCT_LOOKUP = pd.read_parquet(f"{MODELS_DIR}/product_lookup.parquet").set_index("product_id")
HOUSEHOLDS = pd.read_parquet(f"{MODELS_DIR}/household_features.parquet").set_index("household_key")
ACCEPTANCE = joblib.load(f"{MODELS_DIR}/acceptance_model.joblib")
UPSELL_PROPENSITY = joblib.load(f"{MODELS_DIR}/upsell_propensity_model.joblib")

HOUSEHOLD_BRAND_STATS = pd.read_parquet(f"{MODELS_DIR}/household_brand_stats.parquet").set_index("household_key")
_hbs = HOUSEHOLD_BRAND_STATS
POP_TRADE_UP_RATE = float((_hbs["top_tier_rate"] * _hbs["n_purchases"]).sum() / _hbs["n_purchases"].sum())
POP_NATIONAL_BRAND_RATE = float((_hbs["national_brand_rate"] * _hbs["n_purchases"]).sum() / _hbs["n_purchases"].sum())

_hsm = pd.read_parquet(f"{MODELS_DIR}/household_subcommodity_manufacturer.parquet")
DOMINANT_MANUFACTURER = dict(zip(zip(_hsm["household_key"], _hsm["sub_commodity_desc"]), _hsm["dominant_manufacturer"]))

MAX_CROSS_SELL_CANDIDATES = 15
BACKGROUND_SIZE = 100
TOP_DRIVERS = 2

# must match train_acceptance_model.py / train_upsell_model.py
CROSS_SELL_NUMERIC = ["confidence", "lift", "avg_basket_value", "coupon_redemption_count"]
CROSS_SELL_BOOL = ["has_demographic", "has_campaign_exposure"]
CROSS_SELL_CATEGORICAL = ["income_desc", "household_size_desc"]

UPSELL_NUMERIC = ["trade_up_rate_other", "national_brand_rate_other", "avg_basket_value", "coupon_redemption_count"]
UPSELL_BOOL = ["same_manufacturer_as_usual", "has_demographic", "has_campaign_exposure", "discount_active"]
UPSELL_CATEGORICAL = ["income_desc", "household_size_desc"]


def household_row(household_key):
    if household_key in HOUSEHOLDS.index:
        return HOUSEHOLDS.loc[household_key]
    return HOUSEHOLDS.loc[HOUSEHOLDS.index[0]] * 0  # neutral fallback, all zero/unknown


def household_brand_row(household_key):
    if household_key in HOUSEHOLD_BRAND_STATS.index:
        row = HOUSEHOLD_BRAND_STATS.loc[household_key]
        return float(row["top_tier_rate"]), float(row["national_brand_rate"])
    return POP_TRADE_UP_RATE, POP_NATIONAL_BRAND_RATE  # unknown household, population prior


def same_manufacturer_as_usual(household_key, sub_commodity_desc, candidate_manufacturer):
    dominant = DOMINANT_MANUFACTURER.get((household_key, sub_commodity_desc))
    if dominant is None:
        return 0  # no purchase history in this sub_commodity, no basis to claim consistency
    return int(candidate_manufacturer == dominant)


def basket_commodities(basket_product_ids):
    known = [p for p in basket_product_ids if p in PRODUCT_LOOKUP.index]
    return set(PRODUCT_LOOKUP.loc[known, "commodity_desc"]) if known else set()


# --- explainability -------------------------------------------------

def build_cross_sell_background():
    rules_sample = RULES.sample(n=min(BACKGROUND_SIZE, len(RULES)), random_state=42).reset_index(drop=True)
    hh_sample = HOUSEHOLDS.sample(n=len(rules_sample), random_state=42, replace=True).reset_index(drop=True)
    return pd.DataFrame({
        "confidence": rules_sample["confidence"],
        "lift": rules_sample["lift"],
        "avg_basket_value": hh_sample["avg_basket_value"],
        "coupon_redemption_count": hh_sample["coupon_redemption_count"],
        "has_demographic": hh_sample["has_demographic"].astype(int),
        "has_campaign_exposure": hh_sample["has_campaign_exposure"].astype(int),
        "income_desc": hh_sample["income_desc"],
        "household_size_desc": hh_sample["household_size_desc"],
    })


def build_upsell_background():
    rng = np.random.default_rng(42)
    hh_sample = HOUSEHOLDS.sample(n=BACKGROUND_SIZE, random_state=42, replace=True)
    trade_up, national = zip(*(household_brand_row(hh_key) for hh_key in hh_sample.index))
    return pd.DataFrame({
        "trade_up_rate_other": trade_up,
        "national_brand_rate_other": national,
        "avg_basket_value": hh_sample["avg_basket_value"].to_numpy(),
        "coupon_redemption_count": hh_sample["coupon_redemption_count"].to_numpy(),
        "same_manufacturer_as_usual": rng.integers(0, 2, size=len(hh_sample)),
        "has_demographic": hh_sample["has_demographic"].astype(int).to_numpy(),
        "has_campaign_exposure": hh_sample["has_campaign_exposure"].astype(int).to_numpy(),
        "discount_active": 0,
        "income_desc": hh_sample["income_desc"].to_numpy(),
        "household_size_desc": hh_sample["household_size_desc"].to_numpy(),
    })


def build_explainer(bundle, background_df):
    pipeline = bundle["model"]
    features = bundle["features"]
    preprocess = pipeline.named_steps["preprocess"]
    clf = pipeline.named_steps["clf"]
    background_t = preprocess.transform(background_df[features])
    return shap.Explainer(clf, background_t)


ACCEPTANCE_EXPLAINER = build_explainer(ACCEPTANCE, build_cross_sell_background())
UPSELL_EXPLAINER = build_explainer(UPSELL_PROPENSITY, build_upsell_background())


def top_feature_drivers(explainer, pipeline, features, categorical_features, numeric_features, bool_features, row_df):
    preprocess = pipeline.named_steps["preprocess"]
    transformed = preprocess.transform(row_df[features])
    try:
        values = explainer(transformed).values[0]
    except shap.utils._exceptions.ExplainerError:
        # HistGradientBoostingClassifier + TreeExplainer occasionally fails SHAP's
        # additivity check (a documented SHAP/sklearn compatibility quirk, not a
        # correctness issue with our features). SHAP's own error message suggests
        # this exact mitigation; verified against the real failing case
        # (household_key=2445, basket_id=27841106542) to produce valid attributions.
        values = explainer(transformed, check_additivity=False).values[0]

    onehot_names = list(preprocess.named_transformers_["cat"].get_feature_names_out(categorical_features))
    names = onehot_names + numeric_features + bool_features

    agg = {}
    for name, val in zip(names, values):
        key = next((c for c in categorical_features if name.startswith(c + "_")), name)
        agg[key] = agg.get(key, 0.0) + float(val)

    ranked = sorted(agg.items(), key=lambda kv: -abs(kv[1]))[:TOP_DRIVERS]
    return [{"feature": name, "shap_value": round(val, 4)} for name, val in ranked]


def format_drivers(drivers):
    return ", ".join(f"{d['feature']} ({d['shap_value']:+.2f})" for d in drivers)


# --- cross-sell -------------------------------------------------------

def cross_sell_candidates(household_key, basket_product_ids, explain_drivers=True):
    commodities = basket_commodities(basket_product_ids)
    if not commodities:
        return []

    hh = household_row(household_key)
    model_type = ACCEPTANCE.get("model_type", "logistic")
    candidates = []
    rules = RULES[RULES["antecedent"].isin(commodities) & ~RULES["consequent"].isin(commodities)]
    rules = rules.sort_values("lift", ascending=False).drop_duplicates("consequent")
    rules = rules.head(MAX_CROSS_SELL_CANDIDATES)

    for _, rule in rules.iterrows():
        if rule["consequent"] not in REPRESENTATIVE.index:
            continue
        product = REPRESENTATIVE.loc[rule["consequent"]]
        row = pd.DataFrame([{
            "confidence": rule["confidence"],
            "lift": rule["lift"],
            "avg_basket_value": hh["avg_basket_value"],
            "coupon_redemption_count": hh["coupon_redemption_count"],
            "has_demographic": int(hh["has_demographic"]),
            "has_campaign_exposure": int(hh["has_campaign_exposure"]),
            "income_desc": hh["income_desc"],
            "household_size_desc": hh["household_size_desc"],
        }])
        p_accept = float(ACCEPTANCE["model"].predict_proba(row[ACCEPTANCE["features"]])[0, 1])
        incremental_value = float(product["price"])
        if explain_drivers:
            drivers = top_feature_drivers(
                ACCEPTANCE_EXPLAINER, ACCEPTANCE["model"], ACCEPTANCE["features"],
                CROSS_SELL_CATEGORICAL, CROSS_SELL_NUMERIC, CROSS_SELL_BOOL, row,
            )
            reason = (
                f"customers who buy {rule['antecedent'].title()} buy "
                f"{rule['consequent'].title()} {rule['confidence']:.0%} of the time "
                f"(lift {rule['lift']:.1f}); estimated accept probability {p_accept:.0%} "
                f"({model_type}-trained acceptance model; top drivers: {format_drivers(drivers)}); "
                f"{explain(p_accept, incremental_value)}"
            )
        else:
            # Phase 5 bulk simulation path: SHAP is ~half the per-candidate
            # cost (see module docstring) and unused for aggregate stats,
            # skip it rather than compute and discard it thousands of times.
            drivers = []
            reason = None
        candidates.append({
            "action": "cross_sell",
            "product_id": int(product["product_id"]),
            "commodity_desc": rule["consequent"],
            "rule_antecedent": rule["antecedent"],
            "p_accept": p_accept,
            "incremental_value": incremental_value,
            "expected_value": score(p_accept, incremental_value),
            "feature_attribution": drivers,
            "reason": reason,
        })
    return candidates


# --- upsell -------------------------------------------------------

def upsell_propensity_factor(hh, trade_up_rate, national_brand_rate, same_manufacturer_flag, explain_drivers=True):
    row = pd.DataFrame([{
        "trade_up_rate_other": trade_up_rate,
        "national_brand_rate_other": national_brand_rate,
        "avg_basket_value": hh["avg_basket_value"],
        "coupon_redemption_count": hh["coupon_redemption_count"],
        "same_manufacturer_as_usual": same_manufacturer_flag,
        "has_demographic": int(hh["has_demographic"]),
        "has_campaign_exposure": int(hh["has_campaign_exposure"]),
        "discount_active": 0,  # general propensity, not tied to a specific discount
        "income_desc": hh["income_desc"],
        "household_size_desc": hh["household_size_desc"],
    }])
    features = UPSELL_PROPENSITY["features"]
    p_top_tier = float(UPSELL_PROPENSITY["model"].predict_proba(row[features])[0, 1])
    base_rate = UPSELL_PROPENSITY["base_rate"]
    propensity_factor = min(2.0, max(0.5, p_top_tier / base_rate))
    if explain_drivers:
        drivers = top_feature_drivers(
            UPSELL_EXPLAINER, UPSELL_PROPENSITY["model"], features,
            UPSELL_CATEGORICAL, UPSELL_NUMERIC, UPSELL_BOOL, row,
        )
    else:
        drivers = []
    return propensity_factor, drivers


def upsell_p_accept(price_ratio, propensity_factor):
    # price-ratio curve stays a heuristic, there is no per-ratio accept/reject
    # label to learn it from. propensity_factor is trained (train_upsell_model.py).
    base = max(0.05, min(0.5, 0.5 - 0.15 * math.log(price_ratio)))
    return max(0.02, min(0.6, base * propensity_factor))


def upsell_candidates(household_key, basket_product_ids, explain_drivers=True):
    hh = household_row(household_key)
    trade_up_rate, national_brand_rate = household_brand_row(household_key)
    model_type = UPSELL_PROPENSITY.get("model_type", "logistic")

    candidates = []
    for pid in basket_product_ids:
        if pid not in UPSELL_TIERS.index:
            continue
        tier = UPSELL_TIERS.loc[pid]
        if isinstance(tier, pd.DataFrame):
            tier = tier.iloc[0]

        manufacturer_match = same_manufacturer_as_usual(
            household_key, tier["sub_commodity_desc"], tier["upsell_manufacturer"]
        )
        propensity_factor, drivers = upsell_propensity_factor(
            hh, trade_up_rate, national_brand_rate, manufacturer_match, explain_drivers=explain_drivers
        )
        price_ratio = tier["upsell_price"] / tier["price"]
        p_accept = upsell_p_accept(price_ratio, propensity_factor)
        incremental_value = float(tier["price_delta"])

        if explain_drivers:
            brand_note = "same manufacturer as the item in cart" if tier["same_manufacturer"] else "different manufacturer (no same-brand option in price band)"
            reason = (
                f"upsell from product {pid} to {int(tier['upsell_product_id'])} "
                f"({brand_note}), +${incremental_value:.2f}; accept probability {p_accept:.0%} "
                f"(price-ratio heuristic x {model_type}-trained household trade-up propensity, "
                f"top drivers: {format_drivers(drivers)}); {explain(p_accept, incremental_value)}"
            )
        else:
            reason = None
        candidates.append({
            "action": "upsell",
            "product_id": int(tier["upsell_product_id"]),
            "from_product_id": int(pid),
            "p_accept": p_accept,
            "incremental_value": incremental_value,
            "expected_value": score(p_accept, incremental_value),
            "feature_attribution": drivers,
            "reason": reason,
        })
    return candidates


def decide(household_key, basket_product_ids, explain_drivers=True):
    candidates = cross_sell_candidates(household_key, basket_product_ids, explain_drivers=explain_drivers)
    candidates += upsell_candidates(household_key, basket_product_ids, explain_drivers=explain_drivers)
    no_action = {
        "action": "no_action",
        "p_accept": None,
        "incremental_value": 0.0,
        "expected_value": 0.0,
        "feature_attribution": [],
        "reason": "no candidate scored above the no-action baseline of 0",
    }
    all_candidates = candidates + [no_action]
    chosen = max(all_candidates, key=lambda c: c["expected_value"])
    return {
        "chosen_action": chosen,
        "candidate_actions": all_candidates,
    }
