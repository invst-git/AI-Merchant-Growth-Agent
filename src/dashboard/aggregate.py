"""Phase 7: live Phase 5 aggregate metrics for the dashboard.

Every number here is computed fresh from data/experiment/*.parquet on
each call -- nothing in this module is a hand-copied figure from
docs/phase5_results.md. If Phase 5 is ever re-run, this recomputes from
whatever is on disk, matching the plan's own "reading live from ... the
Phase 5 experiment output rather than from any hand-curated numbers."

Targeting comparison (engine-ranked vs random vs offer-to-everyone) reads
straight from data/experiment/uplift_curve.parquet and
final_agent_with_uplift.parquet -- both already contain the seeded
"would this session have converted if targeted" draw stats_module.py
made once and archived. Reusing those columns (rather than re-drawing
fresh Bernoulli outcomes on every dashboard request) is deliberate: this
stays live (reads the real file, reflects a future re-run) without making
the uplift headline flicker between requests on unseeded randomness that
was never the actual Phase 5 result.

The targeting curve's confidence band IS computed fresh every request
(a real case-resampling bootstrap over the archived per-session
outcomes, see _targeting_curve) -- it's cheap enough (a few hundred
milliseconds) that there's no reason to freeze it, unlike the two
headline CIs which reuse stats_module.bootstrap_ci's exact 5000-resample
convention for consistency with docs/phase5_results.md.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "src" / "experiment"))
sys.path.insert(0, str(_ROOT / "src" / "decision_engine"))
from stats_module import bootstrap_ci  # noqa: E402
from objective import MARGIN_PROXY  # noqa: E402

EXPERIMENT_DIR = _ROOT / "data" / "experiment"


def _describe(df: pd.DataFrame) -> dict:
    return {
        "n": int(len(df)),
        "conversion_rate": float(df["converted"].mean()),
        "aov_mean": float(df["order_value"].mean()),
        "aov_median": float(df["order_value"].median()),
        "aov_std": float(df["order_value"].std()),
        "items_mean": float(df["items"].mean()),
        "attach_rate": float(df["attached"].mean()),
        "contribution_margin_mean": float(df["contribution_margin"].mean()),
    }


def _proportion_ci(sample, n_boot=3000, seed=11):
    """Bootstrap CI on a 0/1 rate (attach rate), same percentile-bootstrap
    convention as bootstrap_ci, just single-sample."""
    rng = np.random.default_rng(seed)
    arr = np.asarray(sample)
    boots = np.empty(n_boot)
    for i in range(n_boot):
        boots[i] = rng.choice(arr, size=len(arr), replace=True).mean()
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return float(lo), float(hi)


def _targeting_curve(agent_uplift: pd.DataFrame, control_aov_mean: float,
                      n_points: int = 60, n_boot: int = 300, seed: int = 42) -> list[dict]:
    """Average incremental value captured, as a percent of the control
    arm's AOV, at each targeting depth -- for the engine's real ranking
    (best_expected_value, descending) and for one seeded random targeting
    order, both reading the same real archived realized_if_targeted
    outcomes final_agent_with_uplift.parquet already has.

    The random-targeting line is ONE real seeded permutation, not an
    average over many (which would just converge to a flat line at the
    population mean, a real but visually uninformative fact stated in
    the dashboard's caption instead) -- it fluctuates and converges
    toward the mean exactly as one real random targeting order would.

    The band around the ranked line is a real case-resampling bootstrap
    (resample sessions with replacement, re-rank each resample by its
    own best_expected_value, recompute the running-mean curve), not a
    cosmetic shaded area.
    """
    best_ev = agent_uplift["best_expected_value"].to_numpy()
    realized = agent_uplift["realized_if_targeted"].fillna(0.0).to_numpy()
    n = len(realized)

    order = np.argsort(-best_ev)
    ranked_running_pct = np.cumsum(realized[order]) / np.arange(1, n + 1) / control_aov_mean * 100

    rrng = np.random.default_rng(seed)
    rand_order = rrng.permutation(n)
    random_running_pct = np.cumsum(realized[rand_order]) / np.arange(1, n + 1) / control_aov_mean * 100

    # a k=1 bootstrap point has wild single-session variance (can spike the
    # CI band into the hundreds of percent) and adds nothing informative --
    # start the reported curve at a small but stable floor instead.
    k_floor = max(20, round(n * 0.004))
    k_points = sorted(set(np.linspace(k_floor, n, n_points).astype(int)))
    k_idx = np.array(k_points) - 1

    brng = np.random.default_rng(seed + 1)
    boot_pct = np.empty((n_boot, len(k_points)))
    for b in range(n_boot):
        idx = brng.integers(0, n, n)
        s_ev, s_real = best_ev[idx], realized[idx]
        o = np.argsort(-s_ev)
        running = np.cumsum(s_real[o]) / np.arange(1, n + 1)
        boot_pct[b] = running[k_idx] / control_aov_mean * 100
    ci_lo = np.percentile(boot_pct, 2.5, axis=0)
    ci_hi = np.percentile(boot_pct, 97.5, axis=0)

    curve = []
    for i, k in enumerate(k_points):
        curve.append({
            "pct_targeted": float(k / n * 100),
            "agent_pct_lift": float(ranked_running_pct[k - 1]),
            "agent_ci_lo": float(ci_lo[i]),
            "agent_ci_hi": float(ci_hi[i]),
            "random_pct_lift": float(random_running_pct[k - 1]),
        })
    return curve


def _distribution(control_vals, agent_vals, max_val: float = 200.0, n_bins: int = 20) -> list[dict]:
    """Real normalized histograms (density, not counts, so both arms are
    comparable despite equal n here) of order_value for both arms, binned
    $0-$200 in even steps plus one overflow bin for the real right tail
    beyond $200 (order values are right-skewed, some real baskets go well
    past this). Rendered client-side as a binned area curve, not a
    fabricated smooth KDE."""
    edges = list(np.linspace(0, max_val, n_bins + 1))
    control_clipped = np.clip(np.asarray(control_vals), 0, max_val)
    agent_clipped = np.clip(np.asarray(agent_vals), 0, max_val)
    c_counts, _ = np.histogram(control_clipped, bins=edges)
    a_counts, _ = np.histogram(agent_clipped, bins=edges)
    bin_width = edges[1] - edges[0]
    c_density = c_counts / c_counts.sum() / bin_width if c_counts.sum() else c_counts * 0.0
    a_density = a_counts / a_counts.sum() / bin_width if a_counts.sum() else a_counts * 0.0
    midpoints = [(edges[i] + edges[i + 1]) / 2 for i in range(n_bins)]
    over_control = float((np.asarray(control_vals) > max_val).mean())
    over_agent = float((np.asarray(agent_vals) > max_val).mean())
    return {
        "points": [
            {"x": float(m), "control": float(c), "agent": float(a)}
            for m, c, a in zip(midpoints, c_density, a_density)
        ],
        "pct_above_max_control": over_control,
        "pct_above_max_agent": over_agent,
        "max_val": max_val,
    }


def compute_aggregate() -> dict:
    control_path = EXPERIMENT_DIR / "final_control.parquet"
    agent_path = EXPERIMENT_DIR / "final_agent.parquet"
    uplift_agent_path = EXPERIMENT_DIR / "final_agent_with_uplift.parquet"

    if not (control_path.exists() and agent_path.exists()):
        return {"available": False, "reason": "Phase 5 experiment output not found under data/experiment/"}

    control = pd.read_parquet(control_path)
    agent = pd.read_parquet(agent_path)
    n = len(agent)

    control_stats = _describe(control)
    agent_stats = _describe(agent)

    u_stat, p_one = stats.mannwhitneyu(agent["order_value"], control["order_value"], alternative="greater")
    _, p_two = stats.mannwhitneyu(agent["order_value"], control["order_value"], alternative="two-sided")

    inc_abs = agent["order_value"].mean() - control["order_value"].mean()
    inc_pct = float(inc_abs / control["order_value"].mean() * 100)
    lo, hi, _ = bootstrap_ci(
        agent["order_value"], control["order_value"],
        lambda a, b: a.mean() - b.mean(), n_boot=5000, seed=7,
    )
    pct_lo, pct_hi, _ = bootstrap_ci(
        agent["order_value"], control["order_value"],
        lambda a, b: (a.mean() - b.mean()) / b.mean() * 100, n_boot=5000, seed=7,
    )

    inc_margin_abs = float(agent["contribution_margin"].mean() - control["contribution_margin"].mean())
    inc_margin_pct = float(inc_margin_abs / control_stats["contribution_margin_mean"] * 100)
    lo_m, hi_m, _ = bootstrap_ci(
        agent["contribution_margin"], control["contribution_margin"],
        lambda a, b: a.mean() - b.mean(), n_boot=5000, seed=8,
    )

    attach_lo, attach_hi = _proportion_ci(agent["attached"], n_boot=3000, seed=11)

    result = {
        "available": True,
        "n_per_arm": n,
        "margin_proxy": MARGIN_PROXY,
        "control": control_stats,
        "agent": agent_stats,
        "mannwhitney": {
            "U": float(u_stat), "p_one_sided": float(p_one), "p_two_sided": float(p_two),
            "significant": bool(p_one < 0.05),
        },
        "incremental_revenue": {
            "abs": float(inc_abs), "pct": inc_pct, "ci_lo": float(lo), "ci_hi": float(hi),
            "pct_ci_lo": float(pct_lo), "pct_ci_hi": float(pct_hi),
        },
        "incremental_margin": {
            "abs": inc_margin_abs, "pct": inc_margin_pct, "ci_lo": float(lo_m), "ci_hi": float(hi_m),
        },
        "attach_rate_ci": {"lo": attach_lo, "hi": attach_hi},
        "action_mix": None,
        "targeting": None,
        "targeting_curve": None,
        "distribution": _distribution(control["order_value"], agent["order_value"]),
    }

    if agent_path.exists():
        mix = agent["offered_action"].value_counts(normalize=True).to_dict()
        result["action_mix"] = {str(k): float(v) for k, v in mix.items()}

    if uplift_agent_path.exists():
        agent_uplift = pd.read_parquet(uplift_agent_path)
        curve_source = pd.read_parquet(EXPERIMENT_DIR / "uplift_curve.parquet").sort_values("k").reset_index(drop=True)

        engine_k = int((agent_uplift["offered_action"] != "no_action").sum())
        total_sessions = len(agent_uplift)
        everyone_total = float(curve_source["cum_gain_ranked"].iloc[-1])

        row_at_k = curve_source[curve_source["k"] == engine_k]
        if len(row_at_k) and engine_k > 0:
            engine_total = float(row_at_k["cum_gain_ranked"].iloc[0])
            random_total = float(row_at_k["cum_gain_random"].iloc[0])
        else:
            engine_total = 0.0
            random_total = 0.0

        uplift_vs_random_pct = (
            float((engine_total / random_total - 1) * 100) if random_total > 0 else None
        )

        result["targeting"] = {
            "engine_k": engine_k,
            "engine_rate": float(engine_k / total_sessions) if total_sessions else 0.0,
            "total_sessions": int(total_sessions),
            "engine_total": engine_total,
            "engine_per_targeted": float(engine_total / engine_k) if engine_k else 0.0,
            "random_total": random_total,
            "random_per_targeted": float(random_total / engine_k) if engine_k else 0.0,
            "everyone_total": everyone_total,
            "everyone_per_session": float(everyone_total / total_sessions) if total_sessions else 0.0,
            "uplift_vs_random_pct": uplift_vs_random_pct,
        }

        result["targeting_curve"] = _targeting_curve(agent_uplift, control_stats["aov_mean"])

    return result


if __name__ == "__main__":
    import json
    import time
    t0 = time.time()
    out = compute_aggregate()
    print(f"computed in {time.time()-t0:.2f}s")
    print(json.dumps({k: v for k, v in out.items() if k != "targeting_curve" and k != "distribution"}, indent=2))
    print("targeting_curve points:", len(out["targeting_curve"]) if out.get("targeting_curve") else 0)
    print("distribution points:", len(out["distribution"]["points"]) if out.get("distribution") else 0)
