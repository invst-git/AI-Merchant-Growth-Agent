"""Phase 2: household-level brand and tier statistics, for engine
inference (not training, see upsell_training_data.py for the leave-out
versions used there to avoid label circularity).

At inference time there is no label being derived, so using each
household's full real history is correct and gives the most signal,
unlike training, where a feature built from the same event being
labeled would leak.
"""

import pandas as pd

IN_PATH = "data/processed/dunnhumby_baskets.parquet"
PRODUCT_LOOKUP_PATH = "models/product_lookup.parquet"
OUT_HOUSEHOLD_STATS = "models/household_brand_stats.parquet"
OUT_HOUSEHOLD_SUBCOMMODITY_MANUFACTURER = "models/household_subcommodity_manufacturer.parquet"

MIN_PRODUCTS_PER_SUBCOMMODITY = 5


def label_products():
    products = pd.read_parquet(PRODUCT_LOOKUP_PATH)
    sub_stats = products.groupby("sub_commodity_desc")["price"].agg(["median", "std", "count"]).reset_index()
    sub_stats = sub_stats[(sub_stats["count"] >= MIN_PRODUCTS_PER_SUBCOMMODITY) & (sub_stats["std"] > 0)]
    products = products.merge(sub_stats[["sub_commodity_desc", "median"]], on="sub_commodity_desc", how="inner")
    products["top_tier"] = (products["price"] > products["median"]).astype(int)
    return products[["product_id", "top_tier"]]


def main():
    txn = pd.read_parquet(
        IN_PATH,
        columns=["household_key", "product_id", "brand", "manufacturer", "sub_commodity_desc"],
    )
    labels = label_products()
    df = txn.merge(labels, on="product_id", how="inner")
    df["is_national"] = (df["brand"] == "National").astype(int)

    household_stats = df.groupby("household_key").agg(
        top_tier_rate=("top_tier", "mean"),
        national_brand_rate=("is_national", "mean"),
        n_purchases=("product_id", "count"),
    ).reset_index()
    household_stats.to_parquet(OUT_HOUSEHOLD_STATS, index=False)
    print(f"household_stats rows: {len(household_stats)}")
    print(household_stats.head(3).to_string(index=False))

    dominant = (
        df.groupby(["household_key", "sub_commodity_desc", "manufacturer"])
        .size()
        .reset_index(name="count")
        .sort_values("count", ascending=False)
        .drop_duplicates(["household_key", "sub_commodity_desc"])
        [["household_key", "sub_commodity_desc", "manufacturer"]]
        .rename(columns={"manufacturer": "dominant_manufacturer"})
    )
    dominant.to_parquet(OUT_HOUSEHOLD_SUBCOMMODITY_MANUFACTURER, index=False)
    print(f"household_subcommodity_manufacturer rows: {len(dominant)}")


if __name__ == "__main__":
    main()
