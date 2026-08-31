import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "payments"))
from audit import read_audit_log  # noqa: E402


def trace_transaction(request_id: str) -> dict:
    records = read_audit_log()
    own = [r for r in records if r.get("request_id") == request_id]

    order_id = next((r["razorpay_order_id"] for r in own if r.get("event") == "checkout_order_linked"), None)
    payment_events = []
    if order_id:
        payment_events = [
            r for r in records
            if r.get("razorpay_order_id") == order_id and r.get("request_id") != request_id
        ]

    by_event = {r["event"]: r for r in own if r["event"] in ("intent", "decision", "gate", "cart")}
    all_events = sorted(own + payment_events, key=lambda r: r["timestamp"])

    return {
        "request_id": request_id,
        "found": bool(own),
        "razorpay_order_id": order_id,
        "intent": by_event.get("intent"),
        "decision": by_event.get("decision"),
        "gate": by_event.get("gate"),
        "cart": by_event.get("cart"),
        "payment_events": payment_events,
        "outcome_events": [r for r in own if r.get("event") == "outcome"],
        "all_events_chronological": all_events,
    }


def render(trace: dict) -> str:
    if not trace["found"]:
        return f"No audit events found for request_id={trace['request_id']}"

    lines = [f"=== Transaction trace: {trace['request_id']} ==="]

    intent = trace["intent"]
    if intent:
        lines.append(f"\n1. INTENT (household {intent['household_key']}): \"{intent['raw_query']}\"")
    else:
        lines.append("\n1. INTENT: no record (merchant agent may not have been reached)")

    decision = trace["decision"]
    if decision:
        lines.append(
            f"\n2. DECISION: chose {decision['chosen_action']}"
            + (f" (product {decision['chosen_product_id']})" if decision.get("chosen_product_id") else "")
            + f"\n   expected_value={decision.get('expected_value')}, p_accept={decision.get('p_accept')}"
            + f"\n   reason: {decision.get('reason_text')}"
        )
        if decision.get("bound_rejected"):
            lines.append(f"   [Phase 6 bound rejected the engine's top candidate: {decision.get('rejected_action')}]")
    else:
        lines.append("\n2. DECISION: no record")

    gate = trace["gate"]
    if gate:
        lines.append(
            f"\n3. GATE (explicit accept step): offer={gate.get('offer_action')}, "
            f"accepted={gate.get('accepted')} ({gate.get('mechanism')})\n   {gate.get('note')}"
        )
    else:
        lines.append("\n3. GATE: no record")

    cart = trace["cart"]
    if cart:
        lines.append(f"\n4. CART: before={cart['cart_before']}  after={cart['cart_after']}  delta={cart['delta']}")
    else:
        lines.append("\n4. CART: no record")

    if trace["razorpay_order_id"]:
        lines.append(f"\n5. RAZORPAY ORDER: {trace['razorpay_order_id']}")
        for ev in trace["payment_events"]:
            lines.append(f"   [{ev['timestamp']}] {ev['event']}: status={ev.get('status')} "
                          f"signature_verified={ev.get('signature_verified')} "
                          f"failure_reason={ev.get('failure_reason')}")
    else:
        lines.append("\n5. RAZORPAY ORDER: no order was created for this transaction")

    outcomes = trace["outcome_events"]
    if outcomes:
        for o in outcomes:
            lines.append(f"\n6. FINAL OUTCOME: {o['final_status']} ({o.get('note')}) at {o['timestamp']}")
    else:
        lines.append("\n6. FINAL OUTCOME: not yet known (no terminal event logged for this request_id)")

    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python3 src/audit/trace.py <request_id>")
        sys.exit(1)
    print(render(trace_transaction(sys.argv[1])))
