"""Phase 5: the real historical basket pool the Control-vs-Agent experiment
replays.

Per the plan's own wording, the simulator does not invent customers or
purchase behavior. It replays real dunnhumby households and real dunnhumby
baskets, priced from the same product_lookup table engine.py and
catalogue.py already use, so a basket's value here means exactly what it
means everywhere else in this codebase. No LLM-simulated shopper, no
synthetic basket, no fabricated price.

Each "session" is one real (household_key, basket_id) pair: the household
supplies the price-sensitivity/purchase-frequency/category-preference signal
(via engine.py's real household_features/household_brand_stats tables, used
exactly as Phase 2's decision engine already uses them) and the basket
supplies the "historical basket" the plan calls for. Nothing here is drawn
from an assumed distribution; every field is a real observed value.
"""

import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "src" / "decision_engine"))
import engine  # noqa: E402  (reuses the exact PRODUCT_LOOKUP engine.decide() itself uses)

BASKETS_PATH = _ROOT / "data" / "processed" / "dunnhumby_baskets.parquet"


def load_basket_pool() -> pd.DataFrame:
    """Every real (household_key, basket_id) with at least one catalogue-
    priced product, its distinct valid product_id list, and its base
    basket value (sum of engine.PRODUCT_LOOKUP prices for those ids,
    unit-per-product-id -- matching how basket_product_ids is used
    everywhere else in this codebase: engine.py and checkout.py both
    treat a basket as a list of distinct product ids, never quantities).

    0.33% of real basket line-rows reference a product_id absent from
    product_lookup.parquet (measured directly, not assumed -- see the
    Phase 5 design note in project memory). Those individual line items
    are dropped, matching catalogue.py's own documented policy of only
    recognizing catalogue-priced products as real purchasable items;
    a basket is dropped entirely only if nothing priceable remains.
    """
    raw = pd.read_parquet(BASKETS_PATH, columns=["household_key", "basket_id", "product_id"])
    grouped = raw.groupby(["household_key", "basket_id"])["product_id"].apply(lambda s: sorted(set(s)))

    valid_index = engine.PRODUCT_LOOKUP.index
    price = engine.PRODUCT_LOOKUP["price"]

    records = []
    for (household_key, basket_id), product_ids in grouped.items():
        valid_ids = [p for p in product_ids if p in valid_index]
        if not valid_ids:
            continue
        base_value = float(price.loc[valid_ids].sum())
        records.append({
            "household_key": household_key,
            "basket_id": basket_id,
            "base_product_ids": valid_ids,
            "base_items": len(valid_ids),
            "base_value": base_value,
        })
    return pd.DataFrame.from_records(records)


if __name__ == "__main__":
    pool = load_basket_pool()
    print(f"basket pool: {len(pool)} real sessions")
    print(pool["base_value"].describe())
    print(pool["base_items"].describe())
