"""The standalone conversational checkout: a completely separate product
surface from the dashboard (src/dashboard/dashboard_api.py, port 8002),
with its own link and its own server. Nothing here imports from or writes
to the dashboard's files, and the dashboard no longer has a checkout
surface of its own -- this is the only one.

Every turn here is live: real household, the real buyer/merchant agents
(src/agents/demo_graph.py), the real trained decision engine (Phase 6's
catalogue-bounding guardrail included -- see sales_copy.py's docstring),
and real Razorpay Test Mode orders. The customer types free text; nothing
here validates it against the catalogue up front (that's a deliberate
choice the person running this demo made -- see the project's own notes),
so a request for something outside the catalogue behaves however the
buyer agent's own catalogue search already handles that, same as the CLI.

The one place this adds anything of its own on top of demo_graph.py is
sales_copy.py: a second, small, separate LLM call that turns a real,
already-decided, already-guardrailed offer into one persuasive sentence
for the customer, instead of the flat audit-log phrasing merchant_agent.py
writes on purpose for the dashboard.

Run with (from the repo root, matching every other server here):
    uvicorn src.checkout_ui.app:app --port 8003 --app-dir .
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
from sales_copy import generate_pitch  # noqa: E402

_ROOT = _HERE.parent.parent
sys.path.insert(0, str(_ROOT / "src" / "audit"))
sys.path.insert(0, str(_ROOT / "src" / "decision_engine"))
sys.path.insert(0, str(_ROOT / "src" / "agents"))
import engine  # noqa: E402  (PRODUCT_LOOKUP: the one real price/category table)
from demo_graph import start_conversational_checkout, resolve_conversational_checkout  # noqa: E402

load_dotenv()  # same repo-root .env every other server here reads (RAZORPAY_KEY_ID etc.)

STATIC_DIR = _HERE / "static"
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "")

# Real money here is INR -- Razorpay is an Indian payment gateway and this
# surface creates real Test Mode INR orders (see src/payments/checkout.py,
# which applies this same rate to the actual charge). The dunnhumby
# dataset's prices are real US grocery prices in USD, so this converts at
# the display boundary only, on this own copy of the price table -- the
# decision engine (engine.py, imported above for PRODUCT_LOOKUP) still
# computes everything in USD, and nothing here changes that.
USD_TO_INR = 94.45

app = FastAPI()


def _to_inr(usd_value):
    return usd_value * USD_TO_INR


# ---- real product data, same table every other server reads (own copy --
# not imported from dashboard_api.py, so this has no runtime dependency
# on the dashboard at all) ----

def _price_and_desc(product_id):
    if product_id is None or product_id not in engine.PRODUCT_LOOKUP.index:
        return None
    row = engine.PRODUCT_LOOKUP.loc[product_id]
    return {
        "product_id": int(product_id),
        "commodity_desc": str(row["commodity_desc"]).title(),
        "sub_commodity_desc": str(row["sub_commodity_desc"]).title(),
        "price": _to_inr(float(row["price"])),
    }


def _short_reason(reason_text):
    if not reason_text:
        return None, None
    parts = reason_text.split("; ", 1)
    return parts[0].strip(), (parts[1].strip() if len(parts) > 1 else None)


async def _checkout_display(state):
    """Customer-safe view of one conversational-checkout turn, plus one
    real persuasive sentence for the offer (if any) -- see sales_copy.py.
    Never the agent's own audit-log prose, never the engine's internal
    reasoning unless the caller explicitly expands it."""
    display = {}
    cart_before = state.get("cart_before") or []
    display["base_products"] = [p for p in (_price_and_desc(pid) for pid in cart_before) if p]

    decision = state.get("decision")
    chosen = decision["chosen_action"] if decision else None
    if chosen and chosen.get("action") != "no_action":
        # reason_text isn't on the in-memory decision dict by default (only
        # audit_log.py's log_decision attaches it, for the audit record) --
        # attach it here too so the "why" copy has the real reasoning to draw from.
        reason_text = chosen.get("reason")
        headline, full_reason = _short_reason(reason_text)
        offer_product = _price_and_desc(chosen.get("product_id"))
        display["offer_action"] = chosen["action"]
        display["offer_product"] = offer_product
        display["offer_p_accept"] = chosen.get("p_accept")
        display["offer_why_headline"] = headline
        display["offer_why_full"] = full_reason
        if offer_product:
            base = display["base_products"][-1] if display["base_products"] else None
            display["offer_pitch"] = await generate_pitch(
                action=chosen["action"],
                base_name=base["sub_commodity_desc"] if base else "your order",
                offer_name=offer_product["sub_commodity_desc"],
                price_display=f"₹{offer_product['price']:.2f}",
                why_headline=headline,
                p_accept=chosen.get("p_accept"),
            )
    elif chosen and chosen.get("action") == "no_action" and chosen.get("bound_rejected"):
        display["guardrail_note"] = (
            "The model's top-ranked candidate was blocked because it isn't a "
            "catalogue-declared complement for this basket, so no offer was shown."
        )

    cart_after = state.get("cart_after")
    if cart_after is not None:
        after_products = [p for p in (_price_and_desc(pid) for pid in cart_after) if p]
        display["final_products"] = after_products
        display["final_total"] = sum(p["price"] for p in after_products)
        display["accepted"] = state.get("accepted")

    order = state.get("checkout_order")
    if order:
        display["order_id"] = order.get("order_id")
        display["amount_paise"] = order.get("amount_paise")
        display["amount_display"] = order.get("amount_display")
        display["currency"] = order.get("currency")
        display["checkout_url"] = order.get("checkout_url")

    return display


class CheckoutStartBody(BaseModel):
    intent: str
    household_key: int = 1060


class CheckoutResolveBody(BaseModel):
    request_id: str
    accepted: bool


@app.post("/api/checkout/start")
async def checkout_start(body: CheckoutStartBody):
    try:
        result = await start_conversational_checkout(body.household_key, body.intent)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"checkout agent failed: {e}")
    result["display"] = await _checkout_display(result)
    return JSONResponse(result)


@app.post("/api/checkout/resolve")
async def checkout_resolve(body: CheckoutResolveBody):
    try:
        result = await resolve_conversational_checkout(body.request_id, body.accepted)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"checkout resolution failed: {e}")
    result["display"] = await _checkout_display(result)
    return JSONResponse(result)


@app.get("/", response_class=HTMLResponse)
def index():
    # RAZORPAY_KEY_ID is Razorpay's *publishable* key -- meant to sit in
    # client-side JS (Standard Checkout can't work otherwise), so this is
    # a plain template substitution, not a secret handoff.
    #
    # encoding="utf-8" is required here, not decorative: Path.read_text()
    # without it uses the OS's locale-preferred encoding, which on
    # Windows is usually cp1252, not utf-8 -- it would silently mangle
    # every em dash and middle dot in this file into "mojibake" (e.g.
    # "—" turning into "â€”") the moment this runs on
    # a Windows machine, even though the file on disk is correctly
    # UTF-8-encoded and looks fine when read on Linux.
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    return html.replace("__RAZORPAY_KEY_ID__", RAZORPAY_KEY_ID)
