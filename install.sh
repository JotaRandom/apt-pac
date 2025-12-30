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
fi

# Install global configuration
echo "Installing global configuration..."
if [ -f "config.toml" ]; then
    sudo mkdir -p /etc/apt-pac
    sudo install -Dm644 config.toml /etc/apt-pac/config.toml
    echo "Installed config to /etc/apt-pac/config.toml"
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
echo "  - /etc/apt-pac/config.toml (global config)"
echo ""
echo "User config will be auto-created at:"
echo "  ~/.config/apt-pac/config.toml"
echo ""
echo "You can now run 'apt-pac' directly."
echo "Example: apt-pac update, apt-pac search vim"
echo "--------------------------------------------------"
