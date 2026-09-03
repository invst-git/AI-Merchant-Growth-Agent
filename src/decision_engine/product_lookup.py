"""Phase 2: one row per real product, the master price and category
table every other module reads (src/catalogue/catalogue.py, engine.py,
household_brand_stats.py, upsell_training_data.py, the dashboard).

Rows with no positive observed price are dropped here, since a product
that never sold at a real price can't be shown or priced later. Each
product_id keeps one commodity_desc/sub_commodity_desc (dunnhumby
assigns these from its product master table, so every transaction row
for a given product already agrees; "first" is exact here, not a
tie-break), and price is the product's mean observed loyalty_price.
"""

import pandas as pd

IN_PATH = "data/processed/dunnhumby_baskets.parquet"
OUT_PATH = "models/product_lookup.parquet"


def main():
    df = pd.read_parquet(
        IN_PATH,
        columns=["product_id", "commodity_desc", "sub_commodity_desc", "loyalty_price"],
    )
    df = df[df["loyalty_price"] > 0]

    lookup = df.groupby("product_id").agg(
        commodity_desc=("commodity_desc", "first"),
        sub_commodity_desc=("sub_commodity_desc", "first"),
        price=("loyalty_price", "mean"),
    ).reset_index()

    print(f"products with a positive observed price: {len(lookup)}")
    lookup.to_parquet(OUT_PATH, index=False)
    print(f"saved to {OUT_PATH}")


if __name__ == "__main__":
    main()
