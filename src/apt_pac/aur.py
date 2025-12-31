import json
import urllib.request
import urllib.parse
from typing import List, Dict, Optional, Set, Tuple
import subprocess
import os
import sys
import shutil
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
    """Check if a package exists in official repos (or is provided by one)."""
    # -Si only checks exact name. -Sp checks if it can be resolved (downloadable).
    # We use --noconfirm so it picks defaults for providers check without hanging.
    return subprocess.run(
        ["pacman", "-Sp", "--noconfirm", package], 
        stdout=subprocess.DEVNULL, 
        stderr=subprocess.DEVNULL
    ).returncode == 0

def get_installed_packages() -> Dict[str, str]:
    """
    Get all installed packages and their versions.
    Returns: Dict[package_name, version]
    """
    try:
        result = subprocess.run(["pacman", "-Q"], capture_output=True, text=True)
        packages = {}
        for line in result.stdout.splitlines():
            if not line.strip(): continue
            parts = line.split()
            if len(parts) >= 2:
                packages[parts[0]] = parts[1]
        return packages
    except Exception:
        return {}

def get_installed_aur_packages() -> List[str]:
    """
    Get list of installed packages that are NOT in official repos.
    Uses 'pacman -Qm' (foreign packages).
    """
    try:
        result = subprocess.run(["pacman", "-Qm"], capture_output=True, text=True)
        packages = []
        for line in result.stdout.splitlines():
            if not line.strip(): continue
            parts = line.split()
            if len(parts) >= 1:
                packages.append(parts[0])
        return packages
    except Exception:
        return []

def version_compare(ver1: str, ver2: str) -> int:
    """
    Compare two versions using vercmp.
    Returns: <0 if ver1<ver2, 0 if equal, >0 if ver1>ver2
    """
    try:
        result = subprocess.run(["vercmp", ver1, ver2], capture_output=True, text=True)
        return int(result.stdout.strip())
    except (ValueError, Exception):
        return 0

def check_updates(verbose=False) -> List[Dict]:
    """
    Check for updates for all installed AUR packages.
    Returns list of dicts: {'name': str, 'current': str, 'new': str}
    """
    installed_aur = get_installed_aur_packages()
    if not installed_aur:
        return []

    if verbose:
        console.print(f"[dim]Checking {len(installed_aur)} foreign packages for updates...[/dim]")

    # Get local versions
    installed_map = get_installed_packages()
    
    # Get AUR info (batch request)
    # AUR RPC recommends max 100 args per request usually, but let's try batching chunks of 50
    updates = []
    chunk_size = 50
    
    for i in range(0, len(installed_aur), chunk_size):
        chunk = installed_aur[i:i + chunk_size]
        try:
            aur_info_list = get_aur_info(chunk)
            
            for info in aur_info_list:
                name = info['Name']
                aur_ver = info['Version']
                local_ver = installed_map.get(name)
                
                if local_ver and version_compare(local_ver, aur_ver) < 0:
                    updates.append({
                        'name': name,
                        'current': local_ver,
                        'new': aur_ver
                    })
        except Exception as e:
            if verbose:
                print_error(f"Error checking updates for chunk: {e}")
                
    return updates

def download_aur_source(package_name: str, target_dir: Optional[Path] = None, force=False) -> Optional[Path]:
    """
    Clone an AUR package repository.
    """
    base_url = "https://aur.archlinux.org"
    clone_url = f"{base_url}/{package_name}.git"
    
    if target_dir is None:
        config = get_config()
        target_dir = config.cache_dir / "sources" / "aur" / package_name
    
    if target_dir.exists():
        if force:
            shutil.rmtree(target_dir)
        elif (target_dir / ".git").exists():
            # Already exists and is a git repo, just pull
            try:
                subprocess.run(["git", "pull"], cwd=target_dir, capture_output=True, check=True)
                return target_dir
            except subprocess.CalledProcessError:
                # If pull fails, might need to re-clone
                pass
    
    # Clone
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    if not target_dir.exists():
         try:
            subprocess.run(["git", "clone", clone_url, str(target_dir)], capture_output=True, check=True)
            return target_dir
         except subprocess.CalledProcessError:
            return None
            
    return target_dir

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

    def install(self, packages: List[str], verbose=False, auto_confirm=False):
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
            self._build_pkg(pkg, verbose, auto_confirm)

    def _build_pkg(self, pkg_info: Dict, verbose: bool, auto_confirm: bool):
        name = pkg_info['Name']
        pkg_dir = self.build_dir / name
        
        console.print(f"\n[bold blue]:: Processing {name}...[/bold blue]")
        
        # 1. Clone or Pull
        if not download_aur_source(name, pkg_dir):
            print_error(f"Failed to download source for {name}")
            sys.exit(1)
            
        # Fix permissions if running as root (so ordinary user can build)
        real_user = os.environ.get("SUDO_USER")
        if os.getuid() == 0 and real_user:
            # Recursively chown the specific package directory and parent
            # We chown the whole build_dir to be safe as it's a cache dir
            subprocess.run(["chown", "-R", f"{real_user}:", str(self.build_dir)], check=False)

        # 2. Build
        console.print(f"[dim]Building {name}...[/dim]")
        
        # makepkg -si (sync deps, install, clean, needed)
        # We only add --noconfirm if auto_confirm is True, otherwise allow interaction
        # This effectively enables "Smart Providers" (pacman asks user which provider to pick)
        cmd = ["makepkg", "-si", "--needed"]
        if auto_confirm:
            cmd.append("--noconfirm")
        
        if os.getuid() == 0:
             if real_user:
                 # Drop privileges to build, but allow installing deps (makepkg calls sudo/pacman)
                 cmd = ["sudo", "-u", real_user] + cmd
             else:
                 print_error("E: Cannot build AUR packages as root without SUDO_USER set.")
                 print_info("Please run as a normal user or via sudo.")
                 sys.exit(1)

        try:
            # We redirect output unless verbose
            # Capture output to check for GPG errors if it fails
            subprocess.run(cmd, cwd=pkg_dir, check=True, capture_output=not verbose)
            console.print(f"[success]Successfully installed {name}[/success]")
            
        except subprocess.CalledProcessError as e:
            # Check for GPG errors
            # "One or more PGP signatures could not be verified"
            # "unknown public key D1483FA6C3C07136"
            err_output = e.stderr.decode('utf-8') if e.stderr else ""
            if not verbose and e.stdout:
                err_output += e.stdout.decode('utf-8')

            import re
            # Regex to find key IDs (hex strings) associated with unknown public key errors
            # Look for: "unknown public key <ID>" or "public key <ID> could not be verified"
            key_matches = re.findall(r"public key ([A-Fa-f0-9]+)", err_output)
            
            if ("PGP signatures" in err_output or "unknown public key" in err_output) and key_matches:
                console.print(f"\n[bold yellow]W: GPG verification failed. Missing keys detected: {', '.join(set(key_matches))}[/bold yellow]")
                
                if auto_confirm or console.input("Do you want to try importing these keys? [Y/n] ").lower().startswith('y'):
                    for key_id in set(key_matches):
                        console.print(f"[blue]Importing key {key_id}...[/blue]")
                        gpg_cmd = ["gpg", "--recv-keys", key_id]
                        
                        # IMPORTANT: Import key for the REAL USER, not root
                        if os.getuid() == 0 and real_user:
                             gpg_cmd = ["sudo", "-u", real_user] + gpg_cmd
                        
                        subprocess.run(gpg_cmd, check=False)
                    
                    # Retry build once
                    console.print("[blue]Retrying build...[/blue]")
                    try:
                        subprocess.run(cmd, cwd=pkg_dir, check=True)
                        console.print(f"[success]Successfully installed {name}[/success]")
                        return
                    except subprocess.CalledProcessError:
                         pass # Fallthrough to failure message

            if verbose:
                # If verbose was off, we didn't show the error yet (captured)
                print_error(f"Build output:\n{err_output}")
            
            print_error(f"Failed to build {name}")
            sys.exit(1)
