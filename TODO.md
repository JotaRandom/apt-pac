
# apt-pac TODO & Roadmap

## Critical Features (To Match Full APT/Helper Experience)

- [x] **AUR Upgrades (`apt upgrade`)**: 
    - Current behavior: Checks official packages via `pacman -Syu` and then checks AUR updates via RPC.
    - Implementation: Added `check_updates` in `aur.py` and integrated into `apt upgrade` workflow.

- [x] **APT Repositories (`add-apt-repository`)**:
    - Implementation: Shows educational guide for `pacman.conf` and offers to launch `$EDITOR`. Safer than automated parsing for Arch.

- [x] **Source Management (`apt source`, `apt build-dep`) for AUR**:
    - Current behavior: `apt source` tries ABS first, then falls back to AUR.
    - Implementation: Added `download_aur_source` helper and updated `sources.py`.

- [x] **Cache Maintenance**:
    - Current behavior: `apt clean` cleans both pacman cache (`-Scc`) and apt-pac sources (`~/.cache/apt-pac/sources`).

## Enhancements

- [x] **Smart Provider Selection**:
    - Implementation: Removed forceful `--noconfirm` from `makepkg` (unless `-y` is passed), allowing `pacman` to interactively prompt for providers.

- [x] **GPG Key Import**:
    - Implementation: `AurInstaller` detects PGP signature errors, extracts the Key ID, and runs `gpg --recv-keys` automatically before retrying the build.

- [x] **Performance**:
    - [x] Parallel download simulation (apt-like output).
    - [x] Caching RPC results more aggressively (30m persist cache).

## Refactoring / Code Quality

- [ ] **Configuration Handling**:
    - Better handling of `os.getuid` checks on non-Linux platforms (for testing).
    
- [ ] **Output Parsing**:
    - Intercepting `pacman` stdout for `install` to provide a truly unified progress bar (currently `pacman` output is direct to tty or simple print).

## Just for Fun / Polish

- [x] **"Super Cow Powers"**: 
    - `apt moo` implementation (like `apt moo` on Debian and Ubuntu's apt).
    - `apt pacman` implementation (like `ILoveCandy` on Arch's Pacman config and output). 

## Others

- [x] **Translation**: Make it translatable or at least add i18n support for what apt outputs translated.
