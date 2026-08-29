"""Phase 2: the objective function from docs/objective_function.md.
expected_incremental_contribution = P(accept) * (incremental_value * margin_proxy) - expected_downside
no_action always scores exactly 0 and is not run through this formula.
"""

MARGIN_PROXY = 0.30
EXPECTED_DOWNSIDE = 0.20


def score(p_accept, incremental_value):
    return p_accept * (incremental_value * MARGIN_PROXY) - EXPECTED_DOWNSIDE


def explain(p_accept, incremental_value):
    net = score(p_accept, incremental_value)
    return (
        f"{p_accept:.0%} accept x (${incremental_value:.2f} incremental x {MARGIN_PROXY:.0%} margin proxy) "
        f"- ${EXPECTED_DOWNSIDE:.2f} downside = ${net:.3f} expected value"
    )
