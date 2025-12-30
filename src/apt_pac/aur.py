import json
import urllib.request
import urllib.parse
from typing import List, Dict, Optional, Set, Tuple
import subprocess
import os
import sys
from pathlib import Path
from .ui import console, print_error, print_info, print_command
from .config import get_config

AUR_RPC_URL = "https://aur.archlinux.org/rpc/v5/"

def search_aur(query: str) -> List[Dict]:
    """
    Search the AUR for packages matching the query.
    Returns a list of dicts containing package info.
    """
    try:
        # Construct URL: /rpc/v5/search/{arg}
        # Note: v5 search endpoint documentation typically uses /search/keyword
        safe_query = urllib.parse.quote(query)
        url = f"{AUR_RPC_URL}search/{safe_query}"
        
        req = urllib.request.Request(url)
        # Add user agent strictly required by some APIs
        req.add_header('User-Agent', 'apt-pac/2026.01.01')
        
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status != 200:
                return []
            
            data = json.loads(response.read().decode('utf-8'))
            
            # v5 response structure: {"version":5, "type":"search", "resultcount": N, "results": [...]}
            if data.get("type") == "search" and "results" in data:
                return data["results"]
            
    except Exception:
        return []
    
    return []

def get_aur_info(package_names: List[str]) -> List[Dict]:
    """
    Get detailed info for specific packages.
    """
    if not package_names:
        return []

    # Max URI length is limited, so we might need to batch this if list is huge
    # For now, simple implementation
    
    params = [("v", "5"), ("type", "info")]
    for p in package_names:
        params.append(("arg[]", p))
        
    query_string = urllib.parse.urlencode(params)
    url = f"{AUR_RPC_URL}info?{query_string}"
    
    try:
        req = urllib.request.Request(url)
        req.add_header('User-Agent', 'apt-pac/2026.01.01')
        
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status != 200:
                return []
            
            data = json.loads(response.read().decode('utf-8'))
            
            if data.get("type") == "multiinfo" and "results" in data:
                return data["results"]
                
    except Exception:
        return []
        
    return []

def is_installed(package: str) -> bool:
    """Check if a package is installed locally."""
    return subprocess.run(
        ["pacman", "-Qq", package], 
        stdout=subprocess.DEVNULL, 
        stderr=subprocess.DEVNULL
    ).returncode == 0

def is_in_official_repos(package: str) -> bool:
    """Check if a package exists in official repos."""
    return subprocess.run(
        ["pacman", "-Si", package], 
        stdout=subprocess.DEVNULL, 
        stderr=subprocess.DEVNULL
    ).returncode == 0

class AurResolver:
    def __init__(self):
        self.seen = set()
        self.queue = [] # Topological sort result
        self.aur_info_cache = {}

    def resolve(self, packages: List[str]) -> List[Dict]:
        """
        Resolve dependencies for a list of packages.
        Returns a list of package info dicts in build order.
        """
        for pkg in packages:
            self._visit(pkg)
        return self.queue

    def _visit(self, pkg_name: str):
        if pkg_name in self.seen or is_installed(pkg_name):
            return
        
        # Check if official (ignore if so, makepkg handles it)
        if is_in_official_repos(pkg_name):
            return

        # Fetch info from AUR
        if pkg_name not in self.aur_info_cache:
            info = get_aur_info([pkg_name])
            if not info:
                print_error(f"Package '{pkg_name}' not found in AUR or official repos.")
                sys.exit(1)
            self.aur_info_cache[pkg_name] = info[0]
        
        pkg_info = self.aur_info_cache[pkg_name]
        self.seen.add(pkg_name) # Mark as visiting/visited

        # Dependencies
        deps = pkg_info.get('Depends', []) + pkg_info.get('MakeDepends', []) + pkg_info.get('CheckDepends', [])
        
        # Strip version requirements (e.g. 'python>=3.8' -> 'python')
        clean_deps = []
        for d in deps:
            # Handle headers like 'depend>=1.0'
            clean_name = d.split('>')[0].split('<')[0].split('=')[0].strip()
            clean_deps.append(clean_name)

        # Recurse
        for dep in clean_deps:
            self._visit(dep)
            
        # Add to queue (Post-order)
        self.queue.append(pkg_info)

class AurInstaller:
    def __init__(self):
        self.config = get_config()
        # Use user-writeable cache dir for sources
        # We need a place where the user has permissions. 
        # Typically ~/.cache/apt-pac/sources/
        self.build_dir = self.config.cache_dir / "sources" / "aur"
        if not self.build_dir.exists():
            self.build_dir.mkdir(parents=True, exist_ok=True)

    def install(self, packages: List[str], verbose=False):
        resolver = AurResolver()
        with console.status("[blue]Resolving AUR dependencies...[/blue]", spinner="dots"):
            build_queue = resolver.resolve(packages)
        
        if not build_queue:
            print_info("Nothing to do.")
            return

        # APT-like Summary
        console.print("Reading package lists... Done")
        console.print("Building dependency tree... Done")
        console.print("Reading state information... Done")
        
        console.print("The following NEW packages will be installed:")
        names = [p['Name'] for p in build_queue]
        # Sort for display
        names.sort()
        console.print(f"  {' '.join(names)}")
        
        # Calculate size if possible? AUR RPC doesn't give built size easily, assuming unknown.
        count = len(names)
        console.print(f"0 upgraded, {count} newly installed, 0 to remove and 0 not upgraded.")
        
        if not console.input("Do you want to continue? [Y/n] ").lower().startswith('y'):
            print_info("Aborted.")
            sys.exit(0)

        for pkg in build_queue:
            self._build_pkg(pkg, verbose)

    def _build_pkg(self, pkg_info: Dict, verbose: bool):
        name = pkg_info['Name']
        base_url = "https://aur.archlinux.org"
        clone_url = f"{base_url}/{name}.git"
        pkg_dir = self.build_dir / name
        
        console.print(f"\n[bold blue]:: Processing {name}...[/bold blue]")
        
        # 1. Clone or Pull
        if pkg_dir.exists():
            console.print(f"[dim]Updating {name} sources...[/dim]")
            subprocess.run(["git", "pull"], cwd=pkg_dir, check=False)
        else:
            console.print(f"[dim]Cloning {name}...[/dim]")
            subprocess.run(["git", "clone", clone_url, str(pkg_dir)], check=True)
            
        # 2. Build
        console.print(f"[dim]Building {name}...[/dim]")
        # makepkg -si (sync deps, install, clean, noconfirm for deps)
        # We use --noconfirm for pacman calls inside makepkg, but makepkg itself doesn't always take it well for sudo
        # Using --syncdeps to handle official deps
        # Using --install to install the built package
        cmd = ["makepkg", "-si", "--noconfirm", "--needed"]
        
        if os.getuid() == 0:
             # Dropping privileges is complex without knowing the real user. 
             pass 

        try:
            # We redirect output unless verbose
            # But makepkg interactive password prompt? 
            # We must allow stdout/stdin.
            subprocess.run(cmd, cwd=pkg_dir, check=True)
            console.print(f"[success]Successfully installed {name}[/success]")
        except subprocess.CalledProcessError:
            print_error(f"Failed to build {name}")
            sys.exit(1)
