"""Phase 3: the one thin agent-readable catalogue endpoint.

Plain JSON, queryable in natural language, shaped like the feeds used
by the Agentic Commerce Protocol per the build plan. No auth, no
discovery stack, no ACP conformance attempt, just this one route.
Run: uvicorn catalogue_api:app --port 8001 (from src/catalogue/).
"""

from fastapi import FastAPI, Query

from catalogue import build_entry, search

app = FastAPI(title="Merchant Catalogue", version="0.1")


@app.get("/catalogue/search")
def catalogue_search(q: str = Query(..., description="natural language product query"), max_results: int = 5):
    return {"query": q, "results": search(q, max_results=max_results)}


@app.get("/catalogue/product/{product_id}")
def catalogue_product(product_id: int):
    entry = build_entry(product_id)
    if entry is None:
        return {"error": "not found"}
    return entry
