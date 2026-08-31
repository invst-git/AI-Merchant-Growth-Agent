"""Phase 4 (minimal) / Phase 6 (formalized): append-only audit log.

Field names follow docs/audit_schema.md's payment section directly, plus
enough decision/cart context on each record to satisfy the plan's own
bar for this phase: "one successful and one deliberately failed Test
Mode payment, both fully traceable back to the specific agent decision
that triggered them." This is intentionally the minimal version of that
schema, not the full Phase 6 bounding/gating system, one JSON-lines file,
no database, no querying layer, that formalization is Phase 6's job.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

AUDIT_LOG_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "audit_log.jsonl"


DEDUP_WINDOW_SECONDS = 30
# Razorpay's checkout.js fires payment.failed twice for a single failed
# attempt, found live (not hypothetical): two runs both logged the exact
# same razorpay_payment_id, status, and failure_reason a few seconds
# apart. Rather than trust the browser to only call /checkout/failed
# once, the audit log itself refuses to write a near-duplicate of its
# own last line.
DEDUP_KEYS = ("event", "razorpay_payment_id", "status", "failure_reason")


def _is_duplicate(record: dict) -> bool:
    if not AUDIT_LOG_PATH.exists():
        return False
    with open(AUDIT_LOG_PATH) as f:
        lines = f.readlines()
    if not lines:
        return False
    last = json.loads(lines[-1])
    if any(last.get(k) != record.get(k) for k in DEDUP_KEYS):
        return False
    last_time = datetime.fromisoformat(last["timestamp"])
    now = datetime.now(timezone.utc)
    return (now - last_time).total_seconds() < DEDUP_WINDOW_SECONDS


def log_payment_event(record: dict) -> dict:
    """Append one payment-related event. record should carry whatever
    subset of docs/audit_schema.md's payment fields applies at this point
    in the flow (order creation vs. checkout verification are two
    different events, not one record filled in twice). Silently skips a
    near-duplicate of the immediately preceding record within
    DEDUP_WINDOW_SECONDS, see DEDUP_KEYS."""
    AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if _is_duplicate(record):
        return record
    full_record = {"timestamp": datetime.now(timezone.utc).isoformat(), **record}
    with open(AUDIT_LOG_PATH, "a") as f:
        f.write(json.dumps(full_record) + "\n")
    return full_record


def read_audit_log() -> list[dict]:
    """Read every logged event back, oldest first. Used by verification
    scripts and, later, the Phase 7 dashboard."""
    if not AUDIT_LOG_PATH.exists():
        return []
    with open(AUDIT_LOG_PATH) as f:
        return [json.loads(line) for line in f if line.strip()]
