# AI Merchant Growth Agent

Razorpay AI Buildathon, Track 01. Full context and the phase-by-phase
build plan are in `AI_Merchant_Growth_Agent_Build_Plan.md`.

## Status: Phase 0 (Foundations & scoping)

## Repo layout

- `docs/objective_function.md` — the formula the decision engine
  optimizes, including the margin-proxy and abandonment-risk placeholders
  (Phase 0 draft, revisited in Phase 2).
- `docs/audit_schema.md` — the field contract for every logged
  transaction (intent -> decision -> cart -> payment -> outcome).
- `mcp/` — Razorpay MCP Server setup (remote/hosted, recommended, plus a
  self-hosted Docker alternative). See `mcp/README.md`.
- `scripts/test_razorpay_connection.py` — Phase 0 connectivity check:
  creates and fetches a real Test Mode order.
- `scripts/make_mcp_auth_header.sh` — builds the MCP auth header locally
  from your `.env`, without exposing the secret.
- `src/catalogue/`, `src/decision_engine/`, `src/cart/`, `src/payments/`,
  `src/audit/`, `src/experiment/`, `src/dashboard/` — placeholders for
  the modules described in the build plan; empty until their phase.
- `data/raw/`, `data/processed/` — empty until Phase 1 (dunnhumby, Olist,
  UCI Online Retail II land here; both are gitignored, structure only).

## Setup

1. `pip install -r requirements.txt`
2. `cp .env.example .env` and fill in your real Razorpay **Test Mode**
   Key ID and Key Secret (Dashboard > Account & Settings > API Keys).
3. `python scripts/test_razorpay_connection.py` to confirm the account
   works end to end.
4. See `mcp/README.md` for connecting the Razorpay MCP Server (used
   starting Phase 4, but worth wiring up now while Phase 0 is open).
