"""Phase 4: connection to Razorpay's official hosted MCP server.

Everything in this repo that calls Razorpay does it through this server's
tools (never a hand-rolled REST call to api.razorpay.com), per the build
plan's explicit "highest-leverage move" instruction. That includes calls
made deterministically from Python (capture_payment, fetch_payment in
checkout_api.py) as well as the one call an LLM agent makes directly
(create_order, via the create_checkout_order tool in agents/tools.py).

Endpoint and auth verified live against the real hosted server before
being hardcoded here (not assumed from docs): streamable HTTP at
https://mcp.razorpay.com/mcp, HTTP Basic auth built from
RAZORPAY_KEY_ID:RAZORPAY_KEY_SECRET, base64-encoded. A real create_order
call was made and returned a valid Test Mode order (order_TViNm65ZU16X3E,
receipt claude_verify_001) to confirm this before any agent code was
written against it.
"""

import base64
import json
import os

from langchain_mcp_adapters.client import MultiServerMCPClient

RAZORPAY_MCP_URL = "https://mcp.razorpay.com/mcp"


def _auth_header():
    key_id = os.environ["RAZORPAY_KEY_ID"]
    key_secret = os.environ["RAZORPAY_KEY_SECRET"]
    token = base64.b64encode(f"{key_id}:{key_secret}".encode()).decode()
    return f"Basic {token}"


def _client():
    return MultiServerMCPClient({
        "razorpay": {
            "transport": "streamable_http",
            "url": RAZORPAY_MCP_URL,
            "headers": {"Authorization": _auth_header()},
        }
    })


async def get_razorpay_tools(*names):
    """Connect to the hosted MCP server and return the requested tools as a
    {name: BaseTool} dict. Opens a fresh session per call; MCP tool-listing
    is cheap and this avoids holding a connection open across agent runs.
    Raises if the server doesn't expose one of the requested tool names,
    rather than silently returning a partial set."""
    tools = await _client().get_tools()
    by_name = {t.name: t for t in tools}
    missing = [n for n in names if n not in by_name]
    if missing:
        raise RuntimeError(f"Razorpay MCP server did not expose expected tools: {missing}")
    return {n: by_name[n] for n in names}


class RazorpayMCPError(Exception):
    """Raised when a Razorpay MCP tool call fails. Found live, not
    hypothetical: calling fetch_payment on a nonexistent payment_id
    returns content like {"text": "fetching payment failed: The id
    provided does not exist"}, plain text, not JSON. That's structurally
    indistinguishable from a success response except that it doesn't
    parse as JSON, verified directly against a real failing call before
    writing this. Every caller of parse_mcp_result must be prepared to
    catch this rather than let a bad id or a transient API error crash
    the request, the same "handled gracefully" bar the plan sets for a
    deliberately failed payment."""


def parse_mcp_result(result):
    """MCP tool calls return a list of content blocks, e.g.
    [{"type": "text", "text": "<json string>"}], verified directly against
    a live create_order response rather than assumed. Unwrap and parse the
    JSON payload inside, or raise RazorpayMCPError with the server's own
    message if it isn't valid JSON (an MCP-level tool error)."""
    block = result[0]
    text = block["text"] if isinstance(block, dict) else block.text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        raise RazorpayMCPError(text)
