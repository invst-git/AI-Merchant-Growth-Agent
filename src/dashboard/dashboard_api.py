"""Phase 7: the dashboard's backend. Two views, one API.

Every response here is read live off data/audit_log.jsonl and
data/experiment/*.parquet at request time -- nothing is cached at
startup, nothing is hand-curated. If the audit log or the Phase 5
output changes (a fresh demo run, a re-run of Phase 5), the next
request reflects it immediately.

Run with (from the repo root, matching every other server here):
    uvicorn src.dashboard.dashboard_api:app --port 8002 --app-dir .

Routes:
    GET /                              the dashboard page
    GET /api/transactions              summary list of every traceable
                                        request_id (newest first)
    GET /api/transactions/{request_id} the full per-transaction view
    GET /api/audit/{request_id}        raw chronological audit trace
                                        (src/audit/trace.py's own render())
    GET /api/aggregate                 live Phase 5 aggregate metrics
    GET /api/raw/audit-log             raw audit_log.jsonl tail
    GET /api/raw/decisions             raw decision events only
    GET /api/raw/parquet-files         data/experiment/*.parquet file listing
    GET /api/raw/docs                  real docs/README files, with descriptions
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from aggregate import compute_aggregate  # noqa: E402

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "src" / "audit"))
sys.path.insert(0, str(_ROOT / "src" / "payments"))
sys.path.insert(0, str(_ROOT / "src" / "decision_engine"))
sys.path.insert(0, str(_ROOT / "src" / "agents"))
from trace import trace_transaction, render  # noqa: E402
from audit import read_audit_log  # noqa: E402
import engine  # noqa: E402  (PRODUCT_LOOKUP: the one real price/category table)
from demo_graph import start_conversational_checkout, resolve_conversational_checkout  # noqa: E402

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

app = FastAPI()

STATIC_DIR = Path(__file__).resolve().parent / "static"


def _price_and_desc(product_id):
    """Real category/price for one product_id, straight off
    models/product_lookup.parquet (the same table engine.py and
    catalogue.py already use) -- dunnhumby has no brand-name field, only
    commodity_desc/sub_commodity_desc, see catalogue.py's own docstring.
    Returns None if the id isn't in the table (shouldn't happen for a
    chosen offer post-Phase-6-bounding, but a dashboard reads live data
    and does not assume)."""
    if product_id is None or product_id not in engine.PRODUCT_LOOKUP.index:
        return None
    row = engine.PRODUCT_LOOKUP.loc[product_id]
    return {
        "product_id": int(product_id),
        "commodity_desc": str(row["commodity_desc"]).title(),
        "sub_commodity_desc": str(row["sub_commodity_desc"]).title(),
        "price": float(row["price"]),
    }


def _basket_value(product_ids):
    """Sum of real catalogue prices for a list of product ids, ids not in
    the table dropped -- same policy as src/experiment/basket_pool.py."""
    if not product_ids:
        return 0.0, 0
    valid = [p for p in product_ids if p in engine.PRODUCT_LOOKUP.index]
    if not valid:
        return 0.0, 0
    return float(engine.PRODUCT_LOOKUP.loc[valid, "price"].sum()), len(product_ids)


def _short_reason(reason_text):
    """The decision's real reason_text is one long technical sentence
    (see engine.py's cross_sell_candidates/upsell_candidates). Split off
    its first clause as a headline for the "Why?" line; the full string
    stays available underneath -- this is a display split of real text,
    not a rewritten or invented explanation."""
    if not reason_text:
        return None, None
    parts = reason_text.split("; ", 1)
    headline = parts[0].strip()
    rest = parts[1].strip() if len(parts) > 1 else None
    return headline, rest


def _checkout_display(state):
    """Customer-safe view of one conversational-checkout turn: real
    product names/prices off the same table _price_and_desc already
    serves the Per-Transaction view with, never the agent's own prose
    reply (that text is written for the audit log, not a shopper -- see
    merchant_agent.py's prompt) and never the engine's internal reasoning
    unless the caller explicitly expands it (offer_why_headline/_full,
    same split _short_reason already does for the dashboard)."""
    display = {}
    cart_before = state.get("cart_before") or []
    display["base_products"] = [p for p in (_price_and_desc(pid) for pid in cart_before) if p]

    decision = state.get("decision")
    chosen = decision["chosen_action"] if decision else None
    if chosen and chosen.get("action") != "no_action":
        headline, full_reason = _short_reason(decision.get("reason_text"))
        display["offer_action"] = chosen["action"]
        display["offer_product"] = _price_and_desc(chosen.get("product_id"))
        display["offer_p_accept"] = chosen.get("p_accept")
        display["offer_why_headline"] = headline
        display["offer_why_full"] = full_reason

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


def _outcome_label(gate, outcome_events, payment_events):
    """Compose the plain-English CUSTOMER OUTCOME line from whatever the
    audit log actually recorded -- gate.accepted (offer accepted/declined/
    not applicable) plus the terminal payment outcome, if one has been
    logged yet. A transaction can legitimately have no terminal outcome
    yet (checkout page opened, payment not completed) -- shown as
    "pending", not guessed. Returns (final_status, gate_outcome, text):
    final_status is the payment-side state ("All Payment Status" filter),
    gate_outcome is the offer-side state ("All Outcomes" filter) -- two
    distinct real fields, not the same thing reused twice."""
    accepted = None if gate is None else gate.get("accepted")
    if accepted is True:
        offer_part, gate_outcome = "Offer accepted", "accepted"
    elif accepted is False:
        offer_part, gate_outcome = "Offer declined", "declined"
    elif gate is None:
        offer_part, gate_outcome = "No gate record yet", "unknown"
    else:
        offer_part, gate_outcome = "No offer made", "no_offer"

    final_status = outcome_events[-1]["final_status"] if outcome_events else None
    if final_status == "completed":
        payment_part = "payment captured"
    elif final_status == "failed":
        payment_part = "payment failed"
    elif final_status == "abandoned":
        payment_part = "checkout abandoned"
    elif payment_events:
        payment_part = f"payment {payment_events[-1].get('status', 'pending')}"
    else:
        payment_part = "payment pending"

    return final_status or "pending", gate_outcome, f"{offer_part} → {payment_part}"


def _transaction_view(request_id: str):
    trace = trace_transaction(request_id)
    if not trace["found"]:
        return None

    intent = trace["intent"]
    decision = trace["decision"]
    gate = trace["gate"]
    cart = trace["cart"]

    cart_before_ids = cart["cart_before"] if cart else (decision["basket_product_ids"] if decision else [])
    cart_after_ids = cart["cart_after"] if cart else cart_before_ids
    before_value, before_items = _basket_value(cart_before_ids)
    after_value, after_items = _basket_value(cart_after_ids)

    offer = None
    if decision:
        headline, full_reason = _short_reason(decision.get("reason_text"))
        product = _price_and_desc(decision.get("chosen_product_id"))
        offer = {
            "action": decision.get("chosen_action"),
            "product": product,
            "product_id": decision.get("chosen_product_id"),
            "why_headline": headline,
            "why_full": full_reason,
            "expected_incremental_value": decision.get("incremental_value"),
            "expected_value": decision.get("expected_value"),
            "p_accept": decision.get("p_accept"),
            "bound_rejected": bool(decision.get("bound_rejected")),
            "rejected_action": decision.get("rejected_action"),
        }

    final_status, gate_outcome, outcome_text = _outcome_label(gate, trace["outcome_events"], trace["payment_events"])

    return {
        "request_id": request_id,
        "timestamp": intent["timestamp"] if intent else None,
        "household_key": intent["household_key"] if intent else None,
        "raw_query": intent["raw_query"] if intent else None,
        "basket_before": {"items": before_items, "value": before_value},
        "basket_after": {"items": after_items, "value": after_value},
        "offer": offer,
        "final_status": final_status,
        "gate_outcome": gate_outcome,
        "outcome_text": outcome_text,
        "razorpay_order_id": trace["razorpay_order_id"],
        "has_audit_trail": True,
    }


@app.get("/")
def dashboard_page():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/transactions")
def list_transactions():
    records = read_audit_log()
    intents = [r for r in records if r.get("event") == "intent"]
    intents.sort(key=lambda r: r["timestamp"], reverse=True)

    summaries = []
    for intent in intents:
        request_id = intent["request_id"]
        view = _transaction_view(request_id)
        if view is None:
            continue
        summaries.append({
            "request_id": request_id,
            "timestamp": view["timestamp"],
            "household_key": view["household_key"],
            "raw_query": view["raw_query"],
            "action": view["offer"]["action"] if view["offer"] else None,
            "bound_rejected": bool(view["offer"]["bound_rejected"]) if view["offer"] else False,
            "final_status": view["final_status"],
            "gate_outcome": view["gate_outcome"],
        })
    return JSONResponse({"transactions": summaries, "count": len(summaries)})


@app.get("/api/transactions/{request_id}")
def get_transaction(request_id: str):
    view = _transaction_view(request_id)
    if view is None:
        raise HTTPException(status_code=404, detail=f"no audit events found for request_id={request_id}")
    return JSONResponse(view)


@app.get("/api/audit/{request_id}")
def get_audit_trace(request_id: str):
    trace = trace_transaction(request_id)
    if not trace["found"]:
        raise HTTPException(status_code=404, detail=f"no audit events found for request_id={request_id}")
    return JSONResponse({"request_id": request_id, "rendered": render(trace)})


@app.get("/api/aggregate")
def get_aggregate():
    return JSONResponse(compute_aggregate())


# ---- Conversational checkout: chat UI backend, same catalogue and same
# growth-decision engine as the CLI demo, just reached by typing instead of
# by --household-key/--intent flags. See demo_graph.py for the actual
# agent logic; these two routes are thin wrappers over it. ----

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
    result["display"] = _checkout_display(result)
    return JSONResponse(result)


@app.post("/api/checkout/resolve")
async def checkout_resolve(body: CheckoutResolveBody):
    try:
        result = await resolve_conversational_checkout(body.request_id, body.accepted)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"checkout resolution failed: {e}")
    result["display"] = _checkout_display(result)
    return JSONResponse(result)


@app.get("/api/checkout/razorpay-key")
def checkout_razorpay_key():
    # RAZORPAY_KEY_ID is Razorpay's *public* key (the same value
    # checkout_api.py already embeds directly in the checkout page's HTML
    # source) -- safe to serve to the browser so the conversational
    # checkout tab can open the real payment modal inline, in this same
    # tab, instead of a separate localhost:8001 page. The secret key is
    # never read here or sent anywhere near the browser.
    key_id = os.environ.get("RAZORPAY_KEY_ID", "")
    if not key_id:
        raise HTTPException(status_code=503, detail="RAZORPAY_KEY_ID not configured on this server")
    return JSONResponse({"key_id": key_id})


# ---- Quick Links: real project data, not decorative dead links ----

@app.get("/api/raw/audit-log")
def raw_audit_log(limit: int = 100):
    """The literal tail of data/audit_log.jsonl, newest last (as written) --
    exactly what the exit-criterion sentence in docs/audit_schema.md means
    by "traceable from the log alone", shown unfiltered rather than only
    through the per-transaction reconstruction."""
    records = read_audit_log()
    tail = records[-limit:]
    return JSONResponse({
        "total_events": len(records),
        "shown": len(tail),
        "events": tail,
    })


@app.get("/api/raw/decisions")
def raw_decisions(limit: int = 100):
    """Every decision event logged so far, most recent first -- the
    engine's own raw output records (chosen_action, candidate_actions,
    reason), unformatted, not the display-shaped version the per-
    transaction view builds from the same events."""
    records = read_audit_log()
    decisions = [r for r in records if r.get("event") == "decision"]
    decisions.sort(key=lambda r: r["timestamp"], reverse=True)
    return JSONResponse({
        "total_decisions": len(decisions),
        "shown": min(limit, len(decisions)),
        "decisions": decisions[:limit],
    })


@app.get("/api/raw/parquet-files")
def raw_parquet_files():
    """Real files under data/experiment/, with their real row counts and
    sizes read off disk right now -- not a hand-typed file list. Row
    count comes from the parquet file's own footer metadata (pyarrow),
    not a full data read, so this stays fast even for the larger files."""
    import pyarrow.parquet as pq

    exp_dir = _ROOT / "data" / "experiment"
    files = []
    if exp_dir.exists():
        for p in sorted(exp_dir.glob("*.parquet")):
            try:
                rows = pq.ParquetFile(p).metadata.num_rows
            except Exception:
                rows = None
            files.append({
                "name": p.name,
                "bytes": p.stat().st_size,
                "rows": rows,
            })
    return JSONResponse({"directory": "data/experiment/", "files": files})


@app.get("/api/raw/docs")
def raw_docs():
    """The real docs/ and top-level markdown files this project actually
    has, with a one-line factual description of each -- not a rendered
    fetch of their content (kept light on purpose), just an honest map of
    what exists and where, so "Documentation" points somewhere real."""
    candidates = [
        (_ROOT / "README.md", "Project overview, setup, and a phase-by-phase build log."),
        (_ROOT / "docs" / "phase5_results.md", "Full Phase 5 methodology and results (the numbers behind the Aggregate view)."),
        (_ROOT / "docs" / "audit_schema.md", "The audit log's event schema -- every event type this dashboard reads."),
        (_ROOT / "docs" / "objective_function.md", "The decision engine's objective function and constants."),
        (_ROOT / "docs" / "data_dictionary.md", "Field-level documentation for the underlying datasets."),
        (_ROOT / "docs" / "demo_script.md", "The scripted live-demo sequence this dashboard is meant to support."),
    ]
    docs = [
        {"path": str(p.relative_to(_ROOT)), "description": desc, "bytes": p.stat().st_size}
        for p, desc in candidates if p.exists()
    ]
    return JSONResponse({"docs": docs})
