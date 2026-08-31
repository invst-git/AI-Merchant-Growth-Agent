"""Phase 5: the statistics the plan calls for, run once on the final
confirmatory dataset (data/experiment/final_control.parquet,
data/experiment/final_agent.parquet, plus the no_action alternative-candidate
data needed for the offer-to-everyone/random-targeting comparison).

- Mann-Whitney U (skew-appropriate two-sample test; basket values are
  right-skewed, measured skew ~2.7-3.0, not assumed).
- Bootstrap confidence intervals around incremental revenue and incremental
  AOV.
- Descriptive metrics: conversion rate, AOV, items/order, attach rate,
  revenue/session, raw and margin-proxy-adjusted.
- Uplift/Qini-style analysis: rank all agent-arm sessions by the engine's own
  expected_value score, compare cumulative incremental value captured at each
  targeting rate against a random-targeting baseline (the standard diagonal
  reference for a cumulative-gains/Qini curve) and against an offer-to-
  -everyone baseline (ignore the no-action threshold, target every session
  with its own best-identified candidate). This directly answers the plan's
  question -- is the targeting doing work, not just the act of offering
  something.
"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "src" / "decision_engine"))
from objective import MARGIN_PROXY, score  # noqa: E402

OUT_DIR = _ROOT / "data" / "experiment"
UPLIFT_SEED = 55555  # dedicated seed for the uplift-curve's "if targeted" draws,
# deliberately separate from the primary result's per-session seeds (20260829/30/31)
# -- this analysis asks a different question (ranking quality) and uses a single
# consistent hypothetical outcome per session across all three targeting policies.


def bootstrap_ci(sample_a, sample_b, stat_fn, n_boot=5000, alpha=0.05, seed=7):
    """Percentile bootstrap CI for stat_fn(sample_a) - stat_fn(sample_b) is NOT
    what this does -- it returns a CI for stat_fn applied to (a, b) directly,
    e.g. stat_fn = lambda a, b: a.mean() - b.mean()."""
    rng = np.random.default_rng(seed)
    a = np.asarray(sample_a)
    b = np.asarray(sample_b)
    boots = np.empty(n_boot)
    for i in range(n_boot):
        a_s = rng.choice(a, size=len(a), replace=True)
        b_s = rng.choice(b, size=len(b), replace=True)
        boots[i] = stat_fn(a_s, b_s)
    lo, hi = np.percentile(boots, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return float(lo), float(hi), float(np.mean(boots))


def main():
    control = pd.read_parquet(OUT_DIR / "final_control.parquet")
    agent = pd.read_parquet(OUT_DIR / "final_agent.parquet")
    n = len(agent)
    assert len(control) == n, "arms must be equal size for this report"

    print("=" * 70)
    print(f"PHASE 5 CONFIRMATORY RESULT -- n={n} per arm, real dunnhumby baskets")
    print("=" * 70)

    # --- descriptive metrics, both arms ---
    def describe(df, label):
        print(f"\n[{label}] n={len(df)}")
        print(f"  conversion_rate: {df['converted'].mean():.4f} "
              f"(both arms 1.0 by design -- no measured basis in this dataset for a "
              f"cart-abandonment-from-offer probability, not fabricated)")
        print(f"  AOV / revenue-per-session: mean=${df['order_value'].mean():.4f} "
              f"median=${df['order_value'].median():.4f} std=${df['order_value'].std():.4f}")
        print(f"  items/order: mean={df['items'].mean():.4f}")
        print(f"  attach_rate: {df['attached'].mean():.4f}")
        print(f"  contribution_margin/session (order_value x {MARGIN_PROXY:.0%}): "
              f"mean=${df['contribution_margin'].mean():.4f}")

    describe(control, "CONTROL")
    describe(agent, "AGENT")

    # --- primary test: Mann-Whitney U, agent > control ---
    u, p_one = stats.mannwhitneyu(agent["order_value"], control["order_value"], alternative="greater")
    _, p_two = stats.mannwhitneyu(agent["order_value"], control["order_value"], alternative="two-sided")
    print(f"\nMann-Whitney U (agent.order_value > control.order_value): U={u:.0f}")
    print(f"  one-sided p={p_one:.6g}   two-sided p={p_two:.6g}")

    # --- incremental revenue / AOV, absolute and percentage, with bootstrap CI ---
    inc_abs = agent["order_value"].mean() - control["order_value"].mean()
    inc_pct = inc_abs / control["order_value"].mean() * 100
    lo, hi, boot_mean = bootstrap_ci(
        agent["order_value"], control["order_value"],
        lambda a, b: a.mean() - b.mean(), n_boot=5000, seed=7,
    )
    print(f"\nIncremental revenue/session (= incremental AOV, one order per session): "
          f"${inc_abs:.4f} ({inc_pct:+.2f}%)")
    print(f"  95% bootstrap CI: [${lo:.4f}, ${hi:.4f}]  (bootstrap mean ${boot_mean:.4f}, 5000 resamples)")

    inc_margin_abs = agent["contribution_margin"].mean() - control["contribution_margin"].mean()
    lo_m, hi_m, _ = bootstrap_ci(
        agent["contribution_margin"], control["contribution_margin"],
        lambda a, b: a.mean() - b.mean(), n_boot=5000, seed=8,
    )
    print(f"\nIncremental contribution margin/session (order_value x {MARGIN_PROXY:.0%}): "
          f"${inc_margin_abs:.4f}")
    print(f"  95% bootstrap CI: [${lo_m:.4f}, ${hi_m:.4f}]")

    # --- uplift / Qini-style analysis ---
    print("\n" + "=" * 70)
    print("UPLIFT / QINI-STYLE ANALYSIS (ranking quality, not the headline revenue number)")
    print("=" * 70)

    alt_chunks = sorted(OUT_DIR.glob("best_alt_chunk_*.parquet"))
    alt = pd.concat([pd.read_parquet(c) for c in alt_chunks], ignore_index=True)
    print(f"loaded {len(alt)} no_action alternative-candidate rows from {len(alt_chunks)} chunks")

    df = agent.merge(alt, on=["household_key", "basket_id"], how="left", suffixes=("", "_alt"))
    is_no_action = df["offered_action"] == "no_action"

    df["best_p_accept"] = df["offered_p_accept"]
    df["best_incremental_value"] = df["offered_incremental_value"]
    df.loc[is_no_action, "best_p_accept"] = df.loc[is_no_action, "alt_p_accept"]
    df.loc[is_no_action, "best_incremental_value"] = df.loc[is_no_action, "alt_incremental_value"].fillna(0.0)

    df["best_expected_value"] = df.apply(
        lambda r: score(r["best_p_accept"], r["best_incremental_value"]) if pd.notna(r["best_p_accept"]) else 0.0,
        axis=1,
    )

    no_candidate_at_all = is_no_action & df["alt_p_accept"].isna()
    print(f"sessions with genuinely zero candidates (no cross-sell rule, no upsell tier): {no_candidate_at_all.sum()}")

    rng = np.random.default_rng(UPLIFT_SEED)

    def would_accept(p):
        if pd.isna(p):
            return False
        return bool(rng.random() < p)

    df["would_accept_if_targeted"] = df["best_p_accept"].apply(would_accept)
    df["realized_if_targeted"] = np.where(df["would_accept_if_targeted"], df["best_incremental_value"].fillna(0.0), 0.0)

    total_if_all_targeted = df["realized_if_targeted"].sum()
    n_sessions = len(df)
    print(f"\ntotal realized incremental value if EVERY session were targeted with its own "
          f"best candidate (offer-to-everyone baseline): ${total_if_all_targeted:.2f} "
          f"(${total_if_all_targeted / n_sessions:.4f}/session average)")

    ranked = df.sort_values("best_expected_value", ascending=False).reset_index(drop=True)
    ranked["cum_gain_ranked"] = ranked["realized_if_targeted"].cumsum()
    ranked["k"] = np.arange(1, n_sessions + 1)
    ranked["cum_gain_random"] = ranked["k"] / n_sessions * total_if_all_targeted

    # AUUC: area between the ranked cumulative-gain curve and the random diagonal,
    # normalized by n (average per-session advantage of ranking over random, at
    # matched targeting rate), via the trapezoidal rule over k.
    diff = (ranked["cum_gain_ranked"] - ranked["cum_gain_random"]).values
    auuc = np.trapz(diff, dx=1) / n_sessions
    print(f"AUUC (area between ranked-targeting and random-targeting curves, /session): ${auuc:.4f}")

    # engine's actual real targeting point: K = number of sessions it actually offered
    engine_k = int((df["offered_action"] != "no_action").sum())
    engine_gain_at_k = float(ranked.loc[:engine_k - 1, "realized_if_targeted"].sum()) if engine_k > 0 else 0.0
    random_gain_at_k = engine_k / n_sessions * total_if_all_targeted
    print(f"\nAt the engine's own real targeting rate (K={engine_k}, {engine_k/n_sessions:.1%} of sessions):")
    print(f"  ranked-by-expected-value cumulative gain: ${engine_gain_at_k:.2f} (${engine_gain_at_k/engine_k:.4f}/targeted session)")
    print(f"  random-targeting-at-same-rate expected gain: ${random_gain_at_k:.2f} (${random_gain_at_k/engine_k:.4f}/targeted session)")
    print(f"  offer-to-everyone total (K={n_sessions}): ${total_if_all_targeted:.2f} (${total_if_all_targeted/n_sessions:.4f}/session)")

    ranked[["k", "best_expected_value", "cum_gain_ranked", "cum_gain_random"]].to_parquet(
        OUT_DIR / "uplift_curve.parquet"
    )
    df.to_parquet(OUT_DIR / "final_agent_with_uplift.parquet")
    print(f"\nwrote uplift_curve.parquet ({len(ranked)} rows) and final_agent_with_uplift.parquet")


if __name__ == "__main__":
    main()
