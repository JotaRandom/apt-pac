#!/bin/bash
# Syncs pyproject.toml version to the current date (YYYY.MM.DD)
# This matches the behavior of src/apt_pac/__init__.py

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYPROJECT="$REPO_ROOT/pyproject.toml"

# Get current date in YYYY.MM.DD format
NEW_VERSION=$(date +"%Y.%m.%d")

echo "Syncing pyproject.toml version to $NEW_VERSION..."

# Check if file exists
if [ ! -f "$PYPROJECT" ]; then
    echo "Error: $PYPROJECT not found!"
    exit 1
fi

# Update the version line
# Regex looks for: version = "..." at the start of the line (allowing whitespace)
if grep -q "^version = " "$PYPROJECT"; then
    sed -i "s/^version = \".*\"/version = \"$NEW_VERSION\"/" "$PYPROJECT"
    echo "Done. Version updated."
else
    echo "Error: 'version' key not found in $PYPROJECT"
    exit 1
fi
