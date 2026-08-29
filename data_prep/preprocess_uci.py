import pandas as pd

SHEET_FILES = ["data/raw/uci/sheet1.parquet", "data/raw/uci/sheet2.parquet"]
OUT_PATH = "data/processed/uci_baskets.parquet"


def load_raw():
    df = pd.concat([pd.read_parquet(f) for f in SHEET_FILES], ignore_index=True)
    df.columns = [c.strip().replace(" ", "_") for c in df.columns]
    return df


def clean(df):
    df = df.copy()
    is_cancellation = df["Invoice"].str.startswith("C")
    df = df[~is_cancellation]
    df = df.dropna(subset=["Customer_ID", "Description"])
    df = df[(df["Quantity"] > 0) & (df["Price"] > 0)]
    df["Customer_ID"] = df["Customer_ID"].astype(int)
    df["line_value"] = df["Quantity"] * df["Price"]
    return df


def main():
    df = load_raw()
    before = len(df)
    df = clean(df)
    print(f"rows before clean: {before}, after clean: {len(df)}, dropped: {before - len(df)}")
    print(f"unique invoices (baskets): {df['Invoice'].nunique()}")
    print(f"unique customers: {df['Customer_ID'].nunique()}")
    print(f"unique products: {df['StockCode'].nunique()}")
    df.to_parquet(OUT_PATH, index=False)
    print(f"saved to {OUT_PATH}")


if __name__ == "__main__":
    main()
