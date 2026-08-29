# Objective Function — Source of Truth

This document is the single definition of what the Growth Decision Engine
optimizes. Any change here must be reflected in the Phase 2 decision engine
code and in the Phase 6 audit trail's "reason" field — they should never
drift apart.

## The formula

For a given basket and a given candidate action (a specific upsell, a
specific cross-sell, or no action), the engine computes:

    expected_incremental_contribution =
        P(accept | offer, customer, basket)
        x (incremental_basket_value x margin_proxy)
        - expected_downside

The engine evaluates every candidate action this way and picks whichever
scores highest. "No action" is always one of the candidates, not a
fallback used only when nothing else qualifies — see below.

## Term by term

**P(accept | offer, customer, basket)** — the probability this specific
customer accepts this specific offer, given their current basket. This
comes from the Phase 2 acceptance model (logistic regression), trained on
dunnhumby's basket, demographic, and campaign/coupon history. Not defined
yet — Phase 2 work.

**incremental_basket_value** — the extra revenue the offer would add if
accepted. For a cross-sell, this is the added item's price. For an
upsell (swapping a cheaper item for a pricier one in the same
sub-commodity), this is the price difference, not the full price of the
new item.

**margin_proxy** — none of the three datasets (dunnhumby, Olist, UCI
Online Retail II) contain true cost-of-goods data, so contribution margin
cannot be computed exactly. Starting placeholder: a flat 30% assumed
margin across all categories, applied uniformly. This is a placeholder,
not a researched figure — Phase 1, once category-level pricing is visible
in the cleaned data, should revisit whether a flat proxy is good enough or
whether a small number of category-level proxies (e.g. lower margin on
staples, higher on discretionary/accessory items) is worth the added
complexity. Whatever is chosen, the dashboard (Phase 7) must label every
contribution-margin figure as based on an assumed proxy, not real COGS.

**expected_downside** — a penalty representing the risk that presenting
an offer at all causes some fraction of customers to abandon the basket
(interruption/friction cost), separate from whether the specific offer is
accepted. Starting placeholder: a small fixed constant per offer shown,
tunable later. This is the least-grounded term in the formula and should
be revisited once the Phase 2 acceptance model exists — it is flagged
here so nobody forgets it's a placeholder.

## "No action" as a first-class candidate

No action always scores exactly 0 (no incremental value, no downside). It
is scored on the same footing as every upsell/cross-sell candidate and
the engine's decision is simply the argmax across the full candidate set,
including 0. This is deliberate: the whole point of the project is that
the agent can decide silence is the best move, not that it always finds
some offer to make.

## Status

Placeholder values (30% margin proxy, fixed abandonment constant) are
Phase 0 defaults so the rest of the build isn't blocked. They are meant
to be revisited, not treated as final, once Phase 1 data and the Phase 2
acceptance model exist.
