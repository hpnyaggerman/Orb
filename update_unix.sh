#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if ! command -v git &>/dev/null; then
    echo "Error: git is not installed. Please install it from https://git-scm.com/downloads"
    exit 1
fi

BRANCH=$(git rev-parse --abbrev-ref HEAD)
echo "Current branch: $BRANCH"
echo "Pulling latest changes..."
echo ""

git pull origin "$BRANCH"

echo ""
echo "Update complete."
