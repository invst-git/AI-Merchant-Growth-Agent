"""Phase 4: turns a finalized cart into a bounded Razorpay order amount.

Deterministic on purpose, same reasoning as engine.py never letting an
agent invent a price: the agent names product_ids, this module is the
only thing allowed to turn those into money.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "catalogue"))
import catalogue

CURRENCY = "INR"

# Razorpay's own hard floor (verified live against the create_order tool's
# schema: amount has "minimum": 100). Dataset prices are small enough
# (many real baskets total well under $1) that a floor is a real
# necessity here, not a hypothetical edge case.
MIN_ORDER_PAISE = 100

# Bounded spend cap for this demo (the "bounded" in the plan's own
# language for Phase 6, enforced starting here since Phase 4 is the
# first phase that can actually spend anything). Comfortably above any
# real basket this dataset produces (observed range so far: $0.33-$2.36
# per item), tune with real numbers once Phase 5/6 has a distribution to
# look at instead of a handful of live runs.
MAX_ORDER_PAISE = 50_000  # INR 500.00


class CartPricingError(Exception):
    """Raised when a basket contains a product_id the catalogue doesn't
    recognize. Never silently drop or zero-price an unknown item."""


def basket_amount_paise(basket_product_ids: list[int]) -> dict:
    """Sum real catalogue prices for every product_id in the basket,
    convert to paise, and apply the floor and cap. Returns a dict rather
    than a bare int so the caller (and the audit log) can see exactly
    what happened to the raw total, not just the final bounded number."""
    if not basket_product_ids:
        raise CartPricingError("basket is empty, nothing to charge")

    line_items = []
    raw_total = 0.0
    for product_id in basket_product_ids:
        entry = catalogue.build_entry(product_id)
        if entry is None:
            raise CartPricingError(f"product_id {product_id} not found in catalogue")
        line_items.append({"product_id": product_id, "price": entry["price"]})
        raw_total += entry["price"]

    raw_paise = round(raw_total * 100)
    floor_applied = raw_paise < MIN_ORDER_PAISE
    amount_paise = max(raw_paise, MIN_ORDER_PAISE)
    cap_applied = amount_paise > MAX_ORDER_PAISE
    amount_paise = min(amount_paise, MAX_ORDER_PAISE)

    return {
        "line_items": line_items,
        "raw_total": raw_total,
        "amount_paise": amount_paise,
        "currency": CURRENCY,
        "floor_applied": floor_applied,
        "cap_applied": cap_applied,
    }
