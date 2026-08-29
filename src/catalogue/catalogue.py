"""Phase 3: the agent-readable catalogue.

dunnhumby has no product name or brand-name field, only a category
hierarchy (commodity_desc, sub_commodity_desc) and a numeric
manufacturer id. The catalogue is honest about that: "category" and
"subcategory" are the closest thing to a product name, manufacturer is
just an id, not a brand string.

A small number of rows are dropped before building the catalogue:
unclassified rows (NO COMMODITY/SUBCOMMODITY DESCRIPTION), and
pseudo-categories that are not real purchasable products (FUEL, coupon
bookkeeping rows, bottle deposits, a corp-use-only row). Verified this
against the real category list before excluding anything, not assumed
from the field names alone: 637 of 91,994 rows (0.7%), the rest include
plenty of oddly-named but real categories (e.g. "SEAFOOD - MISC") that
were deliberately kept.

availability is not tracked in this dataset, every catalogue entry says
"in_stock" and is labeled as an assumption, not measured data.

current_offers is deliberately NOT a static per-product field. The
actual offer depends on a specific household's history (Phase 2's
decision engine), so baking a number into the catalogue would be
fabricated. The catalogue instead points to declared_complements (from
affinity_rules) and declared_alternative (from upsell_tiers, if this
product has one) as the static possibility space, and says explicitly
that the real offer is computed per-request by get_growth_decision.
"""

import pandas as pd

PRODUCT_LOOKUP_PATH = "models/product_lookup.parquet"
REPRESENTATIVE_PATH = "models/representative_products.parquet"
RULES_PATH = "models/affinity_rules.parquet"
TIERS_PATH = "models/upsell_tiers.parquet"

EXCLUDED_COMMODITIES = {
    "NO COMMODITY DESCRIPTION", "FUEL", "COUPON/MISC ITEMS",
    "COUPONS/STORE & MFG", "COUPON", "BOTTLE DEPOSITS",
    "MISCELLANEOUS(CORP USE ONLY)",
}
MIN_PRICE = 0.05
MAX_COMPLEMENTS = 3


def _load_catalogue():
    pl = pd.read_parquet(PRODUCT_LOOKUP_PATH)
    pl = pl[
        ~pl["commodity_desc"].isin(EXCLUDED_COMMODITIES)
        & (pl["sub_commodity_desc"] != "NO SUBCOMMODITY DESCRIPTION")
        & (pl["price"] > MIN_PRICE)
    ]
    return pl.set_index("product_id")


PRODUCTS = _load_catalogue()
RULES = pd.read_parquet(RULES_PATH)
TIERS = pd.read_parquet(TIERS_PATH).set_index("product_id")

_COMPLEMENTS_BY_COMMODITY = {
    antecedent: group.sort_values("lift", ascending=False)["consequent"].head(MAX_COMPLEMENTS).tolist()
    for antecedent, group in RULES.groupby("antecedent")
}


def _match_score(query_tokens, text):
    text_tokens = set(text.lower().split())
    if not query_tokens:
        return 0
    return len(query_tokens & text_tokens) + (1 if any(t in text.lower() for t in query_tokens) else 0)


def build_entry(product_id):
    if product_id not in PRODUCTS.index:
        return None
    row = PRODUCTS.loc[product_id]
    tier = TIERS.loc[product_id] if product_id in TIERS.index else None
    declared_alternative = None
    if tier is not None:
        declared_alternative = {
            "upsell_product_id": int(tier["upsell_product_id"]),
            "price": float(tier["upsell_price"]),
            "same_manufacturer": bool(tier["same_manufacturer"]),
        }
    return {
        "product_id": int(product_id),
        "category": row["commodity_desc"],
        "subcategory": row["sub_commodity_desc"],
        "price": float(row["price"]),
        "availability": "in_stock",  # not tracked in this dataset, assumed
        "declared_complements": _COMPLEMENTS_BY_COMMODITY.get(row["commodity_desc"], []),
        "declared_alternative": declared_alternative,
        "current_offers": "computed per request, see get_growth_decision",
        "checkout_capability": True,
    }


def search(query, max_results=5):
    query_tokens = set(query.lower().split())
    scored = []
    for pid, row in PRODUCTS.iterrows():
        score = _match_score(query_tokens, f"{row['commodity_desc']} {row['sub_commodity_desc']}")
        if score > 0:
            scored.append((score, row["price"], pid))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [build_entry(pid) for _, _, pid in scored[:max_results]]
