import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "payments"))
from audit import AUDIT_LOG_PATH  # noqa: E402  (same file, formalized event types)


def log_event(event: str, request_id: str, **fields) -> dict:
    AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "request_id": request_id,
        **fields,
    }
    with open(AUDIT_LOG_PATH, "a") as f:
        f.write(__import__("json").dumps(record) + "\n")
    return record


def log_intent(request_id: str, household_key: int, raw_query: str) -> dict:
    return log_event("intent", request_id, household_key=household_key, raw_query=raw_query)


def log_decision(request_id: str, household_key: int, basket_product_ids: list, decision: dict) -> dict:
    chosen = decision["chosen_action"]
    return log_event(
        "decision", request_id,
        household_key=household_key,
        basket_product_ids=basket_product_ids,
        candidate_actions=decision["candidate_actions"],
        chosen_action=chosen["action"],
        chosen_product_id=chosen.get("product_id"),
        p_accept=chosen.get("p_accept"),
        incremental_value=chosen.get("incremental_value"),
        expected_value=chosen.get("expected_value"),
        reason_text=chosen.get("reason"),
        bound_rejected=chosen.get("bound_rejected", False),
        rejected_action=chosen.get("rejected_action"),
    )


def log_gate(request_id: str, offer_action: str, p_accept, accepted, mechanism: str, note: str) -> dict:
    """The explicit accept step Phase 6 requires before any Razorpay order
    gets created. offer_action/p_accept describe what was offered (None if
    the decision was already no_action -- there is nothing to gate).
    mechanism records how accepted was determined (this demo path uses a
    seeded random draw against the real p_accept, a placeholder documented
    since Phase 4; Phase 5's own offline replay is the real data-grounded
    version of this same draw, kept separate on purpose)."""
    return log_event(
        "gate", request_id,
        offer_action=offer_action, p_accept=p_accept, accepted=accepted,
        mechanism=mechanism, note=note,
    )


def log_cart(request_id: str, cart_before: list, cart_after: list) -> dict:
    delta = [p for p in cart_after if p not in cart_before]
    return log_event("cart", request_id, cart_before=cart_before, cart_after=cart_after, delta=delta)


def log_checkout_link(request_id: str, razorpay_order_id: str) -> dict:
    return log_event("checkout_order_linked", request_id, razorpay_order_id=razorpay_order_id)


def log_outcome(request_id: str, final_status: str, note: str = "") -> dict:
    return log_event("outcome", request_id, final_status=final_status, note=note)


def find_request_id_for_order(razorpay_order_id: str):
    """Reverse lookup for the payment-side handlers in checkout_api.py:
    given a razorpay_order_id, find which request_id created it, by
    scanning for that order's checkout_order_linked event (written by
    checkout_node the moment create_checkout_order returns, before the
    buyer ever reaches the browser). Returns None if this order was never
    linked (e.g. created outside the demo graph) -- outcome then just
    can't be tied back to a request_id, which is itself worth knowing
    rather than guessing one."""
    from audit import read_audit_log  # local import: payments/audit.py
    for record in read_audit_log():
        if record.get("event") == "checkout_order_linked" and record.get("razorpay_order_id") == razorpay_order_id:
            return record["request_id"]
    return None
