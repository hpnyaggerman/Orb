#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.."

# virtualenv
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

source .venv/bin/activate

echo "Installing dev dependencies..."
pip install -q -r requirements-dev.txt

# Usage: ./scripts/tests.sh [unit|integration|all] [extra pytest args...]
#   unit        — run only tests/unit/
#   integration — run only tests/integration/
#   all         — run both suites (default)
SUITE="${1:-all}"

case "$SUITE" in
    unit)
        shift
        echo ""
        echo "=== Unit tests ==="
        python -m pytest tests/unit/ "$@"
        ;;
    integration)
        shift
        echo ""
        echo "=== Integration tests ==="
        python -m pytest tests/integration/ "$@"
        ;;
    all)
        shift
        echo ""
        echo "=== Unit tests ==="
        python -m pytest tests/unit/ "$@"
        echo ""
        echo "=== Integration tests ==="
        python -m pytest tests/integration/ "$@"
        ;;
    *)
        # No recognised suite keyword — pass everything straight to pytest
        echo ""
        python -m pytest "$SUITE" "$@"
        ;;
esac
