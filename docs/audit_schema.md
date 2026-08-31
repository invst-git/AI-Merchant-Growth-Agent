# Audit Record Schema — Finalized (Phase 6)

Every transaction the system touches is reconstructable end to end from
the audit log alone: src/audit/trace.py does exactly that, given one
request_id. Storage backend: one append-only JSON-lines file
(data/audit_log.jsonl), no database, matching Phase 6's own guardrail
against building more than "bounded and gated" requires.

Implementation note: rather than one record per transaction, each section
below is its own event (event: intent / decision / gate / cart /
order_created / checkout_verify / webhook_payment_captured / outcome),
all sharing one request_id (payment events instead share razorpay_order_id,
bridged back to request_id by a checkout_order_linked event -- see "How
events link together" at the end of this document). This reads the same
information back, just as an append-only stream instead of a single
mutated record, which fits an append-only log far better than repeatedly
rewriting one row would.

## intent
- `request_id` — unique id for this buyer interaction (uuid4, generated once
  per demo_graph.run_demo() call)
- `timestamp`
- `household_key` — this system's identifier for the demo customer (the
  "customer_id" this draft anticipated; there is no separate identifier)
- `raw_query` — the buyer agent's natural-language request, verbatim

Simplification from the Phase 0 draft: no separate `parsed_intent` field.
The merchant agent's own tool calls (get_product / query_catalogue,
visible in the `decision` event's basket_product_ids) already are the
structured interpretation of the request; a second, hand-built NLU layer
duplicating that would be exactly the "general compliance or policy
engine" Phase 6's own guardrail says to resist.

## decision
- `request_id`, `timestamp` (join key, as above)
- `household_key`, `basket_product_ids`
- `candidate_actions` — every action the engine scored for this basket,
  each with: action type (upsell / cross_sell / no_action), SKU (if
  applicable), the rule/lift that surfaced it, `p_accept`,
  `incremental_value`, and the resulting `expected_value` (exactly
  engine.decide()'s own candidate_actions list, unmodified)
- `chosen_action`, `chosen_product_id`, `p_accept`, `incremental_value`,
  `expected_value` of the winning candidate, including the no_action case
- `reason_text` — a plain-English sentence generated from the winning
  candidate's numbers (never hand-written, so it can't drift from what the
  engine actually computed)
- `bound_rejected`, `rejected_action` — Phase 6's catalogue-bounding rule
  (see "Bounded", below): true when the engine's own top candidate was not
  a catalogue-declared complement/alternative and was replaced with
  no_action; `rejected_action` keeps the original rejected candidate for
  the record, it is never silently dropped.

## gate

Not in the Phase 0 draft, added because "gated" turned out to need its own
explicit, auditable event, not just an inference from cart_before/after.
This is the record that an explicit accept step happened before any
Razorpay order was created.
- `request_id`, `timestamp`
- `offer_action` — what was offered (cross_sell / upsell / no_action /
  null if the merchant agent was never reached)
- `p_accept` — the real value from the acceptance/upsell-propensity model
- `accepted` — true / false / null (null when there was nothing to accept
  or decline, i.e. no_action)
- `mechanism` — how `accepted` was decided. The live demo path uses
  `seeded_random_draw_vs_real_p_accept`, a documented placeholder (Phase
  5's offline replay is the real data-grounded version of this same draw,
  kept in a separate simulator on purpose, not this live graph)
- `note` — the same plain-English sentence the demo prints

## cart
- `request_id`, `timestamp`
- `cart_before`, `cart_after` — product_id lists (this system has no
  quantity concept anywhere, see engine.py/checkout.py; a basket is a set
  of distinct product ids)
- `delta` — product ids added, for convenience

## checkout_order_linked
Not in the Phase 0 draft. Written the instant create_checkout_order
returns a real order_id, before the buyer ever reaches the browser — this
is the join key between the request_id everything above uses and the
razorpay_order_id everything below uses.
- `request_id`, `razorpay_order_id`

## payment
Event types: `order_created`, `checkout_verify`, `webhook_rejected`,
`webhook_payment_captured`. No request_id (the browser and Razorpay's
webhook don't round-trip one) — joined back via checkout_order_linked.
- `razorpay_order_id`
- `razorpay_payment_id`
- `signature_verified` — boolean, set only after server-side HMAC-SHA256
  verification succeeds
- `status` — created / captured / failed / abandoned
- `amount` — in paise
- `spend_cap_applied` — boolean, on the `order_created` event: whether
  Phase 6's bounded-spend-cap rule constrained the raw basket total.
  (checked a second time at capture, see `failure_reason` below)
- `failure_reason` — populated on a failed or abandoned payment (a
  deliberate `failure@razorpay`/Failure-button decline, a bad signature,
  an amount that slipped past order creation but still exceeds the cap at
  capture time, or the checkout modal being dismissed unsubmitted)

## outcome
Not in the Phase 0 draft as a distinct event; the terminal fact each
payment-side handler in checkout_api.py logs once it knows how a
transaction actually ended, looked up by request_id via
checkout_order_linked.
- `request_id`, `timestamp`
- `final_status` — completed / abandoned / failed
- `note`
- `experiment_run_id` — not used by the live demo path. Phase 5's
  Control-vs-Agent replay deliberately does not write into this log at
  all (data/experiment/*.parquet instead) — it runs thousands of sessions
  per experiment, and this log is for individual live transactions, not a
  bulk statistical replay; see docs/phase5_results.md.

## Bounded
Two concrete rules, not a slogan:
1. **Spend cap** (Phase 4, checkout.py `MAX_ORDER_PAISE`): enforced at
   order creation and re-checked at capture time (`checkout_verify`'s
   `capture_refused_over_cap` status is what a violation at capture looks
   like in the log).
2. **Catalogue-declared SKUs only** (Phase 6, src/decision_engine/bounding.py):
   the agent may only ever offer a cross-sell or upsell the catalogue has
   declared as a complement or alternative for that basket. Verified
   against 1,000 real baskets before this was built: engine.decide()'s own
   ranking is not automatically catalogue-bounded (31% of real chosen
   cross-sell offers referenced a commodity outside the catalogue's
   declared set) — this is enforced inside get_growth_decision itself, so
   every caller gets it, not left as an assumption.

## Gated
An explicit accept step is required before any Razorpay order gets
created. In demo_graph.py, checkout_node is structurally unreachable
before resolve_node runs (StateGraph's edges are linear:
buyer -> merchant -> resolve -> checkout), and resolve_node now logs a
`gate` event on every path before returning, so this is both enforced by
the graph's own structure and independently auditable, not just true by
accident of wiring order.

## How events link together
1. `intent`, `decision`, `gate`, `cart`, `checkout_order_linked`, and
   `outcome` all share one `request_id` (generated once per
   demo_graph.run_demo() call).
2. `order_created`, `checkout_verify`, `webhook_rejected`,
   `webhook_payment_captured` share one `razorpay_order_id` instead (they
   come from the browser and from Razorpay's own webhook, neither of
   which round-trips a request_id).
3. `checkout_order_linked` bridges the two: it carries both fields,
   written the moment a real order exists.
4. src/audit/trace.py does this join automatically —
   `python3 src/audit/trace.py <request_id>` prints the full
   reconstruction. Live-verified structurally (real households, real
   engine.decide() output, the real FastAPI app via TestClient) on three
   scenarios: a genuine no_action, a signature-verification failure, and
   an abandoned checkout. Transactions logged before Phase 6 existed
   (Phase 4's live runs) predate the intent/decision/gate/cart events and
   can only be traced from `order_created` onward — expected, not a gap
   in this phase's own work.

## Notes

- Every field above should be populated even when the outcome is
  no_action or a failed payment — those are not exceptions to log less
  carefully, they're the two things the Track's bar explicitly asks to
  see handled well.
- `reason_text` is generated, not hand-written, so it can never drift
  from the actual numbers the engine computed.
- Phase 5's offline replay does not go through get_growth_decision (it
  calls engine.decide() directly for speed at thousands of sessions), so
  it is not subject to the catalogue-bounding rule above. Its own results
  (docs/phase5_results.md) describe the engine's unconstrained ranking
  quality; a live deployment's realized uplift would be somewhat lower
  once bounding vetoes the ~31% of top-ranked offers that fall outside
  the catalogue's declared surface. Worth a bounded re-run if that number
  matters for the pitch; not done here, out of scope for what Phase 6
  itself asks for.
