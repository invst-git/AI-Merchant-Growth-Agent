set -euo pipefail
cd "$(dirname "$0")/.."

export PATH="$(pwd)/venv/Scripts:$HOME/.local/bin:$PATH"

if [ ! -f .env ]; then
  echo "No .env found. Copy .env.example to .env and fill in your Kaggle credentials first." >&2
  exit 1
fi
set -a
source .env
set +a

if [ -z "${KAGGLE_USERNAME:-}" ] || [ -z "${KAGGLE_KEY:-}" ]; then
  echo "KAGGLE_USERNAME / KAGGLE_KEY not set in .env" >&2
  exit 1
fi

mkdir -p data/raw/dunnhumby data/raw/olist

echo "Downloading dunnhumby Complete Journey..."
venv/Scripts/kaggle.exe datasets download -d frtgnn/dunnhumby-the-complete-journey -p data/raw/dunnhumby --unzip

echo "Downloading Olist Brazilian E-Commerce..."
venv/Scripts/kaggle.exe datasets download -d olistbr/brazilian-ecommerce -p data/raw/olist --unzip
echo "Done."
