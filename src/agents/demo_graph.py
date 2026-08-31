"""Phase 3/4: the top-level demo graph. Wires the Buyer Agent, Merchant
Agent, and (Phase 4) Checkout Agent together as nodes in one LangGraph
StateGraph, plus a deterministic resolve step that tracks cart state
before and after, since that diff is what the Phase 7 dashboard will
read.

resolve_node's accept/decline draw is a placeholder for this phase only,
a seeded random draw against p_accept so demo runs are repeatable. It is
NOT the Phase 5 experiment engine, that phase needs a real data-grounded
simulator, not a coin flip; this one only needs to prove the graph
produces a correct before/after cart diff and handles no_action cleanly.

checkout_node (Phase 4) always runs, even on no_action: the base product
still needs to be paid for regardless of whether an upsell was offered.
It creates a real Razorpay Test Mode order and prints a checkout_url;
completing payment itself needs a browser (verified against Razorpay's
own docs, Standard Checkout cannot be finished server-side), so this
script cannot close that last step by itself. See README for the
uvicorn command that serves that checkout page locally.

The graph runs via ainvoke, not invoke: checkout_node calls an
MCP-backed tool with no sync entry point (verified directly, .invoke()
on one raises NotImplementedError), so run_demo is async.

Run: python3 src/agents/demo_graph.py (needs ANTHROPIC_API_KEY and
RAZORPAY_KEY_ID/SECRET in .env, costs real API calls, not run by me).
"""

import asyncio
import random
from typing import Optional, TypedDict

from dotenv import load_dotenv
from langgraph.graph import END, START, StateGraph

from buyer_agent import run_buyer
from merchant_agent import run_merchant
from checkout_agent import run_checkout

load_dotenv()  # picks up ANTHROPIC_API_KEY, RAZORPAY_KEY_ID/SECRET from .env at the repo root


class DemoState(TypedDict):
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
    return {"buyer_request": run_buyer(state["buyer_intent"])}


def merchant_node(state: DemoState) -> dict:
    result = run_merchant(state["household_key"], state["buyer_request"])
    cart_before = result["basket_product_ids"] or []
    return {
        "merchant_reply": result["reply"],
        "decision": result["decision"],
        "cart_before": cart_before,
    }


def resolve_node(state: DemoState) -> dict:
    cart_before = state["cart_before"] or []
    decision = state["decision"]

    if decision is None:
        return {
            "cart_after": cart_before,
            "accepted": None,
            "resolution_note": "merchant agent never called get_growth_decision, nothing to resolve",
        }

    chosen = decision["chosen_action"]
    if chosen["action"] == "no_action":
        return {
            "cart_after": cart_before,
            "accepted": None,
            "resolution_note": "no offer was made (no_action), cart unchanged",
        }

    p_accept = chosen["p_accept"]
    accepted = random.random() < p_accept
    offered_product_id = chosen["product_id"]
    cart_after = cart_before + [offered_product_id] if accepted else list(cart_before)
    return {
        "cart_after": cart_after,
        "accepted": accepted,
        "resolution_note": (
            f"{chosen['action']} offer (p_accept={p_accept:.0%}) was "
            f"{'accepted' if accepted else 'declined'} (seeded random draw, placeholder for Phase 5)"
        ),
    }


async def checkout_node(state: DemoState) -> dict:
    cart_after = state["cart_after"] or []
    result = await run_checkout(state["household_key"], cart_after)
    return {"checkout_reply": result["reply"], "checkout_order": result["order"]}


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
    return await graph.ainvoke({"household_key": household_key, "buyer_intent": buyer_intent})


async def _main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--household-key", type=int, default=1)
    parser.add_argument("--intent", default="I want to make spaghetti for dinner tonight.")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    result = await run_demo(household_key=args.household_key, buyer_intent=args.intent, seed=args.seed)
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
