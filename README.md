
# apt-pac
**Enterprise-Grade Package Management Wrapper for Arch Linux**

![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)
![Python: 3.8+](https://img.shields.io/badge/Python-3.8%2B-blue)
![Platform: Arch Linux](https://img.shields.io/badge/Platform-Arch_Linux-blue)

## Overview

**apt-pac** is a sophisticated, python-based interface wrapper designed to bridge the operational gap between Debian's Advanced Package Tool (APT) and Arch Linux's Pacman. It provides a familiar, robust, and safe command-line environment for system administrators and developers transitioning to or operating within the Arch Linux ecosystem.

By implementing strict output formatting parity with `apt`, intelligent safeguard mechanisms, and seamless integration with the Arch User Repository (AUR), **apt-pac** ensures a consistent and professional package management experience.

## Key Capabilities

### 🛡️ Operational Safety & Compliance
*   **Partial Upgrade Detection**: Prevents system instability by detecting and blocking partial upgrade states.
*   **Critical Component Protection**: Heuristically alerts administrators when modifying sensitive system components (kernels, bootloaders, systemd).
*   **Threshold-Based Warnings**: Requires explicit confirmation for bulk removal operations exceeding safe thresholds.

### 🔍 Unified Search & Discovery
*   **Hybrid Repository Querying**: Simultaneously searches Official Repositories and the AUR.
*   **APT-Compatible Output**: Search results (`search`) and package metadata (`show`) are formatted exactly like their Debian counterparts, easing parsing and readability.
*   **Enhanced Metadata**: Maps internal Pacman fields to standard APT fields (e.g., `Name` → `Package`, `Required By` → `Reverse-Depends`).

### 📦 Seamless AUR Integration
*   **Native Build Support**: Integrated `makepkg` workflow handles AUR package acquisition, dependency resolution (recursive), and compilation.
*   **Frictionless Installation**: Automates the `git clone` → `makepkg -si` pipeline, presenting a unified progress interface indistinguishable from official repository operations.

### 🖥️ Enterprise UI/UX
*   **Rich Terminal Output**: Utilizes the `rich` library for professional, high-contrast status reporting.
*   **Privilege Management**: Auto-negotiates privilege escalation strategies using system-configured defaults (`run0`, `doas`, or `sudo`).

---

## Installation

### Requirements
*   **Operating System**: Arch Linux (or derivatives)
*   **Python**: >= 3.8
*   **Core Dependencies**: `pacman`, `git`, `base-devel`, `python-rich`, `python-tomli` (if Python < 3.11)
*   **Recommended**: `pacman-contrib` (provides `pactree` for dependency graphs)

### Method 1: System Package (Recommended)
Build and install using the standardized PKGBUILD workflow:
```bash
git clone https://github.com/YourOrg/apt-pac.git
cd apt-pac
makepkg -si
```

### Method 2: Deployment Script
For quick deployment in development environments:
```bash
./install.sh
```

---

## Command Reference

`apt-pac` supports the full spectrum of standard APT commands.

| Command | Description | Pacman Equivalent |
| :--- | :--- | :--- |
| `update` | Synchronize package databases | `pacman -Sy` (+ `-Fy`) |
| `upgrade` | Perform full system upgrade | `pacman -Syu` |
| `install <pkg>` | Install packages (Official/AUR) | `pacman -S` / `makepkg` |
| `remove <pkg>` | Remove packages | `pacman -R` |
| `purge <pkg>` | Remove packages and configs | `pacman -Rn` |
| `autoremove` | Remove unused dependencies | `pacman -Qdtq \| pacman -Rns -` |
| `search <query>` | Search locally & remotely | `pacman -Ss` + `RPC` |
| `show <pkg>` | Display package details | `pacman -Si/Qi` + `RPC` |
| `list --installed` | List installed packages | `pacman -Q` |
| `depends <pkg>` | Show dependencies | `pactree` / `pacman -Qi` |
| `rdepends <pkg>` | Show reverse dependencies | `pactree -r` / `pacman -Sii` |
| `policy <pkg>` | Show version policy | `pacman -Si` |

---

## Configuration

Configuration is managed via TOML files, loaded in the following order of precedence:
1.  `/etc/apt-pac/config.toml` (Global)
2.  `~/.config/apt-pac/config.toml` (User)

### Example Configuration
```toml
[safeguards]
mass_removal_threshold = 20
warn_partial_upgrades = true

[ui]
# output formats: "apt-pac", "apt", "pacman"
show_output = "apt-pac" 
verbosity = 1

[tools]
privilege_tool = "auto" # run0, doas, sudo, or auto
```

---

## Author
Maintained by the **Arch User** team.
Released under the **MIT License**.
