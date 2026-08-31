"""Phase 5 uplift/Qini support: for the no_action-labeled sessions in the
final agent pool, find the best non-no_action candidate the engine actually
evaluated (even though it scored below the no-action baseline) and its real
p_accept/incremental_value. This is the only extra data needed to build the
"offer to everyone" baseline -- for every other session the engine's chosen
action already IS what "offer to everyone" would show, since it cleared the
no-action bar on its own.
Usage: python3 best_alternative_chunk.py <start> <end>
"""
import sys
import time
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "src" / "decision_engine"))
import engine  # noqa: E402

if __name__ == "__main__":
    start, end = int(sys.argv[1]), int(sys.argv[2])
    out_dir = _ROOT / "data" / "experiment"
    out_path = out_dir / f"best_alt_chunk_{start:05d}_{end:05d}.parquet"
    if out_path.exists():
        print(f"chunk {start}:{end} already done, skipping")
        sys.exit(0)

    no_action_sessions = pd.read_parquet(out_dir / "no_action_sessions.parquet")
    pool = pd.read_parquet(out_dir / "basket_pool_cache.parquet")
    sessions = no_action_sessions.merge(pool, on=["household_key", "basket_id"], how="left")
    slice_ = sessions.iloc[start:end].reset_index(drop=True)

    t0 = time.time()
    rows = []
    for rec in slice_.itertuples(index=False):
        candidates = engine.cross_sell_candidates(rec.household_key, list(rec.base_product_ids), explain_drivers=False)
        candidates += engine.upsell_candidates(rec.household_key, list(rec.base_product_ids), explain_drivers=False)
        if candidates:
            best = max(candidates, key=lambda c: c["expected_value"])
            rows.append({
                "household_key": rec.household_key, "basket_id": rec.basket_id,
                "has_alternative": True, "alt_action": best["action"],
                "alt_p_accept": best["p_accept"], "alt_incremental_value": best["incremental_value"],
                "alt_expected_value": best["expected_value"], "alt_product_id": best["product_id"],
            })
        else:
            rows.append({
                "household_key": rec.household_key, "basket_id": rec.basket_id,
                "has_alternative": False, "alt_action": None,
                "alt_p_accept": None, "alt_incremental_value": 0.0,
                "alt_expected_value": None, "alt_product_id": None,
            })
    out = pd.DataFrame.from_records(rows)
    out.to_parquet(out_path)
    print(f"[{time.time()-t0:.1f}s] wrote {out_path.name}, {len(out)} rows, "
          f"{out['has_alternative'].sum()} had a real (sub-threshold) candidate", flush=True)
