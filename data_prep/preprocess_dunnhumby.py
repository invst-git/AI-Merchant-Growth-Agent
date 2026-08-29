import pandas as pd

RAW_DIR = "data/raw/dunnhumby"
OUT_PATH = "data/processed/dunnhumby_baskets.parquet"


def load_csv(name):
    df = pd.read_csv(f"{RAW_DIR}/{name}.csv")
    df.columns = [c.strip().lower() for c in df.columns]
    return df


def compute_loyalty_price(txn):
    txn = txn.copy()
    txn["retail_disc"] = txn["retail_disc"].fillna(0)
    txn["coupon_match_disc"] = txn["coupon_match_disc"].fillna(0)
    txn["loyalty_price"] = (
        txn["sales_value"] - (txn["retail_disc"] + txn["coupon_match_disc"])
    ) / txn["quantity"].replace(0, pd.NA)
    return txn


def main():
    txn = load_csv("transaction_data")
    product = load_csv("product")

    txn = compute_loyalty_price(txn)

    cat_cols = ["product_id", "department", "commodity_desc", "sub_commodity_desc", "brand", "manufacturer"]
    baskets = txn.merge(product[cat_cols], on="product_id", how="left")

    print(f"transaction rows: {len(txn)}")
    print(f"unique baskets: {baskets['basket_id'].nunique()}")
    print(f"unique households: {baskets['household_key'].nunique()}")
    print(f"unique products: {baskets['product_id'].nunique()}")

    baskets.to_parquet(OUT_PATH, index=False)
    print(f"saved to {OUT_PATH}")


if __name__ == "__main__":
    main()
