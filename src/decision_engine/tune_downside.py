"""Tune expected_downside. Candidate generation and P(accept) do not
depend on expected_downside, only the final no-action cutoff does, so
every candidate is scored once and the downside sweep is just cheap
comparisons against each basket's best raw margin.
"""

import pandas as pd

from engine import cross_sell_candidates, upsell_candidates
from objective import MARGIN_PROXY

TXN_PATH = "data/processed/dunnhumby_baskets.parquet"
SAMPLE_SIZE = 500
SEED = 7
SWEEP = [0.05, 0.10, 0.20, 0.30, 0.40, 0.50, 0.75, 1.00, 1.50]


def raw_margin(candidate):
    return candidate["p_accept"] * candidate["incremental_value"] * MARGIN_PROXY


def best_candidate(household_key, basket_product_ids):
    candidates = cross_sell_candidates(household_key, basket_product_ids)
    candidates += upsell_candidates(household_key, basket_product_ids)
    if not candidates:
        return None
    return max(candidates, key=raw_margin)


def main():
    df = pd.read_parquet(TXN_PATH, columns=["basket_id", "household_key", "product_id"])
    basket_ids = df["basket_id"].drop_duplicates().sample(n=SAMPLE_SIZE, random_state=SEED)
    sample_txn = df[df["basket_id"].isin(basket_ids)]
    baskets = sample_txn.groupby(["basket_id", "household_key"])["product_id"].apply(list).reset_index()

    results = []
    for _, row in baskets.iterrows():
        best = best_candidate(row["household_key"], row["product_id"])
        results.append({
            "basket_id": row["basket_id"],
            "best_action": best["action"] if best else "none",
            "best_raw_margin": raw_margin(best) if best else 0.0,
        })
    results = pd.DataFrame(results)

    print("best raw margin percentiles (across all baskets' best candidate):")
    print(results["best_raw_margin"].describe(percentiles=[0.1, 0.25, 0.4, 0.5, 0.6, 0.75, 0.9]).to_string())

    print("\ndownside sweep:")
    for downside in SWEEP:
        no_action = (results["best_raw_margin"] <= downside).sum()
        cross_sell = ((results["best_raw_margin"] > downside) & (results["best_action"] == "cross_sell")).sum()
        upsell = ((results["best_raw_margin"] > downside) & (results["best_action"] == "upsell")).sum()
        n = len(results)
        print(f"downside={downside:.2f}: no_action {no_action/n:.1%}, "
              f"cross_sell {cross_sell/n:.1%}, upsell {upsell/n:.1%}")


if __name__ == "__main__":
    main()
