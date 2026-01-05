# apt-pac TODO & Roadmap

## Recently Completed ✅

- [x] **Internationalization (i18n)**:
    - Complete gettext implementation with `_()` wrappers across all modules.
    - Automated `.pot` template generation via `scripts/compile-translations.sh`.
    - 100% string coverage including help texts, errors, and status messages.

- [x] **Output Standardization**:
    - Unified message prefixes: `E:` (Red/Error), `W:` (Yellow/Warning), `N:` (Magenta/Note).
    - Consistent "Reading package lists... Done" status blocks.
    - Fixed specific "WARNING:" and "Abort" message inconsistencies.

- [x] **AUR Build System Fixes**:
    - Visible `makepkg` output for better debugging.
    - Correct working directory preservation for `makepkg`.
    - Fixed permissions issues when running as root (dropping to `SUDO_USER` or configured build user).

- [x] **Easter Eggs & Polish**:
    - Improved `apt moo` with a cute furry cow.
    - Added `apt pacman` with Unicode animation.
    - "Did you mean?" suggestions for typos.

- [x] **Dependency Cycle Detection**: 
    - Implementation: 3-color DFS algorithm to detect circular dependencies in AUR packages.
    - Provides clear error messages with full cycle path.

- [x] **Split Package Support**:
    - Detects packages with same `PackageBase`, builds only once, and handles sub-packages correctly.

## Critical Features (To Match Full APT/Helper Experience)

- [x] **AUR Upgrades (`apt upgrade`)**: 
    - Checks official packages via `pacman -Syu` and then checks AUR updates via RPC.

- [x] **APT Repositories (`add-apt-repository`)**:
    - Shows educational guide for `pacman.conf` and offers to launch `$EDITOR`.
    - Includes examples for Chaotic AUR and generic repos.

- [x] **Source Management (`apt source`, `apt build-dep`) for AUR**:
    - `apt source` tries ABS first, then falls back to AUR.
    - `apt build-dep` installs dependencies required for building.

- [x] **Cache Maintenance**:
    - `apt clean` cleans both pacman cache and apt-pac sources.

## Enhancements

- [x] **Smart Provider Selection**:
    - Removed forceful `--noconfirm` from `makepkg` to allow provider selection.

- [x] **GPG Key Import**:
    - Automatically detects PGP errors and attempts to import keys via `gpg --recv-keys`.

- [x] **Performance**:
    - [x] Parallel download simulation.
    - [x] Aggressive RPC result caching.

## Advanced Features
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
- [ ] **PKGBUILD Review Prompts**: Security-focused review before building untrusted code
- [ ] **VCS Package Updates**: Smart version checking for `-git`, `-svn`, `-hg` packages
- [ ] **Out-of-date Flagging**: Integration with AUR's flag system

### Package Management
- [ ] **Downgrade Support**: `apt install package=version` syntax
- [x] **Hold/Unhold Packages**: `apt-mark` command with `-D --asdeps` / `--asexplicit`
- [ ] **Package Pinning**: Per-repository priorities
- [ ] **Emergency Rollback**: System snapshot integration
- [ ] **Orphan Detection**: `apt autoremove` removes orphaned dependencies (implemented)

### Output & UI
- [x] **Progress Bars**: Simulated download progress
- [ ] **Parallel Downloads**: True concurrent downloads with aggregate progress
- [ ] **Config File Diffs**: Colored diff when .pacnew files are created
- [ ] **Interactive Resolver**: When conflicts arise, offer choices

### Performance
- [ ] **Parallel AUR Builds**: Build independent packages concurrently
- [ ] **PKGBUILD Cache**: Avoid re-parsing on subsequent operations
- [ ] **Delta Downloads**: Incremental updates for large packages
- [ ] **ccache/sccache Hints**: Suggest compiler cache for frequent rebuilds

## Documentation & Refactoring
- [x] **Man Pages**: Comprehensive documentation for all commands
- [x] **Completion Scripts**: Bash/Zsh auto-completion
- [ ] **Test Coverage**: Integration tests and mock AUR server
- [ ] **Usage Wiki**: Examples and common workflows
