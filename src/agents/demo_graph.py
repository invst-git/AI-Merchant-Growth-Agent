"""Phase 3: the top-level demo graph. Wires the Buyer Agent and
Merchant Agent together as two nodes in one LangGraph StateGraph, plus
a deterministic resolve step that tracks cart state before and after,
since that diff is what the Phase 7 dashboard will read.

resolve_node's accept/decline draw is a placeholder for this phase only,
a seeded random draw against p_accept so demo runs are repeatable. It is
NOT the Phase 5 experiment engine, that phase needs a real data-grounded
simulator, not a coin flip; this one only needs to prove the graph
produces a correct before/after cart diff and handles no_action cleanly.

Run: python3 src/agents/demo_graph.py (needs ANTHROPIC_API_KEY in .env,
costs real API calls, not run by me).
"""

import random
from typing import Optional, TypedDict

from dotenv import load_dotenv
from langgraph.graph import END, START, StateGraph

from buyer_agent import run_buyer
from merchant_agent import run_merchant

load_dotenv()  # picks up ANTHROPIC_API_KEY from .env at the repo root


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


def build_demo_graph():
    graph = StateGraph(DemoState)
    graph.add_node("buyer", buyer_node)
    graph.add_node("merchant", merchant_node)
    graph.add_node("resolve", resolve_node)
    graph.add_edge(START, "buyer")
    graph.add_edge("buyer", "merchant")
    graph.add_edge("merchant", "resolve")
    graph.add_edge("resolve", END)
    return graph.compile()


def run_demo(household_key: int, buyer_intent: str, seed: int = 7) -> dict:
    random.seed(seed)
    graph = build_demo_graph()
    return graph.invoke({"household_key": household_key, "buyer_intent": buyer_intent})


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--household-key", type=int, default=1)
    parser.add_argument("--intent", default="I want to make spaghetti for dinner tonight.")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    result = run_demo(household_key=args.household_key, buyer_intent=args.intent, seed=args.seed)
    print("buyer request:", result["buyer_request"])
    print()
    print("merchant reply:", result["merchant_reply"])
    print()
    print("chosen action:", result["decision"]["chosen_action"]["action"] if result["decision"] else "none")
    print("cart before:", result["cart_before"])
    print("cart after:", result["cart_after"])
    print("resolution:", result["resolution_note"])
