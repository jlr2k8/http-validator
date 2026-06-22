#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .venv/bin/activate ]]; then
  echo "Creating .venv …"
  python3 -m venv .venv
fi
# shellcheck source=/dev/null
source .venv/bin/activate

echo "Installing Python deps …"
pip install -q -e ".[web]"

if [[ ! -d frontend/node_modules ]]; then
  echo "Installing frontend deps …"
  (cd frontend && npm install)
fi

echo "Starting MongoDB + Elasticsearch …"
docker-compose up -d

cleanup() {
  jobs -p | xargs -r kill 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo ""
echo "  UI:    http://127.0.0.1:5173"
echo "  API:   http://127.0.0.1:8000"
echo "  Crawl: .venv/bin/http-validator https://example.com"
echo ""
echo "Ctrl+C stops the UI and API. Stop Docker with: docker-compose down"
echo ""

API_PORT=8000 .venv/bin/http-validator-api &
(cd frontend && npm run dev)
