"""Phase 2: per-household features for the acceptance model.
Demographics and campaign/coupon history have partial coverage
(only 801/2500 households have demographics, 1584/2500 have campaign
exposure), so every field carries an explicit unknown/zero default
rather than dropping households.
"""

import pandas as pd

TXN_PATH = "data/processed/dunnhumby_baskets.parquet"
RAW_DIR = "data/raw/dunnhumby"
OUT_PATH = "models/household_features.parquet"

DEMO_COLS = [
    "age_desc", "marital_status_code", "income_desc",
    "homeowner_desc", "hh_comp_desc", "household_size_desc", "kid_category_desc",
]


def load_csv(name):
    df = pd.read_csv(f"{RAW_DIR}/{name}.csv")
    df.columns = [c.strip().lower() for c in df.columns]
    return df


def main():
    txn = pd.read_parquet(TXN_PATH, columns=["household_key", "basket_id", "sales_value"])
    basket_value = txn.groupby(["household_key", "basket_id"])["sales_value"].sum().reset_index()
    avg_basket_value = basket_value.groupby("household_key")["sales_value"].mean().rename("avg_basket_value")

    households = pd.DataFrame({"household_key": txn["household_key"].unique()})

    demo = load_csv("hh_demographic")
    households = households.merge(demo, on="household_key", how="left")
    households["has_demographic"] = households["age_desc"].notna()
    for col in DEMO_COLS:
        households[col] = households[col].fillna("unknown")

    campaign = load_csv("campaign_table")
    campaign_count = campaign.groupby("household_key").size().rename("campaign_count")
    households = households.merge(campaign_count, on="household_key", how="left")
    households["campaign_count"] = households["campaign_count"].fillna(0).astype(int)
    households["has_campaign_exposure"] = households["campaign_count"] > 0

    coupon_redempt = load_csv("coupon_redempt")
    redempt_count = coupon_redempt.groupby("household_key").size().rename("coupon_redemption_count")
    households = households.merge(redempt_count, on="household_key", how="left")
    households["coupon_redemption_count"] = households["coupon_redemption_count"].fillna(0).astype(int)

    households = households.merge(avg_basket_value, on="household_key", how="left")

    print(f"households: {len(households)}")
    print(f"with demographic: {households['has_demographic'].sum()}")
    print(f"with campaign exposure: {households['has_campaign_exposure'].sum()}")
    print(households.head(3).to_string(index=False))

    households.to_parquet(OUT_PATH, index=False)
    print(f"saved to {OUT_PATH}")


if __name__ == "__main__":
    main()
