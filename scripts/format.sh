#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.."

# Auto-install Biome if not present
if ! command -v biome &> /dev/null; then
    echo "Biome not found, installing..."
    npm install -g @biomejs/biome
fi

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

source .venv/bin/activate

echo "Installing dev dependencies..."
pip install -q -r requirements-dev.txt

echo ""
python -m black backend/ tests/ "$@"

echo "Formatting JavaScript with Biome..."
biome format frontend/ --write "$@"
