import os
import sys

from dotenv import load_dotenv
import razorpay

load_dotenv()

key_id = os.getenv("RAZORPAY_KEY_ID")
key_secret = os.getenv("RAZORPAY_KEY_SECRET")

if not key_id or not key_secret or "xxxx" in key_id:
    print("RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET are not set. ""Copy .env.example to .env and fill in your real test keys.",file=sys.stderr,)
    sys.exit(1)

if not key_id.startswith("rzp_test_"):
    print(f"Warning: key id does not start with 'rzp_test_' - "f"make sure you're using Test Mode keys, not Live Mode.",file=sys.stderr,)

client = razorpay.Client(auth=(key_id, key_secret))

# A trivial order: ₹1.00, the smallest sensible test amount.
order = client.order.create(
    {
        "amount": 100,  # paise
        "currency": "INR",
        "receipt": "phase0-connectivity-check",
        "notes": {"purpose": "Phase 0 setup verification"},
    }
)
print(f"Order created: id={order['id']} status={order['status']} amount={order['amount']}")

fetched = client.order.fetch(order["id"])
print(f"Order fetched back: id={fetched['id']} status={fetched['status']}")

print("\nConnection OK - Test Mode account and API keys are working.")
