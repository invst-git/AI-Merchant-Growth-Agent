"""One dedicated, honest sales pitch per real offer.

merchant_agent.py's own reply is deliberately flat and factual -- its
prompt says so explicitly ("no sales-pitch tone... a factual
confirmation, not an advertisement"), because that text is an audit
record, not something a shopper should ever see. That's still correct
for the audit log. But a real storefront that wants a customer to add
something to their cart needs an actual pitch, not a lab report -- so
this is a second, small, separate LLM call, used only for the
customer-facing copy, that never touches the audit trail and never
influences the decision itself.

The Phase 6 catalogue-bounding guardrail already ran before this is
ever called (get_growth_decision applies it inside src/agents/tools.py,
before the merchant agent even sees a candidate) -- this module only
writes copy for whatever the engine already decided and already
cleared. It cannot invent an offer, change which product is offered,
or override a decline; it only puts real facts (product, price, the
engine's own p_accept and reason) into one persuasive sentence, and is
told explicitly not to add anything that isn't in those facts.
"""
import os

from langchain_anthropic import ChatAnthropic

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")

PITCH_PROMPT = """You are a warm, confident sales associate talking directly to a \
customer who is already buying something. The store's real recommendation \
engine has a suggestion for them, backed by real data. Your only job is to \
turn that data into ONE short, persuasive, natural-sounding sentence that \
would make a real person want to say yes.

Facts (all real, do not add to them):
- Customer is buying: {base_name}
- Recommended {kind}: {offer_name}, {price}
- Why the engine picked it: {why_headline}
- Modeled likelihood this customer accepts it: {p_accept}%

Rules:
- Second person ("you'll love...", "pairs perfectly with...").
- Ground every claim in the facts above. Never invent flavors, brands, \
ingredients, or features -- and never get more specific than the category \
name given (e.g. if the category is "dry sausage", don't call it \
"salami" or "pepperoni", those are guesses this data doesn't support).
- No fake urgency or scarcity ("only 2 left", "today only") -- none of \
that is real, don't imply it.
- At most one exclamation point, and only if it earns it.
- Under 25 words. Reply with only the sentence, nothing else -- no \
quotes, no preamble."""


def _fallback_pitch(kind, offer_name, why_headline):
    if kind == "an upgrade":
        return f"Worth the upgrade to {offer_name} -- {why_headline}."
    return f"{offer_name} is a natural pairing here -- {why_headline}."


async def generate_pitch(action, base_name, offer_name, price_display, why_headline, p_accept):
    """Real LLM call for one persuasive sentence, grounded only in the
    real decision data passed in. Falls back to a still-concrete,
    still-factual line (never a generic "consider upgrading to") if the
    call fails, so a transient LLM error never blocks checkout."""
    kind = "an upgrade" if action == "upsell" else "a pairing"
    try:
        model = ChatAnthropic(model=MODEL, max_tokens=80)
        prompt = PITCH_PROMPT.format(
            base_name=base_name,
            kind=kind,
            offer_name=offer_name,
            price=price_display,
            why_headline=why_headline or "a strong match for this basket",
            p_accept=round((p_accept or 0) * 100),
        )
        result = await model.ainvoke([{"role": "user", "content": prompt}])
        text = (result.content or "").strip().strip('"')
        if text:
            return text
    except Exception:
        pass
    return _fallback_pitch(kind, offer_name, why_headline or "a strong match for this basket")
