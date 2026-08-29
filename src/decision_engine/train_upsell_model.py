"""Phase 2: train the upsell propensity model, logistic regression or
gradient boosting, on the leave-out feature table (upsell_training_data.py).

Usage:
    python3 src/decision_engine/train_upsell_model.py --model logistic --save
    python3 src/decision_engine/train_upsell_model.py --model gbm --save
    python3 src/decision_engine/train_upsell_model.py --model compare

compare fits both on the identical train/test split and prints both
AUCs side by side, plus two baselines, without saving anything. Use it
first to decide which model to keep, then rerun with --model and --save.

Why both are offered: logistic regression was picked originally for
interpretability, not because it was verified to be the best predictor.
trade_up_rate_other and national_brand_rate_other interact with
same_manufacturer_as_usual and the categorical features in ways a linear
model can only capture if those interactions are hand-added. Gradient
boosting (HistGradientBoostingClassifier, sklearn's histogram-based GBM,
picked over the older GradientBoostingClassifier for speed and over
XGBoost/LightGBM to avoid a new dependency) can find those interactions
on its own. compare mode below is the actual test of that claim, not an
assumption either way.

Same preprocessing pipeline (one-hot + scaling) is used for both models
so the comparison isolates the model class, not the preprocessing. This
is slightly unfair to the GBM, which can split on raw categoricals
natively and doesn't need scaling, but keeping the pipeline identical is
worth more here than squeezing out the GBM's last bit of headroom.
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

DATA_PATH = "models/upsell_training_data.parquet"
MODEL_PATH = "models/upsell_propensity_model.joblib"

SAMPLE_SIZE = 300_000

NUMERIC_FEATURES = ["trade_up_rate_other", "national_brand_rate_other", "avg_basket_value", "coupon_redemption_count"]
BOOL_FEATURES = ["same_manufacturer_as_usual", "has_demographic", "has_campaign_exposure", "discount_active"]
CATEGORICAL_FEATURES = ["income_desc", "household_size_desc"]
FEATURES = NUMERIC_FEATURES + BOOL_FEATURES + CATEGORICAL_FEATURES


def load_sample(sample_size):
    df = pd.read_parquet(DATA_PATH)
    for col in BOOL_FEATURES:
        df[col] = df[col].astype(int)
    n = min(sample_size, len(df))
    return df.sample(n=n, random_state=42)


def make_pipeline(model_type):
    preprocess = ColumnTransformer([
        ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_FEATURES),
        ("num", StandardScaler(), NUMERIC_FEATURES),
    ], remainder="passthrough")

    if model_type == "logistic":
        clf = LogisticRegression(max_iter=500)
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

    df = load_sample(args.sample)
    print(f"training rows: {len(df)}, top_tier rate: {df['top_tier'].mean():.3f}")

    X = df[FEATURES]
    y = df["top_tier"]
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)

    baseline_discount_auc = roc_auc_score(y_test, X_test["discount_active"])
    baseline_trade_up_auc = roc_auc_score(y_test, X_test["trade_up_rate_other"])
    print(f"baseline AUC (discount_active only):     {baseline_discount_auc:.4f}")
    print(f"baseline AUC (trade_up_rate_other only): {baseline_trade_up_auc:.4f}")

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
        joblib.dump({
            "model": model,
            "features": FEATURES,
            "model_type": args.model,
            "base_rate": float(y_train.mean()),
        }, MODEL_PATH)
        print(f"saved to {MODEL_PATH}")


if __name__ == "__main__":
    main()
