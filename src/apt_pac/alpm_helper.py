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
