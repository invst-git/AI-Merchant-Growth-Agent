"""Phase 2: build upsell targets. For each product, find the closest
pricier product in the same sub_commodity_desc, within a plausible
price band (1.15x to 3x).

manufacturer-aware: dunnhumby's brand field is only National/Private
(a binary flag, not a specific brand name), so it cannot tell us if two
products are "the same brand". manufacturer has 6,476 distinct values
(median 4 per sub_commodity, verified before writing this) and is the
field that actually identifies a specific maker. A same-manufacturer
upgrade is offered first (a size/tier step within a brand the shopper
already has in their cart); only falls back to a different manufacturer
if no same-manufacturer option exists in the price band.
"""

import pandas as pd

IN_PATH = "data/processed/dunnhumby_baskets.parquet"
OUT_PATH = "models/upsell_tiers.parquet"

MIN_RATIO = 1.15
MAX_RATIO = 3.0


def product_price_table(df):
    valid = df[df["loyalty_price"] > 0]
    prices = valid.groupby("product_id").agg(
        price=("loyalty_price", "mean"),
        sub_commodity_desc=("sub_commodity_desc", "first"),
        commodity_desc=("commodity_desc", "first"),
        manufacturer=("manufacturer", "first"),
    ).reset_index()
    return prices


def closest_in_band(i, products, price_vals, manufacturers, same_manufacturer_only):
    price = price_vals[i]
    for j in range(i + 1, len(products)):
        ratio = price_vals[j] / price
        if ratio > MAX_RATIO:
            break
        if ratio < MIN_RATIO:
            continue
        if same_manufacturer_only and manufacturers[j] != manufacturers[i]:
            continue
        return j
    return None


def build_tiers(prices):
    rows = []
    for _, group in prices.groupby("sub_commodity_desc"):
        group = group.sort_values("price")
        products = group["product_id"].to_numpy()
        price_vals = group["price"].to_numpy()
        manufacturers = group["manufacturer"].to_numpy()

        for i, pid in enumerate(products):
            j = closest_in_band(i, products, price_vals, manufacturers, same_manufacturer_only=True)
            same_manufacturer = j is not None
            if j is None:
                j = closest_in_band(i, products, price_vals, manufacturers, same_manufacturer_only=False)
            if j is None:
                continue
            rows.append({
                "product_id": pid,
                "price": price_vals[i],
                "manufacturer": manufacturers[i],
                "sub_commodity_desc": group["sub_commodity_desc"].iloc[0],
                "upsell_product_id": products[j],
                "upsell_price": price_vals[j],
                "upsell_manufacturer": manufacturers[j],
                "price_delta": price_vals[j] - price_vals[i],
                "same_manufacturer": same_manufacturer,
            })
    return pd.DataFrame(rows)


def main():
    df = pd.read_parquet(
        IN_PATH,
        columns=["product_id", "loyalty_price", "sub_commodity_desc", "commodity_desc", "manufacturer"],
    )
    prices = product_price_table(df)
    print(f"products with valid price: {len(prices)}")

    tiers = build_tiers(prices)
    print(f"products with an upsell target: {len(tiers)}")
    print(f"same-manufacturer upgrades: {tiers['same_manufacturer'].mean():.1%}")
    print(tiers.head(5).to_string(index=False))

    tiers.to_parquet(OUT_PATH, index=False)
    print(f"saved to {OUT_PATH}")


if __name__ == "__main__":
    main()
