#!/bin/bash

# Advanced installer for apt-pac
set -e

echo "Installing apt-pac..."

# Check dependencies
if ! command -v python3 &> /dev/null; then
    echo "Python 3 is required but not installed."
    exit 1
fi

# Install dependencies if not present
echo "Checking dependencies..."

if ! python3 -c "import rich" &> /dev/null; then
    echo "The 'rich' library is required. Installing it via pacman..."
    sudo pacman -S --needed python-rich
fi

# Check for tomllib (Python 3.11+) or tomli
if ! python3 -c "import tomllib" &> /dev/null 2>&1 && ! python3 -c "import tomli" &> /dev/null 2>&1; then
    echo "TOML parser required. Installing python-tomli..."
    sudo pacman -S --needed python-tomli
fi

if ! command -v pactree &> /dev/null; then
    echo "pacman-contrib is recommended for advanced features. Installing..."
    sudo pacman -S --needed pacman-contrib
if ! command -v pactree &> /dev/null; then
    echo "pacman-contrib is recommended for advanced features. Installing..."
    sudo pacman -S --needed pacman-contrib
fi

# Check for git (required for AUR cloning)
if ! command -v git &> /dev/null; then
    echo "git is required for AUR operations. Installing..."
    sudo pacman -S --needed git
fi

# Check for makepkg build tools (base-devel)
# Difficult to check group install status easily, but we can check a key component like 'gcc' or 'make'
if ! command -v make &> /dev/null || ! command -v gcc &> /dev/null; then
    echo "base-devel group is required for building AUR packages. Installing..."
    sudo pacman -S --needed base-devel
fi

# Install global configuration
echo "Installing global configuration..."
if [ -f "config.toml" ]; then
    sudo mkdir -p /etc/apt-pac
    sudo install -Dm644 config.toml /etc/apt-pac/config.toml
    echo "Installed config to /etc/apt-pac/config.toml"
fi

# Install manpage
echo "Installing manpage..."
if [ -f "src/man/apt-pac.8" ]; then
    MAN_DIR="/usr/local/share/man/man8"
    sudo mkdir -p "$MAN_DIR"
    sudo install -Dm644 src/man/apt-pac.8 "$MAN_DIR/apt-pac.8"
    echo "Installed manpage to $MAN_DIR/apt-pac.8"
    # Update man database if possible
    if command -v mandb &> /dev/null; then
        sudo mandb > /dev/null 2>&1 || true
    fi
fi

# Install shell completions
echo "Installing shell completions..."
# Bash
if [ -f "src/completions/apt-pac.bash" ]; then
    BASH_COMP_DIR="/usr/share/bash-completion/completions"
    if [ -d "$BASH_COMP_DIR" ]; then
        sudo install -Dm644 src/completions/apt-pac.bash "$BASH_COMP_DIR/apt-pac"
        echo "Installed bash completion to $BASH_COMP_DIR/apt-pac"
    fi
fi

# Zsh
if [ -f "src/completions/_apt-pac" ]; then
    ZSH_COMP_DIR="/usr/share/zsh/site-functions"
    if [ -d "$ZSH_COMP_DIR" ]; then
        sudo install -Dm644 src/completions/_apt-pac "$ZSH_COMP_DIR/_apt-pac"
        echo "Installed zsh completion to $ZSH_COMP_DIR/_apt-pac"
    fi
fi

# Fish
if [ -f "src/completions/apt-pac.fish" ]; then
    FISH_COMP_DIR="/usr/share/fish/vendor_completions.d"
    if [ -d "$FISH_COMP_DIR" ]; then
        sudo install -Dm644 src/completions/apt-pac.fish "$FISH_COMP_DIR/apt-pac.fish"
        echo "Installed fish completion to $FISH_COMP_DIR/apt-pac.fish"
    fi
fi

# Install translations
echo "Installing translations..."
if compgen -G "locales/*.mo" > /dev/null; then
    for mo_file in locales/*.mo; do
        if [ -f "$mo_file" ]; then
            locale=$(basename "$mo_file" .mo)
            LOCALE_DIR="/usr/share/locale/$locale/LC_MESSAGES"
            sudo mkdir -p "$LOCALE_DIR"
            sudo install -Dm644 "$mo_file" "$LOCALE_DIR/apt-pac.mo"
            echo "Installed $locale translation to $LOCALE_DIR/apt-pac.mo"
        fi
    done
else
    echo "No compiled translations found. Run ./scripts/compile-translations.sh first."
fi

# Create a proper wrapper script to avoid PYTHONPATH issues
INSTALL_DIR="/usr/local/bin"
SRC_PATH="$(pwd)/src"

create_wrapper() {
    local cmd_name=$1
    echo "Creating wrapper for '$cmd_name'..."
    cat <<EOF | sudo tee "$INSTALL_DIR/$cmd_name" > /dev/null
#!/bin/bash
export PYTHONPATH="$SRC_PATH:\$PYTHONPATH"
exec python3 -m apt_pac "\$@"
EOF
    sudo chmod +x "$INSTALL_DIR/$cmd_name"
}

create_wrapper "apt-pac"

echo "--------------------------------------------------"
echo "Installation complete!"
echo "Installed files:"
echo "  - /usr/local/bin/apt-pac"
echo "  - /usr/local/share/man/man8/apt-pac.8 (manpage)
  - Shell completions (bash, zsh, fish)
  - /etc/apt-pac/config.toml (global config)
  - /usr/share/locale/*/LC_MESSAGES/apt-pac.mo (translations)
"
echo ""
echo "User config will be auto-created at:"
echo "  ~/.config/apt-pac/config.toml"
echo ""
echo "You can now run 'apt-pac' directly."
echo "Example: apt-pac update, apt-pac search vim"
echo "--------------------------------------------------"
