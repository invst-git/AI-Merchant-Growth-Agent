"""Phase 3: the Buyer Agent. Exactly one tool (query_catalogue), per
the build plan's spec, so the demo is genuinely agent-to-agent rather
than a human typing a request. Given a rough shopping intent, it looks
at what's actually in the catalogue before phrasing its request, so
the request names a real product_id the Merchant Agent can act on.
"""

import os

from langchain_anthropic import ChatAnthropic
from langgraph.prebuilt import create_react_agent

from tools import query_catalogue

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")

BUYER_PROMPT = """You are a shopper. You have a rough intent for what you want to buy.
Use query_catalogue to see what's actually available before deciding exactly what
to ask for, so your request names a real product. Once you know what you want,
reply with exactly one natural-language sentence, addressed to the merchant,
stating your purchase request and naming the specific product_id you want.
Do not add any other commentary, do not explain your search process.
Plain text only: no markdown formatting, no emoji, no exclamation points."""


def build_buyer_agent():
    model = ChatAnthropic(model=MODEL, max_tokens=1024)
    return create_react_agent(model=model, tools=[query_catalogue], prompt=BUYER_PROMPT)


def run_buyer(intent: str) -> str:
    agent = build_buyer_agent()
    result = agent.invoke({"messages": [{"role": "user", "content": intent}]})
    return result["messages"][-1].content
