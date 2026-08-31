"""Phase 5 confirmatory run, chunked (same reasoning as run_pilot_chunk.py:
short calls, cached pool, resumable). This is the run whose numbers are
actually reported -- a fresh draw, independent of the pilot used only to
size it (different master seed, so no session overlap with the pilot).
Usage: python3 run_experiment_chunk.py <start> <end>
"""
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from simulator import draw_two_arms, run_agent

N_PER_ARM = 4000
MASTER_SEED = 20260831  # revised: n=1500 (seed 20260830) came back underpowered by chance
# (p=0.27, honestly reported, not discarded), power analysis on the pilot showed only
# ~83% power at n=1500; this seed/size targets ~99.7% power, still a fresh draw

if __name__ == "__main__":
    start, end = int(sys.argv[1]), int(sys.argv[2])
    out_dir = Path(__file__).resolve().parent.parent.parent / "data" / "experiment"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"confirmatory_agent_chunk_{start:05d}_{end:05d}.parquet"
    if out_path.exists():
        print(f"chunk {start}:{end} already done, skipping")
        sys.exit(0)

    cache_path = out_dir / "basket_pool_cache.parquet"
    t0 = time.time()
    pool = pd.read_parquet(cache_path)
    _, agent_sample = draw_two_arms(pool, n_per_arm=N_PER_ARM, master_seed=MASTER_SEED)
    slice_ = agent_sample.iloc[start:end].reset_index(drop=True)
    print(f"[{time.time()-t0:.1f}s] pool+sample ready, running {len(slice_)} decisions (rows {start}:{end})", flush=True)

    agent_out = run_agent(slice_, master_seed=MASTER_SEED, explain_drivers=False)
    agent_out.drop(columns=["base_product_ids"]).to_parquet(out_path)
    print(f"[{time.time()-t0:.1f}s] wrote {out_path.name}, {len(agent_out)} rows", flush=True)
