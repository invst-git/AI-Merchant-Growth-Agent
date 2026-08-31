"""Phase 5 pilot, chunked: runs a slice of the deterministic n=4000/arm agent
sample and writes it to its own parquet file, so the pilot can be built up
across several short calls instead of one long-running background process
(this environment does not keep background jobs alive between shell calls,
and this connection caps a single call around 120s).
Usage: python3 run_pilot_chunk.py <start> <end>
"""
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from simulator import draw_two_arms, run_agent

N_PER_ARM = 4000
MASTER_SEED = 20260829

if __name__ == "__main__":
    start, end = int(sys.argv[1]), int(sys.argv[2])
    out_dir = Path(__file__).resolve().parent.parent.parent / "data" / "experiment"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"pilot_agent_chunk_{start:05d}_{end:05d}.parquet"
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
