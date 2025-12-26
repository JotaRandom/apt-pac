import subprocess
import sys
import os
from .ui import print_info, print_command, print_error, console, format_search_results, format_show, show_help

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
    
    # Check for simulation flag
    is_simulation = "-s" in extra_args or "--simulate" in extra_args or "--dry-run" in extra_args
    if is_simulation:
        # Remove the flag from extra_args so it doesn't confuse pacman if it doesn't support it
        extra_args = [a for a in extra_args if a not in ["-s", "--simulate", "--dry-run"]]
        print_info("Simulation mode enabled.")

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

    # Handle list --upgradable
    if apt_cmd == "list" and "--upgradable" in extra_args:
        pacman_cmd = ["pacman", "-Qu"]
        # Filter out --upgradable
        extra_args = [a for a in extra_args if a != "--upgradable"]
    elif apt_cmd == "install":
        # Check if we are installing a local file
        if any(a.endswith((".pkg.tar.zst", ".pkg.tar.xz")) for a in extra_args):
            pacman_cmd = ["pacman", "-U"] + extra_args
        else:
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
        pacman_cmd = ["pacman", "-S", "--force"] + extra_args # Or just -S --needed if re-installing
    elif apt_cmd == "list" and any(a.startswith("--repo") for a in extra_args):
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
    elif apt_cmd == "edit-sources":
        editor = get_editor()
        cmd = [editor, "/etc/pacman.conf"]
        print_command(f"Running: {' '.join(cmd)}")
        try:
            subprocess.run(cmd, check=True)
            return
        except subprocess.CalledProcessError:
            sys.exit(1)

    # Handle autoremove specifically
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
        result = subprocess.run(pacman_cmd, capture_output=True, text=True)
        if result.returncode == 0:
            if apt_cmd == "search":
                format_search_results(result.stdout)
            else:
                format_show(result.stdout)
        else:
            print_error(result.stderr)
        return

    # Show summary for install/upgrade
    if apt_cmd in ["install", "upgrade", "dist-upgrade", "full-upgrade"]:
        show_summary(apt_cmd, extra_args)

    print_command(f"Running: {' '.join(pacman_cmd)}")
    
    try:
        # Use --noconfirm if we already asked
        current_cmd = list(pacman_cmd)
        if apt_cmd in ["install", "upgrade", "dist-upgrade", "full-upgrade"]:
            current_cmd.append("--noconfirm")
        
        # Special case for update: sync files as well
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
            
    except subprocess.CalledProcessError:
        sys.exit(1)
