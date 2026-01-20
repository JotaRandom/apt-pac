#!/bin/bash
# Script to extract, update, and compile translation files

set -e

# Change directory to the repository root to ensure relative paths work correctly
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

LOCALES_DIR="locales"
POT_FILE="$LOCALES_DIR/apt-pac.pot"
LOCALE_INI="$LOCALES_DIR/locale.ini"

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
    src/apt_pac/*.py

echo "Template file updated: $POT_FILE"
echo

# Helper function to process a locale
process_locale() {
    local lang="$1"
    local po_file="$LOCALES_DIR/$lang.po"

    if [ ! -f "$po_file" ]; then
        echo "Creating new translation file for: $lang"
        msginit --input="$POT_FILE" --output-file="$po_file" --locale="$lang" --no-translator
    else
        echo "Updating: $po_file"
        msgmerge --update --backup=none "$po_file" "$POT_FILE"
    fi
}

# Update existing .po files from template and create new ones from INI
echo "==> Updating translation files..."

# 1. Process locales defined in locale.ini
if [ -f "$LOCALE_INI" ]; then
    echo "Reading locales from $LOCALE_INI"
    # Read keys from [Locales] section. Assumes simple INI format: key = value
    # We use awk to find the section and extract keys
    while IFS= read -r lang; do
        if [ -n "$lang" ]; then
            process_locale "$lang"
        fi
    done < <(awk -F '=' '/^\[Locales\]/ {found=1; next} /^\[.*\]/ {found=0} found && /^[a-zA-Z0-9_]+/ {gsub(/^[ \t]+|[ \t]+$/, "", $1); print $1}' "$LOCALE_INI")
fi

# 2. Process any other existing .po files in the directory (in case they are not in INI)
for po_file in "$LOCALES_DIR"/*.po; do
    if [ -f "$po_file" ]; then
        lang=$(basename "$po_file" .po)
        # Check if we already processed this lang (simple check via grep if we were tracking, 
        # but running msgmerge again is harmless/idempotent usually, or we can just skip if we were smarter.
        # For simplicity, we just run it. If it was just created/updated above, msgmerge handles it fine.
        process_locale "$lang"
    fi
done | sort | uniq

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
echo "  1. Add new locales to locales/locale.ini (e.g., pt_BR = Portuguese)"
echo "  2. Edit .po files in locales/ with translations"
echo "  3. Run this script again to compile updated translations"
