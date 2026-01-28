# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Standard development dotfiles: `.pre-commit-config.yaml`, `.editorconfig`, `.vscode/extensions.json`.
- Comprehensive GitHub Actions CI workflow.
- Many new badges to the README (CI, Tests, License, etc.).
- Community files: `CONTRIBUTING.md` and `CHANGELOG.md`.

### Fixed

- Crashes when simulating upgrades (`SystemExit` in build simulation).
- Issues with `makepkg` flag assertions in tests.

## [2026.01.28] - 2026-01-28

### Added

- Recursive AUR package installation and dependency resolution.
- Dedicated unit tests for recursive AUR builds and interactive upgrade flows.
- CI workflow configuration (initial setup).

## [2026.01.27] - 2026-01-27

### Refactored

- Reimplemented `search` and `show` commands using `pyalpm` for better performance.
- Improved console output coloring (removed bold yellow from indices).
- Enhanced 'Hit' and 'Get' messages with clearer AUR path separation.

## [2026.01.20] - 2026-01-20

### Added

- Dynamic multi-column output for `apt-pac list`.
- Rich formatting for package listings (version display, highlighting).
- Detailed AUR installation output (showing built files and source URLs).
- Cache cleaning functionality.
- Portuguese (pt_BR) translations.

### Fixed

- Removal warning and autoremove summary conflicts.
- Separate handling of official vs AUR dependencies in AUR install flow.

## [2026.01.18] - 2026-01-18

### Added

- `apt-pac news` command to fetch Arch Linux news.
- Initial i18n support (es, fr, pt_BR).
- Shell completions for Bash and Fish.
- Man page generation.

### Changed

- Standardized all list subcommands to use `pyalpm`.
- Enforced consistent output formatting (4-space indent) across all commands.

## [2026.01.17] - 2026-01-17

### Added

- Initial release of `apt-pac` (Version 2026.01.17).
- Native `pyalpm` integration for version comparison and search.
- APT-style shortened URLs in update output.

### Refactored

- Massive migration from subprocess calls to `pyalpm`.
- Removed visual dependency on `madison` and `pkgnames`.

## [2026.01.04] - 2026-01-04

### Added

- Core application structure and RPC caching.
- AUR source package management (clone/build).
- `build_user` configuration option.

## [2025.12.31] - 2025-12-31

### Started

- Initial project implementation.
- Core command mapping (APT -> Pacman).
- Basic UI with Rich.
