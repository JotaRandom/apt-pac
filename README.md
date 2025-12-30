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
Simply use `apt-pac` as you would use `apt` on a Debian-based system:

```bash
apt-pac update
apt-pac upgrade
apt-pac install <package>
apt-pac search <keyword>
apt-pac show <package>
apt-pac list --upgradable
apt-mark hold <package>
```

## Version Information
```bash
# Show apt-pac version only
apt --version

# Show both apt-pac and pacman versions
apt --version full

# Show only pacman version
apt --version pacman
```

## Dependencies
- `python >= 3.8`
- `python-rich`
- `pacman-contrib` (for advanced dependency mapping)
- `devtools` (optional, for library link checking)
