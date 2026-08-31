"""Phase 6: "bounded" rule #2 (rule #1, the spend cap, was already built and
enforced in Phase 4's checkout.py). The agent may only offer SKUs the
catalogue has declared as a complement or an alternative for the basket
actually in hand, never an arbitrary upsell.

This is not automatically true of engine.decide()'s output. Verified
directly on 1,000 real baskets before writing this: the engine's cross-sell
ranking considers up to MAX_CROSS_SELL_CANDIDATES=15 candidates per basket
(so it can find the best expected_value one), while the catalogue only
declares the top MAX_COMPLEMENTS=3 by lift per antecedent commodity as
"complements" -- 222 of 708 real chosen offers (31%) referenced a commodity
outside the catalogue's declared set for that basket. Upsell candidates
come from the same upsell_tiers table the catalogue's declared_alternative
already uses 1:1, so those matched with zero violations in the same test.

Rather than raise the catalogue's declared-complements limit to match the
engine's internal ranking width (which would just move the mismatch
somewhere else, and start letting the catalogue expose products the engine
itself considered but rejected as not worth offering), this enforces the
bound at the one place every real offer has to pass through: the tool the
Merchant Agent actually calls. A chosen action outside the catalogue's
declared surface never reaches the agent -- it is replaced with the
no_action candidate, exactly as if no in-bounds offer had scored above the
no-action baseline, and the rejection itself is recorded on the decision so
it is visible on the dashboard, not silently dropped.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "catalogue"))
import catalogue  # noqa: E402

NO_ACTION_TEMPLATE = {
    "action": "no_action",
    "p_accept": None,
    "incremental_value": 0.0,
    "expected_value": 0.0,
    "feature_attribution": [],
}


def _declared_surface(basket_product_ids):
    complements = set()
    alternatives = {}
    for pid in basket_product_ids:
        entry = catalogue.build_entry(pid)
        if entry is None:
            continue
        complements.update(entry["declared_complements"])
        if entry["declared_alternative"]:
            alternatives[pid] = entry["declared_alternative"]["upsell_product_id"]
    return complements, alternatives


def _in_bounds(chosen, complements, alternatives):
    if chosen["action"] == "cross_sell":
        return chosen["commodity_desc"] in complements
    if chosen["action"] == "upsell":
        return alternatives.get(chosen["from_product_id"]) == chosen["product_id"]
    return True  # no_action is always in bounds


def apply_catalogue_bound(decision: dict, basket_product_ids: list[int]) -> dict:
    """decision is engine.decide()'s return value. Returns a decision with
    the same shape; chosen_action is replaced with a no_action fallback,
    tagged bound_rejected=True with the original out-of-bounds candidate
    kept under rejected_action for the audit trail, if the engine's own
    choice was not catalogue-declared."""
    chosen = decision["chosen_action"]
    complements, alternatives = _declared_surface(basket_product_ids)

    if _in_bounds(chosen, complements, alternatives):
        return decision

    fallback = dict(NO_ACTION_TEMPLATE)
    fallback["reason"] = (
        f"{chosen['action']} of product {chosen.get('product_id')} scored highest "
        f"(expected_value {chosen['expected_value']:.3f}) but is not a catalogue-declared "
        f"complement/alternative for this basket, blocked by the Phase 6 bounding rule "
        f"and replaced with no_action"
    )
    fallback["bound_rejected"] = True
    fallback["rejected_action"] = chosen

    return {
        "chosen_action": fallback,
        "candidate_actions": decision["candidate_actions"],
    }
