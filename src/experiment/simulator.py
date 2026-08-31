"""Phase 5: Control vs Agent, run on the real basket pool from basket_pool.py.

Control: cart -> checkout with no intervention (the base historical basket,
unchanged). Agent: the same base basket run through the real Phase 2
decision engine (engine.decide, no-action included as a first-class
candidate, exactly as already validated in Phase 2/3), then a single
Bernoulli draw against the engine's own real p_accept for whichever
candidate it chose, deciding whether that one offer is actually accepted.

Guardrails carried over from the plan's top-level scope section: no
LLM-simulated shopper, no fabricated abandonment probability. There is no
real, measured basis in this dataset for "does showing an offer cause the
customer to abandon the whole cart", so this simulator does not invent one:
the base transaction always completes in both arms (conversion_rate = 1.0
in both arms, reported as such, not hidden -- see the Phase 5 results doc
for why that is the honest number rather than an oversight, not something
worth pretending otherwise about).
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "src" / "decision_engine"))
import engine  # noqa: E402
from objective import MARGIN_PROXY  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from basket_pool import load_basket_pool  # noqa: E402


def _session_rng(master_seed: int, household_key: int, basket_id: int) -> np.random.Generator:
    # Deterministic, independent-enough per-session stream: every session
    # gets its own draw regardless of iteration order, so results are
    # reproducible and one session's draw never depends on another's.
    seed = (master_seed * 1_000_003 + int(household_key) * 100_003 + int(basket_id)) % (2**32)
    return np.random.default_rng(seed)


def run_control(sessions: pd.DataFrame) -> pd.DataFrame:
    out = sessions.copy()
    out["arm"] = "control"
    out["converted"] = 1
    out["order_value"] = out["base_value"]
    out["items"] = out["base_items"]
    out["attached"] = 0
    out["attach_action"] = None
    out["attach_product_id"] = None
    out["offered_action"] = None
    out["offered_p_accept"] = None
    out["offered_incremental_value"] = 0.0
    out["contribution_margin"] = out["order_value"] * MARGIN_PROXY
    return out


def run_agent(sessions: pd.DataFrame, master_seed: int = 20260829, explain_drivers: bool = False) -> pd.DataFrame:
    rows = []
    for rec in sessions.itertuples(index=False):
        result = engine.decide(rec.household_key, rec.base_product_ids, explain_drivers=explain_drivers)
        chosen = result["chosen_action"]

        row = {
            "household_key": rec.household_key,
            "basket_id": rec.basket_id,
            "base_product_ids": rec.base_product_ids,
            "base_items": rec.base_items,
            "base_value": rec.base_value,
            "arm": "agent",
            "converted": 1,
            "offered_action": chosen["action"],
            "offered_p_accept": chosen["p_accept"],
            "offered_incremental_value": chosen["incremental_value"],
        }

        if chosen["action"] == "no_action":
            row.update(order_value=rec.base_value, items=rec.base_items,
                        attached=0, attach_action=None, attach_product_id=None)
        else:
            rng = _session_rng(master_seed, rec.household_key, rec.basket_id)
            accepted = bool(rng.random() < chosen["p_accept"])
            if accepted:
                row.update(order_value=rec.base_value + chosen["incremental_value"],
                            items=rec.base_items + 1,
                            attached=1, attach_action=chosen["action"],
                            attach_product_id=chosen["product_id"])
            else:
                # offer shown, declined -- base order still completes, exactly
                # as Phase 3's own demo transcript and Phase 4's checkout flow
                # already establish: an unaccepted offer never blocks checkout.
                row.update(order_value=rec.base_value, items=rec.base_items,
                            attached=0, attach_action=None, attach_product_id=None)
        row["contribution_margin"] = row["order_value"] * MARGIN_PROXY
        rows.append(row)
    return pd.DataFrame.from_records(rows)


def draw_two_arms(pool: pd.DataFrame, n_per_arm: int, master_seed: int = 20260829):
    """Two independent, non-overlapping random samples from the same real
    basket pool -- the plan's "two matched populations... drawn from that
    same underlying distribution", read as independent-groups sampling
    (the standard design a two-sample test like Mann-Whitney assumes),
    not literal pairing of the same basket into both arms."""
    if 2 * n_per_arm > len(pool):
        raise ValueError(
            f"pool has {len(pool)} sessions, need {2 * n_per_arm} for two non-overlapping arms of {n_per_arm}"
        )
    idx = np.random.default_rng(master_seed).permutation(len(pool))
    control_idx = idx[:n_per_arm]
    agent_idx = idx[n_per_arm:2 * n_per_arm]
    return pool.iloc[control_idx].reset_index(drop=True), pool.iloc[agent_idx].reset_index(drop=True)


if __name__ == "__main__":
    pool = load_basket_pool()
    control_sample, agent_sample = draw_two_arms(pool, n_per_arm=500)
    control_out = run_control(control_sample)
    agent_out = run_agent(agent_sample)
    print("control mean order_value:", control_out["order_value"].mean())
    print("agent   mean order_value:", agent_out["order_value"].mean())
    print("agent attach rate:", agent_out["attached"].mean())
    print("agent action mix:\n", agent_out["offered_action"].value_counts())
