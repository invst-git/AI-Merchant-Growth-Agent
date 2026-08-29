"""Phase 2: mine cross-sell affinity rules at the commodity level.

commodity_desc (308 categories) is used instead of raw product_id
(92k+ SKUs) or sub_commodity_desc (2383). It keeps the basket x item
matrix tractable and the resulting rules interpretable for the audit
trail. sub_commodity_desc + price is used separately for upsell tiers.

max_len=2 in apriori since only pairwise antecedent -> consequent rules
are used downstream. fpgrowth with no max_len was too slow at this scale.
"""

import pandas as pd
from mlxtend.frequent_patterns import apriori, association_rules

IN_PATH = "data/processed/dunnhumby_baskets.parquet"
OUT_PATH = "models/affinity_rules.parquet"

MIN_SUPPORT = 0.01
MIN_LIFT = 1.5


def build_onehot(df):
    ct = pd.crosstab(df["basket_id"], df["commodity_desc"])
    return ct.astype(bool)


def main():
    df = pd.read_parquet(IN_PATH, columns=["basket_id", "commodity_desc"])
    onehot = build_onehot(df)
    print(f"baskets: {onehot.shape[0]}, commodities: {onehot.shape[1]}")

    frequent = apriori(onehot, min_support=MIN_SUPPORT, use_colnames=True, max_len=2, low_memory=True)
    print(f"frequent itemsets: {len(frequent)}")

    rules = association_rules(frequent, metric="lift", min_threshold=MIN_LIFT)
    rules = rules[rules["antecedents"].apply(len) == 1]
    rules = rules[rules["consequents"].apply(len) == 1]
    rules["antecedent"] = rules["antecedents"].apply(lambda s: next(iter(s)))
    rules["consequent"] = rules["consequents"].apply(lambda s: next(iter(s)))
    rules = rules[["antecedent", "consequent", "support", "confidence", "lift"]]
    rules = rules.sort_values("lift", ascending=False).reset_index(drop=True)

    print(f"rules with lift >= {MIN_LIFT}: {len(rules)}")
    print(rules.head(10).to_string(index=False))

    rules.to_parquet(OUT_PATH, index=False)
    print(f"saved to {OUT_PATH}")


if __name__ == "__main__":
    main()
