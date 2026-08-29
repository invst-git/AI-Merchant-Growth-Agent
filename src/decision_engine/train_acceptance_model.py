"""Phase 2: train the cross-sell offer-acceptance model, logistic
regression or gradient boosting, on the same rule-based training set as
before (see build_training_set below). Feature set is unchanged from
the original acceptance_model.py, this is strictly a re-verification of
the model choice, not a feature-engineering pass.

Usage:
    python3 src/decision_engine/train_acceptance_model.py --model logistic --save
    python3 src/decision_engine/train_acceptance_model.py --model gbm --save
    python3 src/decision_engine/train_acceptance_model.py --model compare

Original acceptance_model.py picked logistic regression citing
interpretability, without testing whether a heavier model would have
scored meaningfully higher. compare mode here is that test: same
train/test split, same features, both models, AUC and log_loss side by
side. If gbm doesn't clearly beat logistic, that's the actual
justification for keeping logistic, not just the interpretability
argument alone.
"""

import argparse

import joblib
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

TXN_PATH = "data/processed/dunnhumby_baskets.parquet"
RULES_PATH = "models/affinity_rules.parquet"
HOUSEHOLD_PATH = "models/household_features.parquet"
MODEL_PATH = "models/acceptance_model.joblib"

TOP_N_RULES = 300
SAMPLE_SIZE = 300_000

NUMERIC_FEATURES = ["confidence", "lift", "avg_basket_value", "coupon_redemption_count"]
BOOL_FEATURES = ["has_demographic", "has_campaign_exposure"]
CATEGORICAL_FEATURES = ["income_desc", "household_size_desc"]
FEATURES = NUMERIC_FEATURES + BOOL_FEATURES + CATEGORICAL_FEATURES


def build_training_set(sample_size):
    txn = pd.read_parquet(TXN_PATH, columns=["basket_id", "household_key", "commodity_desc"])
    bc = txn[["basket_id", "commodity_desc"]].drop_duplicates()
    basket_hh = txn[["basket_id", "household_key"]].drop_duplicates()

    rules = pd.read_parquet(RULES_PATH).sort_values("lift", ascending=False).head(TOP_N_RULES)

    ante = bc.rename(columns={"commodity_desc": "antecedent"})
    cand = ante.merge(rules, on="antecedent", how="inner")

    cons = bc.rename(columns={"commodity_desc": "consequent"})
    cons["label"] = 1
    cand = cand.merge(cons, on=["basket_id", "consequent"], how="left")
    cand["label"] = cand["label"].fillna(0).astype(int)

    cand = cand.merge(basket_hh, on="basket_id", how="left")

    households = pd.read_parquet(HOUSEHOLD_PATH)
    cand = cand.merge(households, on="household_key", how="left")

    for col in BOOL_FEATURES:
        cand[col] = cand[col].astype(int)

    n = min(sample_size, len(cand))
    return cand.sample(n=n, random_state=42)


def make_pipeline(model_type):
    preprocess = ColumnTransformer([
        ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_FEATURES),
        ("num", StandardScaler(), NUMERIC_FEATURES),
    ], remainder="passthrough")

    if model_type == "logistic":
        clf = LogisticRegression(max_iter=500, solver="lbfgs")
    elif model_type == "gbm":
        clf = HistGradientBoostingClassifier(random_state=42)
    else:
        raise ValueError(f"unknown model_type: {model_type}")

    return Pipeline([("preprocess", preprocess), ("clf", clf)])


def evaluate(model, X_test, y_test):
    probs = model.predict_proba(X_test)[:, 1]
    return roc_auc_score(y_test, probs), log_loss(y_test, probs)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=["logistic", "gbm", "compare"], default="compare")
    parser.add_argument("--sample", type=int, default=SAMPLE_SIZE)
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()

    df = build_training_set(args.sample)
    print(f"training rows: {len(df)}, positive rate: {df['label'].mean():.3f}")

    X = df[FEATURES]
    y = df["label"]
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)

    baseline_confidence_auc = roc_auc_score(y_test, X_test["confidence"])
    baseline_lift_auc = roc_auc_score(y_test, X_test["lift"])
    print(f"baseline AUC (rule confidence only): {baseline_confidence_auc:.4f}")
    print(f"baseline AUC (rule lift only):       {baseline_lift_auc:.4f}")

    model_types = ["logistic", "gbm"] if args.model == "compare" else [args.model]
    results = {}
    for model_type in model_types:
        model = make_pipeline(model_type)
        model.fit(X_train, y_train)
        auc, loss = evaluate(model, X_test, y_test)
        results[model_type] = model
        print(f"{model_type}: test AUC {auc:.4f}, log_loss {loss:.4f}")

    if args.save:
        if args.model == "compare":
            print("compare mode does not save, rerun with --model logistic or --model gbm --save")
            return
        model = results[args.model]
        joblib.dump({"model": model, "features": FEATURES, "model_type": args.model}, MODEL_PATH)
        print(f"saved to {MODEL_PATH}")


if __name__ == "__main__":
    main()
