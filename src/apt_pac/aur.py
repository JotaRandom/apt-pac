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
from . import ui
from .ui import (
    print_error, print_info, print_command, 
    print_columnar_list, print_transaction_summary, print_reading_status
)
from .i18n import _
from .config import get_config
import tarfile

def is_valid_package(path: str) -> bool:
    """
    Check if a file is a valid pacman package (compressed tar with .PKGINFO).
    Content-based check rather than extension.
    """
    if not os.path.isfile(path):
        return False
        
    try:
        # Optimistic check: tarfile.open handles transparent compression
        # We look for .PKGINFO
        with tarfile.open(path, "r:*") as tar:
             for member in tar:
                 if member.name == ".PKGINFO":
                     return True
             return False
    except (tarfile.TarError, OSError, Exception):
        return False

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
    from . import alpm_helper
    return alpm_helper.is_package_installed(package)

def is_in_official_repos(package: str) -> bool:
    """Check if a package exists in official repos (or is provided by one)."""
    from . import alpm_helper
    return alpm_helper.is_in_official_repos(package)

def get_installed_packages() -> Dict[str, str]:
    """
    Get all installed packages and their versions.
    Returns: Dict[package_name, version]
    """
    from . import alpm_helper
    try:
        packages = {}
        for pkg in alpm_helper.get_installed_packages():
            packages[pkg.name] = pkg.version
        return packages
    except Exception:
        return {}

def get_installed_aur_packages() -> List[str]:
    """
    Get list of installed packages that are NOT in official repos (AUR packages).
    """
    from . import alpm_helper
    try:
        packages = [pkg.name for pkg in alpm_helper.get_installed_packages(foreign_only=True)]
        return packages
    except Exception:
        return []

def version_compare(ver1: str, ver2: str) -> int:
    """
    Compare two versions using pyalpm vercmp.
    Returns: <0 if ver1<ver2, 0 if equal, >0 if ver1>ver2
    """
    import pyalpm
    return pyalpm.vercmp(ver1, ver2)

def check_updates(verbose=False) -> List[Dict]:
    """
    Check for updates for all installed AUR packages.
    Returns list of dicts: {'name': str, 'current': str, 'new': str}
    """
    installed_aur = get_installed_aur_packages()
    if not installed_aur:
        return []

    if verbose:
        ui.console.print(f"[dim]{_('Checking')} {len(installed_aur)} {_('foreign packages for updates...')}[/dim]")

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
                ui.console.print(f"[yellow]{_('Pull failed for')} {package_name}, {_('re-cloning...')}[/yellow]")
                shutil.rmtree(target_dir)
        else:
            # Directory exists but is not a git repo - remove it
            ui.console.print(f"[yellow]{_('Removing incomplete directory for')} {package_name}...[/yellow]")
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
            
        self.resolver = None

    def install(self, packages: List[str], verbose=False, auto_confirm=False, build_queue=None, official_deps=None, skip_summary=False):
        if build_queue is None:
            resolver = AurResolver()
            with ui.console.status("[blue]Resolving AUR dependencies...[/blue]", spinner="dots"):
                try:
                    build_queue = resolver.resolve(packages)
                except CyclicDependencyError as e:
                    print_error(str(e))
                    ui.console.print(f"\n[yellow]{_('Possible solutions:')}[/yellow]")
                    ui.console.print(f"  1. {_('One of these packages may list the other as a dependency incorrectly')}")
                    ui.console.print(f"  2. {_('Try installing packages individually')}")
                    ui.console.print(f"  3. {_('Report this to')} AUR {_('maintainers:')} {', '.join(set(e.cycle))}")
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
            ui.console.print(_("Building dependency tree... Done"))
            ui.console.print(_("Reading state information... Done"))
            
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
            ui.console.print(_(f"0 upgraded, {count} newly installed, 0 to remove and 0 not upgraded."))
            
            if auto_confirm:
                ui.console.print(f"{_('Do you want to continue?')} [Y/n] [bold green]{_('Yes')}[/bold green]")
            elif not ui.console.input(f"{_('Do you want to continue?')} [Y/n] ").lower().startswith('y'):
                print_info(_("Aborted."))
                sys.exit(0)

        # -------------------------------------------------------------
        # STEP 1: Install Official Dependencies First
        # -------------------------------------------------------------
        if official_deps:
            # Install all official deps in one batch first
            # Use --needed to avoid reinstalling up-to-date packages
            # Use --asdeps to mark them correctly
            
            # We want to see apt-style output for this
            cmd = ["pacman", "-S", "--needed", "--asdeps"] + list(official_deps)
            if auto_confirm:
                cmd.append("--noconfirm")
                
            from .commands import run_pacman_with_apt_output
            if not run_pacman_with_apt_output(cmd, show_hooks=True):
                 print_error(_("Failed to install official dependencies"))
                 sys.exit(1)

        # -------------------------------------------------------------
        # STEP 2: Build and Install AUR Packages
        # -------------------------------------------------------------
        
        # We need to know which packages in the queue are dependencies for LATER packages in the queue.
        # If a package is needed by another package in the queue, we must install it immediately as a dep.
        # If it's a top-level package (not needed by anything remaining in queue), we can batch it?
        # Actually, for build correctness, we usually install build-deps immediately.
        # But user requested "install all at once at the end".
        # This implies:
        # 1. Build Pkg A
        # 2. Build Pkg B (which might depend on A) -> If B depends on A, A MUST be installed first.
        # So we can only batch the "final target" packages.
        
        # Simple Logic:
        # Check if the current pkg is a makedep/checkdep/rundep of any FUTURE package in the queue.
        # If yes -> install immediately (--asdeps)
        # If no -> add to final_batch list
        
        final_batch_paths = []
        final_batch_names = []
        
        # Map package names to their position in queue for quick check
        # But queue is sorted by build order.
        # We need to check dependencies of *remaining* items.
        
        # Pre-process dependencies of the queue to make lookups fast
        queue_deps = {} # pkg_name -> set(deps)
        for i, pkg in enumerate(build_queue):
            pname = pkg['Name']
            deps = set()
            deps.update(pkg.get('Depends', []))
            deps.update(pkg.get('MakeDepends', []))
            deps.update(pkg.get('CheckDepends', []))
            
            # Clean version constraints
            clean_deps = set()
            for d in deps:
                clean = d.split('>')[0].split('<')[0].split('=')[0].strip()
                clean_deps.add(clean)
            queue_deps[pname] = clean_deps

        for i, pkg in enumerate(build_queue):
            pkg_name = pkg['Name']
            
            # Determine if this package is needed by any FUTURE package in the queue
            needed_by_future = False
            for j in range(i + 1, len(build_queue)):
                future_pkg = build_queue[j]
                future_name = future_pkg['Name']
                if pkg_name in queue_deps[future_name]:
                    needed_by_future = True
                    break
            
            # Build the package
            # This returns the list of built package files valid for this package
            built_files = self._build_pkg(pkg, verbose, auto_confirm)
            
            if not built_files:
                print_error(_(f"Build failed for {pkg_name}"))
                sys.exit(1)
            
            if needed_by_future:
                # Install immediately as dependency
                # Show what we're installing
                for f in built_files:
                    fname = f.name
                    ui.console.print(f"[bold cyan]Hit:[/bold cyan]1 [blue]file://{f}[/blue] {fname}", highlight=False)
                
                ui.console.print(f"[dim]{_('Installing intermediate dependency')} {pkg_name}...[/dim]")
                cmd = ["pacman", "-U", "--noconfirm", "--asdeps"] + [str(f) for f in built_files]
                
                # We use simple subprocess here to avoid noise, or use our wrapper?
                # Wrapper gives good feedback.
                from .commands import run_pacman_with_apt_output
                if not run_pacman_with_apt_output(cmd, show_hooks=False):
                    print_error(_(f"Failed to install dependency {pkg_name}"))
                    sys.exit(1)
            else:
                # Queue for final install
                final_batch_paths.extend(built_files)
                final_batch_names.append(pkg_name)

        # -------------------------------------------------------------
        # STEP 3: Final Batch Install
        # -------------------------------------------------------------
        if final_batch_paths:
            ui.console.print(f"\n[bold]{_('Installing built packages...')}[/bold]")
            # Show what we're installing
            for i, f in enumerate(final_batch_paths, 1):
                fname = f.name
                ui.console.print(f"[bold cyan]Hit:[/bold cyan]{i} [blue]file://{f}[/blue] {fname}", highlight=False)
            
            cmd = ["pacman", "-U"] + [str(f) for f in final_batch_paths]
            if auto_confirm:
                cmd.append("--noconfirm")
            else:
                 # If explicit install, we usually want to confirm? 
                 # But we already confirmed at the start. So --noconfirm is appropriate unless we want double confirm.
                 # "apt install" confirms once at start.
                 cmd.append("--noconfirm")
                
            from .commands import run_pacman_with_apt_output
            if run_pacman_with_apt_output(cmd, show_hooks=True):
                 ui.console.print(f"[success]{_('Successfully installed')} {', '.join(final_batch_names)}[/success]")
            else:
                 print_error(_("Failed to install packages"))
                 sys.exit(1)


    def _build_pkg(self, pkg_info: Dict, verbose: bool, auto_confirm: bool) -> List[Path]:
        # Use PackageBase for split packages
        base = pkg_info.get('PackageBase', pkg_info['Name'])
        name = pkg_info['Name']
        pkg_dir = self.build_dir / base
        
        # Print GET line for source download with proper formatting
        # Format: Get:N https://aur.archlinux.org/pkgname.git pkgname-source
        ui.console.print(f"[bold cyan]Get:[/bold cyan]1 [blue]https://aur.archlinux.org/{base}.git[/blue] {base}-source", highlight=False)

        # 1. Clone or Pull (using PackageBase)
        # We capture output to hide it unless verbose
        if not self._download_source_silent(base, pkg_dir, verbose):
             print_error(_(f"Failed to download source for {base}"))
             sys.exit(1)
            
        # Fix permissions
        config = get_config()
        build_user_config = config.get("tools", "build_user", "auto")
        if build_user_config == "auto":
            real_user = os.environ.get("SUDO_USER")
        else:
            real_user = build_user_config
        
        if os.getuid() == 0 and real_user:
            subprocess.run(["chown", "-R", f"{real_user}:", str(self.build_dir)], check=False)

        # 2. Build
        # makepkg -f (force rebuild), --needed (skip if existing?), --noconfirm
        # IMPORTANT: NO -s (syncdeps) because we handled deps manually!
        cmd = ["makepkg", "-f", "--needed", "--noconfirm"]
        
        if ui.console.no_color:
            cmd.append("-m")
            
        if os.getuid() == 0:
             # Dropped privileges logic for build
             if real_user:
                 config = get_config()
                 tool = config.get("tools", "privilege_tool", "auto")
                 
                 if tool == "auto":
                     if shutil.which("run0"): tool = "run0"
                     elif shutil.which("doas"): tool = "doas"
                     else: tool = "sudo"
                 
                 makepkg_cmd_str = " ".join(cmd)
                 shell_cmd = f"cd {pkg_dir} && {makepkg_cmd_str}"
                 
                 if tool == "run0":
                     cmd = ["run0", f"--user={real_user}", "sh", "-c", shell_cmd]
                 elif tool == "doas":
                     cmd = ["doas", "-u", real_user, "sh", "-c", shell_cmd]
                 else:
                     cmd = ["sudo", "-u", real_user, "sh", "-c", shell_cmd]
                 
                 run_cwd = None
             else:
                 print_error(_("Cannot build as root without SUDO_USER"))
                 sys.exit(1)
        else:
            run_cwd = pkg_dir

        try:
             # Clean previous packages to avoid confusion
            for existing_pkg in pkg_dir.glob("*.pkg.tar.*"):
                 try:
                     existing_pkg.unlink()
                 except OSError:
                     pass

            subprocess.run(cmd, cwd=run_cwd, check=True)
            
            # 3. Find built packages
            # FILTER logic: Only return packages that match the requested 'name' 
            # OR are part of the 'provides' if split?
            # Actually, we need to match what we expect.
            # If 'name' is 'pix', we want 'pix-*.pkg.tar.*'.
            # We do NOT want 'pix-debug-*.pkg.tar.*' unless name was 'pix-debug'.
            
            all_pkg_files = list(pkg_dir.glob("*.pkg.tar.*"))
            valid_pkg_files = []
            
            for f in all_pkg_files:
                # heuristic: check if filename starts with name-
                # Or check metadata?
                # Simple check:
                fname = f.name
                
                # Check for debug package
                if "-debug" in fname and not name.endswith("-debug"):
                     continue
                
                valid_pkg_files.append(f)
            
            return valid_pkg_files

        except subprocess.CalledProcessError as e:
             print_error(_(f"Failed to build {name}"))
             sys.exit(1)

    def _download_source_silent(self, package_name, target_dir, verbose):
        # Wrapper to reuse download_aur_source but suppress output
        # Since currently download_aur_source prints directly, we might need to modify it or 
        # redirect stdout/stderr here.
        # Ideally we refactor 'download_aur_source' to take a 'silent' flag, but let's try capture.
        
        # Actually, let's just modify download_aur_source logic inline or call it?
        # calling it is better for code reuse.
        # But it calls subprocess.run without capture.
        # We'll just call it for now. If we really want to hide it, we need to change it.
        # Let's trust the user meant 'source download' step is the Get: line.
        # Code above: download_aur_source(base, pkg_dir)
        
        # To truly hide it, we need to refactor `download_aur_source`.
        # For now, let's just run it. The user will see 'Cloning...' which is acceptable?
        # User asked: "this can be used to mask git cloning?"
        # So we should probably modify `download_aur_source` or reimplement the git call here quietly.
        
        base_url = "https://aur.archlinux.org"
        clone_url = f"{base_url}/{package_name}.git"
        
        if target_dir.exists():
            if (target_dir / ".git").exists():
                 cmd = ["git", "pull"]
                 cwd = target_dir
            else:
                 shutil.rmtree(target_dir)
                 target_dir.parent.mkdir(parents=True, exist_ok=True)
                 cmd = ["git", "clone", clone_url, str(target_dir)]
                 cwd = None
        else:
             target_dir.parent.mkdir(parents=True, exist_ok=True)
             cmd = ["git", "clone", clone_url, str(target_dir)]
             cwd = None
             
        try:
            # Capture output unless verbose
            capture = not verbose
            subprocess.run(cmd, cwd=cwd, check=True, capture_output=capture)
            return True
        except subprocess.CalledProcessError:
            return False

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
