import subprocess
import sys
import os
from .ui import print_info, print_command, print_error, console, format_search_results, format_show, show_help, format_aur_search_results
from . import aur
from .config import get_config

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
    "add-repository": ["add-repository"],  # Educational message
    "showsrc": ["showsrc"],  # Placeholder for ABS+AUR
}

NEED_SUDO = {
    "update", "upgrade", "dist-upgrade", "full-upgrade", 
    "install", "reinstall", "remove", "purge", "autoremove", 
    "clean", "autoclean", "edit-sources", "apt-mark", "download"
}

def show_summary(apt_cmd, extra_args):
    pacman_args = COMMAND_MAP[apt_cmd]
    print_cmd = ["pacman"] + pacman_args + extra_args + ["--print", "--print-format", "%n|%v|%s|%m"]
    
    result = subprocess.run(print_cmd, capture_output=True, text=True)
    if result.returncode != 0 or not result.stdout.strip():
        return
    
    from rich.table import Table
    
    lines = result.stdout.strip().split('\n')
    new_pkgs = []
    upgraded_pkgs = []
    total_size = 0
    
    # Simple logic to distinguish new vs upgraded (rough estimate)
    for line in lines:
        if '|' not in line: continue
        name, ver, size, _ = line.split('|')
        try:
            total_size += int(size)
        except: pass
        
        # Check if installed
        check = subprocess.run(["pacman", "-Qq", name], capture_output=True)
        if check.returncode == 0:
            upgraded_pkgs.append(name)
        else:
            new_pkgs.append(name)

    console.print("\nReading package lists... [green]Done[/green]")
    console.print("Building dependency tree... [green]Done[/green]")
    console.print("Reading state information... [green]Done[/green]\n")

    if new_pkgs:
        console.print("[bold]The following NEW packages will be installed:[/bold]")
        console.print(f"  {' '.join(new_pkgs)}\n")
    
    if upgraded_pkgs:
        console.print("[bold]The following packages will be upgraded:[/bold]")
        console.print(f"  {' '.join(upgraded_pkgs)}\n")

    stats = f"{len(upgraded_pkgs)} upgraded, {len(new_pkgs)} newly installed, 0 to remove and 0 not upgraded."
    console.print(stats)
    console.print(f"Need to get {total_size / 1024 / 1024:.1f} MB of archives.")
    
    if not console.input("\n[bold]Do you want to continue? [Y/n][/bold] ").lower().startswith('y'):
        print_info("Aborted.")
        sys.exit(0)

def get_protected_packages():
    """Dynamically detects installed kernels and bootloaders to protect them."""
    core_packages = {"pacman", "systemd", "base", "sudo", "doas", "run0"}
    
    # Detect kernels
    try:
        kernels = subprocess.run(["pacman", "-Qq"], capture_output=True, text=True).stdout.splitlines()
        detected_kernels = {pkg for pkg in kernels if pkg.startswith("linux")}
        core_packages.update(detected_kernels)
    except:
        pass

    # Detect bootloaders
    bootloader_hints = ["grub", "limine", "syslinux", "efibootmgr"]
    try:
        pkgs = subprocess.run(["pacman", "-Qq"], capture_output=True, text=True).stdout.splitlines()
        detected_bootloaders = {pkg for pkg in pkgs if any(hint in pkg for hint in bootloader_hints)}
        core_packages.update(detected_bootloaders)
    except:
        pass
        
    return core_packages

def check_safeguards(apt_cmd, extra_args, is_simulation=False):
    
    # 1. Partial Upgrade Warning
    if apt_cmd == "install":
        # Check if there are pending upgrades
        check_upgrades = subprocess.run(["pacman", "-Qu"], capture_output=True, text=True)
        if check_upgrades.returncode == 0 and check_upgrades.stdout.strip():
            console.print("\n[bold yellow]WARNING: Partial upgrades are unsupported on Arch Linux.[/bold yellow]")
            console.print("You should run [bold]apt upgrade[/bold] before installing new packages.")
            if not console.input("Do you want to continue anyway? [y/N] ").lower().startswith('y'):
                sys.exit(0)

    # 2. Protected Packages
    if apt_cmd in ["remove", "purge"]:
        protected = get_protected_packages()
        for pkg in extra_args:
            if pkg in protected:
                console.print(f"\n[bold red]CRITICAL: You are trying to remove a core system package: {pkg}[/bold red]")
                console.print("Removing this package may render your system unbootable.")
                if console.input(f"To proceed, type: 'Yes, I know what I am doing': ") != "Yes, I know what I am doing":
                    print_info("Aborted.")
                    sys.exit(1)

    # 3. Large Removal Warning
    if apt_cmd in ["remove", "purge", "autoremove"] and not is_simulation:
        pacman_args = COMMAND_MAP[apt_cmd]
        if apt_cmd == "autoremove":
            check_orphans = subprocess.run(["pacman", "-Qdtq"], capture_output=True, text=True)
            if check_orphans.stdout.strip():
                orphans = check_orphans.stdout.split()
                print_cmd = ["pacman", "-Rns"] + orphans + ["--print"]
            else:
                return # No orphans, no removal
        else:
            print_cmd = ["pacman"] + pacman_args + extra_args + ["--print"]
            
        result = subprocess.run(print_cmd, capture_output=True, text=True)
        if result.returncode == 0:
            removed_pkgs = result.stdout.strip().split('\n')
            if len(removed_pkgs) > 20:
                console.print(f"\n[bold yellow]WARNING: You are about to remove {len(removed_pkgs)} packages.[/bold yellow]")
                if not console.input("Are you sure you want to continue? [y/N] ").lower().startswith('y'):
                    print_info("Aborted.")
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

def execute_command(apt_cmd, extra_args):
    if apt_cmd not in COMMAND_MAP:
        import difflib
        matches = difflib.get_close_matches(apt_cmd, COMMAND_MAP.keys(), n=1, cutoff=0.6)
        if matches:
            print_error(f"E: Invalid operation {apt_cmd}")
            console.print(f"[info]Did you mean:[/info] [bold white]{matches[0]}[/bold white]?")
        else:
            print_error(f"E: Invalid operation {apt_cmd}")
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
    
    # Apply config verbosity if not overridden
    config_verbosity = config.get("ui", "verbosity", 1)
    if quiet_level == 0 and not verbose:
        if config_verbosity == 0:
            quiet_level = 2
        elif config_verbosity >= 2:
            verbose = True
    
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
        print_info("Simulation mode enabled.")

    # Handle --fix-broken flag
    if "--fix-broken" in extra_args or "-f" in extra_args:
        extra_args = [a for a in extra_args if a not in ["--fix-broken", "-f"]]
        console.print("\n[bold blue]Reading package lists...[/bold blue]")
        console.print("[bold blue]Building dependency tree...[/bold blue]")
        console.print("[bold blue]Reading state information...[/bold blue]")
        console.print("[info]Correcting dependencies...[/info]\n")
        
        subprocess.run(["pacman", "-Dk"], check=False)
        console.print("[info]Attempting to resolve broken dependencies via system upgrade...[/info]")
        if os.getuid() == 0:
            subprocess.run(["pacman", "-Syu", "--noconfirm"], check=False)
            console.print("\n[green]Done[/green]")
        else:
            console.print("W: Run as root to attempt automatic fixes")
        return
    
    # Handle --no-install-recommends flag
    if "--no-install-recommends" in extra_args:
        extra_args = [a for a in extra_args if a != "--no-install-recommends"]
        if apt_cmd == "install":
            console.print("[info]Note: Pacman doesn't install optional dependencies by default[/info]")
    
    # Handle --only-upgrade flag
    only_upgrade = "--only-upgrade" in extra_args
    if only_upgrade:
        extra_args = [a for a in extra_args if a != "--only-upgrade"]
        if apt_cmd == "install":
            pkgs_to_upgrade = []
            for pkg in extra_args:
                check = subprocess.run(["pacman", "-Qq", pkg], capture_output=True)
                if check.returncode == 0:
                    pkgs_to_upgrade.append(pkg)
                else:
                    console.print(f"[info]Skipping {pkg} (not installed)[/info]")
            
            if not pkgs_to_upgrade:
                print_info("0 upgraded, 0 newly installed, 0 to remove and 0 not upgraded.")
                return
            
            extra_args = pkgs_to_upgrade

    pacman_args = COMMAND_MAP[apt_cmd]
    
    # Check safeguards before doing anything destructive
    if not is_simulation:
        check_safeguards(apt_cmd, extra_args)

    # Handle privilege check (Strict APT style)
    if apt_cmd in NEED_SUDO and os.getuid() != 0:
        if apt_cmd == "update":
            console.print(f"E: Could not open lock file /var/lib/pacman/db.lck - open (13: Permission denied)")
            console.print(f"E: Unable to lock directory /var/lib/pacman/")
        else:
            console.print(f"E: Could not open lock file /var/lib/pacman/db.lck - open (13: Permission denied)")
            console.print(f"E: Unable to lock the administration directory (/var/lib/pacman/), are you root?")
        sys.exit(100)

    # Handle apt list with all options
    if apt_cmd == "list":
        if "--upgradable" in extra_args:
            pacman_cmd = ["pacman", "-Qu"]
            extra_args = [a for a in extra_args if a != "--upgradable"]
        elif "--installed" in extra_args:
            pacman_cmd = ["pacman", "-Q"]
            extra_args = [a for a in extra_args if a != "--installed"]
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
        if any(a.endswith((".pkg.tar.zst", ".pkg.tar.xz")) for a in extra_args):
            pacman_cmd = ["pacman", "-U"] + extra_args
        else:
            # Check for AUR packages
            official_pkgs = []
            aur_pkgs = []
            
            for pkg in extra_args:
                if aur.is_in_official_repos(pkg):
                    official_pkgs.append(pkg)
                elif aur.search_aur(pkg): # Basic check if it exists in AUR
                    aur_pkgs.append(pkg)
                else:
                    # Unknown, assume official so pacman errors out properly or it's a provides
                    official_pkgs.append(pkg)
            
            if aur_pkgs:
                # If we have official packages, install them first
                if official_pkgs:
                    console.print(f"[bold]Installing official packages:[/bold] {' '.join(official_pkgs)}")
                    cmd = ["pacman", "-S"] + official_pkgs
                    if auto_confirm:
                        cmd.append("--noconfirm")
                    subprocess.run(cmd)
                
                # Then install AUR packages
                installer = aur.AurInstaller()
                try:
                    installer.install(aur_pkgs, verbose=verbose)
                except KeyboardInterrupt:
                    print_error("\nInterrupted.")
                    sys.exit(1)
                except Exception as e:
                    print_error(f"AUR Installation failed: {e}")
                    sys.exit(1)
                return # Exit after AUR install handling
            
            # If no AUR packages, just proceed with normal pacman -S
            pacman_cmd = ["pacman", "-S"] + extra_args
    elif apt_cmd == "depends":
        # Check if pactree is installed
        if subprocess.run(["command -v pactree"], shell=True, capture_output=True).returncode == 0:
            pacman_cmd = ["pactree", "-u"] + extra_args
        else:
            pacman_cmd = ["pacman", "-Qi"] + extra_args
    elif apt_cmd == "rdepends":
        if subprocess.run(["command -v pactree"], shell=True, capture_output=True).returncode == 0:
            pacman_cmd = ["pactree", "-ru"] + extra_args
        else:
            pacman_cmd = ["pacman", "-Sii"] + extra_args
    elif apt_cmd == "scripts":
        if subprocess.run(["command -v pacscripts"], shell=True, capture_output=True).returncode == 0:
            pacman_cmd = ["pacscripts"] + extra_args
        else:
            pacman_cmd = ["pacman", "-Qii"] + extra_args
    elif apt_cmd == "reinstall":
        pacman_cmd = ["pacman", "-S", "--force"] + extra_args
    elif apt_cmd == "autoclean":
        if subprocess.run(["command -v paccache"], shell=True, capture_output=True).returncode == 0:
            pacman_cmd = ["paccache", "-rk3"]
        else:
            pacman_cmd = ["pacman", "-Sc"]
    elif apt_cmd == "policy":
        # Simulate apt-cache policy: show installed version and repo version
        pkg = extra_args[0] if extra_args else ""
        if pkg:
            local = subprocess.run(["pacman", "-Qi", pkg], capture_output=True, text=True)
            remote = subprocess.run(["pacman", "-Si", pkg], capture_output=True, text=True)
            console.print(f"[bold]{pkg}:[/bold]")
            if local.returncode == 0:
                for line in local.stdout.splitlines():
                    if line.startswith("Version"):
                        console.print(f"  Installed: {line.split(':', 1)[1].strip()}")
            else:
                console.print("  Installed: (none)")
            
            if remote.returncode == 0:
                for line in remote.stdout.splitlines():
                    if line.startswith("Version"):
                        console.print(f"  Candidate: {line.split(':', 1)[1].strip()}")
            return
    elif apt_cmd == "apt-mark":
        if not extra_args:
            print_info("Usage: apt-mark [auto|manual|hold|unhold] [package]")
            return
        sub = extra_args[0]
        pkgs = extra_args[1:]
        if sub == "auto":
            pacman_cmd = ["pacman", "-D", "--asdeps"] + pkgs
        elif sub == "manual":
            pacman_cmd = ["pacman", "-D", "--asexplicit"] + pkgs
        elif sub == "hold":
            print_info("Note: Arch handles 'hold' via IgnorePkg in /etc/pacman.conf.")
            print_info("Consider adding these packages to IgnorePkg manually.")
            return
        else:
            print_info(f"Subcommand {sub} not yet implemented.")
            return
    elif apt_cmd == "check":
        console.print("\n[bold blue]Reading package lists...[/bold blue]")
        console.print("[bold blue]Building dependency tree...[/bold blue]")
        console.print("[bold blue]Reading state information...[/bold blue]\n")
        
        result_db = subprocess.run(["pacman", "-Dk"], capture_output=True, text=True)
        if result_db.returncode == 0:
            console.print("Database integrity: [green]OK[/green]")
        else:
            console.print(f"[error]E:[/error] Database errors:\n{result_db.stdout}")
        
        result_deps = subprocess.run(["pacman", "-Qk"], capture_output=True, text=True)
        dep_issues = [line for line in result_deps.stdout.splitlines() if "warning" in line.lower()]
        if dep_issues:
            console.print(f"\nW: {len(dep_issues)} package warnings found")
        else:
            console.print("All packages: [green]OK[/green]")
        
        if subprocess.run(["command", "-v", "lddd"], shell=True, capture_output=True).returncode == 0:
            try:
                result_lddd = subprocess.run(["lddd"], capture_output=True, text=True, check=False)
                if result_lddd.returncode == 0:
                    if result_lddd.stdout.strip():
                        console.print("\nW: Broken libraries detected")
                    else:
                        console.print("Library links: [green]OK[/green]")
            except (FileNotFoundError, OSError):
                # lddd not actually available, skip check silently
                pass
        return
    
    elif apt_cmd == "pkgnames":
        if extra_args:
            result = subprocess.run(["pacman", "-Slq"], capture_output=True, text=True)
            prefix = extra_args[0]
            filtered = [line for line in result.stdout.splitlines() if line.startswith(prefix)]
            for pkg in filtered:
                print(pkg)
        else:
            subprocess.run(["pacman", "-Slq"])
        return
    
    elif apt_cmd == "stats":
        console.print("\n[bold]Package Statistics:[/bold]\n")
        
        total_avail = subprocess.run(["pacman", "-Slq"], capture_output=True, text=True)
        num_avail = len(total_avail.stdout.splitlines())
        console.print(f"  Total packages:          [pkg]{num_avail}[/pkg]")
        
        total_installed = subprocess.run(["pacman", "-Qq"], capture_output=True, text=True)
        num_installed = len(total_installed.stdout.splitlines())
        console.print(f"  Installed packages:      [pkg]{num_installed}[/pkg]")
        
        explicit = subprocess.run(["pacman", "-Qeq"], capture_output=True, text=True)
        num_explicit = len(explicit.stdout.splitlines())
        console.print(f"  Explicitly installed:    [pkg]{num_explicit}[/pkg]")
        
        deps = subprocess.run(["pacman", "-Qdq"], capture_output=True, text=True)
        num_deps = len(deps.stdout.splitlines())
        console.print(f"  Installed as deps:       [pkg]{num_deps}[/pkg]")
        
        orphans = subprocess.run(["pacman", "-Qdtq"], capture_output=True, text=True)
        num_orphans = len(orphans.stdout.strip().splitlines()) if orphans.stdout.strip() else 0
        console.print(f"  Orphaned packages:       [pkg]{num_orphans}[/pkg]")
        
        updates = subprocess.run(["pacman", "-Qu"], capture_output=True, text=True)
        num_updates = len(updates.stdout.splitlines()) if updates.returncode == 0 else 0
        console.print(f"  Upgradable packages:     [pkg]{num_updates}[/pkg]")
        
        cache_path = "/var/cache/pacman/pkg"
        if os.path.exists(cache_path):
            cache_files = os.listdir(cache_path)
            num_cached = len([f for f in cache_files if f.endswith('.pkg.tar.zst') or f.endswith('.pkg.tar.xz')])
            console.print(f"\n  Cached package files:    [pkg]{num_cached}[/pkg]")
        return
    
    elif apt_cmd == "source":
        from .sources import handle_apt_source
        if not extra_args:
            print_error("E: No packages specified for source download")
            print_info("Usage: apt source <package>")
            sys.exit(1)
        package_name = extra_args[0]
        success = handle_apt_source(package_name, extra_args[1:], verbose=verbose)
        sys.exit(0 if success else 1)
    
    elif apt_cmd == "build-dep":
        from .sources import handle_build_dep
        if not extra_args:
            print_error("E: No package specified")
            print_info("Usage: apt build-dep <package>")
            sys.exit(1)
        package_name = extra_args[0]
        success = handle_build_dep(package_name, verbose=verbose)
        sys.exit(0 if success else 1)
    
    elif apt_cmd == "dotty":
        if not extra_args:
            print_error("E: No package specified")
            return
        
        if subprocess.run(["command", "-v", "pactree"], shell=True, capture_output=True).returncode == 0:
            pacman_cmd = ["pactree", "-g"] + extra_args
            subprocess.run(pacman_cmd)
        else:
            print_error("E: This command requires 'pacman-contrib' package")
            console.print("Install with: [command]sudo pacman -S pacman-contrib[/command]")
        return
    
    elif apt_cmd == "madison":
        if not extra_args:
            print_error("E: No package specified")
            return
        
        pkg = extra_args[0]
        console.print(f"[bold]{pkg}:[/bold]")
        
        # Show installed version
        local = subprocess.run(["pacman", "-Qi", pkg], capture_output=True, text=True)
        if local.returncode == 0:
            for line in local.stdout.splitlines():
                if line.startswith("Version"):
                    version = line.split(':', 1)[1].strip()
                    console.print(f"  {version} | Installed")
        
        # Show repo version
        remote = subprocess.run(["pacman", "-Si", pkg], capture_output=True, text=True)
        if remote.returncode == 0:
            for line in remote.stdout.splitlines():
                if line.startswith("Repository"):
                    repo = line.split(':', 1)[1].strip()
                if line.startswith("Version"):
                    version = line.split(':', 1)[1].strip()
                    console.print(f"  {version} | {repo}")
        return
    
    elif apt_cmd == "config":
        console.print("\n[bold]Pacman Configuration:[/bold]\n")
        try:
            with open("/etc/pacman.conf", "r") as f:
                content = f.read()
                # Show in a panel
                from rich.panel import Panel
                console.print(Panel(content, title="/etc/pacman.conf", border_style="blue"))
        except FileNotFoundError:
            print_error("E: Cannot read /etc/pacman.conf")
        except PermissionError:
            print_error("E: Permission denied reading /etc/pacman.conf")
        return
    
    elif apt_cmd == "apt-key":
        if not extra_args:
            console.print("\n[bold]Usage:[/bold] apt-key [add|list|del|adv] ...\n")
            console.print("[bold]Examples:[/bold]")
            console.print("  apt-key add <keyfile>     - Import GPG key")
            console.print("  apt-key list              - List all keys")
            console.print("  apt-key del <keyid>       - Remove key\n")
            console.print("[info]Note: This is a wrapper for pacman-key[/info]")
            return
        
        sub = extra_args[0]
        if sub == "add":
            if len(extra_args) < 2:
                print_error("E: No keyfile specified")
                return
            pacman_cmd = ["pacman-key", "--add"] + extra_args[1:]
        elif sub == "list":
            pacman_cmd = ["pacman-key", "--list-keys"]
        elif sub in ["del", "delete", "remove"]:
            if len(extra_args) < 2:
                print_error("E: No key ID specified")
                return
            pacman_cmd = ["pacman-key", "--delete"] + extra_args[1:]
        elif sub == "adv":
            # Pass through to gpg
            pacman_cmd = ["pacman-key"] + extra_args
        else:
            print_error(f"E: Unknown apt-key command: {sub}")
            return
        
        subprocess.run(pacman_cmd)
        return
    
    elif apt_cmd == "add-repository":
        console.print("\n[info]Arch Linux manages repositories via /etc/pacman.conf[/info]\n")
        console.print("[bold]To add a repository:[/bold]")
        console.print("  1. Edit configuration: [command]sudo apt edit-sources[/command]")
        console.print("  2. Add repository section:")
        console.print("     [desc][repository-name][/desc]")
        console.print("     [desc]Server = <mirror-url>[/desc]")
        console.print("  3. Update: [command]sudo apt update[/command]\n")
        console.print("[bold]Popular third-party repos:[/bold]")
        console.print("  - [link]https://wiki.archlinux.org/title/Unofficial_user_repositories[/link]\n")
        console.print("[italic grey70]Note: Arch does not use PPAs like Ubuntu[/italic grey70]")
        return
    
    elif apt_cmd == "showsrc":
        from .sources import handle_showsrc
        if not extra_args:
            print_error("E: No package specified")
            print_info("Usage: apt-cache showsrc <package>")
            sys.exit(1)
        package_name = extra_args[0]
        success = handle_showsrc(package_name, verbose=verbose)
        sys.exit(0 if success else 1)
    
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
            check_orphans = subprocess.run(["pacman", "-Qdtq"], capture_output=True, text=True)
            if not check_orphans.stdout.strip():
                print_info("No orphaned packages to remove.")
                return
            orphans = check_orphans.stdout.split()
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
        if "--aur" in extra_args:
            scope = "aur"
            extra_args = [a for a in extra_args if a != "--aur"]
        elif "--official" in extra_args:
            scope = "official"
            extra_args = [a for a in extra_args if a != "--official"]
            
        pacman_cmd = ["pacman"] + pacman_args + extra_args

        # Official Search
        if scope in ["both", "official"] and apt_cmd == "search":
             result = subprocess.run(pacman_cmd, capture_output=True, text=True)
             if result.returncode == 0 and result.stdout.strip():
                 if show_output in ["apt-pac", "apt"]:
                     format_search_results(result.stdout)
                 else:
                     print(result.stdout, end="")
        
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
             # 1. Try Official Repos (pacman -Si)
             result = subprocess.run(pacman_cmd, capture_output=True, text=True)
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
                 result_local = subprocess.run(local_cmd, capture_output=True, text=True)
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
                 print_error(f"Package '{' '.join(extra_args)}' not found in repositories, local database, or AUR.")

        return

    # Show summary for install/upgrade (unless auto-confirmed or quiet)
    if apt_cmd in ["install", "upgrade", "dist-upgrade", "full-upgrade"]:
        if not auto_confirm and quiet_level == 0:
            show_summary(apt_cmd, extra_args)
    
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
    
    try:
        # Use --noconfirm if we already asked
        current_cmd = list(pacman_cmd)
        if apt_cmd in ["install", "upgrade", "dist-upgrade", "full-upgrade"]:
            current_cmd.append("--noconfirm")
        
        # Special case for update and upgrade: sync files as well
        if apt_cmd == "update":
            with console.status("[bold blue]Updating package databases...", spinner="dots"):
                # Run the main pacman -Sy
                current_cmd = list(pacman_cmd)
                subprocess.run(current_cmd, check=True, capture_output=True)
                
                # Run the file sync pacman -Fy
                sync_cmd = ["pacman", "-Fy"]
                subprocess.run(sync_cmd, check=False, capture_output=True)
                
            console.print("Reading package lists... [green]Done[/green]")
            return # Exit early as we've handled everything for update
        
        elif apt_cmd in ["upgrade", "dist-upgrade", "full-upgrade"]:
            # For upgrades, also sync file database after upgrading packages
            # This is done in the background to not block the main upgrade
            subprocess.run(current_cmd)  # Run the upgrade (with user interaction)
            
            # Sync file database in background (silent)
            console.print("\nSyncing file database...")
            subprocess.run(["pacman", "-Fy"], check=False, capture_output=True)
            console.print("File database: [green]Done[/green]")
            return

            
    except subprocess.CalledProcessError:
        sys.exit(1)
