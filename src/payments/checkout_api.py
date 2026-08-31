"""Phase 4: the one browser step no backend script can substitute for
(verified against Razorpay's own docs: Standard Checkout requires
loading checkout.js and completing its modal, a backend alone cannot
finish a payment). Everything on this page's server side is
deterministic Python, not agent-driven, same reasoning as resolve_node
in demo_graph.py: signature verification and capture are correctness
and security critical, not the kind of decision an LLM should make.

Run with (from the repo root, matching every other script here):
    uvicorn src.payments.checkout_api:app --port 8001 --app-dir .

Routes:
    GET  /checkout/{order_id}   the checkout.js page for one order
    POST /checkout/verify       success callback from checkout.js's handler
    POST /checkout/failed       failure callback from checkout.js's payment.failed event
    POST /webhooks/razorpay     payment.captured webhook, the plan's explicit second
                                 confirmation path (needs RAZORPAY_WEBHOOK_SECRET and a
                                 public URL registered in the Dashboard to fire for real,
                                 see README)
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import razorpay
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from audit import log_payment_event
from checkout import MAX_ORDER_PAISE
from razorpay_mcp import RazorpayMCPError, get_razorpay_tools, parse_mcp_result

load_dotenv()

RAZORPAY_KEY_ID = os.environ["RAZORPAY_KEY_ID"]
RAZORPAY_KEY_SECRET = os.environ["RAZORPAY_KEY_SECRET"]
RAZORPAY_WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")

razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

app = FastAPI()

CHECKOUT_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Checkout</title>
<script src="https://checkout.razorpay.com/v1/checkout.js"></script></head>
<body>
<h3>AI Merchant Growth Agent — Test Mode checkout</h3>
<p>Order {order_id}, amount {amount_display} {currency}.</p>
<p>If UPI is offered, use test UPI ID <code>success@razorpay</code> or
<code>failure@razorpay</code>. If UPI isn't offered (some Test Mode
accounts don't have it provisioned), use card
<code>4111 1111 1111 1111</code>, any future expiry, any CVV, then use
the Success/Failure buttons Razorpay's own Test Mode confirmation
screen shows after you submit the card.</p>
<div id="result"></div>
<script>
var options = {{
    "key": "{key_id}",
    "amount": "{amount}",
    "currency": "{currency}",
    "order_id": "{order_id}",
    "name": "AI Merchant Growth Agent (Test Mode)",
    "handler": function (response) {{
        fetch("/checkout/verify", {{
            method: "POST",
            headers: {{"Content-Type": "application/json"}},
            body: JSON.stringify(response),
        }}).then(function (r) {{ return r.json(); }}).then(function (data) {{
            document.getElementById("result").innerText =
                "verified: " + data.verified + ", status: " + data.status;
        }});
    }},
    "modal": {{
        "ondismiss": function () {{
            document.getElementById("result").innerText = "checkout dismissed without completing payment";
        }}
    }},
}};
var rzp = new Razorpay(options);
rzp.on("payment.failed", function (response) {{
    fetch("/checkout/failed", {{
        method: "POST",
        headers: {{"Content-Type": "application/json"}},
        body: JSON.stringify(response.error),
    }}).then(function (r) {{ return r.json(); }}).then(function (data) {{
        document.getElementById("result").innerText =
            "payment failed (logged): " + data.failure_reason;
    }});
}});
rzp.open();
</script>
</body></html>"""


@app.get("/checkout/{order_id}", response_class=HTMLResponse)
def checkout_page(order_id: str, amount: int, currency: str = "INR"):
    return CHECKOUT_PAGE.format(
        order_id=order_id,
        amount=amount,
        amount_display=f"{amount / 100:.2f}",
        currency=currency,
        key_id=RAZORPAY_KEY_ID,
    )


@app.post("/checkout/verify")
async def verify_checkout(request: Request):
    body = await request.json()
    order_id = body.get("razorpay_order_id")
    payment_id = body.get("razorpay_payment_id")
    signature = body.get("razorpay_signature")

    try:
        razorpay_client.utility.verify_payment_signature({
            "razorpay_order_id": order_id,
            "razorpay_payment_id": payment_id,
            "razorpay_signature": signature,
        })
        verified = True
    except razorpay.errors.SignatureVerificationError:
        verified = False

    if not verified:
        record = log_payment_event({
            "event": "checkout_verify",
            "razorpay_order_id": order_id,
            "razorpay_payment_id": payment_id,
            "signature_verified": False,
            "status": "failed",
            "failure_reason": "signature verification failed, payment rejected",
        })
        return JSONResponse({"verified": False, "status": "failed"})

    try:
        tools = await get_razorpay_tools("fetch_payment", "capture_payment")
        payment = parse_mcp_result(await tools["fetch_payment"].ainvoke({"payment_id": payment_id}))

        if payment["status"] == "authorized":
            amount = payment["amount"]
            if amount > MAX_ORDER_PAISE:
                log_payment_event({
                    "event": "checkout_verify",
                    "razorpay_order_id": order_id,
                    "razorpay_payment_id": payment_id,
                    "signature_verified": True,
                    "status": "failed",
                    "amount": amount,
                    "failure_reason": f"amount {amount} exceeds spend cap {MAX_ORDER_PAISE}, capture refused",
                })
                return JSONResponse({"verified": True, "status": "capture_refused_over_cap"})

            await tools["capture_payment"].ainvoke({
                "payment_id": payment_id,
                "amount": amount,
                "currency": payment["currency"],
            })
            payment = parse_mcp_result(await tools["fetch_payment"].ainvoke({"payment_id": payment_id}))
    except RazorpayMCPError as e:
        # Signature checked out, but Razorpay itself couldn't confirm or
        # capture the payment (bad id, transient API error, etc). Log it
        # as a failure rather than crash the request, same "handled
        # gracefully" bar as a deliberate failure@razorpay decline.
        log_payment_event({
            "event": "checkout_verify",
            "razorpay_order_id": order_id,
            "razorpay_payment_id": payment_id,
            "signature_verified": True,
            "status": "failed",
            "failure_reason": f"Razorpay confirm/capture failed: {e}",
        })
        return JSONResponse({"verified": True, "status": "failed"})

    log_payment_event({
        "event": "checkout_verify",
        "razorpay_order_id": order_id,
        "razorpay_payment_id": payment_id,
        "signature_verified": True,
        "status": payment["status"],
        "amount": payment.get("amount"),
        "currency": payment.get("currency"),
    })

    return JSONResponse({"verified": True, "status": payment["status"]})


@app.post("/checkout/failed")
async def checkout_failed(request: Request):
    error = await request.json()
    metadata = error.get("metadata", {})
    failure_reason = error.get("description") or error.get("reason") or "payment failed"

    log_payment_event({
        "event": "checkout_verify",
        "razorpay_order_id": metadata.get("order_id"),
        "razorpay_payment_id": metadata.get("payment_id"),
        "signature_verified": False,
        "status": "failed",
        "failure_reason": failure_reason,
    })

    return JSONResponse({"status": "failed", "failure_reason": failure_reason})


# Registered in the Razorpay Dashboard as either spelling turned out to
# matter in practice: a real delivery attempt hit /webhook/razorpay
# (singular) and got a plain 404, invisible in the audit log because it
# never reached this function at all. Both paths route here now so a
# Dashboard URL typo like that can't silently swallow every delivery.
@app.post("/webhooks/razorpay")
@app.post("/webhook/razorpay")
async def razorpay_webhook(request: Request):
    # Both failure branches below used to return before logging anything,
    # which is exactly the blind spot that made a real missed webhook
    # (RAZORPAY_WEBHOOK_SECRET added to .env after this server was
    # already running, so the old empty value was still in memory) look
    # like total silence instead of a diagnosable event. Log first, then
    # respond, on every path now.
    if not RAZORPAY_WEBHOOK_SECRET:
        log_payment_event({
            "event": "webhook_rejected",
            "status": "failed",
            "failure_reason": "RAZORPAY_WEBHOOK_SECRET not configured on this server "
                               "(if you just added it to .env, restart uvicorn, env vars "
                               "are only read at process startup)",
        })
        raise HTTPException(status_code=503, detail="RAZORPAY_WEBHOOK_SECRET not configured")

    body_bytes = await request.body()
    signature = request.headers.get("x-razorpay-signature", "")

    try:
        razorpay_client.utility.verify_webhook_signature(
            body_bytes.decode(), signature, RAZORPAY_WEBHOOK_SECRET
        )
    except razorpay.errors.SignatureVerificationError:
        log_payment_event({
            "event": "webhook_rejected",
            "status": "failed",
            "failure_reason": "webhook signature verification failed, check "
                               "RAZORPAY_WEBHOOK_SECRET matches the Dashboard exactly",
        })
        raise HTTPException(status_code=400, detail="invalid webhook signature")

    payload = await request.json()
    event = payload.get("event")

    if event == "payment.captured":
        payment_entity = payload["payload"]["payment"]["entity"]
        log_payment_event({
            "event": "webhook_payment_captured",
            "razorpay_order_id": payment_entity.get("order_id"),
            "razorpay_payment_id": payment_entity.get("id"),
            "signature_verified": True,
            "status": "captured",
            "amount": payment_entity.get("amount"),
            "currency": payment_entity.get("currency"),
        })

    return JSONResponse({"received": True})
