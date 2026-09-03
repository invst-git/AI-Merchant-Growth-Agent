"""Phase 4: turns a finalized cart into a bounded Razorpay order amount.

Deterministic on purpose, same reasoning as engine.py never letting an
agent invent a price: the agent names product_ids, this module is the
only thing allowed to turn those into money.

The dunnhumby dataset's prices are real US grocery prices in USD; this
project's checkout is a real Razorpay (an Indian payment gateway)
integration, so what actually gets charged needs to be real INR, not
the raw USD digits wearing an "INR" label (a $5.13 basket becoming an
order literally called "INR 5.13"). USD_TO_INR below is the one and
only place that conversion happens. The catalogue and decision engine
(catalogue.py, engine.py) stay in USD throughout -- the trained
growth-decision model's features (avg_basket_value and friends) were
fit on that USD scale, and rescaling them would silently corrupt every
p_accept/expected_value prediction. This module is the last stop before
money changes hands, so it's the right and only place to convert.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "catalogue"))
import catalogue

CURRENCY = "INR"

# Live USD -> INR mid-market rate (XE and Wise agreed to within a few
# paise: ~94.4-94.5), snapshotted 2026-09-03 for demo stability rather
# than calling a live FX API on every checkout. Update this constant to
# refresh it; nothing else in this file needs to change.
USD_TO_INR = 94.45

# Razorpay's own hard floor (verified live against the create_order tool's
# schema: amount has "minimum": 100). A real platform rule already in
# paise, independent of our FX rate -- it does not get rescaled.
MIN_ORDER_PAISE = 100

# Bounded spend cap for this demo (the "bounded" in the plan's own
# language for Phase 6, enforced starting here since Phase 4 is the
# first phase that can actually spend anything). A clean INR 50,000
# ceiling -- comfortably above any real basket this dataset produces
# even after the USD->INR conversion above (observed per-item range so
# far: $0.33-$2.36, i.e. roughly INR 31-223 per item).
MAX_ORDER_PAISE = 50_000 * 100  # INR 50,000.00


class CartPricingError(Exception):
    """Raised when a basket contains a product_id the catalogue doesn't
    recognize. Never silently drop or zero-price an unknown item."""


def basket_amount_paise(basket_product_ids: list[int]) -> dict:
    """Sum real catalogue prices (USD) for every product_id in the
    basket, convert to real INR at USD_TO_INR, then to paise, and apply
    the floor and cap. Returns a dict rather than a bare int so the
    caller (and the audit log) can see exactly what happened to the raw
    total, not just the final bounded number -- including both the
    original USD figure and the converted INR figure, for anything that
    wants to show its work."""
    if not basket_product_ids:
        raise CartPricingError("basket is empty, nothing to charge")

    line_items = []
    raw_total_usd = 0.0
    for product_id in basket_product_ids:
        entry = catalogue.build_entry(product_id)
        if entry is None:
            raise CartPricingError(f"product_id {product_id} not found in catalogue")
        line_items.append({"product_id": product_id, "price_usd": entry["price"]})
        raw_total_usd += entry["price"]

    raw_total_inr = raw_total_usd * USD_TO_INR
    raw_paise = round(raw_total_inr * 100)
    floor_applied = raw_paise < MIN_ORDER_PAISE
    amount_paise = max(raw_paise, MIN_ORDER_PAISE)
    cap_applied = amount_paise > MAX_ORDER_PAISE
    amount_paise = min(amount_paise, MAX_ORDER_PAISE)

    return {
        "line_items": line_items,
        "raw_total_usd": raw_total_usd,
        "raw_total_inr": raw_total_inr,
        "amount_paise": amount_paise,
        "currency": CURRENCY,
        "floor_applied": floor_applied,
        "cap_applied": cap_applied,
    }
