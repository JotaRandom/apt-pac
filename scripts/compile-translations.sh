#!/bin/bash
# Script to extract, update, and compile translation files

set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOCALES_DIR="$REPO_ROOT/locales"
POT_FILE="$LOCALES_DIR/apt-pac.pot"

# Extract translatable strings from source code
echo "==> Extracting translatable strings..."
xgettext \
    --from-code=UTF-8 \
    --language=Python \
    --keyword=_ \
    --output="$POT_FILE" \
    --package-name=apt-pac \
    --package-version=1.0 \
    --msgid-bugs-address="https://github.com/JotaRandom/apt-pac/issues" \
    "$REPO_ROOT"/src/apt_pac/*.py

echo "Template file updated: $POT_FILE"
echo

# Update existing .po files from template
echo "==> Updating translation files from template..."
for po_file in "$LOCALES_DIR"/*.po; do
    if [ -f "$po_file" ]; then
        echo "Updating: $po_file"
        msgmerge --update --backup=none "$po_file" "$POT_FILE"
    fi
done

echo
echo "==> Compiling translation files..."

# Compile each .po file to .mo
for po_file in "$LOCALES_DIR"/*.po; do
    if [ -f "$po_file" ]; then
        mo_file="${po_file%.po}.mo"
        echo "Compiling: $po_file -> $mo_file"
        msgfmt -o "$mo_file" "$po_file"
    fi
done

echo
echo "==> Translation workflow complete!"
echo
echo "Locale structure:"
echo "  Development: locales/{lang}.po → locales/{lang}.mo"
echo "  Installed:   /usr/share/locale/{lang}/LC_MESSAGES/apt-pac.mo"
echo
echo "Next steps:"
echo "  1. Edit .po files in locales/ with translations"
echo "  2. Run this script again to compile updated translations"
