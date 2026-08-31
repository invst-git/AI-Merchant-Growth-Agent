import asyncio
import random
import sys
import uuid
from pathlib import Path
from typing import Optional, TypedDict

from dotenv import load_dotenv
from langgraph.graph import END, START, StateGraph

from buyer_agent import run_buyer
from merchant_agent import run_merchant
from checkout_agent import run_checkout

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "audit"))
from audit_log import log_intent, log_decision, log_gate, log_cart, log_checkout_link  # noqa: E402

load_dotenv()  # picks up ANTHROPIC_API_KEY, RAZORPAY_KEY_ID/SECRET from .env at the repo root


class DemoState(TypedDict):
    request_id: str
    household_key: int
    buyer_intent: str
    buyer_request: Optional[str]
    merchant_reply: Optional[str]
    decision: Optional[dict]
    cart_before: Optional[list]
    cart_after: Optional[list]
    accepted: Optional[bool]
    resolution_note: Optional[str]
    checkout_reply: Optional[str]
    checkout_order: Optional[dict]


def buyer_node(state: DemoState) -> dict:
    buyer_request = run_buyer(state["buyer_intent"])
    log_intent(state["request_id"], state["household_key"], state["buyer_intent"])
    return {"buyer_request": buyer_request}


def merchant_node(state: DemoState) -> dict:
    result = run_merchant(state["household_key"], state["buyer_request"])
    cart_before = result["basket_product_ids"] or []
    if result["decision"] is not None:
        log_decision(state["request_id"], state["household_key"], cart_before, result["decision"])
    return {
        "merchant_reply": result["reply"],
        "decision": result["decision"],
        "cart_before": cart_before,
    }


def resolve_node(state: DemoState) -> dict:
    # This is Phase 6's explicit accept step (the "gate"): checkout_node
    # only ever runs after this returns, and every branch below logs a
    # gate event before returning, so the audit trail always shows what
    # was offered and whether it was accepted before any Razorpay order
    # gets created -- nothing charges silently.
    request_id = state["request_id"]
    cart_before = state["cart_before"] or []
    decision = state["decision"]

    if decision is None:
        log_gate(request_id, offer_action=None, p_accept=None, accepted=None,
                  mechanism="n/a", note="merchant agent never called get_growth_decision, nothing to resolve")
        log_cart(request_id, cart_before, cart_before)
        return {
            "cart_after": cart_before,
            "accepted": None,
            "resolution_note": "merchant agent never called get_growth_decision, nothing to resolve",
        }

    chosen = decision["chosen_action"]
    if chosen["action"] == "no_action":
        note = "no offer was made (no_action), cart unchanged"
        if chosen.get("bound_rejected"):
            note += "; the engine's top candidate was blocked by the Phase 6 catalogue bounding rule"
        log_gate(request_id, offer_action="no_action", p_accept=None, accepted=None,
                  mechanism="n/a", note=note)
        log_cart(request_id, cart_before, cart_before)
        return {
            "cart_after": cart_before,
            "accepted": None,
            "resolution_note": note,
        }

    p_accept = chosen["p_accept"]
    accepted = random.random() < p_accept
    offered_product_id = chosen["product_id"]
    cart_after = cart_before + [offered_product_id] if accepted else list(cart_before)
    note = (
        f"{chosen['action']} offer (p_accept={p_accept:.0%}) was "
        f"{'accepted' if accepted else 'declined'} (seeded random draw, placeholder for Phase 5)"
    )
    log_gate(request_id, offer_action=chosen["action"], p_accept=p_accept, accepted=accepted,
              mechanism="seeded_random_draw_vs_real_p_accept", note=note)
    log_cart(request_id, cart_before, cart_after)
    return {
        "cart_after": cart_after,
        "accepted": accepted,
        "resolution_note": note,
    }


async def checkout_node(state: DemoState) -> dict:
    cart_after = state["cart_after"] or []
    result = await run_checkout(state["household_key"], cart_after)
    order = result["order"]
    if order and order.get("order_id"):
        # links this request_id to the real razorpay_order_id the moment it
        # exists, before the buyer ever reaches the browser -- this is what
        # lets trace.py join the agent-side record to whatever the browser
        # and Razorpay's webhook report later (checkout_api.py looks this
        # link up in reverse to log the final outcome against it).
        log_checkout_link(state["request_id"], order["order_id"])
    return {"checkout_reply": result["reply"], "checkout_order": order}


def build_demo_graph():
    graph = StateGraph(DemoState)
    graph.add_node("buyer", buyer_node)
    graph.add_node("merchant", merchant_node)
    graph.add_node("resolve", resolve_node)
    graph.add_node("checkout", checkout_node)
    graph.add_edge(START, "buyer")
    graph.add_edge("buyer", "merchant")
    graph.add_edge("merchant", "resolve")
    graph.add_edge("resolve", "checkout")
    graph.add_edge("checkout", END)
    return graph.compile()


async def run_demo(household_key: int, buyer_intent: str, seed: int = 7) -> dict:
    random.seed(seed)
    graph = build_demo_graph()
    request_id = str(uuid.uuid4())
    result = await graph.ainvoke({
        "request_id": request_id, "household_key": household_key, "buyer_intent": buyer_intent,
    })
    result["request_id"] = request_id
    return result


# --- Conversational checkout (chat) -------------------------------------
# Same buyer -> merchant flow as run_demo above, but split at the offer so
# a live chat can show the merchant's offer and wait for the customer's own
# yes/no instead of resolve_node's seeded random draw. Nothing above this
# line is touched -- the CLI path (_main, run_demo) behaves exactly as
# before; this is purely additive.

_PENDING_OFFERS: dict[str, DemoState] = {}


async def start_conversational_checkout(household_key: int, buyer_intent: str) -> dict:
    request_id = str(uuid.uuid4())
    state: DemoState = {
        "request_id": request_id, "household_key": household_key, "buyer_intent": buyer_intent,
    }
    state.update(buyer_node(state))
    state.update(merchant_node(state))

    decision = state.get("decision")
    chosen = decision["chosen_action"] if decision else None

    if chosen is None or chosen["action"] == "no_action":
        # Nothing to ask the customer -- resolve_node's no-decision and
        # no_action branches are fully deterministic (no random draw), so
        # they're safe to reuse as-is, then go straight to checkout.
        state.update(resolve_node(state))
        state.update(await checkout_node(state))
        state["awaiting_reply"] = False
        return state

    _PENDING_OFFERS[request_id] = state
    return {**state, "awaiting_reply": True}


async def resolve_conversational_checkout(request_id: str, accepted: bool) -> dict:
    state = _PENDING_OFFERS.pop(request_id, None)
    if state is None:
        raise KeyError(f"no pending offer for request_id={request_id!r} (already resolved, or never existed)")

    cart_before = state["cart_before"] or []
    chosen = state["decision"]["chosen_action"]
    cart_after = cart_before + [chosen["product_id"]] if accepted else list(cart_before)
    note = (
        f"{chosen['action']} offer (p_accept={chosen['p_accept']:.0%}) was "
        f"{'accepted' if accepted else 'declined'} by the customer in the conversational checkout"
    )
    log_gate(request_id, offer_action=chosen["action"], p_accept=chosen["p_accept"], accepted=accepted,
              mechanism="customer_reply_via_chat", note=note)
    log_cart(request_id, cart_before, cart_after)
    state.update({"cart_after": cart_after, "accepted": accepted, "resolution_note": note})

    state.update(await checkout_node(state))
    state["awaiting_reply"] = False
    return state


async def _main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--household-key", type=int, default=1)
    parser.add_argument("--intent", default="I want to make spaghetti for dinner tonight.")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    result = await run_demo(household_key=args.household_key, buyer_intent=args.intent, seed=args.seed)
    print("request id (for tracing, see src/audit/trace.py):", result["request_id"])
    print()
    print("buyer request:", result["buyer_request"])
    print()
    print("merchant reply:", result["merchant_reply"])
    print()
    print("chosen action:", result["decision"]["chosen_action"]["action"] if result["decision"] else "none")
    print("cart before:", result["cart_before"])
    print("cart after:", result["cart_after"])
    print("resolution:", result["resolution_note"])
    print()
    print("checkout reply:", result["checkout_reply"])
    order = result["checkout_order"]
    if order and "checkout_url" in order:
        print()
        print("To complete this Test Mode payment, make sure the checkout")
        print("page is running (uvicorn src.payments.checkout_api:app")
        print("--port 8001 --app-dir . , in a separate terminal), then open:")
        print(" ", order["checkout_url"])
        print("Use success@razorpay to rehearse a successful payment, or")
        print("failure@razorpay to rehearse a deliberately failed one.")


if __name__ == "__main__":
    asyncio.run(_main())
