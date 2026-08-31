"""Phase 3/4: tools shared by the Buyer, Merchant, and Checkout agents.

query_catalogue calls the catalogue module directly (in-process, not
over HTTP) for speed and reliability inside the agent loop. The
standalone HTTP endpoint (catalogue_api.py) exists separately as the
actual agent-readable artifact the build plan asks for; nothing stops
an external agent from calling that instead of this in-process version.

get_growth_decision wraps engine.decide() as-is, no logic duplicated
here. Its return value is already verified JSON-safe (all numpy types
cast to native python in engine.py).

create_checkout_order (Phase 4) is async, unlike the three tools above,
because it calls Razorpay's MCP server over the network rather than
in-process code. Verified directly: an MCP tool built with only a
coroutine (no sync func) raises NotImplementedError on .invoke(), so any
agent holding this tool must be run with .ainvoke(), not .invoke(). It
never lets the agent name a price, same reasoning as get_product never
letting it invent one: the amount comes from checkout.basket_amount_paise,
which prices every product_id against the real catalogue and applies the
Razorpay-required floor and the demo's spend cap before any money-shaped
number reaches the Razorpay API.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "catalogue"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "decision_engine"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "payments"))

from langchain_core.tools import tool

import catalogue
import engine
import checkout
from audit import log_payment_event
from razorpay_mcp import RazorpayMCPError, get_razorpay_tools, parse_mcp_result

CHECKOUT_BASE_URL = "http://localhost:8001"


@tool
def query_catalogue(query: str, max_results: int = 5) -> list[dict]:
    """Search the merchant catalogue in natural language. Returns matching
    products with product_id, category, subcategory, price, availability,
    declared_complements, declared_alternative, checkout_capability."""
    return catalogue.search(query, max_results=max_results)


@tool
def get_product(product_id: int) -> dict:
    """Look up one exact product by its product_id. Returns the full
    catalogue entry, or {"found": false} if that id does not exist. Use
    this whenever you already have a specific product_id to confirm (from
    a buyer's request or your own earlier search), instead of re-searching
    by text, since query_catalogue only matches on category text and will
    not find a bare numeric id."""
    entry = catalogue.build_entry(product_id)
    return entry if entry is not None else {"found": False}


@tool
def get_growth_decision(household_key: int, basket_product_ids: list[int]) -> dict:
    """Given a household and the product ids currently in their basket,
    return the growth decision: the chosen action (cross_sell, upsell, or
    no_action), its expected value, and the plain-English reason. Also
    returns every candidate that was considered, not just the winner."""
    return engine.decide(household_key, basket_product_ids)


@tool
async def create_checkout_order(household_key: int, basket_product_ids: list[int]) -> dict:
    """Create a real Razorpay Test Mode order for the buyer's finalized
    cart, so they can complete Standard Checkout. Prices are looked up
    from the real catalogue for every product_id, never taken from the
    conversation, and the amount is bounded by both Razorpay's own
    minimum and this demo's spend cap before the order is created.
    Returns order_id, amount_paise, amount_display (a rupee string), the
    checkout_url to hand to the buyer, and whether the floor or cap
    changed the raw basket total. Call this once you have the buyer's
    final basket_product_ids (after any offer has been resolved), not
    before."""
    try:
        pricing = checkout.basket_amount_paise(basket_product_ids)
    except checkout.CartPricingError as e:
        return {"error": str(e)}

    receipt = f"demo-{household_key}-{int(time.time())}"[:40]
    notes = {
        "household_key": str(household_key),
        "basket_product_ids": ",".join(str(p) for p in basket_product_ids),
    }

    try:
        tools = await get_razorpay_tools("create_order")
        raw_result = await tools["create_order"].ainvoke({
            "amount": pricing["amount_paise"],
            "currency": pricing["currency"],
            "receipt": receipt,
            "notes": notes,
        })
        order = parse_mcp_result(raw_result)
    except RazorpayMCPError as e:
        return {"error": f"Razorpay order creation failed: {e}"}

    log_payment_event({
        "event": "order_created",
        "razorpay_order_id": order["id"],
        "status": order["status"],
        "amount": pricing["amount_paise"],
        "currency": pricing["currency"],
        "spend_cap_applied": pricing["cap_applied"],
        "floor_applied": pricing["floor_applied"],
        "household_key": household_key,
        "basket_product_ids": basket_product_ids,
        "receipt": receipt,
    })

    return {
        "order_id": order["id"],
        "amount_paise": pricing["amount_paise"],
        "amount_display": f"INR {pricing['amount_paise'] / 100:.2f}",
        "currency": pricing["currency"],
        "checkout_url": f"{CHECKOUT_BASE_URL}/checkout/{order['id']}?amount={pricing['amount_paise']}&currency={pricing['currency']}",
        "floor_applied": pricing["floor_applied"],
        "cap_applied": pricing["cap_applied"],
    }
