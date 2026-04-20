#!/usr/bin/env bash
# Mirror all origin branches to origin-gh, excluding HEAD symref.
# Usage: ./scripts/mirror_to_gh.sh [--tags]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.."

SRC_REMOTE="${SRC_REMOTE:-origin}"
DST_REMOTE="${DST_REMOTE:-origin-gh}"

git fetch "$SRC_REMOTE" --prune

BRANCHES=()
while IFS= read -r br; do
    BRANCHES+=("$br")
done < <(
    git for-each-ref --format='%(refname:lstrip=3)' "refs/remotes/$SRC_REMOTE/" \
        | grep -v '^HEAD$' || true
)

if [ ${#BRANCHES[@]} -eq 0 ]; then
    echo "No branches found under refs/remotes/$SRC_REMOTE/."
    exit 1
fi

echo "Mirroring ${#BRANCHES[@]} branches from $SRC_REMOTE to $DST_REMOTE:"
printf '  - %s\n' "${BRANCHES[@]}"

REFSPECS=()
for br in "${BRANCHES[@]}"; do
    REFSPECS+=("refs/remotes/$SRC_REMOTE/$br:refs/heads/$br")
done

git push "$DST_REMOTE" "${REFSPECS[@]}"

if [[ "${1:-}" == "--tags" ]]; then
    git push "$DST_REMOTE" --tags
fi

echo "Done."
