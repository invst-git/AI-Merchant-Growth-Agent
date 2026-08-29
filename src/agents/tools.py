"""Phase 3: tools shared by the Buyer and Merchant agents.

query_catalogue calls the catalogue module directly (in-process, not
over HTTP) for speed and reliability inside the agent loop. The
standalone HTTP endpoint (catalogue_api.py) exists separately as the
actual agent-readable artifact the build plan asks for; nothing stops
an external agent from calling that instead of this in-process version.

get_growth_decision wraps engine.decide() as-is, no logic duplicated
here. Its return value is already verified JSON-safe (all numpy types
cast to native python in engine.py).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "catalogue"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "decision_engine"))

from langchain_core.tools import tool

import catalogue
import engine


@tool
def query_catalogue(query: str, max_results: int = 5) -> list[dict]:
    """Search the merchant catalogue in natural language. Returns matching
    products with product_id, category, subcategory, price, availability,
    declared_complements, declared_alternative, checkout_capability."""
    return catalogue.search(query, max_results=max_results)


@tool
def get_product(product_id: int) -> dict:
    """Look up one exact product by its product_id. Returns the full
    catalogue entry, or {"found": false} if that id does not exist. Use
    this whenever you already have a specific product_id to confirm (from
    a buyer's request or your own earlier search), instead of re-searching
    by text, since query_catalogue only matches on category text and will
    not find a bare numeric id."""
    entry = catalogue.build_entry(product_id)
    return entry if entry is not None else {"found": False}


@tool
def get_growth_decision(household_key: int, basket_product_ids: list[int]) -> dict:
    """Given a household and the product ids currently in their basket,
    return the growth decision: the chosen action (cross_sell, upsell, or
    no_action), its expected value, and the plain-English reason. Also
    returns every candidate that was considered, not just the winner."""
    return engine.decide(household_key, basket_product_ids)
