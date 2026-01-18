import subprocess
import sys
import shutil
import os
import re
import tarfile
import platform
from . import ui # Needed for ui.set_force_colors
from .ui import (
    console, print_error, print_info, print_command, 
    print_success, print_apt_download_line, format_show, 
    format_search_results, print_columnar_list, show_help, 
    format_aur_search_results, print_transaction_summary, print_reading_status
)
from .config import get_config
from . import aur
from . import alpm_helper
from rich.text import Text
from rich.table import Table
from rich.padding import Padding
from rich.panel import Panel

def run_pacman(cmd, **kwargs):
    """
    Wrapper for subprocess.run that forces LC_ALL=C for consistent English output.
    Use this instead of subprocess.run when calling pacman to avoid locale issues.
    """
    env = kwargs.get('env', os.environ.copy())
    env['LC_ALL'] = 'C'
    kwargs['env'] = env
    return subprocess.run(cmd, **kwargs)

from .i18n import _

COMMAND_MAP = {
    "update": ["-Sy"],
    "upgrade": ["-Syu"],
    "dist-upgrade": ["-Syu"],
    "full-upgrade": ["-Syu"],
    "install": ["-S"],
    "remove": ["-R"],
    "purge": ["-Rns"],
    "autoremove": ["-Rns", "$(pacman -Qdtq)"],
    "search": ["-Ss"],
    "show": ["-Si"],
    "list": ["-Q"],
    "clean": ["-Scc"],
    "autoclean": ["-Sc"],
    "file-search": ["-F"],
    "edit-sources": ["edit-sources"],
    "depends": ["-Qi"], # Fallback
    "rdepends": ["-Qi"], # Fallback
    "scripts": ["-Qii"], # Fallback
    "reinstall": ["-S"],
    "policy": ["-Si"],
    "apt-mark": ["-D"],
    "download": ["-Sw"],
    "changelog": ["-Qc"],
    # Advanced commands
    "pkgnames": ["-Slq"],
    "check": ["-Dk"],
    "stats": ["stats"],  # Custom implementation
    "source": ["pkgctl", "repo", "clone"],
    "build-dep": ["build-dep"],  # Educational message
    "dotty": ["pactree", "-g"],  # GraphViz dependency graph
    "madison": ["madison"],  # Custom implementation
    "config": ["config"],  # Show pacman.conf
    "apt-key": ["pacman-key"],  # GPG key management
    "key": ["pacman-key"],  # Alias for apt-key
    "add-repository": ["add-repository"],  # Educational message
    "showsrc": ["showsrc"],  # Placeholder for ABS+AUR
    "help": ["help"],  # Show package manpage
    # Easter Eggs
    "moo": [], 
    "pacman": [],
}

NEED_SUDO = {
    "update", "upgrade", "dist-upgrade", "full-upgrade", 
    "install", "reinstall", "remove", "purge", "autoremove", 
    "clean", "autoclean", "edit-sources", "apt-mark", "download"
}

def parse_pacman_size(size_str):
    """Parse '22.27 MiB' style strings to bytes."""
    if not size_str or size_str.strip() in ['N/A', '']:
        return 0
    
    parts = size_str.strip().split()
    if len(parts) != 2:
        return 0
    
    try:
        value = float(parts[0])
        unit = parts[1]
        
        if unit == 'B':
            return int(value)
        elif unit == 'KiB':
            return int(value * 1024)
        elif unit == 'MiB':
            return int(value * 1024 * 1024)
        elif unit == 'GiB':
            return int(value * 1024 * 1024 * 1024)
        else:
            return 0
    except (ValueError, IndexError):
        return 0

def fmt_adaptive_size(bytes_val):
    # 1 MB = 1,000,000 Bytes (Decimal)
    mb_val = bytes_val / 1000000.0
    
    if mb_val < 0.1: # Less than 100 kB -> Show Bytes
        return f"{int(bytes_val)} B"
    elif mb_val > 10000: # Greater than 10,000 MB (10 GB) -> Show GB
        gb_val = mb_val / 1000.0
        return f"{gb_val:.1f} GB"
    else:
        return f"{mb_val:.1f} MB"


def show_summary(apt_cmd, extra_args, auto_confirm=False, aur_new=None, aur_upgrades=None):
    """
    Show APT-style installation summary with accurate package sizes using pacman dry-run.
    """
    from .ui import console as c_console
    # print(f"DEBUG: ...", flush=True) # Debug removed for clean code
    # Use pacman -Sp to get list of downloadable packages (URLs)
    # This resolves dependencies effectively for official repos.
    # For AUR, our separate logic handles it, so this is mostly for official packages.

    from rich.table import Table, box
    from rich.padding import Padding
    from rich.panel import Panel
    import urllib.parse
    
    # ... (rest of function)
    


    # 1. Resolve Packages
    # We run 'pacman -Sp' with the user arguments.
    # If upgrading, we need to add '-u' to the simulation to see upgrades.
    # 1. Resolve Packages
    # For upgrades, use 'pacman -Qu' which is reliable for listing upgrades.
    # For install/remove, use 'pacman -Sp' to resolve dependencies.
    
    clean_names = []
    pkg_versions = {} # name -> new_version
    installed_map = {} # name -> old_version (if known)
    
    # Initialize outcome variables
    new_pkgs = []
    upgraded_pkgs = []
    total_dl_size = 0
    total_inst_size_change = 0
    
    if apt_cmd in ["upgrade", "dist-upgrade", "full-upgrade"] and not extra_args:
        # Check for upgrades
        cmd = ["pacman", "-Qu"]
        result = run_pacman(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                parts = line.split()
                # Format: "pkgname oldver -> newver"
                if len(parts) >= 4 and parts[2] == "->":
                    name = parts[0]
                    old_ver = parts[1]
                    new_ver = parts[3]
                    clean_names.append(name)
                    pkg_versions[name] = new_ver
                    installed_map[name] = old_ver
                else:
                    # Fallback or weird format
                    clean_names.append(parts[0])
    
    else:
        base_sim = ["pacman", "-Sp"]
        cmd = base_sim + extra_args
        result = run_pacman(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            return

        urls = [line.strip() for line in result.stdout.splitlines() if "://" in line]
        
        import urllib.parse
        
        for url in urls:
            filename = urllib.parse.urlparse(url).path.split('/')[-1]
            base = filename
            for ext in ['.pkg.tar.zst', '.pkg.tar.xz', '.pkg.tar.gz', '.pkg.tar']:
                 if base.endswith(ext):
                     base = base[:-len(ext)]
                     break
            
            parts = base.split('-')
            if len(parts) >= 4:
                name = "-".join(parts[:-3])
                ver_rel = f"{parts[-3]}-{parts[-2]}"
                clean_names.append(name)
                pkg_versions[name] = ver_rel
            else:
                clean_names.append(base)
                pkg_versions[base] = "?"
    
    if not clean_names:
        # Fallback if no URLs were found (e.g. up to date or already installed, or not found)
        # We should check if they are installed to verify '0 upgraded'.
        # But if checking deps, maybe none needed.
        # Let's use user args to at least show something if mostly empty?
        # No, if empty it means nothing to do.
        pass

    # Batch query -Si for all
    # To properly separate NEW vs UPGRADE, we need to check -Qi.
    # Batch -Qi
    installed_map = {}
    installed_size_map = {} # To store current installed sizes for diff calculation
    visible_suggestions = set()
    
    if clean_names:
        # Check installed status and get current versions/sizes
        q_res = run_pacman(["pacman", "-Q"] + clean_names, capture_output=True, text=True)
        installed_set = set()
        if q_res.returncode != 127: # 127 is command not found
            for line in q_res.stdout.splitlines():
                # line is "name version"
                if " " in line:
                    name, version = line.split(maxsplit=1)
                    installed_set.add(name)
                    installed_map[name] = version
        
        # Get installed sizes for packages that are currently installed
        if installed_set:
            qi_res = run_pacman(["pacman", "-Qi"] + list(installed_set), capture_output=True, text=True)
            current_pkg = None
            for line in qi_res.stdout.splitlines():
                line = line.strip()
                if not line: continue
                if line.startswith("Name"):
                    current_pkg = line.split(":", 1)[1].strip()
                elif line.startswith("Installed Size"):
                    size = parse_pacman_size(line.split(":", 1)[1].strip())
                    if current_pkg:
                        installed_size_map[current_pkg] = size

        # Calculate sizes from -Si
        # Note: -Si might fail for local packages not in repo?
        # But 'pacman -Sp' returned them, so they must be downloadables (repo packages).
        
        si_res = run_pacman(["pacman", "-Si"] + clean_names, capture_output=True, text=True)
        
        # Parse -Si output (blocks separated by blank lines)
        pkg_sizes = {}
        suggested_pkgs = set()
        current_pkg = None
        curr_dl = 0
        curr_inst = 0
        
        # Improved Parse -Si output
        current_section = None
        new_optdeps_map = {} # pkg -> set(optdeps_names)
        
        for line in si_res.stdout.splitlines():
            if not line.strip(): 
                current_pkg = None # Reset on blank line separator
                continue
                
            if line.startswith("Name"):
                current_pkg = line.split(":", 1)[1].strip()
                curr_dl = 0
                curr_inst = 0
                current_section = "Name"
            elif line.startswith("Download Size"):
                curr_dl = parse_pacman_size(line.split(":", 1)[1].strip())
                current_section = "Download Size"
            elif line.startswith("Installed Size"):
                curr_inst = parse_pacman_size(line.split(":", 1)[1].strip())
                if current_pkg:
                    pkg_sizes[current_pkg] = (curr_dl, curr_inst)
                current_section = "Installed Size"
            elif line.startswith("Optional Deps"):
                content = line.split(":", 1)[1].strip()
                if content and content != "None":
                   # content format: "pkgname: description"
                   pkg_name = content.split(":")[0].strip()
                   if current_pkg:
                       if current_pkg not in new_optdeps_map: new_optdeps_map[current_pkg] = set()
                       new_optdeps_map[current_pkg].add(pkg_name)
                current_section = "Optional Deps"
            elif line.startswith(" "):
                 # Continuation line
                 if current_section == "Optional Deps" and current_pkg:
                     content = line.strip()
                     if ":" in content:
                         pkg_name = content.split(":")[0].strip()
                         if current_pkg not in new_optdeps_map: new_optdeps_map[current_pkg] = set()
                         new_optdeps_map[current_pkg].add(pkg_name)
            else:
                 current_section = line.split(":")[0].strip() # Other headers


        # Now iterate clean_names to build lists and calculating diffs for suggestions
        # We need old optdeps for upgraded packages
        old_optdeps_map = {}
        if installed_set:
            # We already ran -Qi for sizes (lines 220), but we didn't capture optdeps.
            # We need to parse them now or we should have parsed them earlier.
            # To avoid re-running, let's just parsing -Qi output again if we saved it? 
            # We didn't save the full output object, just used it. 
            # Re-running -Qi for installed_set is cheap (local).
            qi_res_full = run_pacman(["pacman", "-Qi"] + list(installed_set), capture_output=True, text=True)
            curr_qi_pkg = None
            curr_qi_section = None
            for line in qi_res_full.stdout.splitlines():
                if not line.strip():
                    curr_qi_pkg = None
                    continue
                if line.startswith("Name"):
                    curr_qi_pkg = line.split(":", 1)[1].strip()
                    curr_qi_section = "Name"
                elif line.startswith("Optional Deps"):
                    content = line.split(":", 1)[1].strip()
                    if content and content != "None":
                        p = content.split(":")[0].strip()
                        if curr_qi_pkg:
                             if curr_qi_pkg not in old_optdeps_map: old_optdeps_map[curr_qi_pkg] = set()
                             old_optdeps_map[curr_qi_pkg].add(p)
                    curr_qi_section = "Optional Deps"
                elif line.startswith(" "):
                    if curr_qi_section == "Optional Deps" and curr_qi_pkg:
                         content = line.strip()
                         if ":" in content:
                             p = content.split(":")[0].strip()
                             if curr_qi_pkg:
                                 if curr_qi_pkg not in old_optdeps_map: old_optdeps_map[curr_qi_pkg] = set()
                                 old_optdeps_map[curr_qi_pkg].add(p)
                else:
                    curr_qi_section = line.split(":")[0].strip()


        
        
        for name in clean_names:
            dl, inst = pkg_sizes.get(name, (0, 0))
            total_dl_size += dl
            
            # Logic for Suggestions
            new_opts = new_optdeps_map.get(name, set())
            
            if name in installed_set:
                ver = pkg_versions.get(name, "")
                old_ver = installed_map.get(name, "")
                upgraded_pkgs.append((name, old_ver, ver)) # (name, old_version, new_version)
                
                old_size = installed_size_map.get(name, 0)
                total_inst_size_change += (inst - old_size)
                
                # Smart Suggestion Trigger: Upgrading
                # Only show NEW suggestions
                old_opts = old_optdeps_map.get(name, set())
                diff_opts = new_opts - old_opts
                visible_suggestions.update(diff_opts)
                
            else:
                ver = pkg_versions.get(name, "")
                new_pkgs.append((name, ver)) # (name, new_version)
                total_inst_size_change += inst
                
                # New Install: Show all suggestions
                visible_suggestions.update(new_opts)

    # Merge AUR packages if provided
    if aur_new:
        new_pkgs.extend(aur_new)
    if aur_upgrades:
        # Convert AUR upgrades to 3-tuple format if they aren't already
        # Assumes input might be (name, version) or (name, old, new)
        for item in aur_upgrades:
            if len(item) == 2:
                upgraded_pkgs.append((item[0], _("unknown"), item[1]))
            else:
                upgraded_pkgs.append(item)

    if not new_pkgs and not upgraded_pkgs:
        console.print(_("0 upgraded, 0 newly installed, 0 to remove and 0 not upgraded."))
        return

    print_reading_status()

    # Identify explicit names from extra_args (excluding flags)
    explicit_names = {arg for arg in extra_args if not arg.startswith('-')}
    
    # Use shared UI helper
    print_transaction_summary(
        new_pkgs=new_pkgs,
        upgraded_pkgs=upgraded_pkgs,
        explicit_names=explicit_names
    )
        
    # Process Suggestions to show status
    if visible_suggestions:
         # Filter out things we are about to install (transaction_pkgs)
         # transaction_pkgs = set([p[0] for p in new_pkgs]) | set([p[0] for p in upgraded_pkgs])
         # User request: "only listen the new IF isn't installed and print [installed] if is already installed AND new."
         # Wait, if I am installing 'foo' and it suggests 'bar', and 'bar' is NOT installed -> show 'bar'
         # If 'bar' IS installed -> show 'bar [installed]'
         # If 'bar' is being installed right now? -> Probably show 'bar [installed]' or hide? 
         # APT hides it if it's part of the transaction. User said "print [installed] if is already installed".
         # Let's check installed status of all visible_suggestions.
         
         sorted_sug = sorted(list(visible_suggestions))
         
         # Check which ones are installed
         check_installed = run_pacman(["pacman", "-Qq"] + sorted_sug, capture_output=True, text=True)
         already_installed = set(check_installed.stdout.splitlines())
         
         final_suggestions = []
         for sug in sorted_sug:
             if sug in already_installed:
                 final_suggestions.append(f"{sug} [dim][installed][/dim]")
             else:
                 # Check if it is being installed in this transaction? 
                 # If it is in new_pkgs names, it will be installed.
                 # Usually suggestions are for things NOT being installed.
                 # But if user requested it specifically?
                 # Let's just print it as is (clean).
                 final_suggestions.append(sug)
         
         if final_suggestions:
             console.print(f"{_('Suggested packages:')}")
             print_columnar_list(final_suggestions, "default")

    # Show Orphans / No longer required
    orphan_pkgs = alpm_helper.get_orphan_packages()
    if orphan_pkgs:
        orphans = [pkg.name for pkg in orphan_pkgs]
        console.print(f"\n[bold]{_('The following packages are no longer required:')}[/bold]")
        print_columnar_list(orphans, "dim")
        console.print(f"{_('Use')} [bold]apt-pac autoremove[/bold] {_('to remove them.')}")

    # APT 3.1 Summary Style
    # Upgrading: 0, Installing: 129, Removals: 0, Not Upgrading: 0
    # Download Size: 87.3 MB
    # Installed size: 319.6 MB
    
    removals_count = 0 # In install mode usually 0 unless conflict resolution?
    # We didn't parse removals from -Sp, only adds. -Sp doesn't show removals easily (unless -Ru?).
    
    summary_line = f"[bold]{_('Summary:')}[/bold]\n   {_('Upgrading:')} {len(upgraded_pkgs)}, {_('Installing:')} {len(new_pkgs)}, {_('Removals:')} {removals_count}, {_('Not Upgrading:')} 0"
    console.print(summary_line)
    
    # Format sizes (Decimal MB)
    # Format sizes (Adaptive: <0.1MB -> B, >10GB -> GB)
    dl_suffix = ""
    inst_suffix = ""
    
    has_aur = bool(aur_new or aur_upgrades)
    
    if has_aur:
        dl_suffix = f" (+ AUR)"
        inst_suffix = f" (+ AUR)"
        
        # If total sizes are 0 but we have AUR, show "Unknown" instead of 0 B
        if total_dl_size == 0:
            dl_str = f"{_('Unknown')} (AUR)"
            dl_suffix = "" # Reset suffix as we incorporated it
        else:
             dl_str = fmt_adaptive_size(total_dl_size)

        if total_inst_size_change == 0:
             inst_str = f"{_('Unknown')} (AUR)"
             inst_suffix = ""
             show_freed = False
        else:
             inst_str = fmt_adaptive_size(abs(total_inst_size_change))
             show_freed = total_inst_size_change < 0
    else:
        dl_str = fmt_adaptive_size(total_dl_size)
        inst_str = fmt_adaptive_size(abs(total_inst_size_change))
        show_freed = total_inst_size_change < 0


    console.print(f"   {_('Download Size:')} {dl_str}{dl_suffix}")
    if show_freed:
        console.print(f"   {_('Freed Space:')} {inst_str}{inst_suffix}")
    else:
        console.print(f"   {_('Installed Size:')} {inst_str}{inst_suffix}")
    
    # Check Disk Space
    warnings = []
    
    # 1. Check Root (Install Size)
    # Only if we are growing
    if total_inst_size_change > 0:
        try:
            slash_usage = shutil.disk_usage("/")
            if total_inst_size_change > slash_usage.free:
                warnings.append({
                    "path": "/",
                    "needed": total_inst_size_change,
                    "avail": slash_usage.free
                })
        except Exception: 
            pass
            
    # 2. Check Cache (Download Size)
    # Assume /var/cache/pacman/pkg
    cache_path = "/var/cache/pacman/pkg"
    # If using custom cache from config? complex. default to standard.
    # If not exists, check /var
    if not os.path.exists(cache_path):
        cache_path = "/var"
    
    if total_dl_size > 0:
        try:
            cache_usage = shutil.disk_usage(cache_path)
            if total_dl_size > cache_usage.free:
                warnings.append({
                    "path": cache_path,
                    "needed": total_dl_size,
                    "avail": cache_usage.free
                })
        except Exception:
            pass

    prompt_msg = f"\n{_('Continue?')} [Y/n] "
    
    if warnings:
        for w in warnings:
            needed_str = fmt_adaptive_size(w['needed'])
            avail_str = fmt_adaptive_size(w['avail'])
            console.print(f"{_('Space needed:')} {needed_str} / {avail_str} {_('available')}")
            console.print(f"[bold red]W: {_('More space needed in')} {w['path']} {_('than available')}: {needed_str} > {avail_str}[/bold red]")
        
        prompt_msg = f"\n[bold red]{_('Installation may fail, Continue?')} [Y/n] [/bold red]"
    
    if auto_confirm:
         console.print(prompt_msg + "[bold green]Yes[/bold green]")
    else:
        if not console.input(prompt_msg).lower().startswith('y'):
            print_info(_("Aborted."))
            sys.exit(0)


def get_protected_packages():
    """Dynamically detects installed kernels and bootloaders to protect them."""
    core_packages = {"pacman", "systemd", "base", "sudo", "doas", "run0"}
    
    # Detect kernels
    try:
        installed = alpm_helper.get_installed_packages()
        kernels = [pkg.name for pkg in installed]
        detected_kernels = {pkg for pkg in kernels if pkg.startswith("linux")}
        core_packages.update(detected_kernels)
    except Exception:
        pass

    # Detect bootloaders
    bootloader_hints = ["grub", "limine", "syslinux", "efibootmgr"]
    try:
        detected_bootloaders = {pkg for pkg in kernels if any(hint in pkg for hint in bootloader_hints)}
        core_packages.update(detected_bootloaders)
    except Exception:
        pass
        
    return core_packages

def check_safeguards(apt_cmd, extra_args, is_simulation=False):
    
    # 1. Partial Upgrade Warning
    # 1. Partial Upgrade Warning - REMOVED (Handled later with more detail)
    # The check is performed in the main execution block to include accurate count.

    # 2. Protected Packages
    if apt_cmd in ["remove", "purge"]:
        protected = get_protected_packages()
        for pkg in extra_args:
            if pkg in protected:
                console.print(f"\n[bold red]E:[/bold red] {_('You are trying to remove a core system package:')} {pkg}[/bold red]")  
                console.print(_("Removing this package may render your system unbootable."))
                required_phrase = _("Yes, I know what I am doing")
                if console.input(f"{_('To proceed, type')} '{required_phrase}': ") != required_phrase:
                    print_info(_("Aborted."))
                    sys.exit(1)

    # 3. Large Removal Warning
    if apt_cmd in ["remove", "purge", "autoremove"] and not is_simulation:
        pacman_args = COMMAND_MAP[apt_cmd]
        if apt_cmd == "autoremove":
            orphan_pkgs = alpm_helper.get_orphan_packages()
            if orphan_pkgs:
                orphans = [pkg.name for pkg in orphan_pkgs]
                print_cmd = ["pacman", "-Rns"] + orphans + ["--print"]
            else:
                return # No orphans, no removal
        else:
            print_cmd = ["pacman"] + pacman_args + extra_args + ["--print"]
            
        print_reading_status()
            
        result = subprocess.run(print_cmd, capture_output=True, text=True)
        if result.returncode == 0:
            # Output lines are "pkgname version"
            lines = result.stdout.strip().splitlines()
            # filter empty
            lines = [x.strip() for x in lines if x.strip()]
            
            if lines:
                 remove_pkgs_info = []
                 for line in lines:
                     line = line.strip()
                     parts = line.split()
                     
                     # Try to match pkgname-version-release (common in Arch)
                     # e.g. fish-4.3.2-1 -> match(fish, 4.3.2-1)
                     # Regex: ^(.*)-([^-]+-[^-]+)$ -> grabs last two hyphenated parts as ver-rel
                     m = re.match(r'^(.*)-([^-]+-[^-]+)$', line)
                     
                     if len(parts) >= 2:
                         remove_pkgs_info.append((parts[0], parts[1]))
                     elif m:
                         remove_pkgs_info.append((m.group(1), m.group(2)))
                     else:
                         remove_pkgs_info.append((line, ""))
                         
                 print_transaction_summary(remove_pkgs=remove_pkgs_info)
                 
                 # Check for mass removal
                 config = get_config()
                 threshold = config.get("ui", "mass_removal_threshold", 20)
                 count = len(remove_pkgs_info)
                 
                 if count >= threshold:
                     console.print(f"\n[yellow]{_('W:')}[/yellow] {_('You are about to remove')} [bold]{count}[/bold] {_('packages')} (Threshold: {threshold}).")
                     if not console.input(f"{_('Are you sure you want to proceed?')} [Y/n] ").lower().startswith('y'):
                         print_info(_("Aborted."))
                         sys.exit(0)
                 
                 if not console.input(f"\n{_('Do you want to continue?')} [Y/n] ").lower().startswith('y'):
                     print_info(_("Aborted."))
                     sys.exit(0)

def get_editor():
    """Detects available editor in order: $EDITOR, nano, vi."""
    editor = os.environ.get("EDITOR")
    if editor:
        return editor
    for cmd in ["nano", "vi"]:
        if subprocess.run(["command", "-v", cmd], shell=True, capture_output=True).returncode == 0:
            return cmd
    return "vi"  # Ultimate fallback as it's likely in base

def get_short_url(url):
    import urllib.parse
    parsed = urllib.parse.urlparse(url)
    short_url = f"{parsed.scheme}://{parsed.netloc}/"
    if not short_url.endswith('/'): short_url += "/"
    return short_url

def sync_databases(cmd=None):
    """
    Runs pacman -Sy (or similar) with APT-like progress output (Hit/Get).
    """
    if cmd is None:
        cmd = ["pacman", "-Sy"]
    
    # 1. Pre-fetch URLs using --print
    # We use this to map repo names to URLs for the "Get:" lines
    repo_url_map = {} # repo -> (short_url, arch)
    
    try:
        # pacman -Sy --print prints the URIs for the databases
        print_cmd = list(cmd) + ["--print"]
        
        # This might fail if not root, but if we are here we expect to be able to run it?
        # Or if we rely on sudo in the real cmd, here we might fail if not wrapped?
        # But 'cmd' usually contains 'pacman'. If 'apt-pac' was run with sudo, this inherits it.
        result = subprocess.run(print_cmd, capture_output=True, text=True)
        if result.returncode == 0:
            urls = [line.strip() for line in result.stdout.splitlines() if "://" in line]
            for url in urls:
                # Format: http://mirror/repo/os/arch/repo.db
                # We need to extract repo name and arch
                try:
                    filename = url.split('/')[-1]
                    # core.db -> core
                    repo_name = filename.replace('.db', '').replace('.files', '')
                    
                    # Arch: usually 2nd to last part? /os/x86_64/core.db
                    # But structure varies.
                    # Heuristic: verify if any part matches current machine arch
                    parts = url.split('/')
                    arch = platform.machine() # fallback
                    if arch in parts:
                        pass # confirmed
                    elif "x86_64" in parts:
                        arch = "x86_64"
                    elif "aarch64" in parts:
                        arch = "aarch64"
                        
                    short = get_short_url(url)
                    repo_url_map[repo_name] = (short, arch)
                except Exception:
                    pass
    except Exception:
        pass # Ignore errors in pre-fetch, fallback to basic output

    # Force C locale for parsing
    env = os.environ.copy()
    env["LC_ALL"] = "C"
    
    # Regex to strip ANSI codes
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env
        )
        
        index = 1
        with console.status(f"[bold blue]{_('Updating package databases...')}[/bold blue]", spinner="dots"):
             for line in iter(process.stdout.readline, ''):
                 if not line: break
                 
                 # Strip ANSI for parsing
                 line_clean = ansi_escape.sub('', line).strip()
                 if not line_clean: continue
                 
                 lower_line = line_clean.lower()
                 
                 # Parse
                 if "is up to date" in lower_line:
                      repo = line_clean.split(" is up to date")[0].strip()
                      # Cleaning ":: " prefix
                      if "::" in repo: 
                           repo = repo.split("::")[-1].strip()
                      
                      console.print(f"Hit:{index} {repo}")
                      index += 1
                      
                 elif "downloading" in lower_line:
                      # extracting repo name. Format could be:
                      # "downloading core.db..."
                      # "downloading core..."
                      # ":: downloading core..."
                      
                      parts = line_clean.split()
                      repo = ""
                      
                      # Find word containing "downloading"
                      try:
                          # Find index of word matching "downloading"
                          idx = -1
                          for i, p in enumerate(parts):
                              if "downloading" in p.lower():
                                  idx = i
                                  break
                          
                          if idx != -1:
                              # Check word After (downloading core...)
                              if idx + 1 < len(parts):
                                  candidate = parts[idx + 1]
                                  # Heuristic: usually repo names are alphanumeric. 
                                  # If candidate is "...", skip.
                                  if "..." not in candidate: 
                                       repo = candidate.replace("...", "").replace(".db", "").replace(".files", "")
                              
                              # Check word Before (core downloading...) if not found after
                              if not repo and idx - 1 >= 0:
                                  candidate = parts[idx - 1]
                                  # Ignore "::"
                                  if candidate != "::":
                                       repo = candidate.replace("...", "").replace(".db", "").replace(".files", "")
                      except Exception:
                          pass

                      # heuristic: check if any map key is in the line (fallback)
                      if not repo and repo_url_map:
                           for r in repo_url_map:
                               if r in line_clean:
                                   repo = r
                                   break

                      if repo:
                           if repo in repo_url_map:
                               short, arch = repo_url_map[repo]
                               # Get:NUMERO web repo arquitectura ...
                               console.print(f"Get:{index} {short} {repo} {arch}")
                           else:
                               console.print(f"Get:{index} {repo}")
                           index += 1
                      else:
                           # Fallback if we can't identify repo
                           console.print(f"[dim]{line_clean}[/dim]")

                 elif "synchronizing package databases" in lower_line:
                      # Ignore introductory line
                      pass
                 else:
                      # Fallback: print unknown lines (dimmed)
                      console.print(f"[dim]{line_clean}[/dim]")
        
        process.wait()
        if process.returncode != 0:
            print_error(_("Failed to synchronize databases"))
            sys.exit(1)
            
    except subprocess.CalledProcessError:
        print_error(_("Failed to run pacman"))
        sys.exit(1)

def simulate_apt_download_output(pacman_cmd, config):
    """
    Simulates APT's "Get:1 ..." output by running pacman -Sp first.
    Parses URLs to shorten them and matches packages to get Epoch/Version info.
    """
    import urllib.parse
    
    # Construct simulation command: pacman_cmd + -p
    # Note: pacman_cmd usually has -S or -Syu. Adding -p makes it a dry run printing URLs.
    cmd = list(pacman_cmd)
    
    # Ensure -p is added. 
    # If -w (download only) is present, -p still works to print URLs.
    if "-p" not in cmd and "--print" not in cmd:
        cmd.append("-p")
    
    try:
        # Run pacman -Sp ...
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            return # Fail silently on simulation
            
        lines = result.stdout.strip().splitlines()
        urls = [line.strip() for line in lines if "://" in line]
        
        if not urls:
            return
            
        # 1. Parse Names from Filenames
        # Filename format: name-version-release-arch.pkg.tar.zst
        # We need 'name' to query -Si for the proper Version string (with Epoch)
        
        pkg_map = {} # filename -> name
        names_to_query = set()
        
        url_info = [] # list of (url, filename, pkg_name)
        
        for url in urls:
            parsed = urllib.parse.urlparse(url)
            filename = parsed.path.split('/')[-1]
            
            # Shorten URL to scheme://netloc/
            short_url = f"{parsed.scheme}://{parsed.netloc}/"
            if not short_url.endswith('/'): short_url += "/"
            
            # Parse filename
            # Heuristic: strip known extensions, then reverse split
            base = filename
            for ext in ['.pkg.tar.zst', '.pkg.tar.xz', '.pkg.tar.gz', '.pkg.tar', '.pkg.tar.zst.sig']:
                if base.endswith(ext):
                    base = base[:-len(ext)]
                    break
            
            # base is now "name-ver-rel-arch"
            # Split by '-'
            parts = base.split('-')
            pkg_name = base # fallback
            
            if len(parts) >= 4:
                # Last part: arch
                # 2nd last: rel
                # 3rd last: ver
                # Rest: name (joined by -)
                pkg_name = "-".join(parts[:-3])
                names_to_query.add(pkg_name)
            
            url_info.append({
                'full_url': url,
                'short_url': short_url,
                'filename': filename,
                'pkg_name': pkg_name
            })

        # 2. Batch Query Version Info (including Epoch)
        # We query -Si for all these names
        version_map = {} # name -> full_version (with epoch)
        
        if names_to_query:
            # We can pass multiple args to -Si
            # Split into chunks if too many? typical cmdline limits ~32k chars.
            # 100 packages is fine.
            q_cmd = ["pacman", "-Si"] + list(names_to_query)
            si_res = run_pacman(q_cmd, capture_output=True, text=True)
            
            if si_res.returncode == 0:
                curr_name = None
                for line in si_res.stdout.splitlines():
                    line = line.strip()
                    if line.startswith("Name"):
                        curr_name = line.split(":", 1)[1].strip()
                    elif line.startswith("Version") and curr_name:
                        ver = line.split(":", 1)[1].strip()
                        version_map[curr_name] = ver
                        curr_name = None # Reset to wait for next name

        # 3. Print Output
        total = len(urls)
        for i, info in enumerate(url_info, 1):
            name = info['pkg_name']
            
            # Get version from -Si if available, otherwise fallback to filename parsing if possible?
            # Or just name.
            if name in version_map:
                version_str = version_map[name]
                # Format: name-version
                # version_str includes epoch if present (e.g. 1:2.0-3)
                final_str = f"{name}-{version_str}"
            else:
                # Fallback: display filename? or just name
                # If we couldn't parse name correctly, using filename is safer than nothing.
                # But info['filename'] is bulky.
                # Use name we parsed from filename
                final_str = f"{name} [?]"
            
            print_apt_download_line(i, total, info['short_url'], final_str)
            
    except Exception:
        pass

def run_pacman_with_apt_output(cmd, show_hooks=True):
    """
    Runs pacman command and parses output to show:
    - Package installation progress in APT style
    - Hooks/triggers in APT trigger format
    Returns True if successful, False otherwise
    
    Preserves stdin for interactive prompts (e.g., remove confirmations)
    """
    import re
    
    try:
        # Run pacman with stdout/stderr captured, but stdin passed through
        # This allows user interaction while we parse the output
        env = os.environ.copy()
        env['LC_ALL'] = 'C'
        
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=None,  # stdin not captured - passes through to user
            text=True,
            bufsize=1,
            env=env
        )

        current_action = _("Processing...")
        
        # Regex for progress: ( 1/15) or 25%
        # Pacman style: "( 1/ 5) Installing package"
        progress_re = re.compile(r'\(\s*(\d+)/(\d+)\s*\)')
        percent_re = re.compile(r'(\d+)%')

        with console.status(f"[bold blue]{current_action}[/bold blue]", spinner="dots") as status:
            for line in iter(process.stdout.readline, ''):
                if not line:
                    break
                    
                line_lower = line.lower()
                
                # Check for progress info in the line
                p_match = progress_re.search(line)
                pct_match = percent_re.search(line)
                
                progress_info = ""
                if p_match:
                    curr, total = p_match.groups()
                    # Calculate percentage?
                    try:
                        pct = int(curr) / int(total) * 100
                        progress_info = f" {int(pct)}% ({curr}/{total})"
                    except ZeroDivisionError:
                        progress_info = f" ({curr}/{total})"
                elif pct_match:
                    progress_info = f" {pct_match.group(1)}%"

                # Determine action
                if "downloading" in line_lower:
                    current_action = _("Downloading")
                    status.update(f"[bold blue]{current_action}{progress_info}...[/bold blue]")
                elif "installing" in line_lower:
                    current_action = _("Installing")
                    status.update(f"[bold blue]{current_action}{progress_info}...[/bold blue]")
                elif "upgrading" in line_lower:
                    current_action = _("Upgrading")
                    status.update(f"[bold blue]{current_action}{progress_info}...[/bold blue]")
                elif "removing" in line_lower:
                    current_action = _("Removing")
                    status.update(f"[bold blue]{current_action}{progress_info}...[/bold blue]")
                elif "checking keys" in line_lower or "keyring" in line_lower:
                    current_action = _("Checking keys")
                    status.update(f"[bold blue]{current_action}{progress_info}...[/bold blue]")
                elif "checking" in line_lower:
                    # Generic checking
                    pass 
                elif progress_info:
                    # Update just progress if action didn't change
                    status.update(f"[bold blue]{current_action}{progress_info}...[/bold blue]")

                # APT Style Output Parsing
                
                # Case 1: "(N/M) Installing foo (1.0-1)..."
                # Pacman often prints this.
                # We want: "Unpacking foo (1.0-1) ..."
                # Or "Selecting previously unselected package foo..."
                
                clean_line = line.strip()
                
                if "installing" in line_lower and formatting_is_ok(line):
                     # Extract pkg name
                     # "( 1/ 4) installing python (3.11...)"
                     parts = line.split()
                     if len(parts) >= 4 and parts[2] == "installing":
                         pkg = parts[3]
                         ver = parts[4].strip('()') if len(parts) > 4 else ""
                         console.print(f"{_('Selecting previously unselected package')} {pkg}.")
                         console.print(f"({_('Reading database')} ... 100% {_('files and directories currently installed')}.)")
                         console.print(f"{_('Unpacking')} {pkg} ({ver}) ...")
                         continue
                
                if "upgrading" in line_lower and formatting_is_ok(line):
                     parts = line.split()
                     if len(parts) >= 4 and parts[2] == "upgrading":
                         pkg = parts[3]
                         ver = parts[4].strip('()') if len(parts) > 4 else ""
                         console.print(f"{_('Preparing to unpack')} .../{pkg}_{ver}_... ...")
                         console.print(f"{_('Unpacking')} {pkg} ({ver}) over ({ver}) ...") # Approximate
                         continue

                # Hooks / Triggers
                # ":: Running post-transaction hooks..."
                if "running" in line_lower and "hooks" in line_lower:
                     # APT: "Processing triggers for man-db (2.12.0-1) ..."
                     # Pacman: ":: Running post-transaction hooks..."
                     # We can't know exactly which trigger maps to which package easily.
                     # But we can show it as Processing triggers.
                     console.print(f"{_('Processing triggers for system')} ...")
                     continue
                
                if show_hooks and line.strip().startswith("("):
                     # Hook output: "(1/5) Arming ConditionNeedsUpdate..."
                     # Show as "Setting up ..."
                     parts = line.split(')', 1)
                     if len(parts) > 1:
                         desc = parts[1].strip()
                         console.print(f"{_('Setting up system')} ({desc}) ...")
                         continue

                # Default: Don't print internal pacman messages unless error or important
                if "error" in line_lower or "warning" in line_lower:
                    console.print(line.strip())
        
        process.wait()
        
        # Sync filesystem on success
        if process.returncode == 0:
            try:
                subprocess.run(["sync"], check=False)
            except FileNotFoundError:
                pass # sync not found (e.g. non-standard env)

        return process.returncode == 0
        
    except Exception as e:
        print_error(f"[red]{_('E:')}[/red] {f'{_('Error running pacman: ')}{e}'}")
        return False

def formatting_is_ok(line):
    # Heuristic to check if line is structured as expected for parsing
    return True # Simplified for now


def execute_command(apt_cmd, extra_args):
    # Log the action system-wide
    from . import logger
    logger.log_action(apt_cmd, extra_args)

    if apt_cmd not in COMMAND_MAP:
        import difflib
        matches = difflib.get_close_matches(apt_cmd, COMMAND_MAP.keys(), n=1, cutoff=0.6)
        if matches:
            print_error(f"[red]{_('E:')}[/red] {f'{_('Invalid operation ')}{apt_cmd}'}")
            console.print(f"[info]{_('Did you mean:')}[/info] [bold white]{matches[0]}[/bold white]?")
        else:
            print_error(f"[red]{_('E:')}[/red] {f'{_('Invalid operation ')}{apt_cmd}'}")
        sys.exit(1)
    
    # Get configuration for flag defaults
    config = get_config()
    
    # Parse global flags early (before processing commands)
    auto_confirm = False
    quiet_level = 0
    verbose = False
    download_only = False
    
    # -y, --yes, --assume-yes: Auto-confirm installations
    if any(flag in extra_args for flag in ["-y", "--yes", "--assume-yes"]):
        auto_confirm = True
        extra_args = [a for a in extra_args if a not in ["-y", "--yes", "--assume-yes"]]
    
    # -q, --quiet: Reduce verbosity (can be repeated: -q, -qq)
    quiet_level = extra_args.count("-q")
    if "--quiet" in extra_args:
        quiet_level = max(quiet_level, 1)
        extra_args.remove("--quiet")
    extra_args = [a for a in extra_args if a != "-q"]
    
    # --verbose: Increase verbosity
    if "--verbose" in extra_args:
        verbose = True
        extra_args.remove("--verbose")
    
    # --download-only: Only download packages
    if "--download-only" in extra_args:
        download_only = True
        extra_args.remove("--download-only")
    
    # Selective upgrade flags
    only_official = False
    only_aur = False
    if "--official" in extra_args:
        only_official = True
        extra_args.remove("--official")
    if "--aur" in extra_args:
        only_aur = True
        extra_args.remove("--aur")
    if "--aur-only" in extra_args:
        only_aur = True
        extra_args.remove("--aur-only")
    
    # Apply config verbosity if not overridden
    config_verbosity = config.get("ui", "verbosity", 1)
    if quiet_level == 0 and not verbose:
        if config_verbosity == 0:
            quiet_level = 2
        elif config_verbosity >= 2:
            verbose = True
            
    # Apply force_colors config
    force_colors = config.get("ui", "force_colors", False)
    if force_colors:
        ui.set_force_colors(True)
        # Also force pacman color by adding to extra_args
        extra_args.append("--color=always")
    
    # Show verbose information if enabled
    if verbose:
        console.print(f"[dim]Config dir: {config.config_dir}[/dim]")
        console.print(f"[dim]Cache dir: {config.cache_dir}[/dim]")
        console.print(f"[dim]Verbosity: {config_verbosity}, Quiet: {quiet_level}, Auto-confirm: {auto_confirm}[/dim]")
    
    # Check for simulation flag
    is_simulation = "-s" in extra_args or "--simulate" in extra_args or "--dry-run" in extra_args
    if is_simulation:
        # Remove the flag from extra_args so it doesn't confuse pacman if it doesn't support it
        extra_args = [a for a in extra_args if a not in ["-s", "--simulate", "--dry-run"]]
        print_info(_("Simulation mode enabled."))

    # Handle --fix-broken flag
    if "--fix-broken" in extra_args or "-f" in extra_args:
        extra_args = [a for a in extra_args if a not in ["--fix-broken", "-f"]]
        print_reading_status()
        console.print(f"[info]{_('Correcting dependencies...')}[/info]\n")
        
        subprocess.run(["pacman", "-Dk"], check=False)
        console.print(f"[info]{_('Attempting to resolve broken dependencies via system upgrade...')}[/info]")
        if os.getuid() == 0:
            subprocess.run(["pacman", "-Syu", "--noconfirm"], check=False)
            subprocess.run(["pacman", "-Syu", "--noconfirm"], check=False)
            console.print(f"\n[green]{_('Done')}[/green]")
        else:
            console.print(f"[yellow]{_('W:')}[/yellow] {_('Run as root to attempt automatic fixes')}")
        return
    
    # Handle --no-install-recommends flag
    if "--no-install-recommends" in extra_args:
        extra_args = [a for a in extra_args if a != "--no-install-recommends"]
        if apt_cmd == "install":
            msg = f"[magenta]{_('N:')}[/magenta] {_('Pacman doesn\'t install optional dependencies by default')}"
            console.print(f"[info]{msg}[/info]")
    
    # Handle --only-upgrade flag
    only_upgrade = "--only-upgrade" in extra_args
    if only_upgrade:
        extra_args = [a for a in extra_args if a != "--only-upgrade"]
        if apt_cmd == "install":
            pkgs_to_upgrade = []
            for pkg in extra_args:
                if alpm_helper.is_package_installed(pkg):
                    pkgs_to_upgrade.append(pkg)
                else:
                    console.print(f"[info]{_('Skipping')} {pkg} ({_('not installed')})[/info]")
            
            if not pkgs_to_upgrade:
                print_info(_("0 upgraded, 0 newly installed, 0 to remove and 0 not upgraded."))
                return
            
            extra_args = pkgs_to_upgrade

    pacman_args = COMMAND_MAP[apt_cmd]

    # Easter Eggs
    if apt_cmd == "moo":
        # Cute furry cow OwO
        console.print("        ^__^")
        console.print("        (oo)\\_______")
        console.print("        (__)\\       )\\")
        console.print("            ||----w | *")
        console.print("            ||     ||")
        console.print(_("...\"Have you mooed today?\"..."))
        return
        
    if apt_cmd == "pacman":
        # Cool Pacman!
        console.print("")
        console.print("    ᗧ···· ᗣ  ᗣ  ᗣ")
        console.print("")
        console.print(_("...Waka waka!..."))
        return

    # Check safeguards before doing anything destructive
    if not is_simulation:
        check_safeguards(apt_cmd, extra_args)

    # Handle privilege check (Strict APT style)
    if apt_cmd in NEED_SUDO and os.getuid() != 0:
        if apt_cmd == "update":
            console.print(f"[red]{_('E:')}[/red] {_('Could not open lock file /var/lib/pacman/db.lck - open (13: Permission denied)')}")
            console.print(f"[red]{_('E:')}[/red] {_('Unable to lock directory /var/lib/pacman/')}")
        else:
            console.print(f"[red]{_('E:')}[/red] {_('Could not open lock file /var/lib/pacman/db.lck - open (13: Permission denied)')}")
            console.print(f"[red]{_('E:')}[/red] {_('Unable to lock the administration directory (/var/lib/pacman/), are you root?')}")
        sys.exit(100)

    # Handle apt list with all options
    if apt_cmd == "list":
        # Show help with pacman -Q options
        if "--help" in extra_args or "-h" in extra_args:
            console.print("[bold]Usage:[/bold] apt list [options]")
            console.print("\n[bold]apt-specific options:[/bold]")
            console.print("  --installed         List installed packages")
            console.print("  --upgradable        List upgradable packages")  
            console.print("  --manual-installed  List manually installed packages")
            console.print("  --all-versions      List all available versions")
            console.print("\n[bold]Run 'pacman -Q --help' for additional pacman options[/bold]")
            return
        
        
        if "--upgradable" in extra_args:
            # Use native pyalpm for upgradable packages
            updates = alpm_helper.get_available_updates()
            
            if updates:
                # Show partial upgrade warning
                console.print(f"[yellow]{_('W:')}[/yellow] {_('Partial upgrades are not supported on Arch Linux.')}")
                console.print(f"[dim]{_('It is recommended to run a full system upgrade instead.')}[/dim]\n")
                
                # Display upgradable packages
                for pkg in sorted(updates, key=lambda p: p.name):
                    # Get sync version
                    sync_pkg = alpm_helper.get_package(pkg.name)
                    if sync_pkg:
                        repo = sync_pkg.db.name
                        new_version = sync_pkg.version
                        console.print(f"[green]{pkg.name}[/green]/[bold blue]{repo}[/bold blue] {pkg.version} -> [bold]{new_version}[/bold]")
            else:
                console.print(_("All packages are up to date."))
            
            extra_args = [a for a in extra_args if a != "--upgradable"]
            return
        elif "--installed" in extra_args:
            # Use native pyalpm for richer output
            installed_pkgs = alpm_helper.get_installed_packages()
            orphans = set(pkg.name for pkg in alpm_helper.get_orphan_packages())
            
            # Get AUR updates if requested (for [outdated] tag)
            aur_outdated = set()
            if hasattr(aur, 'check_updates'):
                try:
                    aur_updates = aur.check_updates(verbose=False)
                    aur_outdated = set(u['name'] for u in aur_updates)
                except:
                    pass
            
            for pkg in sorted(installed_pkgs, key=lambda p: p.name):
                # Find real repository by looking up in sync databases
                repo = 'local'
                sync_pkg = alpm_helper.get_package(pkg.name)
                if sync_pkg:
                    repo = sync_pkg.db.name
                
                # Format with colorization
                name_repo = f"[green]{pkg.name}[/green]/[bold blue]{repo}[/bold blue]"
                
                # Architecture - use 'all' for 'any', 'multilib' if from multilib repo
                arch = pkg.arch
                if arch == 'any':
                    arch = 'all'
                elif repo == 'multilib':
                    arch = 'multilib'
                
                # Installation type
                import pyalpm
                if pkg.name in orphans:
                    install_type = "[dim][installed, huerfano][/dim]"
                elif pkg.reason == pyalpm.PKG_REASON_DEPEND:
                    # Find what installed it (first requiredby)
                    requiredby = pkg.compute_requiredby()
                    if requiredby:
                        install_type = f"[dim][installed by {requiredby[0]}][/dim]"
                    else:
                        install_type = "[installed]"
                elif pkg.name in aur_outdated:
                    install_type = "[yellow][installed, outdated][/yellow]"
                else:
                    install_type = "[installed]"
                
                console.print(f"{name_repo} [bold]{pkg.version}[/bold] {arch} {install_type}")
            
            extra_args = [a for a in extra_args if a != "--installed"]
            return
        elif "--manual-installed" in extra_args:
            pacman_cmd = ["pacman", "-Qe"]
            extra_args = [a for a in extra_args if a != "--manual-installed"]
        elif "--all-versions" in extra_args:
            pacman_cmd = ["pacman", "-Sl"]
            extra_args = [a for a in extra_args if a != "--all-versions"]
        elif any(a.startswith("--repo") for a in extra_args):
            repo = next((a.split("=")[1] for a in extra_args if a.startswith("--repo=")), None)
            if not repo and "--repo" in extra_args:
                idx = extra_args.index("--repo")
                if idx + 1 < len(extra_args):
                    repo = extra_args[idx + 1]


            if repo:
                if subprocess.run(["command -v paclist"], shell=True, capture_output=True).returncode == 0:
                    pacman_cmd = ["paclist", repo]
                else:
                    pacman_cmd = ["pacman", "-Sl", repo]
            else:
                pacman_cmd = ["pacman", "-Q"] + extra_args
        else:
            pacman_cmd = ["pacman", "-Q"] + extra_args
    elif apt_cmd == "install":
        # Check if we are installing a local file
        # We check content (.PKGINFO in tar) to be sure
        if any(aur.is_valid_package(a) for a in extra_args):
            pacman_cmd = ["pacman", "-U"] + extra_args
        else:
            # Check for AUR packages
            official_pkgs = []
            aur_pkgs = []
            
            for pkg in extra_args:
                if pkg.startswith('-'):
                    # Pass flags through to pacman
                    official_pkgs.append(pkg)
                    continue

                if aur.is_in_official_repos(pkg):
                    official_pkgs.append(pkg)
                elif aur.get_aur_info([pkg]): 
                    # Check if it exists in AUR (exact match via info)
                    aur_pkgs.append(pkg)
                else:
                    # Not found in either
                    console.print(f"[bold red]E:[/bold red] {_('Unable to locate package')} {pkg}[/bold red]")
                    sys.exit(100)
            
            if aur_pkgs:
                # If we have official packages, install them first
                if official_pkgs:
                    console.print(f"[bold]{_('Installing official packages:')}[/bold] {' '.join(official_pkgs)}")
                    cmd = ["pacman", "-S"] + official_pkgs
                    if auto_confirm:
                        cmd.append("--noconfirm")
                    subprocess.run(cmd)
                
                # Then install AUR packages
                installer = aur.AurInstaller()
                try:
                    installer.install(aur_pkgs, verbose=verbose, auto_confirm=auto_confirm)
                except KeyboardInterrupt:
                    print_error(_("\nInterrupted."))
                    sys.exit(1)
                except Exception as e:
                    print_error(f"{_("AUR Installation failed: ")}{e}")
                    sys.exit(1)
                return # Exit after AUR install handling
            
            # If no AUR packages, just proceed with normal pacman -S
            pacman_cmd = ["pacman", "-S"] + extra_args
    elif apt_cmd == "depends":
        if not extra_args:
            print_error(f"[bold red]{_('E')}[/bold red]: {_('No package specified')}")
            sys.exit(1)
        
        # Use native pyalpm for dependency listing
        pkgname = extra_args[0]
        
        # Try installed package first, then sync repos
        pkg = alpm_helper.get_local_package(pkgname)
        if not pkg:
            pkg = alpm_helper.get_package(pkgname)
        
        if pkg:
            console.print(f"[bold]{pkgname}[/bold]")
            if pkg.depends:
                # Convert to list and display in columns
                deps_list = [str(dep) for dep in pkg.depends]
                print_columnar_list(deps_list, "default")
            else:
                console.print(f"  {_('(no dependencies)')}")
        else:
            print_error(f"{_('Package not found:')} {pkgname}")
            sys.exit(1)
        return
    elif apt_cmd == "rdepends":
        if not extra_args:
            print_error(f"[bold red]{_('E')}[/bold red]: {_('No package specified')}")
            sys.exit(1)
        
        # Use native pyalpm for reverse dependency listing
        pkgname = extra_args[0]
        
        # Only installed packages have reverse dependencies
        pkg = alpm_helper.get_local_package(pkgname)
        
        if pkg:
            console.print(f"[bold]{pkgname}[/bold]")
            # compute_requiredby returns list of package names that depend on this package
            rdeps = pkg.compute_requiredby()
            if rdeps:
                # Display in columns
                print_columnar_list(rdeps, "default")
            else:
                console.print(f"  {_('(no reverse dependencies)')}")
        else:
            print_error(f"{_('Package not installed:')} {pkgname}")
            sys.exit(1)
        return
    elif apt_cmd == "scripts":
        if subprocess.run(["command -v pacscripts"], shell=True, capture_output=True).returncode == 0:
            pacman_cmd = ["pacscripts"] + extra_args
        else:
            pacman_cmd = ["pacman", "-Qii"] + extra_args
    elif apt_cmd == "reinstall":
        pacman_cmd = ["pacman", "-S", "--force"] + extra_args
    elif apt_cmd == "clean":
        # Run pacman clean
        subprocess.run(["pacman", "-Scc"], check=False)
        
        # Clean apt-pac cache
        cache_dir = config.cache_dir
        if cache_dir.exists():
            console.print(f"\n[bold]{_('Cleaning apt-pac cache')} ({cache_dir})...[/bold]")
            sources_dir = cache_dir / "sources"
            if sources_dir.exists():
                import shutil
                shutil.rmtree(sources_dir)
                console.print(f"[green]{_('Removed')} {sources_dir}[/green]")
        return

    elif apt_cmd == "autoclean":
        if subprocess.run(["command -v paccache"], shell=True, capture_output=True).returncode == 0:
            pacman_cmd = ["paccache", "-rk3"]
        else:
            pacman_cmd = ["pacman", "-Sc"]
    elif apt_cmd == "policy":
        # Simulate apt-cache policy: show installed version and repo version
        pkg = extra_args[0] if extra_args else ""
        if pkg:
            console.print(f"[bold]{pkg}:[/bold]")
            
            # Check installed version
            local_pkg = alpm_helper.get_local_package(pkg)
            if local_pkg:
                console.print(f"  Installed: {local_pkg.version}")
            else:
                console.print(f"  {_('Installed:')} ({_('none')})")
            
            # Check candidate (repo) version
            remote_pkg = alpm_helper.get_package(pkg)
            if remote_pkg:
                console.print(f"  Candidate: {remote_pkg.version}")
            return
    elif apt_cmd == "apt-mark":
        if not extra_args:
            print_info(_("Usage: apt-mark [auto|manual|hold|unhold] [package]"))
            return
        sub = extra_args[0]
        pkgs = extra_args[1:]
        if sub == "auto":
            pacman_cmd = ["pacman", "-D", "--asdeps"] + pkgs
        elif sub == "manual":
            pacman_cmd = ["pacman", "-D", "--asexplicit"] + pkgs
        elif sub == "hold":
            print_info(f"[magenta]{_('N:')}[/magenta] {_('Arch handles \'hold\' via IgnorePkg in /etc/pacman.conf.')}")  
            print_info(_("Consider adding these packages to IgnorePkg manually."))
            return
        else:
            print_info(f"{_("Subcommand ")}{sub}{_(" not yet implemented.")}")
            return
    elif apt_cmd == "check":
        print_reading_status()
        
        result_db = subprocess.run(["pacman", "-Dk"], capture_output=True, text=True)
        if result_db.returncode == 0:
            console.print(f"{_('Database integrity:')} [green]{_('OK')}[/green]")
        else:
            console.print(f"[{_('error')}]{_('E')}:[/{_('error')}] {_('Database errors')}:\n{result_db.stdout}")
        
        result_deps = subprocess.run(["pacman", "-Qk"], capture_output=True, text=True)
        dep_issues = [line for line in result_deps.stdout.splitlines() if "warning" in line.lower()]
        if dep_issues:
            console.print(f"\nW: {len(dep_issues)} {_('package warnings found')}")
        else:
            console.print(f"{_('All packages:')} [green]{_('OK')}[/green]")
        
        if subprocess.run(["command", "-v", "lddd"], shell=True, capture_output=True).returncode == 0:
            try:
                result_lddd = subprocess.run(["lddd"], capture_output=True, text=True, check=False)
                if result_lddd.returncode == 0:
                    if result_lddd.stdout.strip():
                        console.print(f"\nW: {_('Broken libraries detected')}")
                    else:
                        console.print(f"{_('Library links:')} [green]{_('OK')}[/green]")
            except (FileNotFoundError, OSError):
                # lddd not actually available, skip check silently
                pass
        return
    
    elif apt_cmd == "pkgnames":
        # Use pyalpm to list package names
        all_pkgs = alpm_helper.get_all_repo_packages()
        
        if extra_args:
            # Filter by prefix
            prefix = extra_args[0]
            for pkg in all_pkgs:
                if pkg.name.startswith(prefix):
                    print(pkg.name)
        else:
            # Print all package names
            for pkg in all_pkgs:
                print(pkg.name)
        return
    
    elif apt_cmd == "stats":
        console.print(f"\n[bold]{_('Package Statistics:')}[/bold]\n")
        
        # Use pyalpm for all queries
        all_repo_pkgs = alpm_helper.get_all_repo_packages()
        num_avail = len(all_repo_pkgs)
        console.print(f"  {_('Total packages')}:          [pkg]{num_avail}[/pkg]")
        
        installed_pkgs = alpm_helper.get_installed_packages()
        num_installed = len(installed_pkgs)
        console.print(f"  {_('Installed packages')}:      [pkg]{num_installed}[/pkg]")
        
        explicit_pkgs = alpm_helper.get_installed_packages(explicit_only=True)
        num_explicit = len(explicit_pkgs)
        console.print(f"  {_('Explicitly installed')}:    [pkg]{num_explicit}[/pkg]")
        
        deps_pkgs = alpm_helper.get_installed_packages(deps_only=True)
        num_deps = len(deps_pkgs)
        console.print(f"  {_('Installed as deps')}:       [pkg]{num_deps}[/pkg]")
        
        orphan_pkgs = alpm_helper.get_orphan_packages()
        num_orphans = len(orphan_pkgs)
        console.print(f"  {_('Orphaned packages')}:       [pkg]{num_orphans}[/pkg]")
        
        updates = alpm_helper.get_available_updates()
        num_updates = len(updates)
        console.print(f"  {_('Upgradable packages')}:     [pkg]{num_updates}[/pkg]")
        
        cache_path = "/var/cache/pacman/pkg"
        if os.path.exists(cache_path):
            cache_files = os.listdir(cache_path)
            num_cached = len([f for f in cache_files if f.endswith('.pkg.tar.zst') or f.endswith('.pkg.tar.xz')])
            console.print(f"\n  {_('Cached package files')}:    [pkg]{num_cached}[/pkg]")
        return
    
    elif apt_cmd == "source":
        from .sources import handle_apt_source
        if not extra_args:
            print_error(f"[red]{_('E:')}[/red] {_('No packages specified for source download')}")
            print_info(_("Usage: apt source <package>"))
            sys.exit(1)
        package_name = extra_args[0]
        success = handle_apt_source(package_name, extra_args[1:], verbose=verbose)
        sys.exit(0 if success else 1)
    
    elif apt_cmd == "build-dep":
        from .sources import handle_build_dep
        if not extra_args:
            print_error(f"[red]{_('E:')}[/red] {_('No package specified')}")
            print_info(_("Usage: apt build-dep <package>"))
            sys.exit(1)
        package_name = extra_args[0]
        success = handle_build_dep(package_name, verbose=verbose)
        sys.exit(0 if success else 1)
    
    elif apt_cmd == "dotty":
        # Check if pactree is installed
        if subprocess.run(["command -v pactree"], shell=True, capture_output=True).returncode == 0:
             pacman_cmd = ["pactree", "-g"] + extra_args
        else:
             print_error(_("pactree (pacman-contrib) is required for dotty."))
             sys.exit(1)

    elif apt_cmd == "add-repository":
        # from rich.panel import Panel
        # from rich.text import Text
        
        text = Text()
        text.append(_(f"Adding repositories in Arch Linux differs from Debian/Ubuntu.") + "\n", style="bold")
        text.append(_(f"You need to edit /etc/pacman.conf and add a [section].") + "\n\n")
        
        text.append(f"{_('Example')} (Chaotic AUR):\n", style="bold green")
        text.append("[chaotic-aur]\n")
        text.append("Include = /etc/pacman.d/chaotic-mirrorlist\n\n")
        
        text.append(f"{_('Example (Generic)')}):\n", style="bold green")
        text.append("[repo-name]\n")
        text.append("Server = https://example.com/$arch\n")
        text.append("SigLevel = Required DatabaseOptional\n\n")
        
        text.append(f"[magenta]{_('N:')}[/magenta] {_('You may need to import GPG keys first using apt-key (pacman-key).')}\n", style="magenta")
        
        console.print(Panel(text, title=_("How to add a repository"), border_style="blue"))
        
        if console.input(f"\n{_('Do you want to edit /etc/pacman.conf now?')} [Y/n] ").lower().startswith('y'):
            # Reuse edit-sources logic
            # Just recursively call execute_command or copy logic. Copying is safer to avoid recursion limits/state issues.
            editor = get_editor()
            cmd = ["sudo", editor, "/etc/pacman.conf"]
            if os.getuid() == 0:
                 cmd = [editor, "/etc/pacman.conf"]
                 
            print_command(f"Running: {' '.join(cmd)}")
            try:
                subprocess.run(cmd, check=True)
            except subprocess.CalledProcessError:
                sys.exit(1)
        return
        
        if subprocess.run(["command", "-v", "pactree"], shell=True, capture_output=True).returncode == 0:
            pacman_cmd = ["pactree", "-g"] + extra_args
            subprocess.run(pacman_cmd)
        else:
            print_error(f"[red]{_('E:')}[/red] {_('This command requires \'pacman-contrib\' package')}")
            console.print(f"{_('Install with:')} [command]sudo pacman -S pacman-contrib[/command]")
        return
    
    elif apt_cmd == "madison":
        if not extra_args:
            print_error(f"[red]{_('E:')}[/red] {_('No package specified')}")
            return
        
        pkg = extra_args[0]
        console.print(f"[bold]{pkg}:[/bold]")
        
        # Show installed version
        local_pkg = alpm_helper.get_local_package(pkg)
        if local_pkg:
            console.print(f"  {local_pkg.version} | Installed")
        
        # Show repo version
        remote_pkg = alpm_helper.get_package(pkg)
        if remote_pkg:
            repo = remote_pkg.db.name if hasattr(remote_pkg, 'db') else 'unknown'
            console.print(f"  {remote_pkg.version} | {repo}")
        return
    
    elif apt_cmd == "config":
        console.print(f"\n[bold]{_('Pacman Configuration:')}[/bold]\n")
        try:
            with open("/etc/pacman.conf", "r") as f:
                content = f.read()
                # Show in a panel
                # Show in a panel
                console.print(Panel(content, title="/etc/pacman.conf", border_style="blue"))
        except FileNotFoundError:
            print_error(f"[red]{_('E:')}[/red] {_('Cannot read /etc/pacman.conf')}")
        except PermissionError:
            print_error(f"[red]{_('E:')}[/red] {_('Permission denied reading /etc/pacman.conf')}")
        return
    
    elif apt_cmd in ["apt-key", "key"]:
        if not extra_args:
            console.print(f"\n[bold]{_('Usage:')}[/bold] apt-key [add|list|del|adv] ...\n")
            console.print(f"[bold]{_('Examples:')}[/bold]")
            console.print(f"  apt-key add <keyfile>     - {_('Import GPG key')}")
            console.print(f"  apt-key list              - {_('List all keys')}")
            console.print(f"  apt-key del <keyid>       - {_('Remove key')}\n")
            console.print(f"[magenta]{_('N:')}[/magenta] {_('This is a wrapper for pacman-key')}")
            return
        
        sub = extra_args[0]
        if sub == "add":
            if len(extra_args) < 2:
                print_error(f"[red]{_('E:')}[/red] {_('No keyfile specified')}")
                return
            pacman_cmd = ["pacman-key", "--add"] + extra_args[1:]
        elif sub == "list":
            pacman_cmd = ["pacman-key", "--list-keys"]
        elif sub in ["del", "delete", "remove"]:
            if len(extra_args) < 2:
                print_error(f"[red]{_('E:')}[/red] {_('No key ID specified')}")
                return
            pacman_cmd = ["pacman-key", "--delete"] + extra_args[1:]
        elif sub == "adv":
            # Pass through to gpg
            pacman_cmd = ["pacman-key"] + extra_args
        else:
            print_error(f"[red]{_('E:')}[/red] {f'{_('Unknown apt-key command: ')}{sub}'}")
            return
        
        # For add/del, apt-key only prints "OK" on success
        if sub in ["add", "del", "delete", "remove"]:
            try:
                subprocess.run(pacman_cmd, check=True, capture_output=True)
                print("OK")
            except subprocess.CalledProcessError as e:
                # pass through stderr if failed
                sys.stderr.write(e.stderr.decode() if e.stderr else f"Error running {' '.join(pacman_cmd)}\n")
                sys.exit(e.returncode)
        else:
            # list/adv pass through directly
            subprocess.run(pacman_cmd)
        return
    
    elif apt_cmd == "add-repository":
        # from rich.panel import Panel
        # from rich.text import Text
        
        text = Text()
        text.append(_(f"Adding repositories in Arch Linux differs from Debian/Ubuntu.") + "\n", style="bold")
        text.append(_(f"You need to edit /etc/pacman.conf and add a [section].") + "\n\n")
        
        text.append(f"{_('Example')} (Chaotic AUR):\n", style="bold green")
        text.append("[chaotic-aur]\n")
        text.append("Include = /etc/pacman.d/chaotic-mirrorlist\n\n")
        
        text.append(f"{_('Example')} ({_('Generic')}):\n", style="bold green")
        text.append("[repo-name]\n")
        text.append("Server = https://example.com/$arch\n")
        text.append("SigLevel = Required DatabaseOptional\n\n")
        
        text.append(f"[magenta]{_('N:')}[/magenta] {_('You may need to import GPG keys first using apt-key (pacman-key).')}\n", style="magenta")
        
        console.print(Panel(text, title="How to add a repository", border_style="blue"))
        
        if console.input(f"\n{_('Do you want to edit /etc/pacman.conf now?')} [Y/n] ").lower().startswith('y'):
            editor = get_editor()
            cmd = ["sudo", editor, "/etc/pacman.conf"]
            if os.getuid() == 0:
                 cmd = [editor, "/etc/pacman.conf"]
                 
            print_command(f"Running: {' '.join(cmd)}")
            try:
                subprocess.run(cmd, check=True)
            except subprocess.CalledProcessError:
                sys.exit(1)
        return
    
    elif apt_cmd == "showsrc":
        from .sources import handle_showsrc
        if not extra_args:
            print_error("E: No package specified")
            print_info(_("Usage: apt-cache showsrc <package>"))
            sys.exit(1)
        package_name = extra_args[0]
        success = handle_showsrc(package_name, verbose=verbose)
        sys.exit(0 if success else 1)
    
    elif apt_cmd == "help":
        if not extra_args:
            print_error("E: No package specified")
            print_info(_("Usage: apt help <package>"))
            sys.exit(1)
        
        package_name = extra_args[0]
        
        # Check if man command is installed
        if subprocess.run(["command", "-v", "man"], shell=True, capture_output=True).returncode != 0:
            print_error(_("E: man is not installed"))
            print_info(_("Install man-db or man-pages to use this feature"))
            sys.exit(1)
        
        # Try to show manpage for package
        result = subprocess.run(["man", package_name], capture_output=False)
        if result.returncode != 0:
            # Manpage not found
            console.print(f"[yellow]W:[/yellow] {_('No manual entry for')} {package_name}")
            console.print(f"{_('Try:')} apt-pac show {package_name}")
            sys.exit(1)
        return
    
    elif apt_cmd == "edit-sources":
        editor = get_editor()
        cmd = [editor, "/etc/pacman.conf"]
        print_command(f"Running: {' '.join(cmd)}")
        try:
            subprocess.run(cmd, check=True)
            return
        except subprocess.CalledProcessError:
            sys.exit(1)

    # If pacman_cmd was not set by a special handler above, set it now
    if 'pacman_cmd' not in locals():
        if apt_cmd == "autoremove":
            orphan_pkgs = alpm_helper.get_orphan_packages()
            if not orphan_pkgs:
                print_info(_("No orphaned packages to remove."))
                return
            orphans = [pkg.name for pkg in orphan_pkgs]
            pacman_cmd = ["pacman", "-Rns"] + orphans
        else:
            pacman_cmd = ["pacman"] + pacman_args + extra_args

    # Check if we need to format output (search/show)
    if apt_cmd in ["search", "show"]:
        # Get user preference for output format
        config = get_config()
        show_output = config.get("ui", "show_output", "apt-pac")
        
        # Determine Search Scope
        scope = "both"
        if only_aur:
            scope = "aur"
        elif only_official:
            scope = "official"
            
        pacman_cmd = ["pacman"] + pacman_args + extra_args

        # Official Search
        if scope in ["both", "official"] and apt_cmd == "search":
            # Use native pyalpm search instead of subprocess
            
            # Extract query from extra_args
            queries = [arg for arg in extra_args if not arg.startswith("-")]
            if queries:
                query = queries[0]
                try:
                    results = alpm_helper.search_packages(query)
                    if results:
                        if show_output in ["apt-pac", "apt"]:
                            # Get installed packages once for efficient lookup
                            installed_pkgs = set(pkg.name for pkg in alpm_helper.get_installed_packages())
                            
                            # Convert pyalpm results to pacman -Ss format for format_search_results
                            pacman_style_output = []
                            for pkg in results:
                                repo = pkg.db.name if hasattr(pkg, 'db') else 'unknown'
                                # Check if package is installed
                                is_installed = pkg.name in installed_pkgs
                                status = " [installed]" if is_installed else ""
                                
                                # Line 1: repo/pkgname version [installed]
                                header = f"{repo}/{pkg.name} {pkg.version}{status}"
                                # Line 2: description
                                desc = f"    {pkg.desc}"
                                
                                pacman_style_output.append(header)
                                pacman_style_output.append(desc)
                            
                            # Pass to format_search_results
                            format_search_results("\n".join(pacman_style_output))
                        else:
                            # Pacman-style output
                            installed_pkgs = set(pkg.name for pkg in alpm_helper.get_installed_packages())
                            for pkg in results:
                                repo = pkg.db.name if hasattr(pkg, 'db') else 'unknown'
                                is_installed = pkg.name in installed_pkgs
                                status = " [installed]" if is_installed else ""
                                print(f"{repo}/{pkg.name} {pkg.version}{status}")
                                print(f"    {pkg.desc}")
                except Exception as e:
                    # Log error but don't fall back (pyalpm is required)
                    print_error(f"Search error: {e}")
        
        # AUR Search
        if scope in ["both", "aur"] and apt_cmd == "search":
            # Extract query from extra_args (assume arg not starting with - is the query)
            queries = [arg for arg in extra_args if not arg.startswith("-")]
            if queries:
                with console.status("[magenta]Searching AUR...[/magenta]", spinner="dots"):
                    matches = aur.search_aur(queries[0]) # Search first query arg
                if matches:
                    format_aur_search_results(matches)

        # Show Command (Official -> Local -> AUR)
        if apt_cmd == "show":
             # 1. Try Official Repos (pacman -Si) with English output
             result = run_pacman(pacman_cmd, capture_output=True, text=True)
             found = False
             
             if result.returncode == 0:
                 found = True
                 if show_output in ["apt-pac", "apt"]:
                     format_show(result.stdout)
                 else:
                     print(result.stdout, end="")
             
             # 2. If not found, try Local Database (pacman -Qi)
             # Only if user didn't explicitly request official-only (implicit)
             # But 'show' doesn't strictly support --official flag in our logic yet, 
             # preventing partial output. Let's assume we want to find it anywhere.
             
             if not found:
                 # Try -Qi
                 local_cmd = ["pacman", "-Qi"] + extra_args
                 result_local = run_pacman(local_cmd, capture_output=True, text=True)
                 if result_local.returncode == 0:
                     found = True
                     if show_output in ["apt-pac", "apt"]:
                         format_show(result_local.stdout)
                     else:
                         print(result_local.stdout, end="")
            
             # 3. If still not found, try AUR
             if not found:
                 queries = [arg for arg in extra_args if not arg.startswith("-")]
                 if queries:
                    with console.status("[magenta]Checking AUR...[/magenta]", spinner="dots"):
                         # aur.get_aur_info returns detailed info list
                         aur_info = aur.get_aur_info(queries)
                    
                    if aur_info:
                        found = True
                        from .ui import format_aur_info
                        format_aur_info(aur_info)
            
             if not found:
                 print_error(f"{_('Package')} '{' '.join(extra_args)}' {_('not found in repositories, local database, or')} AUR.")

        return

    # Show summary for install/upgrade (unless auto-confirmed or quiet)
    if apt_cmd in ["install"]:
        if not is_simulation:
            show_summary(apt_cmd, extra_args, auto_confirm=auto_confirm)
            
            # If we are here, user confirmed.
        
        # 4. Execute
        # If user confirmed in show_summary (or auto-confirm), we can run with --noconfirm
        if not is_simulation:
            if "--noconfirm" not in pacman_cmd:
                pacman_cmd.append("--noconfirm")
    
    # Apply download-only flag
    if download_only and apt_cmd in ["install", "upgrade", "dist-upgrade", "full-upgrade"]:
        # Add -w flag for download only
        if "-S" in pacman_cmd:
            pacman_cmd.append("-w")
        elif "-Syu" in pacman_cmd or "-Sy" in pacman_cmd:
            pacman_cmd.append("-w")
    
    # Check if user wants to see the pacman command
    if config.get("ui", "show_pacman_command", False) or verbose:
        print_command(f"Running: {' '.join(pacman_cmd)}")
    
    # Apply quiet flags to pacman
    if quiet_level >= 1:
        pacman_cmd.append("-q")
    if quiet_level >= 2:
        pacman_cmd.append("-q")  # -qq for very quiet
    
    # Apply auto-confirm to pacman
    if auto_confirm:
        if apt_cmd in ["install", "upgrade", "dist-upgrade", "full-upgrade", "remove", "purge", "autoremove"]:
            pacman_cmd.append("--noconfirm")
    
    # Simulate download output if applicable
    # REMOVED: Early simulation for upgrade is now handled specifically inside the upgrade block 
    # to ensure correct order (Sync -> Summary -> Simulate -> Execute)
    if apt_cmd in ["install", "reinstall"]:
         # Only if not --print or --dry-run (which is -s)
         if not any(x in extra_args for x in ["--print", "-p"]):
             # Check if we are doing a real op
             simulate_apt_download_output(pacman_cmd, config)

    # Check for Partial Upgrades (Arch Best Practice)
    # If installing/removing software while system is out of date, warn user.
    if apt_cmd in ["install", "reinstall", "remove", "purge", "autoremove"] and not is_simulation:
        # Check updates without syncing
        updates = alpm_helper.get_available_updates()
        if updates:
             num_updates = len(updates)
             
             prog_name = os.path.basename(sys.argv[0])
             if prog_name.endswith(".py"): # Fallback if running via python -m
                 prog_name = "apt-pac"
                 
             console.print(Text(f"\n[yellow]{_('W:')}[/yellow] {_(f'You have {num_updates} pending system upgrades.')}"))
             console.print(_("Performing partial upgrades is [bold]unsupported[/bold] on Arch Linux and may break your system."))
             console.print(f"[dim]{_('It is recommended to run')} [bold white]'{prog_name} upgrade'[/bold white] {_('first.')}[/dim]\n")
             
             if not auto_confirm:
                 prompt = Text(f"{_('Proceed with partial operation?')} [Y/n] ", style="bold yellow")
                 if not console.input(prompt).lower().startswith('y'):
                     print_info(_("Aborted."))
                     sys.exit(0)

    if apt_cmd in ["remove", "purge", "autoremove"]:
        # We handled summary/prompt in check_safeguards.
        # Now ensuring execution is seamless.
        # If not simulation, we usually want to suppress pacman's prompt because we already asked.
        # However, check_safeguards is unaware of auto_confirm status from flags?
        # Actually execute_command handles flags.
        # Logic update needed: passing confirmation to pacman.
        if not is_simulation:
            # Assume check_safeguards prompt satisfied the need.
            if "--noconfirm" not in pacman_cmd:
                pacman_cmd.append("--noconfirm")


    try:
        # Use --noconfirm if we already asked
        current_cmd = list(pacman_cmd)
        if apt_cmd in ["install", "upgrade", "dist-upgrade", "full-upgrade", "remove", "purge", "autoremove"]:
             if "--noconfirm" in pacman_cmd: # Ensure we don't duplicate
                 pass
             elif auto_confirm: 
                 current_cmd.append("--noconfirm")
        
        # Special case for update and upgrade: sync files as well
        if apt_cmd == "update":
            # Run the main pacman -Sy
            sync_databases(pacman_cmd)
            
            # Run the file sync pacman -Fy
            if config.get("ui", "always_sync_files", True):
                with console.status(f"[bold blue]{_('Syncing file database...')}[/bold blue]", spinner="dots"):
                    sync_cmd = ["pacman", "-Fy"]
                    subprocess.run(sync_cmd, check=False, capture_output=True)
                
            # print_reading_status() would add newline, so just print first line
            console.print(f"\n{_('Reading package lists...')} [green]{_('Done')}[/green]")
            if only_aur:
                print_info(f"[magenta]{_('N:')}[/magenta] {_('\'update --aur\' simply checks official DBs as')} AUR {_('has no central DB to sync.')}")  
            return # Exit early as we've handled everything for update
        
        elif apt_cmd in ["upgrade", "dist-upgrade", "full-upgrade"]:
            # Logic:
            # 1. Sync DB (pacman -Sy)
            # 2. Show Summary (pacman -Qu based) & Prompt
            # 3. Simulate Download (pacman -Su -p) -> Get: ...
            # 4. Execute (pacman -Su ...)
            
            # Smart logic for flags
            run_official = True
            run_aur = True
            
            # If dist-upgrade, force EVERYTHING regardless of flags (apt-like power)
            if apt_cmd in ["dist-upgrade", "full-upgrade"]:
                run_official = True
                run_aur = True
                if only_official or only_aur:
                    print_info(f"{_('Ignoring selective flags for')} {apt_cmd}: {_('performing full system upgrade.')}")
            else:
                # Normal upgrade: respect flags
                if only_official:
                    run_aur = False
                if only_aur:
                    run_official = False
            
            # Prepare AUR data containers
            aur_new = []
            aur_upgrades = []
            aur_candidates = []
            aur_build_queue = []
            official_deps_for_aur = []
            
            if run_official:
                # 1. Sync DB first
                sync_databases()

            # Check for AUR updates EARLY (Pre-calc)
            if run_aur:
                console.print(f"[bold blue]{_('Checking for')} AUR {_('updates...')}[/bold blue]")
                try:
                    aur_updates = aur.check_updates(verbose=verbose)
                    
                    if aur_updates:
                        # Resolve dependencies immediately (One-Pass)
                        aur_candidates = [u['name'] for u in aur_updates]
                        resolver = aur.AurResolver()
                        with console.status(f"[blue]{_('Resolving')} AUR {_('dependencies...')}[/blue]", spinner="dots"):
                            aur_build_queue = resolver.resolve(aur_candidates)
                        
                        official_deps_for_aur = resolver.official_deps
                        full_aur_info = aur.get_resolved_package_info(aur_build_queue, resolver.official_deps)
                        
                        # Split based on whether it was in original update list
                        candidate_set = set(aur_candidates)
                        for name, ver in full_aur_info:
                            if name in candidate_set:
                                # Try to find old version?
                                old_ver = _("unknown")
                                for u in aur_updates:
                                    if u['name'] == name:
                                        old_ver = u.get('current', _("unknown"))
                                        break
                                aur_upgrades.append((name, old_ver, ver))
                            else:
                                # Dependency
                                aur_new.append((name, ver))
                    else:
                        console.print(f"{_('All')} AUR {_('packages are up to date.')}")
                except Exception as e:
                     print_error(f"{_('Failed to check')} AUR {_('updates:')} {e}")
                     aur_candidates = [] # Prevent execution on failure

            # 2. Show Summary (Unified)
            if not is_simulation:
                # Note: show_summary uses 'pacman -Qu' which works perfectly after -Sy
                user_confirmed_summary = False
                show_summary(apt_cmd, extra_args, auto_confirm=auto_confirm, aur_new=aur_new, aur_upgrades=aur_upgrades)
                # If we return, user confirmed.
                user_confirmed_summary = True
                
                if "--noconfirm" not in current_cmd:
                    current_cmd.append("--noconfirm")

            # 3. Simulate Download Output (Get: ...)
            # Use a specific command for simulation: pacman -Su
            sim_cmd = ["pacman", "-Su"]
            if not is_simulation:
                 simulate_apt_download_output(sim_cmd, config)

            # 4. Execute Upgrade (Official)
            if run_official:
                # Reconstruct execution command to be just -Su + flags
                exec_cmd = ["pacman", "-Su"]
                # Add preserved flags
                for arg in extra_args:
                    if arg not in ["-Syu", "-Sy", "-u"]:
                         exec_cmd.append(arg)
                
                if user_confirmed_summary or auto_confirm or "--noconfirm" in current_cmd:
                    # PROMPT FIX: If user confirmed summary, we MUST pass --noconfirm to pacman
                    # checking current_cmd is not enough if it wasn't updated correctly.
                    if "--noconfirm" not in exec_cmd:
                        exec_cmd.append("--noconfirm")
                if verbose:
                    exec_cmd.append("--verbose")
                if quiet_level > 0:
                    exec_cmd.append("-q")

                success = run_pacman_with_apt_output(exec_cmd, show_hooks=True)
                if not success:
                    print_error(_("Upgrade failed"))
                    sys.exit(1)
            else:
                if not run_aur: # If running ONLY aur, don't show this message if we are proceeding to AUR
                   console.print(f"[dim]{_('Skipping official packages upgrade (--aur provided)')}[/dim]")
            
            # 5. Execute Upgrade (AUR)
            if run_aur and aur_candidates:
                try:
                    installer = aur.AurInstaller()
                    installer.install(
                        aur_candidates, 
                        verbose=verbose, 
                        auto_confirm=True, # User confirmed at summary
                        build_queue=aur_build_queue,
                        official_deps=official_deps_for_aur,
                        skip_summary=True
                    )
                except Exception as e:
                    print_error(_(f"AUR Upgrade failed: {e}"))

            # Sync file database in background (silent)
            if not run_aur:
                console.print(f"\n[dim]{_('Skipping')} AUR {_('updates (--official provided)')}[/dim]")

            # Sync file database in background (silent)
            if run_official:
                console.print(f"\n{_('Syncing file database...')}")
                subprocess.run(["pacman", "-Fy"], check=False, capture_output=True)
                console.print(f"{_('File database:')} [green]{_('Done')}[/green]")
            return  # Exit after upgrade handling

        else:
            # For install/reinstall/remove/purge/autoremove: use APT-style output with hooks
            if apt_cmd in ["install", "reinstall", "remove", "purge", "autoremove"]:
                if not is_simulation:
                    simulate_apt_download_output(current_cmd, config)
                success = run_pacman_with_apt_output(current_cmd, show_hooks=True)
                if not success:
                    sys.exit(1)
            else:
                # Run directly without output capture - shows pacman's normal output
                subprocess.run(current_cmd, check=False)
            
    except subprocess.CalledProcessError:
        sys.exit(1)
