# apt-pac TODO & Roadmap

## Recently Completed ✅

- [x] **Dependency Cycle Detection**: 
    - Implementation: 3-color DFS algorithm (visiting/visited sets) to detect circular dependencies in AUR packages.
    - Provides clear error messages with full cycle path (e.g., "pkg-a → pkg-b → pkg-a").

- [x] **Split Package Support**:
    - Implementation: Detects packages with same `PackageBase` field (e.g., `linux`/`linux-headers` share base).
    - Builds only once per PackageBase, uses base for directory/download.
    - Enhanced UI messages showing all sub-packages from split base.

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

### Advanced Features
- [x] **Dependency Graphs**: `apt depends` / `apt rdepends` with pactree integration
- [x] **GraphViz Export**: `apt dotty` generates visual dependency graphs
- [x] **Package Statistics**: `apt stats` shows system package analytics
- [x] **Version Policy**: `apt policy` displays installed vs candidate versions
- [x] **Download-Only Mode**: `--download-only` flag for package caching
- [ ] **Automatic PKGBUILD Review**: Security prompts before building
- [ ] **AUR Voting**: Vote for packages from CLI
- [ ] **Local Repository**: Create custom package repos
- [ ] **Change Analytics**: Track installation/removal patterns

## Planned Features

### AUR Enhancements
- [ ] **Conflict Detection**: Detect conflicts between AUR packages before building
- [ ] **Provides/Replaces Handling**: Check provides lists before declaring "not found"
- [x] **AUR Search Improvements**: Simultaneous official + AUR search with formatted output
- [ ] **PKGBUILD Review Prompts**: Security-focused review before building untrusted code
- [ ] **VCS Package Updates**: Smart version checking for `-git`, `-svn`, `-hg` packages
- [ ] **Out-of-date Flagging**: Integration with AUR's flag system

### Package Management
- [ ] **Downgrade Support**: `apt install package=version` syntax
- [x] **Hold/Unhold Packages**: `apt-mark` command with `-D --asdeps` / `--asexplicit`
- [ ] **Package Pinning**: Per-repository priorities
- [ ] **Emergency Rollback**: System snapshot integration
- [x] **Orphan Detection**: `apt autoremove` removes orphaned dependencies

### Output & UI
- [x] **Progress Bars**: Simulated download progress (apt-like "Get:1..." output)
- [ ] **Parallel Downloads**: True concurrent downloads with aggregate progress
- [x] **Better Error Messages**: Context-aware suggestions (e.g., cycle detection solutions)
- [ ] **Config File Diffs**: Colored diff when .pacnew files are created
- [ ] **Interactive Resolver**: When conflicts arise, offer choices

### Performance
- [ ] **Parallel AUR Builds**: Build independent packages concurrently
- [ ] **PKGBUILD Cache**: Avoid re-parsing on subsequent operations
- [ ] **Delta Downloads**: Incremental updates for large packages
- [ ] **ccache/sccache Hints**: Suggest compiler cache for frequent rebuilds

### Compatibility
- [ ] **Full apt-get Mode**: 100% command compatibility
- [ ] **aptitude Support**: Interactive TUI mode
- [ ] **Snap/Flatpak Awareness**: Suggest alternatives when AUR unavailable
- [ ] **needrestart Integration**: Auto-detect services needing restart

### Safety & Notifications
- [x] **Mass Removal Warnings**: Configurable threshold alerts (20+ packages)
- [x] **Partial Upgrade Detection**: Warns when installing during available updates
- [x] **Critical Package Protection**: Safeguards for kernels, bootloaders, systemd
- [ ] **Backup Hooks**: Pre-removal snapshots for critical packages
- [ ] **Change Notifications**: Email/webhook on major system changes

## Refactoring / Code Quality

- [ ] **Configuration Handling**:
    - Better handling of `os.getuid` checks on non-Linux platforms (for testing).
    
- [ ] **Output Parsing**:
    - Intercepting `pacman` stdout for `install` to provide a truly unified progress bar (currently `pacman` output is direct to tty or simple print).

- [ ] **Test Coverage**:
    - Integration tests for all commands
    - Mock AUR server for reproducible testing
    - Performance benchmarks vs yay/paru
    - Regression test suite

## Documentation

- [ ] **Man Pages**: Comprehensive documentation for all commands
- [ ] **Completion Scripts**: Bash/Zsh auto-completion
- [ ] **Usage Wiki**: Examples and common workflows
- [ ] **Video Tutorials**: Screen recordings for new users
- [ ] **Migration Guide**: From yay/paru to apt-pac

## Just for Fun / Polish

- [x] **"Super Cow Powers"**: 
    - `apt moo` implementation (like `apt moo` on Debian and Ubuntu's apt).
    - `apt pacman` implementation (like `ILoveCandy` on Arch's Pacman config and output). 

## Others

- [x] **Translation**: Make it translatable or at least add i18n support for what apt outputs translated.
