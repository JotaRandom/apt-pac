# apt-pac

**APT-style package manager wrapper for Arch Linux**

![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)
![Python: 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue)
![Platform: Arch Linux](https://img.shields.io/badge/Platform-Arch_Linux-blue)

> [!NOTE]
> This project was developed with AI assistance / Vibe-coding. It's a fun experiment to make Arch feel a bit more like Debian!

## What is this?

**apt-pac** is a simple wrapper that lets you use `apt` commands on Arch Linux. If you're coming from Debian/Ubuntu and miss typing `apt install` instead of `pacman -S`, this tool is for you.

It translates familiar APT commands into their Pacman equivalents and adds some safety features to prevent you from breaking your system.

## Features

- **Use APT commands on Arch**: Type `apt install`, `apt update`, `apt search`, etc.
- **AUR support**: Install AUR packages just like official ones
- **Safety checks**: Warns you when removing many packages or modifying critical system components
- **APT-style output**: Search and info commands look like what you're used to from Debian
- **Smart privilege handling**: Uses `run0`, `doas`, or `sudo` depending on what you have

## Installation

### Requirements

- Arch Linux (or derivatives like Manjaro, EndeavourOS, etc.)
- Python 3.11 or newer
- `pacman`, `git`, `base-devel`, `python-rich`, `pyalpm`

### Quick Install

```bash
git clone https://github.com/YourOrg/apt-pac.git
cd apt-pac
makepkg -si
```

Or use the install script:

```bash
./install.sh
```

## Commands

| APT Command | What it does | Pacman Equivalent |
| :--- | :--- | :--- |
| `apt update` | Update package databases | `pacman -Sy` |
| `apt upgrade` | Upgrade all packages | `pacman -Syu` |
| `apt install <pkg>` | Install a package | `pacman -S` or AUR |
| `apt remove <pkg>` | Remove a package | `pacman -R` |
| `apt purge <pkg>` | Remove with configs | `pacman -Rn` |
| `apt autoremove` | Remove orphaned packages | `pacman -Qdtq \| pacman -Rns -` |
| `apt search <query>` | Search for packages | `pacman -Ss` + AUR |
| `apt show <pkg>` | Show package info | `pacman -Si/Qi` + AUR |
| `apt list --installed` | List installed packages | `pacman -Q` |
| `apt depends <pkg>` | Show dependencies | `pactree` |
| `apt rdepends <pkg>` | Show reverse dependencies | `pactree -r` |
| `apt policy <pkg>` | Show version info | `pacman -Si` |

## Configuration

You can customize behavior with TOML config files:

- System-wide: `/etc/apt-pac/config.toml`
- User-specific: `~/.config/apt-pac/config.toml`

Example:

```toml
[safeguards]
mass_removal_threshold = 20  # Warn if removing more than 20 packages
warn_partial_upgrades = true

[ui]
show_output = "apt-pac"  # Options: "apt-pac", "apt", "pacman"
verbosity = 1

[tools]
privilege_tool = "auto"  # Options: run0, doas, sudo, or auto
```

## License

MIT License - do whatever you want with it!

## Contributing

This is a casual project made with AI. Feel free to open issues or PRs if you want to improve it!
