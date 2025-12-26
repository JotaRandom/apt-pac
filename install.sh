#!/bin/bash

# Advanced installer for apt-pac
set -e

echo "Installing apt-pac..."

# Check dependencies
if ! command -v python3 &> /dev/null; then
    echo "Python 3 is required but not installed."
    exit 1
fi

# Install rich and pacman-contrib if not present
if ! python3 -c "import rich" &> /dev/null; then
    echo "The 'rich' library is required. Installing it via pacman..."
    sudo pacman -S --needed python-rich
fi

if ! command -v pactree &> /dev/null; then
    echo "pacman-contrib is recommended for advanced features. Installing..."
    sudo pacman -S --needed pacman-contrib
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

create_wrapper "apt"
create_wrapper "apt-pac"

echo "--------------------------------------------------"
echo "Installation complete!"
echo "You can now run 'apt update' or 'apt-pac' directly."
echo "--------------------------------------------------"
