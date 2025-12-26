# apt-pac

An APT-style wrapper for `pacman` with beautiful output and robust safeguards.

## Features
- **APT-like Output**: Colorized tables, summaries, and formatted search/show results.
- **Dynamic Privilege Escalation**: Automatically uses `run0`, `doas`, or `sudo`.
- **System Safeguards**:
    - Partial upgrade detection.
    - Large removal warnings (>20 packages).
    - Dynamic protection for kernels and bootloaders.
- **Advanced Mappings**: Supports `depends`, `rdepends`, `scripts`, `policy`, `apt-mark`, and more.
- **Improved Sync**: `apt update` automatically syncs the file database (`pacman -Fy`).

## Installation

### Method 1: Quick Install (Local)
1. Clone the repository.
2. Run the installer:
   ```bash
   ./install.sh
   ```
This will create symlinks in `/usr/local/bin/apt` and `apt-pac`.

### Method 2: Arch Linux Package (Recommended)
1. Use the provided `PKGBUILD`:
   ```bash
   makepkg -si
   ```
This installs `apt-pac` as a system package.

## Usage
Simply use `apt` or `apt-pac` as you would on a Debian-based system:
```bash
apt update
apt upgrade
apt install <package>
apt search <keyword>
apt show <package>
apt list --upgradable
apt-mark hold <package>
```

## Dependencies
- `python >= 3.8`
- `python-rich`
- `pacman-contrib` (for advanced dependency mapping)
