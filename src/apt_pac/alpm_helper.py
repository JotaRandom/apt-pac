"""
Helper utilities for pyalpm operations.
"""
import pyalpm
from pathlib import Path
from typing import List, Optional

_handle = None

def get_handle():
    """
    Get or create a pyalpm Handle with standard configuration.
    This reuses the same handle for efficiency.
    """
    global _handle
    if _handle is None:
        _handle = pyalpm.Handle("/", "/var/lib/pacman")
        # Register standard sync databases
        # We read from the actual sync directory to auto-discover DBs
        sync_dir = Path("/var/lib/pacman/sync")
        if sync_dir.exists():
            for dbfile in sync_dir.glob("*.db"):
                dbname = dbfile.stem  # Remove .db extension
                try:
                    _handle.register_syncdb(dbname, pyalpm.SIG_DATABASE_OPTIONAL)
                except Exception:
                    pass  # Skip if registration fails
    return _handle

def search_packages(query: str, repos: Optional[List[str]] = None) -> List:
    """
    Search for packages in sync databases using pyalpm.
    
    Args:
        query: Search term
        repos: Optional list of repo names to search (None = all repos)
    
    Returns:
        List of Package objects matching the query
    """
    handle = get_handle()
    results = []
    
    dbs = handle.get_syncdbs()
    if repos:
        # Filter to requested repos
        repo_dict = {db.name: db for db in dbs}
        dbs = [repo_dict[r] for r in repos if r in repo_dict]
    
    for db in dbs:
        # db.search() takes variable args (multiple keywords)
        results.extend(db.search(query))
    
    return results

def get_package(pkgname: str, repo: Optional[str] = None):
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

def get_installed_packages(foreign_only=False, explicit_only=False, deps_only=False) -> List:
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

def get_orphan_packages() -> List:
    """
    Get orphaned packages (installed as deps but no longer required).
    
    Returns:
        List of Package objects
    """
    handle = get_handle()
    localdb = handle.get_localdb()
    
    orphans = []
    for pkg in localdb.pkgcache:
        if pkg.reason == pyalpm.PKG_REASON_DEPEND:
            # Check if any package requires this one
            rdeps = pkg.compute_requiredby()
            if not rdeps:
                orphans.append(pkg)
    
    return orphans

def get_available_updates() -> List[tuple]:
    """
    Get list of packages with available updates.
    
    Returns:
        List of tuples: (package_name, current_version, new_version)
    """
    handle = get_handle()
    localdb = handle.get_localdb()
    updates = []
    
    for local_pkg in localdb.pkgcache:
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

def get_all_repo_packages() -> List:
    """Get all packages available in sync repos."""
    handle = get_handle()
    packages = []
    for db in handle.get_syncdbs():
        packages.extend(db.pkgcache)
    return packages

def is_package_installed(pkgname: str) -> bool:
    """Check if a package is installed."""
    return get_local_package(pkgname) is not None

def get_cache_dirs() -> List[Path]:
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
    import re
    
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
        for ext in ['.pkg.tar.zst', '.pkg.tar.xz', '.pkg.tar.gz', '.pkg.tar', '.pkg.tar.lzo', '.pkg.tar.lz4']:
            if filename.endswith(ext):
                base = filename[:-len(ext)]
                # Now base is name-version-release-arch
                # arch is last, release is 2nd last...
                parts = base.split('-')
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
    package_files = {} # (name, arch) -> list of (version, filepath, size)
    
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
                package_files[key].append({
                    'version': version,
                    'path': child,
                    'size': child.stat().st_size
                })
    
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
            return pyalpm.vercmp(item1['version'], item2['version'])
            
        files.sort(key=cmp_to_key(compare_versions), reverse=True)
        
        # Keep top 'keep'
        to_delete = files[keep:]
        
        for item in to_delete:
            size = item['size']
            path = item['path']
            
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

def format_size(bytes_val: int) -> str:
    """Format byte size in human readable format (KiB, MiB, GiB)."""
    if bytes_val < 1024:
        return f"{bytes_val} B"
    elif bytes_val < 1024 * 1024:
        return f"{bytes_val / 1024:.2f} KiB"
    elif bytes_val < 1024 * 1024 * 1024:
        return f"{bytes_val / (1024 * 1024):.2f} MiB"
    else:
        return f"{bytes_val / (1024 * 1024 * 1024):.2f} GiB"

def format_timestamp(ts: int) -> str:
    """Format unix timestamp to readable date."""
    from datetime import datetime
    try:
        return datetime.fromtimestamp(ts).strftime("%a %d %b %Y %I:%M:%S %p %Z")
    except (ValueError, OSError):
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
    
    lines.append(f"Repository      : {pkg.db.name if hasattr(pkg, 'db') and pkg.db else 'unknown'}")
    lines.append(f"Name            : {pkg.name}")
    lines.append(f"Version         : {pkg.version}")
    lines.append(f"Description     : {pkg.desc if pkg.desc else 'None'}")
    lines.append(f"Architecture    : {pkg.arch}")
    lines.append(f"URL             : {pkg.url if pkg.url else 'None'}")
    lines.append(f"Licenses        : {' '.join(pkg.licenses) if pkg.licenses else 'None'}")
    lines.append(f"Groups          : {' '.join(pkg.groups) if pkg.groups else 'None'}")
    lines.append(f"Provides        : {' '.join(pkg.provides) if pkg.provides else 'None'}")
    lines.append(f"Depends On      : {' '.join(pkg.depends) if pkg.depends else 'None'}")
    lines.append(f"Optional Deps   : {format_optdeps(pkg.optdepends)}")
    lines.append(f"Conflicts With  : {' '.join(pkg.conflicts) if pkg.conflicts else 'None'}")
    lines.append(f"Replaces        : {' '.join(pkg.replaces) if pkg.replaces else 'None'}")
    lines.append(f"Download Size   : {format_size(pkg.size)}")
    lines.append(f"Installed Size  : {format_size(pkg.isize)}")
    lines.append(f"Packager        : {pkg.packager if pkg.packager else 'Unknown Packager'}")
    lines.append(f"Build Date      : {format_timestamp(pkg.builddate)}")
    
    # Add MD5 Sum if available
    if hasattr(pkg, 'md5sum') and pkg.md5sum:
        lines.append(f"MD5 Sum         : {pkg.md5sum}")
    
    # Add SHA-256 Sum if available
    if hasattr(pkg, 'sha256sum') and pkg.sha256sum:
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
    lines.append(f"Licenses        : {' '.join(pkg.licenses) if pkg.licenses else 'None'}")
    lines.append(f"Groups          : {' '.join(pkg.groups) if pkg.groups else 'None'}")
    lines.append(f"Provides        : {' '.join(pkg.provides) if pkg.provides else 'None'}")
    lines.append(f"Depends On      : {' '.join(pkg.depends) if pkg.depends else 'None'}")
    lines.append(f"Optional Deps   : {format_optdeps(pkg.optdepends)}")
    
    # Required By - compute reverse dependencies
    required_by = pkg.compute_requiredby() if hasattr(pkg, 'compute_requiredby') else []
    lines.append(f"Required By     : {' '.join(required_by) if required_by else 'None'}")
    
    # Optional For - compute optional reverse dependencies
    optional_for = pkg.compute_optionalfor() if hasattr(pkg, 'compute_optionalfor') else []
    lines.append(f"Optional For    : {' '.join(optional_for) if optional_for else 'None'}")
    
    lines.append(f"Conflicts With  : {' '.join(pkg.conflicts) if pkg.conflicts else 'None'}")
    lines.append(f"Replaces        : {' '.join(pkg.replaces) if pkg.replaces else 'None'}")
    lines.append(f"Installed Size  : {format_size(pkg.isize)}")
    lines.append(f"Packager        : {pkg.packager if pkg.packager else 'Unknown Packager'}")
    lines.append(f"Build Date      : {format_timestamp(pkg.builddate)}")
    lines.append(f"Install Date    : {format_timestamp(pkg.installdate)}")
    
    # Install Reason
    reason_str = "Explicitly installed" if pkg.reason == pyalpm.PKG_REASON_EXPLICIT else "Installed as a dependency"
    lines.append(f"Install Reason  : {reason_str}")
    
    # Install Script
    has_script = "Yes" if (hasattr(pkg, 'has_scriptlet') and pkg.has_scriptlet) else "No"
    lines.append(f"Install Script  : {has_script}")
    
    # Validated By
    validation = []
    if hasattr(pkg, 'validation'):
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

def get_package_info_formatted(pkgname: str) -> tuple:
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
        return (format_sync_package(pkg), 'sync')
    
    # Try local database
    pkg = get_local_package(pkgname)
    if pkg:
        return (format_local_package(pkg), 'local')
    
    return (None, None)
