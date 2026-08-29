"""Phase 2: build the upsell propensity TRAINING table.

Three engineered features, each computed leave-out to stop the model
from learning a trivial identity mapping during fitting:

household_trade_up_rate_other: the household's top-tier purchase rate
across every OTHER sub_commodity_desc (this subcommodity's own
purchases excluded). Smoothed toward the population rate with a
Bayesian prior (weight SMOOTHING_K), since some households have very
little history outside one category.

household_national_brand_rate_other: same idea, using brand ==
National vs Private instead of price tier. Verified before building
this that National-brand items are top-tier 46.5% of the time vs 26.6%
for Private label, so this is a real complementary signal, not a
duplicate of trade_up_rate.

same_manufacturer_as_usual: was this specific purchase's manufacturer
the household's dominant manufacturer in this sub_commodity, using
everyone ELSE's purchases in that household+subcommodity (this one
transaction excluded). Computed properly leave-one-out (comparing this
manufacturer's count minus 1 against the best remaining manufacturer),
not just "was it the plain historical majority", since for a household
with very few purchases in a subcommodity the plain majority can just
be this one purchase, which would leak.

At inference time (engine.py) these are computed from FULL household
history instead, since no label is being derived there, leaving them
out would just be throwing away real signal. See household_brand_stats.py.
"""

import pandas as pd

TXN_PATH = "data/processed/dunnhumby_baskets.parquet"
PRODUCT_LOOKUP_PATH = "models/product_lookup.parquet"
HOUSEHOLD_PATH = "models/household_features.parquet"
OUT_PATH = "models/upsell_training_data.parquet"

MIN_PRODUCTS_PER_SUBCOMMODITY = 5
SMOOTHING_K = 10


def label_products():
    products = pd.read_parquet(PRODUCT_LOOKUP_PATH)
    sub_stats = products.groupby("sub_commodity_desc")["price"].agg(["median", "std", "count"]).reset_index()
    sub_stats = sub_stats[(sub_stats["count"] >= MIN_PRODUCTS_PER_SUBCOMMODITY) & (sub_stats["std"] > 0)]
    products = products.merge(sub_stats[["sub_commodity_desc", "median"]], on="sub_commodity_desc", how="inner")
    products["top_tier"] = (products["price"] > products["median"]).astype(int)
    return products[["product_id", "top_tier"]]


def add_leave_subcommodity_out_rates(df, population_top_tier_rate, population_national_rate):
    hh_sub = df.groupby(["household_key", "sub_commodity_desc"]).agg(
        sub_purchases=("product_id", "count"),
        sub_top_tier_sum=("top_tier", "sum"),
        sub_national_sum=("is_national", "sum"),
    ).reset_index()

    hh_total = df.groupby("household_key").agg(
        total_purchases=("product_id", "count"),
        total_top_tier_sum=("top_tier", "sum"),
        total_national_sum=("is_national", "sum"),
    ).reset_index()

    hh_sub = hh_sub.merge(hh_total, on="household_key", how="left")
    hh_sub["other_purchases"] = hh_sub["total_purchases"] - hh_sub["sub_purchases"]
    hh_sub["other_top_tier_sum"] = hh_sub["total_top_tier_sum"] - hh_sub["sub_top_tier_sum"]
    hh_sub["other_national_sum"] = hh_sub["total_national_sum"] - hh_sub["sub_national_sum"]

    k = SMOOTHING_K
    hh_sub["trade_up_rate_other"] = (
        (hh_sub["other_top_tier_sum"] + k * population_top_tier_rate) / (hh_sub["other_purchases"] + k)
    )
    hh_sub["national_brand_rate_other"] = (
        (hh_sub["other_national_sum"] + k * population_national_rate) / (hh_sub["other_purchases"] + k)
    )

    return df.merge(
        hh_sub[["household_key", "sub_commodity_desc", "trade_up_rate_other", "national_brand_rate_other"]],
        on=["household_key", "sub_commodity_desc"],
        how="left",
    )


def add_leave_transaction_out_same_manufacturer(df):
    manu_counts = (
        df.groupby(["household_key", "sub_commodity_desc", "manufacturer"])
        .size()
        .reset_index(name="manufacturer_count")
    )
    manu_counts["rank"] = manu_counts.groupby(
        ["household_key", "sub_commodity_desc"]
    )["manufacturer_count"].rank(method="first", ascending=False)

    top1 = manu_counts[manu_counts["rank"] == 1][
        ["household_key", "sub_commodity_desc", "manufacturer", "manufacturer_count"]
    ].rename(columns={"manufacturer": "top1_manufacturer", "manufacturer_count": "top1_count"})
    top2 = manu_counts[manu_counts["rank"] == 2][
        ["household_key", "sub_commodity_desc", "manufacturer_count"]
    ].rename(columns={"manufacturer_count": "top2_count"})

    group_stats = top1.merge(top2, on=["household_key", "sub_commodity_desc"], how="left")
    group_stats["top2_count"] = group_stats["top2_count"].fillna(0)

    df = df.merge(manu_counts[["household_key", "sub_commodity_desc", "manufacturer", "manufacturer_count"]],
                  on=["household_key", "sub_commodity_desc", "manufacturer"], how="left")
    df = df.merge(group_stats, on=["household_key", "sub_commodity_desc"], how="left")

    is_top1 = df["manufacturer"] == df["top1_manufacturer"]
    max_of_others = df["top2_count"].where(is_top1, df["top1_count"])
    df["same_manufacturer_as_usual"] = ((df["manufacturer_count"] - 1) >= max_of_others).astype(int)

    return df.drop(columns=["manufacturer_count", "top1_manufacturer", "top1_count", "top2_count"])


def main():
    txn = pd.read_parquet(
        TXN_PATH,
        columns=["household_key", "product_id", "sub_commodity_desc", "manufacturer", "brand",
                 "retail_disc", "coupon_disc"],
    )
    labels = label_products()
    df = txn.merge(labels, on="product_id", how="inner")
    df["is_national"] = (df["brand"] == "National").astype(int)
    df["discount_active"] = ((df["retail_disc"] != 0) | (df["coupon_disc"] != 0)).astype(int)

    population_top_tier_rate = df["top_tier"].mean()
    population_national_rate = df["is_national"].mean()
    print(f"population top_tier rate: {population_top_tier_rate:.3f}")
    print(f"population national-brand rate: {population_national_rate:.3f}")

    df = add_leave_subcommodity_out_rates(df, population_top_tier_rate, population_national_rate)
    df = add_leave_transaction_out_same_manufacturer(df)

    households = pd.read_parquet(HOUSEHOLD_PATH)
    df = df.merge(households, on="household_key", how="left")

    keep_cols = [
        "household_key", "top_tier", "discount_active",
        "trade_up_rate_other", "national_brand_rate_other", "same_manufacturer_as_usual",
        "avg_basket_value", "coupon_redemption_count", "has_demographic", "has_campaign_exposure",
        "income_desc", "household_size_desc",
    ]
    df = df[keep_cols]

    print(f"final training table rows: {len(df)}")
    print(df.describe(include="all").to_string())

    df.to_parquet(OUT_PATH, index=False)
    print(f"saved to {OUT_PATH}")


if __name__ == "__main__":
    main()
