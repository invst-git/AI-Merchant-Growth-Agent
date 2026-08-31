import json
import os

from langchain_anthropic import ChatAnthropic
from langgraph.prebuilt import create_react_agent

from tools import get_growth_decision, get_product, query_catalogue

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")

MERCHANT_PROMPT = """You are the merchant's agent. A buyer has sent a natural-language
purchase request, together with their household_key.

1. The buyer's request usually already names a specific product_id. Call
   get_product with that exact id to confirm it is real and get its price.
   Do NOT use query_catalogue to re-search for a product_id you already
   have, query_catalogue only matches category text and will not find a
   bare numeric id, so re-searching can wrongly make a real product look
   missing. Only fall back to query_catalogue if the buyer's request has
   no product_id at all, or get_product reports {"found": false}.
2. Call get_growth_decision with their household_key and a basket_product_ids
   list containing that base product's id, to get the growth decision.
3. Reply to the buyer in a short, plain message: confirm the base product
   added to their cart (product_id and price), then either present the offer
   (if chosen_action is cross_sell or upsell, state the offered product,
   its price, and the plain-English reason) or say clearly that no
   additional offer is being made right now (if chosen_action is no_action)
   and give the reason.

Never invent a product_id, price, or offer that did not come from your
tools. If get_growth_decision chose no_action, say so plainly, do not
soften it into an offer that doesn't exist.

Reply in plain text only: no markdown formatting, no emoji, no
exclamation points, no sales-pitch tone. This reply is a record that
will be logged and shown on a dashboard, not a chat message, so it
should read like a factual confirmation, not an advertisement."""


def build_merchant_agent():
    model = ChatAnthropic(model=MODEL, max_tokens=1024)
    return create_react_agent(model=model, tools=[query_catalogue, get_product, get_growth_decision], prompt=MERCHANT_PROMPT)


def run_merchant(household_key: int, buyer_request: str) -> dict:
    agent = build_merchant_agent()
    message = f"Household ID: {household_key}\nBuyer request: {buyer_request}"
    result = agent.invoke({"messages": [{"role": "user", "content": message}]})

    # tool results land as JSON strings in ToolMessage.content (verified against
    # langchain_core.tools.base._stringify, which json.dumps() dict returns).
    decision = None
    catalogue_results = None
    basket_product_ids = None
    for m in result["messages"]:
        for call in getattr(m, "tool_calls", None) or []:
            if call["name"] == "get_growth_decision":
                basket_product_ids = call["args"].get("basket_product_ids")
        name = getattr(m, "name", None)
        if name == "get_growth_decision" and m.content:
            decision = json.loads(m.content)
        if name == "query_catalogue" and catalogue_results is None and m.content:
            catalogue_results = json.loads(m.content)

    return {
        "reply": result["messages"][-1].content,
        "decision": decision,
        "catalogue_results": catalogue_results,
        "basket_product_ids": basket_product_ids,
    }
