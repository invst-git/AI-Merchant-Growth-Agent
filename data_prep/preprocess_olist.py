import pandas as pd

RAW_DIR = "data/raw/olist"
OUT_PATH = "data/processed/olist_baskets.parquet"


def load_csv(name):
    return pd.read_csv(f"{RAW_DIR}/{name}.csv")


def main():
    orders = load_csv("olist_orders_dataset")
    items = load_csv("olist_order_items_dataset")
    payments = load_csv("olist_order_payments_dataset")
    products = load_csv("olist_products_dataset")
    sellers = load_csv("olist_sellers_dataset")
    reviews = load_csv("olist_order_reviews_dataset")

    df = items.merge(orders, on="order_id", how="left")
    df = df.merge(products, on="product_id", how="left")
    df = df.merge(sellers, on="seller_id", how="left")

    payments_agg = payments.groupby("order_id").agg(
        payment_type=("payment_type", "first"),
        installments=("payment_installments", "max"),
        payment_value=("payment_value", "sum"),
    ).reset_index()
    df = df.merge(payments_agg, on="order_id", how="left")

    reviews_agg = reviews.groupby("order_id").agg(review_score=("review_score", "mean")).reset_index()
    df = df.merge(reviews_agg, on="order_id", how="left")

    print(f"rows: {len(df)}")
    print(f"unique orders (baskets): {df['order_id'].nunique()}")
    print(f"unique sellers: {df['seller_id'].nunique()}")
    print(f"unique products: {df['product_id'].nunique()}")

    df.to_parquet(OUT_PATH, index=False)
    print(f"saved to {OUT_PATH}")


if __name__ == "__main__":
    main()
