"""SUPERSEDED, not used. Background jobs (nohup ... &) do not survive
between shell calls in this environment, so this script never actually ran
to completion; see run_pilot_chunk.py for the chunked replacement that
produced the real Phase 5 pilot data.
"""
"""Phase 5 pilot run: a real, independent-arms Control-vs-Agent replay large
enough to (a) get a stable empirical order_value distribution per arm to
drive the sample-size power simulation (see power_analysis.py) and (b) get a
second, larger real timing sample for engine.decide(explain_drivers=False).

This pilot's own p-value/CI is NOT the reported experimental result -- it is
design input only, discarded after sample size is chosen. The confirmatory
run uses a freshly drawn sample at the size this pilot justifies.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from basket_pool import load_basket_pool
from simulator import draw_two_arms, run_control, run_agent

N_PER_ARM = 4000
MASTER_SEED = 20260829

if __name__ == "__main__":
    t_start = time.time()
    pool = load_basket_pool()
    print(f"[{time.time()-t_start:.1f}s] pool loaded: {len(pool)} real baskets", flush=True)

    control_sample, agent_sample = draw_two_arms(pool, n_per_arm=N_PER_ARM, master_seed=MASTER_SEED)
    control_out = run_control(control_sample)
    print(f"[{time.time()-t_start:.1f}s] control arm done: {len(control_out)} sessions", flush=True)

    t_agent0 = time.time()
    agent_out = run_agent(agent_sample, master_seed=MASTER_SEED, explain_drivers=False)
    agent_elapsed = time.time() - t_agent0
    print(f"[{time.time()-t_start:.1f}s] agent arm done: {len(agent_out)} sessions "
          f"({agent_elapsed:.1f}s total, {1000*agent_elapsed/len(agent_out):.2f}ms/decision)", flush=True)

    out_dir = Path(__file__).resolve().parent.parent.parent / "data" / "experiment"
    out_dir.mkdir(parents=True, exist_ok=True)
    control_out.drop(columns=["base_product_ids"]).to_parquet(out_dir / "pilot_control.parquet")
    agent_out.drop(columns=["base_product_ids"]).to_parquet(out_dir / "pilot_agent.parquet")

    print("\n=== PILOT SUMMARY ===")
    print("control order_value: mean=%.3f std=%.3f n=%d" % (
        control_out["order_value"].mean(), control_out["order_value"].std(), len(control_out)))
    print("agent   order_value: mean=%.3f std=%.3f n=%d" % (
        agent_out["order_value"].mean(), agent_out["order_value"].std(), len(agent_out)))
    print("agent attach rate: %.4f" % agent_out["attached"].mean())
    print("agent action mix:\n", agent_out["offered_action"].value_counts())
    print(f"\nTOTAL WALL TIME: {time.time()-t_start:.1f}s")
    print("DONE", flush=True)
