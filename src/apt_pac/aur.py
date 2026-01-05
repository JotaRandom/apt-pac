import json
import time
import urllib.request
import urllib.parse
from typing import List, Dict, Optional, Set, Tuple
import subprocess
import os
import sys
import shutil
from pathlib import Path
from .ui import (
    console, print_error, print_info, print_command, 
    print_columnar_list, print_transaction_summary, print_reading_status
)
from .i18n import _
from .config import get_config

class CyclicDependencyError(Exception):
    """Raised when a circular dependency is detected in AUR packages."""
    def __init__(self, cycle_path: List[str]):
        self.cycle = cycle_path
        cycle_str = " → ".join(cycle_path)
        super().__init__(f"Dependency cycle detected: {cycle_str}")

AUR_RPC_URL = "https://aur.archlinux.org/rpc/v5/"
CACHE_FILE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "apt-pac" / "rpc_cache.json"

def _load_cache() -> Dict:
    if not CACHE_FILE.exists():
        return {}
    try:
        with open(CACHE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def _save_cache(cache: Dict):
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache, f)
    except Exception:
        pass

def _get_cached(key: str) -> Optional[List[Dict]]:
    config = get_config()
    # Default to 30 minutes if not set
    ttl_minutes = config.get("performance", "rpc_cache_ttl", 30)
    ttl_seconds = ttl_minutes * 60
    
    cache = _load_cache()
    if key in cache:
        entry = cache[key]
        if time.time() - entry.get('timestamp', 0) < ttl_seconds:
            return entry.get('data')
        else:
            # Expired
            del cache[key]
            _save_cache(cache)
    return None

def _set_cached(key: str, data: List[Dict]):
    cache = _load_cache()
    # Clean up old entries occasionally? For now just append/overwrite.
    # Simple size limit check could be added here if needed.
    cache[key] = {
        'timestamp': time.time(),
        'data': data
    }
    _save_cache(cache)

def search_aur(query: str) -> List[Dict]:
    """
    Search the AUR for packages matching the query.
    Returns a list of dicts containing package info.
    """
    try:
        # Construct URL: /rpc/v5/search/{arg}
        # Note: v5 search endpoint documentation typically uses /search/keyword
        safe_query = urllib.parse.quote(query)
        cache_key = f"search:{safe_query}"
        
        cached = _get_cached(cache_key)
        if cached is not None:
            return cached
            
        url = f"{AUR_RPC_URL}search/{safe_query}"
        
        req = urllib.request.Request(url)
        # Add user agent strictly required by some APIs
        req.add_header('User-Agent', 'apt-pac/2026.01.01')
        
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status != 200:
                return []
            
            data = json.loads(response.read().decode('utf-8'))
            
            # v5 response structure: {"version":5, "type":"search", "resultcount": N, "results": [...]}
            # v5 response structure: {"version":5, "type":"search", "resultcount": N, "results": [...]}
            if data.get("type") == "search" and "results" in data:
                results = data["results"]
                _set_cached(cache_key, results)
                return results
            
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
    
    # Cache key based on sorted package names to ensure consistency
    sorted_names = ",".join(sorted(package_names))
    cache_key = f"info:{sorted_names}"
    
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    url = f"{AUR_RPC_URL}info?{query_string}"
    
    try:
        req = urllib.request.Request(url)
        req.add_header('User-Agent', 'apt-pac/2026.01.01')
        
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status != 200:
                return []
            
            data = json.loads(response.read().decode('utf-8'))
            
            if data.get("type") == "multiinfo" and "results" in data:
                results = data["results"]
                _set_cached(cache_key, results)
                return results
                
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
        console.print(f"[dim]{_('Checking')} {len(installed_aur)} {_('foreign packages for updates...')}[/dim]")

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
                print_error(_(f"Error checking updates for chunk: {e}"))
                
    return updates

def get_privilege_command(target_user: str, cmd: List[str]) -> List[str]:
    """
    Wrap a command to run as a specific user using the configured tool.
    Dropped privileges context (root -> user).
    """
    config = get_config()
    tool = config.get("tools", "privilege_tool", "auto")
    
    # Auto-detect if auto
    if tool == "auto":
        # Check what's available
        # Prioritize run0 if available (systemd v256+), then doas, then sudo
        if shutil.which("run0"):
            tool = "run0"
        elif shutil.which("doas"):
            tool = "doas"
        else:
            tool = "sudo"
            
    if tool == "run0":
        return ["run0", f"--user={target_user}"] + cmd
    elif tool == "doas":
        return ["doas", "-u", target_user] + cmd
    else:
        # sudo or fallback
        return ["sudo", "-u", target_user] + cmd

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
                subprocess.run(["git", "pull"], cwd=target_dir, check=True)
                return target_dir
            except subprocess.CalledProcessError:
                # If pull fails, remove and re-clone
                console.print(f"[yellow]{_('Pull failed for')} {package_name}, {_('re-cloning...')}[/yellow]")
                shutil.rmtree(target_dir)
        else:
            # Directory exists but is not a git repo - remove it
            console.print(f"[yellow]{_('Removing incomplete directory for')} {package_name}...[/yellow]")
            shutil.rmtree(target_dir)
    
    # Clone
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    try:
        # Show git clone output so users can see progress/errors
        subprocess.run(["git", "clone", clone_url, str(target_dir)], check=True)
        return target_dir
    except subprocess.CalledProcessError:
        print_error(_(f"Failed to clone {package_name} from AUR"))
        return None

class AurResolver:
    def __init__(self):
        self.visiting = set()      # Currently visiting (gray nodes for cycle detection)
        self.visited = set()       # Fully processed (black nodes)
        self.queue = []            # Topological sort result
        self.aur_info_cache = {}
        self.official_deps = set()
        self.package_bases = {}    # PackageBase → set of package names (for split packages)
        self.base_to_info = {}     # PackageBase → representative package info

    def resolve(self, packages: List[str]) -> List[Dict]:
        """
        Resolve dependencies for a list of packages.
        Returns a list of package info dicts in build order.
        """
        for pkg in packages:
            # Force visit explicitly requested packages even if installed
            self._visit(pkg, force_visit=True)
        return self.queue

    def _visit(self, pkg_name: str, force_visit=False, path=None):
        if path is None:
            path = []
        
        # Cycle detection: if we encounter a package we're currently visiting, it's a cycle
        if pkg_name in self.visiting:
            cycle_path = path + [pkg_name]
            raise CyclicDependencyError(cycle_path)
        
        # If already fully processed, skip
        if pkg_name in self.visited:
            return
        
        # If installed and not forced (explicitly requested), skip
        if not force_visit and is_installed(pkg_name):
            self.visited.add(pkg_name)
            return
        
        # Check if official (ignore if so, makepkg handles it)
        if is_in_official_repos(pkg_name):
            self.official_deps.add(pkg_name)
            self.visited.add(pkg_name)
            return

        # Fetch info from AUR
        if pkg_name not in self.aur_info_cache:
            info = get_aur_info([pkg_name])
            if not info:
                print_error(_(f"Package '{pkg_name}' not found in AUR or official repos."))
                sys.exit(1)
            self.aur_info_cache[pkg_name] = info[0]
        
        pkg_info = self.aur_info_cache[pkg_name]
        base = pkg_info.get('PackageBase', pkg_name)
        
        # Track split packages: multiple packages from same PKGBUILD
        if base not in self.package_bases:
            self.package_bases[base] = set()
            self.base_to_info[base] = pkg_info
        self.package_bases[base].add(pkg_name)
        
        # Mark as visiting (gray node)
        self.visiting.add(pkg_name)

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
            self._visit(dep, force_visit=False, path=path + [pkg_name])
        
        # Mark as visited (black node) and remove from visiting
        self.visiting.remove(pkg_name)
        self.visited.add(pkg_name)
            
        # Add to queue (Post-order), but only once per PackageBase
        if base not in [p.get('PackageBase', p['Name']) for p in self.queue]:
            self.queue.append(self.base_to_info[base])

class AurInstaller:
    def __init__(self):
        self.config = get_config()
        # Use user-writeable cache dir for sources
        # IMPORTANT: If running as root via sudo, use the real user's cache, not root's
        # This way the user can access the files when we drop privileges
        if os.getuid() == 0:
            real_user = os.environ.get("SUDO_USER")
            if real_user:
                # Get the real user's home directory
                import pwd
                try:
                    user_info = pwd.getpwnam(real_user)
                    user_home = Path(user_info.pw_dir)
                    # Use XDG_CACHE_HOME or ~/.cache
                    user_cache = Path(os.environ.get("XDG_CACHE_HOME", user_home / ".cache"))
                    self.build_dir = user_cache / "apt-pac" / "sources" / "aur"
                except KeyError:
                    # Fallback to config if we can't find user
                    self.build_dir = self.config.cache_dir / "sources" / "aur"
            else:
                self.build_dir = self.config.cache_dir / "sources" / "aur"
        else:
            self.build_dir = self.config.cache_dir / "sources" / "aur"
        
        if not self.build_dir.exists():
            self.build_dir.mkdir(parents=True, exist_ok=True)

    def install(self, packages: List[str], verbose=False, auto_confirm=False, build_queue=None, official_deps=None, skip_summary=False):
        if build_queue is None:
            resolver = AurResolver()
            with console.status("[blue]Resolving AUR dependencies...[/blue]", spinner="dots"):
                try:
                    build_queue = resolver.resolve(packages)
                except CyclicDependencyError as e:
                    print_error(str(e))
                    console.print(f"\n[yellow]{_('Possible solutions:')}[/yellow]")
                    console.print(f"  1. {_('One of these packages may list the other as a dependency incorrectly')}")
                    console.print(f"  2. {_('Try installing packages individually')}")
                    console.print(f"  3. {_('Report this to')} AUR {_('maintainers:')} {', '.join(set(e.cycle))}")
                    sys.exit(1)
            official_deps = resolver.official_deps
            # Store resolver for split package info access
            self.resolver = resolver
        else:
            official_deps = official_deps or set()
            # No resolver if build_queue was provided directly
            self.resolver = None
        
        if not build_queue:
            print_info(_("Nothing to do."))
            return

        if not skip_summary:
            console.print("Building dependency tree... Done")
            console.print("Reading state information... Done")
            
            # Prepare list of (name, version) for summary
            install_info = get_resolved_package_info(build_queue, official_deps)
            explicit_set = set(packages)

            # Use shared UI helper
            print_transaction_summary(
                new_pkgs=install_info,
                explicit_names=explicit_set
            )
            
            # Calculate size if possible?
            count = len(install_info)
            console.print(_(f"0 upgraded, {count} newly installed, 0 to remove and 0 not upgraded."))
            
            if auto_confirm:
                console.print(f"{_('Do you want to continue?')} [Y/n] [bold green]Yes[/bold green]")
            elif not console.input(f"{_('Do you want to continue?')} [Y/n] ").lower().startswith('y'):
                print_info(_("Aborted."))
                sys.exit(0)

        for pkg in build_queue:
            self._build_pkg(pkg, verbose, auto_confirm)



    def _build_pkg(self, pkg_info: Dict, verbose: bool, auto_confirm: bool):
        # Use PackageBase for split packages (e.g., linux-headers uses 'linux' base)
        base = pkg_info.get('PackageBase', pkg_info['Name'])
        name = pkg_info['Name']
        pkg_dir = self.build_dir / base  # Download/build in PackageBase directory
        
        # Determine if this is a split package
        is_split = False
        split_pkgs = []
        if self.resolver and base in self.resolver.package_bases:
            split_pkgs = sorted(self.resolver.package_bases[base])
            is_split = len(split_pkgs) > 1
        
        # Processing message
        if is_split:
            console.print(f"\n[bold blue]:: {_('Processing')} {base} ({_('split package')})...[/bold blue]")
        else:
            console.print(f"\n[bold blue]:: {_('Processing')} {name}...[/bold blue]")
        
        # 1. Clone or Pull (using PackageBase)
        if not download_aur_source(base, pkg_dir):
            print_error(_(f"Failed to download source for {base}"))
            sys.exit(1)
            
        # Fix permissions if running as root (so ordinary user can build)
        # Get the build user from config or auto-detect
        config = get_config()
        build_user_config = config.get("tools", "build_user", "auto")
        
        if build_user_config == "auto":
            real_user = os.environ.get("SUDO_USER")
        else:
            real_user = build_user_config
        
        if os.getuid() == 0 and real_user:
            # Recursively chown the specific package directory and parent
            # We chown the whole build_dir to be safe as it's a cache dir
            subprocess.run(["chown", "-R", f"{real_user}:", str(self.build_dir)], check=False)

        # 2. Build
        if is_split:
            console.print(f"[dim]{_('Building')} {base} ({_('provides')}: {', '.join(split_pkgs)})...[/dim]")
        else:
            console.print(f"[dim]{_('Building')} {base}...[/dim]")
        
        # makepkg -sf (sync deps, force rebuild, clean, needed)
        # We build WITHOUT -i flag so we can install it ourselves with apt-pac formatting
        # -f flag forces rebuild even if package already exists (needed for upgrades/reinstalls)
        # This ensures consistent APT-style output for the installation step
        cmd = ["makepkg", "-sf", "--needed"]
        if auto_confirm:
            cmd.append("--noconfirm")
        
        if os.getuid() == 0:
             if real_user:
                 # Drop privileges to build, but allow installing deps (makepkg calls sudo/pacman)
                 # IMPORTANT: We need to cd into the directory because run0/sudo don't preserve cwd
                 config = get_config()
                 tool = config.get("tools", "privilege_tool", "auto")
                 
                 # Auto-detect if auto
                 if tool == "auto":
                     if shutil.which("run0"):
                         tool = "run0"
                     elif shutil.which("doas"):
                         tool = "doas"
                     else:
                         tool = "sudo"
                 
                 # Build the command as: tool --user=X sh -c 'cd /path && makepkg ...'
                 makepkg_cmd_str = " ".join(cmd)
                 shell_cmd = f"cd {pkg_dir} && {makepkg_cmd_str}"
                 
                 if tool == "run0":
                     cmd = ["run0", f"--user={real_user}", "sh", "-c", shell_cmd]
                 elif tool == "doas":
                     cmd = ["doas", "-u", real_user, "sh", "-c", shell_cmd]
                 else:
                     cmd = ["sudo", "-u", real_user, "sh", "-c", shell_cmd]
                 
                 # Since we're using shell with cd, we don't need to pass cwd to subprocess
                 run_cwd = None
             else:
                 print_error(f"[red]{_('E:')}[/red] {_('Cannot build')} AUR {_('packages as root without SUDO_USER set.')}")
                 print_info(_("Please run as a normal user or via sudo."))
                 sys.exit(1)
        else:
            # Running as normal user, just use the pkg_dir as cwd
            run_cwd = pkg_dir

        try:
            # Always show makepkg output so users can see build errors
            subprocess.run(cmd, cwd=run_cwd, check=True)
            
            # 3. Find the built package(s)
            # makepkg creates .pkg.tar.* files in the build directory
            # For split packages, there may be multiple files
            pkg_files = list(pkg_dir.glob("*.pkg.tar.*"))
            if not pkg_files:
                print_error(_(f"No package files found after building {base}"))
                sys.exit(1)
            
            # 4. Show summary and install using existing apt-pac UI functions
            # Extract package names and versions from built files
            pkg_info = []
            for f in pkg_files:
                # Parse filename: pkgname-pkgver-pkgrel-arch.pkg.tar.*
                # Example: xapp-symbolic-icons-git-1.0.7+0-1-any.pkg.tar.zst
                stem = f.stem
                # Remove .tar from .pkg.tar.* if present
                if stem.endswith('.tar'):
                    stem = stem[:-4]
                # Split: name-ver-rel-arch
                parts = stem.rsplit('-', 3)
                if len(parts) >= 2:
                    pkg_name = parts[0]
                    pkg_ver = f"{parts[1]}-{parts[2]}" if len(parts) >= 3 else parts[1]
                    pkg_info.append((pkg_name, pkg_ver))
                else:
                    pkg_info.append((stem, ""))
            
            # Show APT-style summary using existing function
            print_reading_status()
            print_transaction_summary(new_pkgs=pkg_info, explicit_names=set([p[0] for p in pkg_info]))
            
            # Summary line
            console.print(_(f"0 upgraded, {len(pkg_info)} newly installed, 0 to remove and 0 not upgraded."))
            
            # Prompt if not auto_confirm
            if not auto_confirm:
                from rich.text import Text
                prompt = Text(f"Do you want to continue? [Y/n] ", style="bold yellow")
                response = console.input(prompt)
                if response and not response.lower().startswith('y'):
                    console.print(_("Aborted."))
                    sys.exit(0)
            
            # Install using existing apt-pac wrapper for consistent output
            install_cmd = ["pacman", "-U"] + [str(f) for f in pkg_files] + ["--noconfirm"]
            
            from .commands import run_pacman_with_apt_output
            success = run_pacman_with_apt_output(install_cmd, show_hooks=True)
            if not success:
                print_error(_(f"Failed to install {name}"))
                sys.exit(1)
            
            # Success message
            if is_split:
                console.print(f"[success]{_('Successfully installed')} {', '.join(split_pkgs)}[/success]")
            else:
                console.print(f"[success]{_('Successfully installed')} {name}[/success]")
            
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
                console.print(f"\n[bold yellow]W: {_('GPG verification failed. Missing keys detected:')} {', '.join(set(key_matches))}[/bold yellow]")
                
                if auto_confirm or console.input("Do you want to try importing these keys? [Y/n] ").lower().startswith('y'):
                    for key_id in set(key_matches):
                        console.print(f"[blue]{_('Importing key')} {key_id}...[/blue]")
                        gpg_cmd = ["gpg", "--recv-keys", key_id]
                        
                        # IMPORTANT: Import key for the REAL USER, not root
                        if os.getuid() == 0 and real_user:
                             gpg_cmd = get_privilege_command(real_user, gpg_cmd)
                        
                        subprocess.run(gpg_cmd, check=False)
                    
                    # Retry build once
                    console.print(f"[blue]{_('Retrying build...')}[/blue]")
                    try:
                        subprocess.run(cmd, cwd=run_cwd, check=True)
                        
                        # Find the built package(s)
                        # FIXME: This is not the best way to do this, packages can be split AND have multiple versions AND be different extensions (in this case what mather is the content not the extension)
                        pkg_files = list(pkg_dir.glob("*.pkg.tar.*"))
                        if not pkg_files:
                            print_error(_(f"No package files found after building {base}"))
                            sys.exit(1)
                        
                        # Install using same consistent approach as main install
                        # Parse package info
                        pkg_info = []
                        for f in pkg_files:
                            stem = f.stem
                            if stem.endswith('.tar'):
                                stem = stem[:-4]
                            parts = stem.rsplit('-', 3)
                            if len(parts) >= 2:
                                pkg_name = parts[0]
                                pkg_ver = f"{parts[1]}-{parts[2]}" if len(parts) >= 3 else parts[1]
                                pkg_info.append((pkg_name, pkg_ver))
                            else:
                                pkg_info.append((stem, ""))
                        
                        # Show summary and prompt
                        print_reading_status()
                        print_transaction_summary(new_pkgs=pkg_info, explicit_names=set([p[0] for p in pkg_info]))
                        console.print(_(f"0 upgraded, {len(pkg_info)} newly installed, 0 to remove and 0 not upgraded."))
                        
                        if not auto_confirm:
                            from rich.text import Text
                            prompt = Text(f"Do you want to continue? [Y/n] ", style="bold yellow")
                            response = console.input(prompt)
                            if response and not response.lower().startswith('y'):
                                console.print("Abort.")
                                sys.exit(0)
                        
                        # Install with apt-pac wrapper
                        install_cmd = ["pacman", "-U"] + [str(f) for f in pkg_files] + ["--noconfirm"]
                        from .commands import run_pacman_with_apt_output
                        success = run_pacman_with_apt_output(install_cmd, show_hooks=True)
                        if not success:
                            print_error(_(f"Failed to install {name}"))
                            sys.exit(1)
                    except subprocess.CalledProcessError:
                         pass # Fallthrough to failure message

            if verbose:
                # If verbose was off, we didn't show the error yet (captured)
                print_error(_(f"Build output:\n{err_output}"))
            
            print_error(_(f"Failed to build {name}"))
            sys.exit(1)

def get_resolved_package_info(build_queue: List[Dict], official_deps: set) -> List[tuple]:
    """
    Helper to convert build queue and official deps into a list of (name, version) tuples
    for the transaction summary. Resolves versions of official deps using pacman.
    """
    install_info = []

    # Add AUR packages from build queue
    for p in build_queue:
        ver = p.get('Version', '')
        install_info.append((p['Name'], ver))
        
    # Add Official deps
    if official_deps:
            # run pacman -S --print to get versions
            try:
                cmd = ["pacman", "-S", "--print", "--print-format", "%n %v"] + list(official_deps)
                res = subprocess.run(cmd, capture_output=True, text=True)
                if res.returncode == 0:
                    for line in res.stdout.splitlines():
                        parts = line.split()
                        if len(parts) >= 2:
                            install_info.append((parts[0], parts[1]))
                        else:
                            install_info.append((line.strip(), ""))
                else:
                    for dep in official_deps:
                        install_info.append((dep, ""))
            except Exception:
                for dep in official_deps:
                    install_info.append((dep, ""))
                    
    return install_info
