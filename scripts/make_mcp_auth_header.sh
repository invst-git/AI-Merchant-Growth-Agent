set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -f .env ]; then
  echo "No .env found. Copy .env.example to .env and fill in your keys first." >&2
  exit 1
fi
set -a
source .env
set +a
if [ -z "${RAZORPAY_KEY_ID:-}" ] || [ -z "${RAZORPAY_KEY_SECRET:-}" ]; then
  echo "RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET not set in .env" >&2
  exit 1
fi
echo -n "${RAZORPAY_KEY_ID}:${RAZORPAY_KEY_SECRET}" | base64