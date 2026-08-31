"""Phase 4: the Checkout Agent. Exactly one tool (create_checkout_order),
mirroring the Buyer Agent's one-tool-only shape, for the same reason: a
narrow tool surface leaves no room for the LLM to improvise around it.
Its only job is to turn a finalized cart into a real Razorpay Test Mode
order and hand back the checkout link, once the buyer/merchant/resolve
steps have already decided what's actually in the cart.

Async because create_checkout_order is async (it calls Razorpay's MCP
server over the network), and an MCP-backed tool has no sync entry
point: verified directly, invoking one via .invoke() outside an agent
raises NotImplementedError. run_checkout must be awaited.
"""

import os

from langchain_anthropic import ChatAnthropic
from langgraph.prebuilt import create_react_agent

from tools import create_checkout_order

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")

CHECKOUT_PROMPT = """You are the merchant's checkout step. You will be given a
household_key and the exact list of product_ids in the buyer's finalized cart.

Call create_checkout_order with exactly those values, no others. Do not
change, add, or drop any product_id, and do not call it more than once.

If the tool returns an error, report that error plainly, do not invent an
order.

Otherwise reply in one short plain sentence: confirm the order was
created, state the amount (amount_display), and give the checkout_url
for the buyer to complete payment. If floor_applied or cap_applied is
true, say so in one clause so it's clear the charged amount was
adjusted from the raw basket total.

Plain text only: no markdown formatting, no emoji, no exclamation
points. This reply is a logged record, not a chat message."""


def build_checkout_agent():
    model = ChatAnthropic(model=MODEL, max_tokens=1024)
    return create_react_agent(model=model, tools=[create_checkout_order], prompt=CHECKOUT_PROMPT)


async def run_checkout(household_key: int, basket_product_ids: list[int]) -> dict:
    agent = build_checkout_agent()
    message = (
        f"Household ID: {household_key}\n"
        f"Finalized basket_product_ids: {basket_product_ids}"
    )
    result = await agent.ainvoke({"messages": [{"role": "user", "content": message}]})

    order = None
    for m in result["messages"]:
        name = getattr(m, "name", None)
        if name == "create_checkout_order" and m.content:
            import json
            order = json.loads(m.content)

    return {
        "reply": result["messages"][-1].content,
        "order": order,
    }
