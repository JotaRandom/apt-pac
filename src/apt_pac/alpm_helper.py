"""
Helper utilities for pyalpm operations.
"""

import fnmatch
import re
import subprocess
from pathlib import Path

import pyalpm

_handle = None


def reset_handle():
    """Reset the cached pyalpm Handle (e.g. after DB sync)."""
    global _handle
    _handle = None


def _pacman_conf(key: str) -> list[str]:
    """Query a directive from /etc/pacman.conf via pacman-conf."""
    values: list[str] = []
    try:
        res = subprocess.run(
            ["pacman-conf", key],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.returncode == 0:
            values = [line.strip() for line in res.stdout.splitlines() if line.strip()]
    except (OSError, subprocess.SubprocessError):
        pass
    return values


def get_pacman_conf(key: str) -> list[str]:
    """Public wrapper around _pacman_conf for querying /etc/pacman.conf."""
    return _pacman_conf(key)


def _pacman_conf_repos() -> list[str]:
    """Return configured sync repository names in /etc/pacman.conf order."""
    repos: list[str] = []
    try:
        res = subprocess.run(
            ["pacman-conf", "-l"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.returncode == 0:
            repos = [
                line.strip()
                for line in res.stdout.splitlines()
                if re.fullmatch(r"[A-Za-z0-9._+-]+", line.strip())
            ]
    except (OSError, subprocess.SubprocessError):
        pass
    return repos


def get_handle():
    """
    Get or create a pyalpm Handle configured from pacman.conf.
    This reuses the same handle for efficiency until reset_handle() is called.
    """
    global _handle
    if _handle is None:
        root_dirs = _pacman_conf("RootDir")
        db_paths = _pacman_conf("DBPath")
        cache_dirs = _pacman_conf("CacheDir")

        root_dir = (
            root_dirs[0] if (root_dirs and Path(root_dirs[0]).is_dir()) else "/"
        )
        db_path = (
            db_paths[0]
            if (db_paths and Path(db_paths[0]).is_dir())
            else "/var/lib/pacman"
        )
        cache_dirs = [d for d in cache_dirs if Path(d).is_dir()]
        if not cache_dirs:
            cache_dirs = ["/var/cache/pacman/pkg/"]

        _handle = pyalpm.Handle(root_dir, db_path)
        _handle.cachedirs = cache_dirs

        # Register sync databases in exact /etc/pacman.conf priority order
        repos = _pacman_conf_repos()
        if not repos:
            sync_dir = Path(db_path) / "sync"
            if sync_dir.exists():
                repos = [dbfile.stem for dbfile in sorted(sync_dir.glob("*.db"))]

        for dbname in repos:
            try:
                _handle.register_syncdb(dbname, pyalpm.SIG_DATABASE_OPTIONAL)
            except Exception:
                pass  # Skip if registration fails
    return _handle


def search_packages(query, repos: list[str] | None = None) -> list:
    """
    Search for packages in sync databases using pyalpm.

    Args:
        query: Search term string (or sequence of terms)
        repos: Optional list of repo names to search (None = all repos)

    Returns:
        List of Package objects matching the query
    """
    handle = get_handle()
    results = []

    if isinstance(query, str):
        terms = [t for t in query.split() if t] or [query]
    else:
        terms = [str(t) for t in query if str(t)]
        if not terms:
            return []

    dbs = handle.get_syncdbs()
    if repos:
        # Filter to requested repos
        repo_dict = {db.name: db for db in dbs}
        dbs = [repo_dict[r] for r in repos if r in repo_dict]

    for db in dbs:
        # db.search() takes variable args (multiple keywords as regexes)
        try:
            results.extend(db.search(*terms))
        except pyalpm.error:
            escaped_terms = [re.escape(t) for t in terms]
            try:
                results.extend(db.search(*escaped_terms))
            except pyalpm.error:
                continue

    return results


def get_package(pkgname: str, repo: str | None = None):
    """
    Get a package by name, optionally from a specific repo.

    Args:
        pkgname: Package name
        repo: Optional repo name

    Returns:
        Package object or None
    """
    handle = get_handle()

    if repo:
        # Search specific repo
        for db in handle.get_syncdbs():
            if db.name == repo:
                return db.get_pkg(pkgname)
        return None
    else:
        # Search all repos (first match wins)
        for db in handle.get_syncdbs():
            pkg = db.get_pkg(pkgname)
            if pkg:
                return pkg
        return None


def get_local_package(pkgname: str):
    """Get an installed package by name."""
    handle = get_handle()
    return handle.get_localdb().get_pkg(pkgname)


def get_installed_packages(
    foreign_only=False, explicit_only=False, deps_only=False
) -> list:
    """
    Get list of installed packages.

    Args:
        foreign_only: Only packages not in any sync repo (AUR packages)
        explicit_only: Only explicitly installed packages
        deps_only: Only packages installed as dependencies

    Returns:
        List of Package objects
    """
    handle = get_handle()
    localdb = handle.get_localdb()
    packages = list(localdb.pkgcache)

    if foreign_only:
        # Filter to packages not in any sync DB
        sync_pkgs = set()
        for db in handle.get_syncdbs():
            sync_pkgs.update(pkg.name for pkg in db.pkgcache)
        packages = [pkg for pkg in packages if pkg.name not in sync_pkgs]

    if explicit_only:
        packages = [pkg for pkg in packages if pkg.reason == pyalpm.PKG_REASON_EXPLICIT]

    if deps_only:
        packages = [pkg for pkg in packages if pkg.reason == pyalpm.PKG_REASON_DEPEND]

    return packages


def get_orphan_packages() -> list:
    """
    Get orphaned packages (installed as deps and not required or optionally required).

    Returns:
        List of Package objects
    """
    handle = get_handle()
    localdb = handle.get_localdb()

    orphans = []
    for pkg in localdb.pkgcache:
        if pkg.reason == pyalpm.PKG_REASON_DEPEND:
            # Check if any package requires or optionally depends on this one
            rdeps = pkg.compute_requiredby()
            optfor = (
                pkg.compute_optionalfor()
                if hasattr(pkg, "compute_optionalfor")
                else []
            )
            if not rdeps and not optfor:
                orphans.append(pkg)

    return orphans


def get_available_updates() -> list[tuple]:
    """
    Get list of packages with available updates (respecting IgnorePkg/IgnoreGroup).

    Returns:
        List of tuples: (package_name, current_version, new_version)
    """
    handle = get_handle()
    localdb = handle.get_localdb()
    ignore_pkgs = [p for line in _pacman_conf("IgnorePkg") for p in line.split()]
    ignore_groups = [g for line in _pacman_conf("IgnoreGroup") for g in line.split()]
    updates = []

    for local_pkg in localdb.pkgcache:
        if any(fnmatch.fnmatchcase(local_pkg.name, pat) for pat in ignore_pkgs):
            continue
        pkg_groups = getattr(local_pkg, "groups", None) or []
        if ignore_groups and any(
            fnmatch.fnmatchcase(grp, pat)
            for grp in pkg_groups
            for pat in ignore_groups
        ):
            continue

        # Find this package in sync repos
        new_pkg = None
        for syncdb in handle.get_syncdbs():
            new_pkg = syncdb.get_pkg(local_pkg.name)
            if new_pkg:
                break

        if new_pkg:
            # Compare versions
            cmp = pyalpm.vercmp(new_pkg.version, local_pkg.version)
            if cmp > 0:  # new version is greater
                updates.append((local_pkg.name, local_pkg.version, new_pkg.version))

    return updates


def get_all_repo_packages() -> list:
    """Get all packages available in sync repos."""
    handle = get_handle()
    packages = []
    for db in handle.get_syncdbs():
        packages.extend(db.pkgcache)
    return packages


def is_package_installed(pkgname: str) -> bool:
    """Check if a package or a provider for it is installed."""
    if get_local_package(pkgname) is not None:
        return True
    handle = get_handle()
    localdb = handle.get_localdb()
    return pyalpm.find_satisfier(localdb.pkgcache, pkgname) is not None


def get_cache_dirs() -> list[Path]:
    """Get list of cache directories from pyalpm."""
    handle = get_handle()
    return [Path(p) for p in handle.cachedirs]


def clean_cache(keep: int = 3, dry_run: bool = False, verbose: bool = True) -> int:
    """
    Remove old package versions from cache, keeping the latest 'keep' versions.
    Equivalent to paccache -rk3.

    Args:
        keep: Number of versions to keep (default 3)
        dry_run: If True, do not actually delete files
        verbose: If True, print information about deleted files

    Returns:
        Number of bytes freed (or would be freed)
    """
    import os

    freed_bytes = 0
    cache_dirs = get_cache_dirs()

    # Regex to match package files: name-version-release-arch.pkg.tar.zst (or other extensions)
    # This is tricky because version can contain hyphens.
    # However, standard Arch package naming is relatively strict.
    # We can try to rely on the fact that we can listing all files and grouping them.
    # Better approach: Use a regex that captures the known suffix structure.
    # .pkg.tar.zst | .pkg.tar.xz | .pkg.tar.gz | .pkg.tar

    # But names can also have hyphens.
    # Helper to parse filename
    def parse_pkg_filename(filename):
        # Remove extension
        for ext in [
            ".pkg.tar.zst",
            ".pkg.tar.xz",
            ".pkg.tar.gz",
            ".pkg.tar.bz2",
            ".pkg.tar",
            ".pkg.tar.lzo",
            ".pkg.tar.lz4",
        ]:
            if filename.endswith(ext):
                base = filename[: -len(ext)]
                # Now base is name-version-release-arch
                # arch is last, release is 2nd last...
                parts = base.split("-")
                if len(parts) >= 4:
                    arch = parts[-1]
                    # We need to reconstruct name and version.
                    # As version can have hyphens? Generally pkgver()-release
                    # Arch packages format: name-version-release-arch
                    # but version itself can be like 1.2.3-1 (if release is included in version? no release is separate)
                    # wait, verify standard:
                    # pkgname-pkgver-pkgrel-arch.pkg.tar.zst
                    # pkgver can contain hyphens? No, pkgver cannot contain hyphens.
                    # pkgrel cannot contain hyphens.
                    # So:
                    # parts[-1] = arch
                    # parts[-2] = pkgrel
                    # parts[-3] = pkgver (no hyphens allowed in Arch pkgver)
                    # parts[:-3] = name (can contain hyphens)

                    pkgrel = parts[-2]
                    pkgver = parts[-3]
                    name = "-".join(parts[:-3])
                    full_version = f"{pkgver}-{pkgrel}"
                    return name, full_version, arch
        return None, None, None

    # Group files by (name, arch)
    # We treat different architectures as distinct sets of packages to version
    package_files = {}  # (name, arch) -> list of (version, filepath, size)

    for cache_dir in cache_dirs:
        if not cache_dir.exists():
            continue

        for child in cache_dir.iterdir():
            if not child.is_file():
                continue

            name, version, arch = parse_pkg_filename(child.name)
            if name and version and arch:
                key = (name, arch)
                if key not in package_files:
                    package_files[key] = []
                package_files[key].append(
                    {"version": version, "path": child, "size": child.stat().st_size}
                )

    # Process groups
    deleted_count = 0

    for key, files in package_files.items():
        if len(files) <= keep:
            continue

        # Sort by version using pyalpm.vercmp
        # We want descending order (newest first)
        # functools.cmp_to_key is needed for sort
        from functools import cmp_to_key

        def compare_versions(item1, item2):
            return pyalpm.vercmp(item1["version"], item2["version"])

        files.sort(key=cmp_to_key(compare_versions), reverse=True)

        # Keep top 'keep'
        to_delete = files[keep:]

        for item in to_delete:
            size = item["size"]
            path = item["path"]

            freed_bytes += size
            deleted_count += 1

            if verbose:
                # Calculate size in sensible units for display
                # We can import fmt_adaptive_size from commands but that would be a circular import.
                # Let's just print simple info or rely on caller?
                # The function signature says "verbose=True", so let's print.
                # But we should use the logger or print. Since this is alpm_helper, maybe plain print or localized?
                # Let's return the info or print if verbose.

                # To avoid circular import, we won't import from ui/commands
                pass

            if not dry_run:
                try:
                    os.remove(path)
                    # Also remove signature file if exists (.sig)
                    sig_path = path.parent / (path.name + ".sig")
                    if sig_path.exists():
                        os.remove(sig_path)
                except OSError:
                    pass

    return freed_bytes


def is_in_official_repos(pkgname: str) -> bool:
    """
    Check if a package exists in official repos (exact match or provider).
    """
    handle = get_handle()
    for db in handle.get_syncdbs():
        # Check exact match first
        if db.get_pkg(pkgname):
            return True
        # Check providers
        if pyalpm.find_satisfier(db.pkgcache, pkgname):
            return True
    return False


# =============================================================================
# Formatting functions for pacman-style output
# =============================================================================


def format_size(bytes_val: int | None) -> str:
    """Format byte size in human readable format (KiB, MiB, GiB)."""
    if bytes_val is None:
        bytes_val = 0
    if bytes_val < 1024:
        return f"{bytes_val} B"
    elif bytes_val < 1024 * 1024:
        return f"{bytes_val / 1024:.2f} KiB"
    elif bytes_val < 1024 * 1024 * 1024:
        return f"{bytes_val / (1024 * 1024):.2f} MiB"
    else:
        return f"{bytes_val / (1024 * 1024 * 1024):.2f} GiB"


def format_timestamp(ts: int | None) -> str:
    """Format unix timestamp to readable date."""
    from datetime import datetime

    if ts is None:
        return "Unknown"
    try:
        return datetime.fromtimestamp(ts).strftime("%a %d %b %Y %I:%M:%S %p %Z")
    except (TypeError, ValueError, OSError, OverflowError):
        return "Unknown"


def format_optdeps(optdeps: list) -> str:
    """Format optional dependencies list for multi-line display."""
    if not optdeps:
        return "None"
    # optdeps is a list of strings "pkgname: description"
    formatted = []
    for dep in optdeps:
        formatted.append(f"                     {dep}")
    return "\n" + "\n".join(formatted)


def format_sync_package(pkg) -> str:
    """
    Format sync DB package in pacman -Si style.

    Args:
        pkg: pyalpm Package object from sync database

    Returns:
        Formatted string in pacman -Si format
    """
    lines = []

    lines.append(
        f"Repository      : {pkg.db.name if hasattr(pkg, 'db') and pkg.db else 'unknown'}"
    )
    lines.append(f"Name            : {pkg.name}")
    lines.append(f"Version         : {pkg.version}")
    lines.append(f"Description     : {pkg.desc if pkg.desc else 'None'}")
    lines.append(f"Architecture    : {pkg.arch}")
    lines.append(f"URL             : {pkg.url if pkg.url else 'None'}")
    lines.append(
        f"Licenses        : {' '.join(pkg.licenses) if pkg.licenses else 'None'}"
    )
    lines.append(f"Groups          : {' '.join(pkg.groups) if pkg.groups else 'None'}")
    lines.append(
        f"Provides        : {' '.join(pkg.provides) if pkg.provides else 'None'}"
    )
    lines.append(
        f"Depends On      : {' '.join(pkg.depends) if pkg.depends else 'None'}"
    )
    lines.append(f"Optional Deps   : {format_optdeps(pkg.optdepends)}")
    lines.append(
        f"Conflicts With  : {' '.join(pkg.conflicts) if pkg.conflicts else 'None'}"
    )
    lines.append(
        f"Replaces        : {' '.join(pkg.replaces) if pkg.replaces else 'None'}"
    )
    lines.append(f"Download Size   : {format_size(pkg.size)}")
    lines.append(f"Installed Size  : {format_size(pkg.isize)}")
    lines.append(
        f"Packager        : {pkg.packager if pkg.packager else 'Unknown Packager'}"
    )
    lines.append(f"Build Date      : {format_timestamp(pkg.builddate)}")

    # Add MD5 Sum if available
    if hasattr(pkg, "md5sum") and pkg.md5sum:
        lines.append(f"MD5 Sum         : {pkg.md5sum}")

    # Add SHA-256 Sum if available
    if hasattr(pkg, "sha256sum") and pkg.sha256sum:
        lines.append(f"SHA-256 Sum     : {pkg.sha256sum}")

    return "\n".join(lines)


def format_local_package(pkg) -> str:
    """
    Format local DB package in pacman -Qi style.

    Args:
        pkg: pyalpm Package object from local database

    Returns:
        Formatted string in pacman -Qi format
    """
    lines = []

    lines.append(f"Name            : {pkg.name}")
    lines.append(f"Version         : {pkg.version}")
    lines.append(f"Description     : {pkg.desc if pkg.desc else 'None'}")
    lines.append(f"Architecture    : {pkg.arch}")
    lines.append(f"URL             : {pkg.url if pkg.url else 'None'}")
    lines.append(
        f"Licenses        : {' '.join(pkg.licenses) if pkg.licenses else 'None'}"
    )
    lines.append(f"Groups          : {' '.join(pkg.groups) if pkg.groups else 'None'}")
    lines.append(
        f"Provides        : {' '.join(pkg.provides) if pkg.provides else 'None'}"
    )
    lines.append(
        f"Depends On      : {' '.join(pkg.depends) if pkg.depends else 'None'}"
    )
    lines.append(f"Optional Deps   : {format_optdeps(pkg.optdepends)}")

    # Required By - compute reverse dependencies
    required_by = pkg.compute_requiredby() if hasattr(pkg, "compute_requiredby") else []
    lines.append(
        f"Required By     : {' '.join(required_by) if required_by else 'None'}"
    )

    # Optional For - compute optional reverse dependencies
    optional_for = (
        pkg.compute_optionalfor() if hasattr(pkg, "compute_optionalfor") else []
    )
    lines.append(
        f"Optional For    : {' '.join(optional_for) if optional_for else 'None'}"
    )

    lines.append(
        f"Conflicts With  : {' '.join(pkg.conflicts) if pkg.conflicts else 'None'}"
    )
    lines.append(
        f"Replaces        : {' '.join(pkg.replaces) if pkg.replaces else 'None'}"
    )
    lines.append(f"Installed Size  : {format_size(pkg.isize)}")
    lines.append(
        f"Packager        : {pkg.packager if pkg.packager else 'Unknown Packager'}"
    )
    lines.append(f"Build Date      : {format_timestamp(pkg.builddate)}")
    lines.append(f"Install Date    : {format_timestamp(pkg.installdate)}")

    # Install Reason
    reason_str = (
        "Explicitly installed"
        if pkg.reason == pyalpm.PKG_REASON_EXPLICIT
        else "Installed as a dependency"
    )
    lines.append(f"Install Reason  : {reason_str}")

    # Install Script
    has_script = (
        "Yes" if (hasattr(pkg, "has_scriptlet") and pkg.has_scriptlet) else "No"
    )
    lines.append(f"Install Script  : {has_script}")

    # Validated By
    validation = []
    if hasattr(pkg, "validation"):
        if pkg.validation & pyalpm.PKG_VALIDATION_NONE:
            validation.append("None")
        if pkg.validation & pyalpm.PKG_VALIDATION_MD5SUM:
            validation.append("MD5 Sum")
        if pkg.validation & pyalpm.PKG_VALIDATION_SHA256SUM:
            validation.append("SHA256 Sum")
        if pkg.validation & pyalpm.PKG_VALIDATION_SIGNATURE:
            validation.append("Signature")
    lines.append(f"Validated By    : {' '.join(validation) if validation else 'None'}")

    return "\n".join(lines)


def get_package_info_formatted(pkgname: str) -> tuple[str | None, str | None]:
    """
    Get package info formatted as pacman -Si/Qi.

    Args:
        pkgname: Package name to look up

    Returns:
        Tuple of (formatted_string, source) where:
        - formatted_string: The formatted package info, or None if not found
        - source: 'sync' for sync repos, 'local' for installed, or None
    """
    # Try sync repos first
    pkg = get_package(pkgname)
    if pkg:
        return (format_sync_package(pkg), "sync")

    # Try local database
    pkg = get_local_package(pkgname)
    if pkg:
        return (format_local_package(pkg), "local")

    return (None, None)
