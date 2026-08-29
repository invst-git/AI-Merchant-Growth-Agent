"""Phase 2: pick one representative product per commodity (the best
seller by total quantity), so a cross-sell candidate can name an actual
SKU and price, not just a category.
"""

import pandas as pd

IN_PATH = "data/processed/dunnhumby_baskets.parquet"
OUT_PATH = "models/representative_products.parquet"


def main():
    df = pd.read_parquet(IN_PATH, columns=["product_id", "commodity_desc", "quantity", "loyalty_price"])
    df = df[df["loyalty_price"] > 0]

    sold = df.groupby(["commodity_desc", "product_id"])["quantity"].sum().reset_index()
    top = sold.sort_values("quantity", ascending=False).drop_duplicates("commodity_desc")

    price = df.groupby("product_id")["loyalty_price"].mean().rename("price")
    top = top.merge(price, on="product_id", how="left")
    top = top[["commodity_desc", "product_id", "price"]]

    print(f"commodities with a representative product: {len(top)}")
    top.to_parquet(OUT_PATH, index=False)
    print(f"saved to {OUT_PATH}")


if __name__ == "__main__":
    main()
