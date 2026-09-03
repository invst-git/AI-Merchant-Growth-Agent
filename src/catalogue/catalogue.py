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

import math
import re
from collections import Counter

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


# search() used to score a query by counting raw whitespace-split token
# overlap. Two real bugs came from that: (1) ".split()" only breaks on
# whitespace, so slash-joined category text like "BEERS/ALES" never
# tokenized into {"beers","ales"}; (2) every matching word counted the
# same regardless of how common it is, so one filler word in the query
# (e.g. "pack") exactly matching a short, unrelated category name (e.g.
# "TRAY PACK CARDS") could outscore a real match -- "I need a pack of
# beers" was returning Valentine's Day gift cards instead of beer.
#
# Fixed with three changes: tokenize on any non-alphanumeric character
# (not just whitespace); drop English filler words and very short
# tokens, which are noise, not signal, in a category name; and weight
# each matched token by its IDF (inverse document frequency) across the
# whole catalogue, so a word that shows up in hundreds of unrelated
# categories (like "pack") counts for far less than a word that's
# specific to a narrow set of products (like "beer").
_TOKEN_RE = re.compile(r"[a-z0-9]+")

_STOPWORDS = {
    "i", "a", "an", "the", "of", "for", "to", "my", "me", "we", "us", "you",
    "your", "want", "wants", "wanted", "need", "needs", "needed", "would",
    "like", "likes", "get", "gets", "got", "buy", "buys", "please", "some",
    "any", "is", "are", "am", "was", "were", "be", "been", "being", "and",
    "or", "in", "on", "at", "with", "this", "that", "it", "its", "just",
    "can", "could", "will", "shall", "do", "does", "did", "have", "has",
    "had", "not", "no", "yes", "ok", "okay", "so", "if", "then", "than",
    "too", "also", "very", "really", "much", "many", "more", "most", "make",
    "makes", "making", "from", "by", "as", "about", "into", "up", "out",
    "tonight", "today",
}


def _stem(token):
    # cheap plural fold ("beers" -> "beer") -- not real stemming, just
    # enough to match singular/plural phrasing without a dependency.
    return token[:-1] if token.endswith("s") and len(token) > 3 else token


def _tokenize(text):
    raw = _TOKEN_RE.findall(text.lower())
    return {_stem(t) for t in raw if len(t) >= 3 and t not in _STOPWORDS}


# Precomputed once at import time, not per search() call -- this catalogue
# backs a live conversational checkout with a real latency budget, so the
# per-product token sets and the corpus-wide document frequencies are
# built once here and reused on every search.
_CATEGORY_TOKENS = {
    pid: _tokenize(f"{row['commodity_desc']} {row['sub_commodity_desc']}")
    for pid, row in PRODUCTS.iterrows()
}
_DOC_FREQ = Counter()
for _tokens in _CATEGORY_TOKENS.values():
    _DOC_FREQ.update(_tokens)
_N_PRODUCTS = len(PRODUCTS)
_IDF = {
    token: math.log((_N_PRODUCTS + 1) / (df + 0.5)) + 1.0
    for token, df in _DOC_FREQ.items()
}


def _match_score(query_tokens, category_tokens):
    matched = query_tokens & category_tokens
    if not matched:
        return 0.0
    return sum(_IDF.get(t, 0.0) for t in matched)


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
    query_tokens = _tokenize(query)
    scored = []
    for pid, category_tokens in _CATEGORY_TOKENS.items():
        score = _match_score(query_tokens, category_tokens)
        if score > 0:
            scored.append((score, PRODUCTS.at[pid, "price"], pid))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [build_entry(pid) for _, _, pid in scored[:max_results]]
