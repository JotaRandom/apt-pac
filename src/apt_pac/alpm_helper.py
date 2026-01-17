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
