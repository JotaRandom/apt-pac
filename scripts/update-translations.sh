#!/bin/bash
# Script to extract, update, and compile translation files

set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOCALES_DIR="$REPO_ROOT/locales"
POT_FILE="$LOCALES_DIR/apt-pac.pot"
LOCALES_INI="$LOCALES_DIR/locales.ini"

# Helper function to check if a command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

if ! command_exists xgettext; then
    echo "Error: xgettext is not installed. Please install gettext."
    exit 1
fi

# Change to repo root to ensure relative paths
cd "$REPO_ROOT"

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
    --directory="$REPO_ROOT" \
    src/apt_pac/*.py

echo "Template file updated: $POT_FILE"
echo

# Get locales from ini file
if [ -f "$LOCALES_INI" ]; then
    echo "==> Reading locales from $LOCALES_INI..."
    # Extract keys from [locales] section
    # 1. sed: print lines between [locales] and next section (starting with [)
    # 2. grep -v: exclude section headers
    # 3. grep =: ensure it's a key=value line
    # 4. cut: get the key
    # 5. awk: trim whitespace
    LOCALES=$(sed -n '/^\[locales\]/,/^\[/p' "$LOCALES_INI" | grep -v '^\[' | grep '=' | cut -d'=' -f1 | awk '{$1=$1};1')
else
    echo "Warning: $LOCALES_INI not found!"
    LOCALES=""
fi

if [ -z "$LOCALES" ]; then
    echo "No locales found in $LOCALES_INI."
    exit 0
fi

# Process each locale
for lang in $LOCALES; do
    PO_FILE="$LOCALES_DIR/${lang}.po"
    
    if [ ! -f "$PO_FILE" ]; then
        echo "==> Initializing new locale: $lang"
        if command_exists msginit; then
            msginit --input="$POT_FILE" --output-file="$PO_FILE" --locale="$lang" --no-translator
        else
            cp "$POT_FILE" "$PO_FILE"
            echo "Warning: msginit not found, copied POT file. Please update header manually."
        fi
        echo "Created: $PO_FILE"
    else
        echo "==> Updating locale: $lang"
        msgmerge --update --backup=none "$PO_FILE" "$POT_FILE"
    fi
done

echo
echo "==> Compiling translation files..."

# Compile defined locales
for lang in $LOCALES; do
    PO_FILE="$LOCALES_DIR/${lang}.po"
    if [ -f "$PO_FILE" ]; then
        mo_file="${PO_FILE%.po}.mo"
        echo "Compiling: $PO_FILE -> $mo_file"
        msgfmt -o "$mo_file" "$PO_FILE"
    else
        echo "Warning: $PO_FILE not found, skipping compilation."
    fi
done

echo
echo "==> Translation workflow complete!"
echo
echo "Locale structure:"
echo "  Configuration: locales/locales.ini"
echo "  Development:   locales/{lang}.po → locales/{lang}.mo"
echo "  Installed:     /usr/share/locale/{lang}/LC_MESSAGES/apt-pac.mo"
