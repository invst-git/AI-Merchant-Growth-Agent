"""Phase 2: offline sanity check. Runs the engine on a sample of real
held-out baskets and reports the decision mix and a few examples.
"""

import pandas as pd

from engine import decide

TXN_PATH = "data/processed/dunnhumby_baskets.parquet"
SAMPLE_SIZE = 500
SEED = 7


def main():
    df = pd.read_parquet(TXN_PATH, columns=["basket_id", "household_key", "product_id"])

    basket_ids = df["basket_id"].drop_duplicates().sample(n=SAMPLE_SIZE, random_state=SEED)
    sample_txn = df[df["basket_id"].isin(basket_ids)]
    baskets = sample_txn.groupby(["basket_id", "household_key"])["product_id"].apply(list).reset_index()

    counts = {"cross_sell": 0, "upsell": 0, "no_action": 0}
    examples = []

    for _, row in baskets.iterrows():
        result = decide(row["household_key"], row["product_id"])
        action = result["chosen_action"]["action"]
        counts[action] += 1
        if len(examples) < 6 and action != "no_action":
            examples.append((row["household_key"], row["basket_id"], result["chosen_action"]))

    print(f"sample size: {len(baskets)}")
    for action, n in counts.items():
        print(f"{action}: {n} ({n / len(baskets):.1%})")

    print("\nexample decisions:")
    for hh, basket_id, chosen in examples:
        print(f"household {hh}, basket {basket_id}: {chosen['action']}, "
              f"expected_value={chosen['expected_value']:.3f}")
        print(f"  reason: {chosen['reason']}")


if __name__ == "__main__":
    main()
