import codecs
import errno
import select
import subprocess
import sys
import shutil
import os
import re

_ORIGINAL_POPEN = subprocess.Popen
from pathlib import Path
import urllib.request
import xml.etree.ElementTree as ET
import html
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from rich.markup import escape
from rich.measure import Measurement
from .i18n import _
from . import ui
from .ui import (
    console,
    print_error,
    print_info,
    print_command,
    print_success,
    print_apt_download_line,
    format_show,
    format_search_results,
    print_columnar_list,
    format_aur_search_results,
    print_transaction_summary,
    print_reading_status,
)
from .config import get_config
from . import aur
from . import alpm_helper
from rich.console import Console, ConsoleOptions, RenderResult
from rich.text import Text
from rich.table import Table, Column
from rich.padding import Padding
from rich import box
from rich.panel import Panel
from rich.progress import (
    Progress,
    TextColumn,
    ProgressColumn,
    Task,
)


def run_pacman(cmd, **kwargs):
    """
    Wrapper for subprocess.run that forces LC_ALL=C for consistent English output.
    Use this instead of subprocess.run when calling pacman to avoid locale issues.
    """
    env = kwargs.get("env", os.environ.copy())
    env["LC_ALL"] = "C"
    kwargs["env"] = env
    return subprocess.run(cmd, **kwargs)


def _confirm_yes(prompt) -> bool:
    """Confirm a [Y/n] prompt accepting Enter (empty string) as Yes."""
    try:
        resp = console.input(prompt)
    except (EOFError, KeyboardInterrupt):
        console.print()
        return False
    if isinstance(resp, str):
        ans = resp.strip().lower()
        return ans == "" or ans.startswith("y")
    return bool(resp)


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
    "depends": ["-Qi"],  # Fallback
    "rdepends": ["-Qi"],  # Fallback
    "scripts": ["-Qii"],  # Fallback
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
    "news": ["news"],  # Show Arch Linux news
    # Easter Eggs
    "moo": [],
    "pacman": [],
}

NEED_SUDO = {
    "update",
    "upgrade",
    "dist-upgrade",
    "full-upgrade",
    "install",
    "reinstall",
    "remove",
    "purge",
    "autoremove",
    "clean",
    "autoclean",
    "edit-sources",
    "apt-mark",
    "download",
}


def parse_pacman_size(size_str):
    """Parse '22.27 MiB' style strings to bytes."""
    if not size_str or size_str.strip() in ["N/A", ""]:
        return 0

    parts = size_str.strip().split()
    if len(parts) != 2:
        return 0

    try:
        value = float(parts[0])
        unit = parts[1]

        if unit == "B":
            return int(value)
        elif unit == "KiB":
            return int(value * 1024)
        elif unit == "MiB":
            return int(value * 1024 * 1024)
        elif unit == "GiB":
            return int(value * 1024 * 1024 * 1024)
        elif unit == "TiB":
            return int(value * 1024 * 1024 * 1024 * 1024)
        else:
            return 0
    except (ValueError, IndexError):
        return 0


def fmt_adaptive_size(bytes_val):
    # 1 MB = 1,000,000 Bytes (Decimal)
    mb_val = bytes_val / 1000000.0

    if mb_val < 0.1:  # Less than 100 kB -> Show Bytes
        return f"{int(bytes_val)} B"
    elif mb_val > 10000:  # Greater than 10,000 MB (10 GB) -> Show GB
        gb_val = mb_val / 1000.0
        return f"{gb_val:.1f} GB"
    else:
        return f"{mb_val:.1f} MB"


def show_summary(
    apt_cmd,
    extra_args,
    auto_confirm=False,
    aur_new=None,
    aur_upgrades=None,
    skip_official=False,
):
    """
    Show APT-style installation summary with accurate package sizes using pacman dry-run.
    Returns True if there are packages to process and the user confirmed, False if nothing to do.
    """
    import urllib.parse

    clean_names = []
    pkg_versions = {}  # name -> new_version
    installed_map = {}  # name -> old_version (if known)

    # Initialize outcome variables
    new_pkgs = []
    upgraded_pkgs = []
    total_dl_size = 0
    total_inst_size_change = 0

    non_flag_args = [arg for arg in extra_args if not arg.startswith("-")]

    if skip_official:
        pass
    elif apt_cmd in ["upgrade", "dist-upgrade", "full-upgrade"] and not non_flag_args:
        # Check for upgrades using pyalpm
        updates = alpm_helper.get_available_updates()
        for name, old_ver, new_ver in updates:
            clean_names.append(name)
            pkg_versions[name] = new_ver
            installed_map[name] = old_ver

    else:
        base_sim = ["pacman", "-Sp"]
        cmd = base_sim + extra_args
        result = run_pacman(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            return None

        urls = [line.strip() for line in result.stdout.splitlines() if "://" in line]

        for url in urls:
            filename = urllib.parse.urlparse(url).path.split("/")[-1]
            base = filename
            for ext in [
                ".pkg.tar.zst",
                ".pkg.tar.xz",
                ".pkg.tar.gz",
                ".pkg.tar.bz2",
                ".pkg.tar.lzo",
                ".pkg.tar.lz4",
                ".pkg.tar",
            ]:
                if base.endswith(ext):
                    base = base[: -len(ext)]
                    break

            parts = base.split("-")
            if len(parts) >= 4:
                name = "-".join(parts[:-3])
                ver_rel = f"{parts[-3]}-{parts[-2]}"
                clean_names.append(name)
                pkg_versions[name] = ver_rel
            else:
                clean_names.append(base)
                pkg_versions[base] = "?"

    # Batch query -Si for all
    # To properly separate NEW vs UPGRADE, we need to check -Qi.
    installed_size_map = {}  # To store current installed sizes for diff calculation
    visible_suggestions = set()

    if clean_names:
        # Check installed status and get current versions/sizes
        # Optimized: Use pyalpm instead of pacman -Q
        installed_set = set()
        for name in clean_names:
            pkg = alpm_helper.get_local_package(name)
            if pkg:
                installed_set.add(name)
                installed_map[name] = pkg.version

        # Get installed sizes for packages that are currently installed
        # Get installed sizes for packages that are currently installed
        if installed_set:
            # Optimized: Use pyalpm instead of pacman -Qi
            for name in list(installed_set):
                pkg = alpm_helper.get_local_package(name)
                if pkg:
                    installed_size_map[name] = pkg.isize

        # Calculate sizes and suggestions using pyalpm
        # Note: -Si might fail for local packages not in repo?
        # But 'pacman -Sp' returned them, so they must be downloadables (repo packages).
        pkg_sizes = {}
        new_optdeps_map = {}  # pkg -> set(optdeps_names)

        # Batch lookup for remote packages?
        # pyalpm doesn't have batch lookup, but get_package is fast because it searches in-memory DB references.
        for name in clean_names:
            pkg = alpm_helper.get_package(name)
            if pkg:
                pkg_sizes[name] = (pkg.download_size, pkg.isize)
                if pkg.optdepends:
                    new_optdeps_map[name] = set()
                    for dep_str in pkg.optdepends:
                        # Format is "pkgname: description" or just "pkgname"
                        if ":" in dep_str:
                            dname = dep_str.split(":")[0].strip()
                            new_optdeps_map[name].add(dname)
                        else:
                            new_optdeps_map[name].add(dep_str.strip())

        # Now iterate clean_names to build lists and calculating diffs for suggestions
        # We need old optdeps for upgraded packages
        old_optdeps_map = {}

        # Optimized: Use pyalpm to get old optdeps
        if installed_set:
            for name in installed_set:
                pkg = alpm_helper.get_local_package(name)
                if pkg and pkg.optdepends:
                    old_optdeps_map[name] = set()
                    for dep_str in pkg.optdepends:
                        # Format is "pkgname: description" or just "pkgname"
                        if ":" in dep_str:
                            dname = dep_str.split(":")[0].strip()
                            old_optdeps_map[name].add(dname)
                        else:
                            old_optdeps_map[name].add(dep_str.strip())

        for name in clean_names:
            dl, inst = pkg_sizes.get(name, (0, 0))
            total_dl_size += dl

            # Logic for Suggestions
            new_opts = new_optdeps_map.get(name, set())

            if name in installed_set:
                ver = pkg_versions.get(name, "")
                old_ver = installed_map.get(name, "")
                upgraded_pkgs.append(
                    (name, old_ver, ver)
                )  # (name, old_version, new_version)

                old_size = installed_size_map.get(name, 0)
                total_inst_size_change += inst - old_size

                # Smart Suggestion Trigger: Upgrading
                # Only show NEW suggestions
                old_opts = old_optdeps_map.get(name, set())
                diff_opts = new_opts - old_opts
                visible_suggestions.update(diff_opts)

            else:
                ver = pkg_versions.get(name, "")
                new_pkgs.append((name, ver))  # (name, new_version)
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
        console.print(
            _("0 upgraded, 0 newly installed, 0 to remove and 0 not upgraded.")
        )
        return False

    print_reading_status()

    # Identify explicit names from extra_args (excluding flags)
    explicit_names = {arg for arg in extra_args if not arg.startswith("-")}

    # Use shared UI helper
    print_transaction_summary(
        new_pkgs=new_pkgs, upgraded_pkgs=upgraded_pkgs, explicit_names=explicit_names
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
        already_installed = set()
        for sug in sorted_sug:
            if alpm_helper.is_package_installed(sug):
                already_installed.add(sug)

        final_suggestions = []
        for sug in sorted_sug:
            safe_sug = escape(sug)
            if sug in already_installed:
                final_suggestions.append(
                    f"{safe_sug} [dim]\\[{_('installed')}][/dim]"
                )
            else:
                # Check if it is being installed in this transaction?
                # If it is in new_pkgs names, it will be installed.
                # Usually suggestions are for things NOT being installed.
                # But if user requested it specifically?
                # Let's just print it as is (clean).
                final_suggestions.append(safe_sug)

        if final_suggestions:
            console.print(f"{_('Suggested packages:')}")
            print_columnar_list(final_suggestions, "default")

    # Show Orphans / No longer required
    orphan_pkgs = alpm_helper.get_orphan_packages()
    if orphan_pkgs:
        orphans = [pkg.name for pkg in orphan_pkgs]
        console.print(
            f"\n[bold]{_('The following packages are no longer required:')}[/bold]"
        )
        print_columnar_list(orphans, "dim")
        console.print(
            f"{_('Use')} [bold]apt-pac autoremove[/bold] {_('to remove them.')}"
        )

    # APT 3.1 Summary Style
    # Upgrading: 0, Installing: 129, Removals: 0, Not Upgrading: 0
    # Download Size: 87.3 MB
    # Installed size: 319.6 MB

    removals_count = 0  # In install mode usually 0 unless conflict resolution?
    # We didn't parse removals from -Sp, only adds. -Sp doesn't show removals easily (unless -Ru?).

    # Format counts with bold if > 0
    upgraded_str = f"[bold]{len(upgraded_pkgs)}[/bold]" if upgraded_pkgs else "0"
    installing_str = f"[bold]{len(new_pkgs)}[/bold]" if new_pkgs else "0"
    removals_str = f"[bold]{removals_count}[/bold]" if removals_count > 0 else "0"

    summary_line = f"[bold]{_('Summary:')}[/bold]\n   {_('Upgrading:')} {upgraded_str}, {_('Installing:')} {installing_str}, {_('Removals:')} {removals_str}, {_('Not Upgrading:')} 0"
    console.print(summary_line, highlight=False)

    # Format sizes (Decimal MB)
    # Format sizes (Adaptive: <0.1MB -> B, >10GB -> GB)
    dl_suffix = ""
    inst_suffix = ""

    has_aur = bool(aur_new or aur_upgrades)

    if has_aur:
        dl_suffix = " (+ AUR)"
        inst_suffix = " (+ AUR)"

        # If total sizes are 0 but we have AUR, show "Unknown" instead of 0 B
        if total_dl_size == 0:
            dl_str = f"{_('Unknown')} (AUR)"
            dl_suffix = ""  # Reset suffix as we incorporated it
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

    console.print(f"   {_('Download Size:')} {dl_str}{dl_suffix}", highlight=False)
    if show_freed:
        console.print(
            f"   {_('Freed Space:')} {inst_str}{inst_suffix}", highlight=False
        )
    else:
        console.print(
            f"   {_('Installed Size:')} {inst_str}{inst_suffix}", highlight=False
        )

    # Check Disk Space
    warnings = []

    # 1. Check Root (Install Size)
    # Only if we are growing
    if total_inst_size_change > 0:
        try:
            slash_usage = shutil.disk_usage("/")
            if total_inst_size_change > slash_usage.free:
                warnings.append(
                    {
                        "path": "/",
                        "needed": total_inst_size_change,
                        "avail": slash_usage.free,
                    }
                )
        except Exception:
            pass

    # 2. Check Cache (Download Size)
    cache_path = "/var/cache/pacman/pkg"
    try:
        cache_dirs = alpm_helper.get_cache_dirs()
        if isinstance(cache_dirs, (list, tuple)) and cache_dirs:
            cache_path = str(cache_dirs[0])
    except Exception:
        pass
    if not os.path.exists(cache_path):
        cache_path = "/var"

    if total_dl_size > 0:
        try:
            cache_usage = shutil.disk_usage(cache_path)
            if total_dl_size > cache_usage.free:
                warnings.append(
                    {
                        "path": cache_path,
                        "needed": total_dl_size,
                        "avail": cache_usage.free,
                    }
                )
        except Exception:
            pass

    prompt_msg = f"\n{_('Continue?')} [Y/n] "

    if warnings:
        for w in warnings:
            needed_str = fmt_adaptive_size(w["needed"])
            avail_str = fmt_adaptive_size(w["avail"])
            console.print(
                f"{_('Space needed:')} {needed_str} / {avail_str} {_('available')}",
                highlight=False,
            )
            console.print(
                f"[bold red]W: {_('More space needed in')} {w['path']} {_('than available')}: {needed_str} > {avail_str}[/bold red]",
                highlight=False,
            )

        prompt_msg = (
            f"\n[bold red]{_('Installation may fail, Continue?')} [Y/n] [/bold red]"
        )

    if auto_confirm:
        console.print(prompt_msg + "[bold green]Yes[/bold green]")
    else:
        if not _confirm_yes(prompt_msg):
            print_info(_("Aborted."))
            sys.exit(0)

    return True


def get_protected_packages():
    """Dynamically detects installed kernels, bootloaders, and HoldPkg to protect them."""
    core_packages = {"pacman", "glibc", "systemd", "base", "sudo", "doas", "run0"}
    kernels = []

    try:
        hold_pkgs = alpm_helper._pacman_conf("HoldPkg")
        if isinstance(hold_pkgs, list):
            for line in hold_pkgs:
                core_packages.update(line.split())
    except Exception:
        pass

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
        detected_bootloaders = {
            pkg for pkg in kernels if any(hint in pkg for hint in bootloader_hints)
        }
        core_packages.update(detected_bootloaders)
    except Exception:
        pass

    return core_packages


def check_safeguards(apt_cmd, extra_args, is_simulation=False, auto_confirm=False):
    # 2. Protected Packages
    if apt_cmd in ["remove", "purge"]:
        protected = get_protected_packages()
        for pkg in extra_args:
            if pkg in protected:
                console.print(
                    f"\n[bold red]E:[/bold red] {_('You are trying to remove a core system package:')} [bold]{escape(pkg)}[/bold]",
                    highlight=False,
                )
                console.print(
                    _("Removing this package may render your system unbootable.")
                )
                required_phrase = _("Yes, I know what I am doing")
                try:
                    phrase_input = console.input(
                        f"{_('To proceed, type')} '{escape(required_phrase)}': "
                    )
                except (EOFError, KeyboardInterrupt):
                    console.print()
                    print_info(_("Aborted."))
                    sys.exit(1)
                if phrase_input != required_phrase:
                    print_info(_("Aborted."))
                    sys.exit(1)

    # 3. Large Removal Warning & Autoremove Summary
    if apt_cmd in ["remove", "purge", "autoremove"] and not is_simulation:
        pacman_args = list(COMMAND_MAP[apt_cmd])

        # Remove --nosave/-n from args for print simulation because it conflicts with --print
        pacman_args = [a for a in pacman_args if a not in ["-n", "--nosave"]]
        for i, arg in enumerate(pacman_args):
            if arg.startswith("-") and "n" in arg and "R" in arg:
                pacman_args[i] = arg.replace("n", "")

        if apt_cmd == "autoremove":
            orphan_pkgs = alpm_helper.get_orphan_packages()
            if orphan_pkgs:
                orphans = [pkg.name for pkg in orphan_pkgs]
                print_cmd = ["pacman", "-Rs"] + orphans + ["--print"]
            else:
                return  # No orphans, no removal
        else:
            targets = [a for a in extra_args if not a.startswith("-")]
            if not targets:
                print_error(f"[bold red]{_('E')}[/bold red]: {_('No package specified')}")
                sys.exit(1)
            print_cmd = ["pacman"] + pacman_args + extra_args + ["--print"]

        print_reading_status()

        try:
            env = os.environ.copy()
            env["LC_ALL"] = "C"
            result = subprocess.run(
                print_cmd, capture_output=True, text=True, check=True, env=env
            )
            lines = [x.strip() for x in result.stdout.strip().splitlines() if x.strip()]

            if lines:
                remove_pkgs_info = []
                for line in lines:
                    parts = line.split()
                    m = re.match(r"^(.*)-([^-]+-[^-]+)$", line)

                    if len(parts) >= 2:
                        remove_pkgs_info.append((parts[0], parts[1]))
                    elif m:
                        remove_pkgs_info.append((m.group(1), m.group(2)))
                    else:
                        remove_pkgs_info.append((line, ""))

                print_transaction_summary(remove_pkgs=remove_pkgs_info)

                # Check for mass removal
                config = get_config()
                threshold = config.get("safeguards", "mass_removal_threshold", 20)
                count = len(remove_pkgs_info)

                if count >= threshold:
                    console.print(
                        f"\n[yellow]{_('W:')}[/yellow] {_('You are about to remove')} [bold]{count}[/bold] {_('packages')} (Threshold: {threshold}).",
                        highlight=False,
                    )
                    if not auto_confirm and not _confirm_yes(
                        f"{_('Are you sure you want to proceed?')} [Y/n] "
                    ):
                        print_info(_("Aborted."))
                        sys.exit(0)

                # Standard confirmation
                if not auto_confirm and not _confirm_yes(
                    f"\n{_('Do you want to continue?')} [Y/n] "
                ):
                    print_info(_("Aborted."))
                    sys.exit(0)

        except subprocess.CalledProcessError as e:
            print_error(
                f"[red]{_('E:')}[/red] {_('Failed to calculate removal summary: ')}{escape(e.stderr if e.stderr else str(e))}"
            )
            sys.exit(1)


def get_editor():
    """Detects available editor in order: config, $EDITOR, $VISUAL, nano, vim, vi."""
    config = get_config()
    editor = (
        config.get("tools", "editor", "")
        or os.environ.get("EDITOR")
        or os.environ.get("VISUAL")
    )
    if editor:
        return editor
    for cmd in ["nano", "vim", "vi", "micro"]:
        if shutil.which(cmd):
            return cmd
    return "vi"  # Ultimate fallback as it's likely in base


def get_short_url(url):
    import urllib.parse

    parsed = urllib.parse.urlparse(url)
    short_url = f"{parsed.scheme}://{parsed.netloc}/"
    if not short_url.endswith("/"):
        short_url += "/"
    return short_url


def sync_databases(cmd=None, quiet=0, include_aur=True):
    """
    Runs pacman -Sy (or similar) with APT-like progress output (Hit/Get).
    """
    if cmd is None:
        cmd = ["pacman", "-Sy"]

    # 1. Map repo names to URLs using pacman-conf
    repo_url_map = {}  # repo -> short_url

    try:
        repo_list_result = subprocess.run(
            ["pacman-conf", "-l"], capture_output=True, text=True
        )
        if repo_list_result.returncode == 0:
            repos = repo_list_result.stdout.strip().splitlines()
            for repo in repos:
                repo_conf_result = subprocess.run(
                    ["pacman-conf", "-r", repo], capture_output=True, text=True
                )
                if repo_conf_result.returncode == 0:
                    for line in repo_conf_result.stdout.splitlines():
                        if line.strip().startswith("Server ="):
                            url = line.split("=", 1)[1].strip()
                            if url:
                                repo_url_map[repo] = get_short_url(url)
                                break
    except Exception:
        pass  # Fallback to basic output if pacman-conf fails

    env = os.environ.copy()
    env["LC_ALL"] = "C"

    ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
    db_dl_re = re.compile(
        r"^\s*([A-Za-z0-9._+-]+?)(?:\.(?:db|files))?\s+[\d.,]+\s+[KMG]?i?B.*%\s*$",
        re.I,
    )

    show_connecting = quiet == 0 and bool(getattr(console, "is_terminal", False))
    cleared_connecting = False

    def _clear_connecting():
        nonlocal cleared_connecting
        if show_connecting and not cleared_connecting:
            cleared_connecting = True
            try:
                clear_len = min(ui.get_terminal_width(console), 40)
                console.file.write("\r" + (" " * clear_len) + "\r")
                console.file.flush()
            except Exception:
                pass

    try:
        if show_connecting:
            console.print(f"0% \\[{_('Connecting...')}]", end="\r", highlight=False)

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )

        index = 1
        seen_repos = set()

        for line in iter(process.stdout.readline, ""):
            if not line:
                break

            line_clean = ansi_escape.sub("", line).strip()
            if not line_clean:
                continue

            lower_line = line_clean.lower()

            if "synchronizing package databases" in lower_line:
                continue

            if lower_line.startswith(("error:", ":: error")) or (
                "failed to" in lower_line and "synchroniz" in lower_line
            ):
                _clear_connecting()
                msg = re.sub(r"^(?::: )?error:\s*", "", line_clean, count=1, flags=re.I)
                console.print(
                    f"[bold red]{_('E:')}[/bold red] {escape(msg)}",
                    highlight=False,
                )
                continue

            if lower_line.startswith(("warning:", ":: warning")):
                _clear_connecting()
                msg = re.sub(
                    r"^(?::: )?warning:\s*", "", line_clean, count=1, flags=re.I
                )
                console.print(
                    f"[bold yellow]{_('W:')}[/bold yellow] {escape(msg)}",
                    highlight=False,
                )
                continue

            if "is up to date" in lower_line:
                repo = line_clean.split(" is up to date")[0].strip()
                if "::" in repo:
                    repo = repo.split("::")[-1].strip()
                if repo in seen_repos:
                    continue
                seen_repos.add(repo)

                url = repo_url_map.get(repo, repo).rstrip("/")
                _clear_connecting()
                if quiet < 2:
                    console.print(
                        f"[bold cyan]Hit:[/bold cyan]{index} [blue]{escape(url)}[/blue] [bold blue]{escape(repo)}[/bold blue]",
                        highlight=False,
                    )
                index += 1
                continue

            repo = ""
            is_dl = "downloading" in lower_line
            dl_match = db_dl_re.match(line_clean)
            if dl_match and dl_match.group(1).lower() != "total":
                candidate = dl_match.group(1)
                if not repo_url_map or candidate in repo_url_map or (
                    ".db" in lower_line or ".files" in lower_line
                ):
                    repo = candidate
                    is_dl = True

            if is_dl:
                if not repo:
                    parts = line_clean.split()
                    try:
                        idx = next(
                            (i for i, p in enumerate(parts) if "downloading" in p.lower()),
                            -1,
                        )
                        if idx != -1:
                            if idx + 1 < len(parts) and "..." not in parts[idx + 1]:
                                repo = (
                                    parts[idx + 1]
                                    .replace("...", "")
                                    .replace(".db", "")
                                    .replace(".files", "")
                                )
                            if not repo and idx - 1 >= 0 and parts[idx - 1] != "::":
                                repo = (
                                    parts[idx - 1]
                                    .replace("...", "")
                                    .replace(".db", "")
                                    .replace(".files", "")
                                )
                    except Exception:
                        pass

                if not repo and repo_url_map:
                    for r in repo_url_map:
                        if r in line_clean:
                            repo = r
                            break

                if repo:
                    if repo in seen_repos:
                        continue
                    seen_repos.add(repo)

                    url = repo_url_map.get(repo, repo).rstrip("/")
                    action = "Hit" if url.startswith("file://") else "Get"
                    _clear_connecting()
                    if quiet < 2:
                        console.print(
                            f"[bold cyan]{action}:[/bold cyan]{index} [blue]{escape(url)}[/blue] [bold blue]{escape(repo)}[/bold blue]",
                            highlight=False,
                        )
                    index += 1
                else:
                    _clear_connecting()
                    if quiet < 2:
                        console.print(f"[dim]{escape(line_clean)}[/dim]", highlight=False)
                continue

            if "downloading " in lower_line or dl_match:
                continue

            _clear_connecting()
            if quiet < 2:
                console.print(f"[dim]{escape(line_clean)}[/dim]", highlight=False)

        process.wait()
        _clear_connecting()

        if process.returncode != 0:
            print_error(_("Failed to synchronize databases"))
            sys.exit(1)

        if include_aur and quiet < 2:
            try:
                console.print(
                    f"[bold cyan]Get:[/bold cyan]{index} [blue]https://aur.archlinux.org[/blue] [bold blue]AUR[/bold blue]",
                    highlight=False,
                )
            except Exception:
                pass

        alpm_helper.reset_handle()

    except subprocess.CalledProcessError:
        _clear_connecting()
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
            return 0  # Fail silently on simulation

        lines = result.stdout.strip().splitlines()
        urls = [line.strip() for line in lines if "://" in line]

        if not urls:
            return 0

        # 1. Parse Names from Filenames
        # Filename format: name-version-release-arch.pkg.tar.zst
        # We need 'name' to query repo/version/download size via pyalpm
        names_to_query = set()

        url_info = []

        for url in urls:
            parsed = urllib.parse.urlparse(url)
            filename = parsed.path.split("/")[-1]

            # Shorten URL to scheme://netloc/
            short_url = f"{parsed.scheme}://{parsed.netloc}/"
            if parsed.scheme == "file":
                short_url = f"[{_('in cache')}]"

            if not short_url.endswith("/") and parsed.scheme != "file":
                short_url += "/"

            # Parse filename
            # Heuristic: strip known extensions, then reverse split
            base = filename
            for ext in [
                ".pkg.tar.zst",
                ".pkg.tar.xz",
                ".pkg.tar.gz",
                ".pkg.tar.bz2",
                ".pkg.tar.lzo",
                ".pkg.tar.lz4",
                ".pkg.tar",
                ".pkg.tar.zst.sig",
            ]:
                if base.endswith(ext):
                    base = base[: -len(ext)]
                    break

            # base is now "name-ver-rel-arch"
            parts = base.split("-")
            pkg_name = base  # fallback
            ver_fallback = ""

            if len(parts) >= 4:
                pkg_name = "-".join(parts[:-3])
                ver_fallback = f"{parts[-3]}-{parts[-2]}"
                names_to_query.add(pkg_name)

            url_info.append(
                {
                    "full_url": url,
                    "short_url": short_url,
                    "filename": filename,
                    "pkg_name": pkg_name,
                    "ver_fallback": ver_fallback,
                }
            )

        # 2. Batch Query Version, Repo, and Download Size using pyalpm
        pkg_meta = {}  # name -> (version_str, repo_name, download_size_bytes)

        if names_to_query:
            for name in names_to_query:
                pkg = alpm_helper.get_package(name)
                if pkg:
                    ver_val = getattr(pkg, "version", None)
                    ver_str = ver_val if isinstance(ver_val, str) else ""

                    db_obj = getattr(pkg, "db", None)
                    repo_val = getattr(db_obj, "name", None) if db_obj else None
                    repo_name = repo_val if isinstance(repo_val, str) else ""

                    raw_dl = getattr(pkg, "download_size", 0)
                    if not isinstance(raw_dl, (int, float)) or isinstance(raw_dl, bool):
                        raw_dl = 0
                    if raw_dl <= 0:
                        raw_sz = getattr(pkg, "size", 0)
                        if (
                            isinstance(raw_sz, (int, float))
                            and not isinstance(raw_sz, bool)
                            and raw_sz > 0
                        ):
                            raw_dl = raw_sz

                    pkg_meta[name] = (ver_str, repo_name, raw_dl)

        # 3. Print Output in APT style: Get:1 https://mirror/ repo/pkg ver [size]
        total = len(urls)
        for i, info in enumerate(url_info, 1):
            name = info["pkg_name"]
            meta = pkg_meta.get(name)
            repo_name = ""
            size_bytes = 0
            version_str = info["ver_fallback"]

            if meta:
                meta_ver, meta_repo, meta_size = meta
                if meta_ver:
                    version_str = meta_ver
                repo_name = meta_repo
                size_bytes = meta_size

            display_pkg = f"{repo_name}/{name}" if repo_name else name
            if version_str:
                final_str = f"{display_pkg} {version_str}"
            else:
                final_str = f"{display_pkg} [?]"

            size_str = fmt_adaptive_size(size_bytes) if size_bytes > 0 else ""

            # Determine action (Get vs Hit)
            action = "Hit" if info["full_url"].startswith("file://") else "Get"

            print_apt_download_line(
                i,
                total,
                info["short_url"],
                final_str,
                size_str=size_str,
                action=action,
            )

        return total

    except Exception:
        pass
    return 0


class TotalCountColumn(ProgressColumn):
    """Renders completed/total, handling None totals gracefully."""

    def __init__(self):
        from rich.table import Column

        super().__init__(table_column=Column(no_wrap=True, min_width=5))

    def render(self, task: "Task") -> Text:
        total = task.total
        if total is None:
            return Text(f"[{task.completed}/?]", style="progress.remaining")
        return Text(f"[{task.completed}/{total}]", style="progress.remaining")


class CandyBar:
    """Renderable for the Candy Progress Bar."""

    def __init__(self, completed, total, time_t):
        self.completed = completed
        self.total = total
        self.time_t = time_t

    def __rich_measure__(self, console, options):
        # Allow full expansion (ratio=1 handles distribution)
        # We rely on neighbors being hardened (min_width) to prevent crushing.
        return Measurement(1, options.max_width)

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        width = options.max_width
        if width < 3:
            yield Text("")
            return

        total = self.total or 100
        completed = min(max(self.completed, 0), total)
        percent = completed / total if total > 0 else 0

        if ui.is_linux_console(console):
            empty_char = "."
        else:
            empty_char = "⚬"
            try:
                empty_char.encode(console.encoding or "utf-8")
            except Exception:
                empty_char = "."

        # Pacman Animation
        pacman_icon = "c" if int(self.time_t * 5) % 2 == 0 else "C"
        if percent >= 1.0:
            pacman_icon = "C"

        inner_width = width - 2
        if percent <= 0:
            dash_len = 0
            remaining_len = inner_width - 1
        elif percent >= 1.0:
            dash_len = inner_width - 1
            remaining_len = 0
        else:
            filled_len = max(1, min(inner_width, int(inner_width * percent)))
            dash_len = filled_len - 1
            remaining_len = inner_width - filled_len

        bar_text = Text("[", style="bold white")
        if dash_len > 0:
            bar_text.append("-" * dash_len, style="bold magenta")
        bar_text.append(pacman_icon, style="bold yellow")
        if remaining_len > 0:
            bar_text.append(empty_char * remaining_len, style="white")
        bar_text.append("]", style="bold white")
        yield bar_text


class CandyBarColumn(ProgressColumn):
    """Rich column for CandyBar."""

    def __init__(self, bar_width=None):
        from rich.table import Column

        super().__init__(
            table_column=Column(no_wrap=True, ratio=1 if bar_width is None else 0)
        )
        self.bar_width = bar_width

    def render(self, task) -> RenderResult:
        return CandyBar(task.completed, task.total, task.get_time())


_PROMPT_RE = re.compile(
    r"(?:\[[yYnN]/[yYnN]\]|\([yYnN]/[yYnN]\)|Enter a (?:selection|number)[^:\n]*|password[^:\n]*:\s*|\?\s*$)\s*$"
)

_AUTO_PROMPT_LINE_RE = re.compile(
    r"^(?::: )?(?:Proceed with installation\?|Do you want to remove)\s*\[[yYnN]/[yYnN]\]\s*$",
    re.I,
)

_BOILERPLATE_RE = re.compile(
    r"^(?:"
    r"resolving dependencies\.{0,3}|"
    r"looking for conflicting packages\.{0,3}|"
    r"loading packages\.{0,3}|"
    r"loading package files\.{0,3}|"
    r"checking dependencies\.{0,3}|"
    r"checking package integrity\.{0,3}|"
    r"checking keys in keyring\.{0,3}|"
    r"checking for file conflicts\.{0,3}|"
    r"checking available disk space\.{0,3}|"
    r"there is nothing to do|"
    r"Packages\s*\(\d+\).*|"
    r"Total (?:Download|Installed|Removed) Size:.*|"
    r"Net Upgrade Size:.*|"
    r"(?::: )?Synchronizing package databases\.{0,3}|"
    r"(?::: )?Starting full system upgrade\.{0,3}|"
    r"(?::: )?Retrieving packages\.{0,3}|"
    r"(?::: )?Processing package changes\.{0,3}|"
    r"\S+\s+is up to date"
    r")$",
    re.I,
)

_PACMAN_ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def _iter_process_events(process, stream_fd=None):
    """
    Yield ('line', text) or ('prompt', text) events from a child process without
    blocking indefinitely on interactive prompts that do not end in a newline.
    """
    fd = stream_fd
    if fd is None and process.stdout is not None:
        fileno_fn = getattr(process.stdout, "fileno", None)
        if callable(fileno_fn):
            try:
                candidate_fd = fileno_fn()
                if (
                    isinstance(candidate_fd, int)
                    and not isinstance(candidate_fd, bool)
                    and candidate_fd >= 0
                ):
                    fd = candidate_fd
            except Exception:
                fd = None

    if fd is None:
        if process.stdout is not None:
            for line in iter(process.stdout.readline, ""):
                if not line:
                    break
                yield ("line", line)
        return

    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    buf = ""
    idle_timeouts = 0
    eof = False

    while not eof:
        try:
            ready, _, _ = select.select([fd], [], [], 0.12)
        except (ValueError, OSError):
            break

        if ready:
            try:
                chunk = os.read(fd, 4096)
            except OSError as exc:
                if exc.errno == errno.EIO:
                    eof = True
                    chunk = b""
                elif exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK, errno.EINTR):
                    continue
                else:
                    break

            if not chunk:
                eof = True
            else:
                idle_timeouts = 0
                buf += decoder.decode(chunk, final=False)
        else:
            idle_timeouts += 1
            if buf:
                if buf.endswith("\r"):
                    seg = buf[:-1]
                    buf = ""
                    if seg:
                        yield ("line", seg + "\n")
                    continue

                clean_buf = _PACMAN_ANSI_RE.sub("", buf)
                if process.poll() is None and (
                    _PROMPT_RE.search(clean_buf)
                    or (idle_timeouts >= 10 and not clean_buf.rstrip().endswith("..."))
                ):
                    prompt_text = buf
                    buf = ""
                    idle_timeouts = 0
                    yield ("prompt", prompt_text)
                    continue

        buf = buf.replace("\r\n", "\n")
        while True:
            nl_idx = buf.find("\n")
            cr_idx = buf.find("\r")
            if cr_idx == len(buf) - 1:
                cr_idx = -1

            if nl_idx == -1 and cr_idx == -1:
                break

            if nl_idx != -1 and (cr_idx == -1 or nl_idx < cr_idx):
                seg = buf[: nl_idx + 1]
                buf = buf[nl_idx + 1 :]
                yield ("line", seg)
            else:
                seg = buf[:cr_idx]
                buf = buf[cr_idx + 1 :]
                if seg:
                    yield ("line", seg + "\n")

    buf += decoder.decode(b"", final=True)
    buf = buf.replace("\r\n", "\n")
    if buf:
        for seg in buf.replace("\r", "\n").splitlines(keepends=True):
            yield ("line", seg)


def run_pacman_with_apt_output(cmd, show_hooks=True, total_pkgs=None, quiet=0):
    """
    Runs pacman command and parses output to show:
    - Package installation progress in APT style
    - Interactive prompts (even without trailing newline) without deadlocking
    - Hooks/triggers, optional dependencies, scriptlets, warnings, and errors
    Returns True if successful, False otherwise

    Preserves stdin for interactive prompts (e.g., remove confirmations)
    """
    master_fd = None
    slave_fd = None
    try:
        env = os.environ.copy()
        env["LC_ALL"] = "C"

        use_pty = False
        if subprocess.Popen is _ORIGINAL_POPEN:
            try:
                import pty

                master_fd, slave_fd = pty.openpty()
                use_pty = True
            except (ImportError, OSError):
                master_fd = None
                slave_fd = None
                use_pty = False

        if use_pty:
            try:
                process = subprocess.Popen(
                    cmd,
                    stdout=slave_fd,
                    stderr=slave_fd,
                    stdin=None,  # stdin not captured - passes through to user
                    close_fds=True,
                    env=env,
                )
            finally:
                if slave_fd is not None:
                    try:
                        os.close(slave_fd)
                    except OSError:
                        pass
                    slave_fd = None
        else:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=None,  # stdin not captured - passes through to user
                text=True,
                bufsize=1,
                env=env,
            )

        current_action = _("Processing")

        # Regex for progress: ( 1/15) or 25%
        progress_re = re.compile(r"\(\s*(\d+)/(\d+)\s*\)")
        percent_re = re.compile(r"(\d+)%")
        pkg_action_re = re.compile(
            r"\)\s+(installing|upgrading|reinstalling|downgrading|removing)\s+(\S+)(?:\s+\(([^)]+)\))?",
            re.I,
        )
        ansi_escape = _PACMAN_ANSI_RE
        error_start_re = re.compile(
            r"^(?::: )?(?:error\s*:|(?:failed to (?:commit|prepare|retrieve|synchronize)|could not satisfy|errors occurred)\b)",
            re.I,
        )
        warning_start_re = re.compile(r"^(?::: )?warning:\s*", re.I)

        if total_pkgs:
            total_pkgs_int = int(total_pkgs)
        else:
            total_pkgs_int = None

        printed_reading_db = False
        in_hooks = False
        in_optdeps = False
        in_error_block = False
        in_pkg_list = False
        pacnew_files = []
        progress_paused = False

        term_width = ui.get_terminal_width(console)
        desc_min = min(18, max(8, term_width // 4))
        desc_max = max(12, min(32, term_width // 3))
        progress_kwargs = {
            "console": console,
            "transient": True,  # Remove bar when done
        }
        if quiet >= 1:
            progress_kwargs["disable"] = True

        try:
            with Progress(
                TextColumn(
                    "[bold blue]{task.description}",
                    table_column=Column(
                        no_wrap=True,
                        min_width=desc_min,
                        max_width=desc_max,
                        overflow="ellipsis",
                    ),
                ),
                TotalCountColumn(),
                CandyBarColumn(bar_width=None),
                TextColumn("[white]{task.percentage:>3.0f}%"),
                **progress_kwargs,
            ) as progress:
                # APT style: Description [0/10] [#####] 0%
                task_id = progress.add_task(
                    description=current_action, total=total_pkgs_int
                )

                for event_kind, line in _iter_process_events(
                    process, stream_fd=master_fd
                ):
                    if event_kind == "prompt":
                        if not progress_paused:
                            try:
                                progress.stop()
                            except Exception:
                                pass
                            progress_paused = True

                        clean_prompt = ansi_escape.sub("", line).rstrip("\r\n")
                        if clean_prompt.strip():
                            in_hooks = False
                            in_optdeps = False
                            in_pkg_list = False
                            console.print(escape(clean_prompt), end="", highlight=False)
                            try:
                                console.file.flush()
                            except Exception:
                                pass
                        continue

                    if progress_paused:
                        try:
                            progress.start()
                        except Exception:
                            pass
                        progress_paused = False

                    # Strip ANSI codes for parsing
                    line_clean = ansi_escape.sub("", line)
                    line_strip = line_clean.strip()
                    line_lower = line_clean.lower()

                    if not line_strip:
                        in_optdeps = False
                        in_error_block = False
                        in_pkg_list = False
                        continue

                    # Check for progress info in the line
                    p_match = progress_re.search(line_clean)
                    pct_match = percent_re.search(line_clean)
                    a_match = pkg_action_re.search(line_clean)

                    progress_suffix = ""
                    if pct_match:
                        progress_suffix = f" {pct_match.group(1)}%"

                    is_error_line = bool(error_start_re.match(line_strip))
                    is_warning_line = bool(warning_start_re.match(line_strip))

                    # Determine action and update description
                    is_dl_bar = bool(
                        pct_match
                        and (
                            "/s " in line_lower
                            or "b/s" in line_lower
                            or line_lower.lstrip().startswith("total (")
                        )
                    )
                    if (
                        "downloading" in line_lower
                        or "synchronizing" in line_lower
                        or ((".files" in line_lower or ".db" in line_lower) and pct_match)
                        or is_dl_bar
                    ) and not (is_error_line or is_warning_line):
                        in_hooks = False
                        in_optdeps = False
                        in_pkg_list = False
                        in_error_block = False
                        current_action = _("Downloading")
                        parts = line_clean.split()
                        pkg_name = ""
                        keywords = ["downloading", "synchronizing"]
                        try:
                            idx_list = [
                                i
                                for i, part in enumerate(parts)
                                if any(kw in part.lower() for kw in keywords)
                            ]
                            if idx_list:
                                idx = idx_list[0]
                                if idx + 1 < len(parts):
                                    candidate = parts[idx + 1]
                                    pkg_name = candidate.replace("...", "")
                                elif (
                                    idx - 1 >= 0
                                    and "..." not in parts[idx - 1]
                                    and parts[idx - 1] != "::"
                                ):
                                    pkg_name = parts[idx - 1]
                            elif parts:
                                if (
                                    ".files" in parts[0].lower()
                                    or ".db" in parts[0].lower()
                                ):
                                    pkg_name = parts[0]
                                elif parts[0].lower() != "total":
                                    pkg_name = parts[0]
                        except (IndexError, ValueError):
                            pass

                        desc = (
                            f"{current_action} {pkg_name}{progress_suffix}"
                            if pkg_name
                            else f"{current_action}{progress_suffix}"
                        )
                        progress.update(task_id, description=desc)
                        if p_match:
                            progress.update(
                                task_id,
                                completed=int(p_match.group(1)),
                                total=int(p_match.group(2)),
                            )
                        continue

                    if a_match:
                        in_hooks = False
                        in_optdeps = False
                        in_pkg_list = False
                        in_error_block = False
                        verb = a_match.group(1).lower()
                        pkg_name = a_match.group(2).rstrip(".")
                        if verb in ("installing", "reinstalling"):
                            current_action = _("Installing")
                        elif verb in ("upgrading", "downgrading"):
                            current_action = _("Upgrading")
                        else:
                            current_action = _("Removing")
                        progress.update(
                            task_id, description=f"{current_action} {pkg_name}"
                        )
                    elif not in_hooks and (
                        "checking keys" in line_lower
                        or "keyring" in line_lower
                        or (
                            line_strip.startswith("(")
                            and any(
                                kw in line_lower
                                for kw in (
                                    "checking package integrity",
                                    "loading package files",
                                    "checking for file conflicts",
                                    "checking available disk space",
                                )
                            )
                        )
                    ):
                        if "checking keys" in line_lower or "keyring" in line_lower:
                            current_action = _("Checking keys")
                        elif "integrity" in line_lower:
                            current_action = _("Checking integrity")
                        elif "file conflicts" in line_lower:
                            current_action = _("Checking conflicts")
                        elif "disk space" in line_lower:
                            current_action = _("Checking disk space")
                        else:
                            current_action = _("Loading packages")
                        progress.update(task_id, description=current_action)
                        if p_match:
                            progress.update(
                                task_id,
                                completed=int(p_match.group(1)),
                                total=int(p_match.group(2)),
                            )
                        if not (is_error_line or is_warning_line):
                            continue

                    # Update Progress Match (N/M)
                    if p_match:
                        curr = int(p_match.group(1))
                        total = int(p_match.group(2))
                        progress.update(task_id, completed=curr, total=total)

                    # APT Style Output Parsing
                    if a_match and formatting_is_ok(line_clean):
                        verb = a_match.group(1).lower()
                        pkg = a_match.group(2).rstrip(".")
                        ver = (a_match.group(3) or "").strip()
                        if verb == "installing":
                            console.print(
                                f"{_('Selecting previously unselected package')} {escape(pkg)}.",
                                highlight=False,
                            )
                            if not printed_reading_db:
                                console.print(
                                    f"({_('Reading database')} ... 100% {_('files and directories currently installed')}.)",
                                    highlight=False,
                                )
                                printed_reading_db = True
                            ver_part = f" ({escape(ver)})" if ver else ""
                            console.print(
                                f"{_('Unpacking')} {escape(pkg)}{ver_part} ...",
                                highlight=False,
                            )
                            continue
                        elif verb in ("upgrading", "downgrading"):
                            if not printed_reading_db:
                                console.print(
                                    f"({_('Reading database')} ... 100% {_('files and directories currently installed')}.)",
                                    highlight=False,
                                )
                                printed_reading_db = True
                            new_ver = (
                                ver.split("->")[-1].strip() if "->" in ver else ver
                            )
                            old_ver = ver.split("->")[0].strip() if "->" in ver else ""
                            console.print(
                                f"{_('Preparing to unpack')} .../{escape(pkg)}_{escape(new_ver)}.pkg ...",
                                highlight=False,
                            )
                            if verb == "downgrading" and old_ver and "->" in ver:
                                console.print(
                                    f"[yellow]{_('dpkg: warning: downgrading')}[/yellow] {escape(pkg)} {_('from')} {escape(old_ver)} {_('to')} {escape(new_ver)}",
                                    highlight=False,
                                )
                            if old_ver and "->" in ver:
                                console.print(
                                    f"{_('Unpacking')} {escape(pkg)} ({escape(new_ver)}) over ({escape(old_ver)}) ...",
                                    highlight=False,
                                )
                            else:
                                console.print(
                                    f"{_('Unpacking')} {escape(pkg)} ({escape(ver)}) ...",
                                    highlight=False,
                                )
                            continue
                        elif verb == "reinstalling":
                            if not printed_reading_db:
                                console.print(
                                    f"({_('Reading database')} ... 100% {_('files and directories currently installed')}.)",
                                    highlight=False,
                                )
                                printed_reading_db = True
                            console.print(
                                f"{_('Preparing to unpack')} .../{escape(pkg)}_{escape(ver)}.pkg ...",
                                highlight=False,
                            )
                            console.print(
                                f"{_('Unpacking')} {escape(pkg)} ({escape(ver)}) over ({escape(ver)}) ...",
                                highlight=False,
                            )
                            continue
                        elif verb == "removing":
                            if not printed_reading_db:
                                console.print(
                                    f"({_('Reading database')} ... 100% {_('files and directories currently installed')}.)",
                                    highlight=False,
                                )
                                printed_reading_db = True
                            console.print(
                                f"{_('Removing')} {escape(pkg)} ...",
                                highlight=False,
                            )
                            continue

                    # Hooks / Triggers
                    # ":: Running post-transaction hooks..."
                    if (
                        "hooks" in line_lower
                        and (
                            line_strip.startswith("::")
                            or "running" in line_lower
                            or "transaction hooks" in line_lower
                        )
                        and not (is_error_line or is_warning_line)
                    ):
                        in_hooks = True
                        in_optdeps = False
                        in_pkg_list = False
                        in_error_block = False
                        if show_hooks:
                            cleaned = line_clean.replace(":: ", "").strip()
                            if cleaned.endswith("..."):
                                cleaned = cleaned[:-3].strip()
                            console.print(
                                f"[bold]{_('Processing triggers for')}[/bold] {escape(cleaned)} ...",
                                highlight=False,
                            )
                        continue

                    if in_hooks:
                        if line_strip.startswith("("):
                            if show_hooks:
                                parts = line_clean.split(")", 1)
                                if len(parts) > 1:
                                    desc = parts[1].strip()
                                    if desc.endswith("..."):
                                        desc = desc[:-3].strip()
                                    console.print(
                                        f"{_('Setting up system')} ({escape(desc)}) ...",
                                        highlight=False,
                                    )
                            continue
                        elif line_strip.startswith("::"):
                            in_hooks = False

                    # Optional dependencies block
                    if line_strip.lower().startswith("optional dependencies for "):
                        in_optdeps = True
                        in_hooks = False
                        in_pkg_list = False
                        in_error_block = False
                        console.print(f"[bold]{escape(line_strip)}[/bold]", highlight=False)
                        continue

                    if in_optdeps:
                        if line_clean[0].isspace():
                            dep_text = line_strip
                            badge = ""
                            if dep_text.endswith("[installed]"):
                                dep_text = dep_text[: -len("[installed]")].rstrip()
                                badge = f" [green]\\[{_('installed')}][/green]"
                            elif dep_text.endswith("[pending]"):
                                dep_text = dep_text[: -len("[pending]")].rstrip()
                                badge = f" [yellow]\\[{_('pending')}][/yellow]"
                            console.print(
                                f"   {escape(dep_text)}{badge}",
                                highlight=False,
                            )
                            continue
                        in_optdeps = False

                    # Warnings & .pacnew/.pacsave/.pacorig tracking
                    if is_warning_line:
                        in_error_block = False
                        msg = warning_start_re.sub("", line_strip, count=1).strip()
                        if any(
                            ext in line_lower
                            for ext in (".pacnew", ".pacsave", ".pacorig")
                        ):
                            pacnew_files.append(msg)
                        console.print(
                            f"[bold yellow]{_('W:')}[/bold yellow] {escape(msg)}",
                            highlight=False,
                        )
                        continue

                    # Error blocks (dependency conflicts, file conflicts, target not found)
                    if is_error_line:
                        in_error_block = True
                        in_hooks = False
                        in_optdeps = False
                        in_pkg_list = False
                        msg = re.sub(r"^error:\s*", "", line_strip, count=1, flags=re.I)
                        console.print(
                            f"[bold red]{_('E:')}[/bold red] {escape(msg)}",
                            highlight=False,
                        )
                        continue

                    if in_error_block:
                        console.print(
                            f"[red]{escape(line_strip)}[/red]",
                            highlight=False,
                        )
                        continue

                    # Suppress pacman transaction boilerplate / multi-line Packages (N) list
                    if in_pkg_list:
                        if (
                            "total " in line_lower
                            or "net upgrade size" in line_lower
                        ):
                            in_pkg_list = False
                            continue
                        if not line_strip.startswith("::"):
                            continue
                        in_pkg_list = False

                    if re.match(r"^Packages\s*\(\d+\)", line_strip, re.I):
                        in_pkg_list = True
                        continue

                    if _BOILERPLATE_RE.match(line_strip) or _AUTO_PROMPT_LINE_RE.match(
                        line_strip
                    ):
                        continue

                    # Scriptlets and any other meaningful messages (providers, conflicts, notes)
                    if line_strip.startswith("==>"):
                        rest = line_strip[3:].strip()
                        console.print(
                            f"[bold cyan]==>[/bold cyan] {escape(rest)}",
                            highlight=False,
                        )
                    elif line_strip.startswith("->"):
                        rest = line_strip[2:].strip()
                        console.print(
                            f"  [blue]->[/blue] {escape(rest)}",
                            highlight=False,
                        )
                    else:
                        console.print(escape(line_clean.rstrip()), highlight=False)
        finally:
            if master_fd is not None:
                try:
                    os.close(master_fd)
                except OSError:
                    pass

        process.wait()

        if pacnew_files:
            console.print(
                f"\n[bold yellow]{_('W:')}[/bold yellow] {_('Configuration file updates detected (.pacnew/.pacsave/.pacorig):')}",
                highlight=False,
            )
            for item in pacnew_files:
                console.print(f"   {escape(item)}", highlight=False)
            console.print(
                f"   {_('Review these files (e.g. with pacdiff) to merge changes.')}",
                highlight=False,
            )

        # Sync filesystem on success
        if process.returncode == 0:
            try:
                subprocess.run(["sync"], check=False)
            except FileNotFoundError:
                pass  # sync not found (e.g. non-standard env)

        return process.returncode == 0

    except Exception as e:
        if os.environ.get("APT_PAC_DEBUG") == "1":
            import traceback

            traceback.print_exc()
        print_error(
            f"[bold red]{_('E:')}[/bold red] {_('Error running pacman: ')}{escape(str(e))}"
        )
        return False


def formatting_is_ok(line):
    # Heuristic to check if line is structured as expected for parsing
    return True  # Simplified for now


def execute_command(apt_cmd, extra_args):
    # Log the action system-wide
    from . import logger

    logger.log_action(apt_cmd, extra_args)

    if apt_cmd not in COMMAND_MAP:
        import difflib

        matches = difflib.get_close_matches(
            apt_cmd, COMMAND_MAP.keys(), n=1, cutoff=0.6
        )
        if matches:
            print_error(
                f"[red]{_('E:')}[/red] {_('Invalid operation ')}{escape(str(apt_cmd))}"
            )
            console.print(
                f"[info]{_('Did you mean:')}[/info] [bold white]{escape(matches[0])}[/bold white]?"
            )
        else:
            print_error(
                f"[red]{_('E:')}[/red] {_('Invalid operation ')}{escape(str(apt_cmd))}"
            )
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
    quiet_level = extra_args.count("-q") + 2 * extra_args.count("-qq")
    if "--quiet" in extra_args:
        quiet_level = max(quiet_level, 1)
    extra_args = [a for a in extra_args if a not in ("-q", "-qq", "--quiet")]

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

    # Apply force_colors config (do not pollute extra_args; apply to pacman commands later)
    force_colors = config.get("ui", "force_colors", False)
    if force_colors:
        ui.set_force_colors(True)

    # Show verbose information if enabled
    if verbose:
        console.print(f"[dim]Config dir: {config.config_dir}[/dim]")
        console.print(f"[dim]Cache dir: {config.cache_dir}[/dim]")
        console.print(
            f"[dim]Verbosity: {config_verbosity}, Quiet: {quiet_level}, Auto-confirm: {auto_confirm}[/dim]"
        )

    # Check for simulation flag
    is_simulation = (
        "-s" in extra_args or "--simulate" in extra_args or "--dry-run" in extra_args
    )
    if is_simulation:
        # Remove the flag from extra_args so it doesn't confuse pacman if it doesn't support it
        extra_args = [
            a for a in extra_args if a not in ["-s", "--simulate", "--dry-run"]
        ]
        print_info(_("Simulation mode enabled."))

    # Check for Partial Upgrades (Arch Best Practice)
    # If installing/removing software while system is out of date, warn user.
    if (
        apt_cmd in ["install", "reinstall", "remove", "purge", "autoremove"]
        and not is_simulation
        and config.get("safeguards", "warn_partial_upgrades", True)
    ):
        # Check updates without syncing
        updates = alpm_helper.get_available_updates()
        if updates:
            num_updates = len(updates)

            prog_name = os.path.basename(sys.argv[0])
            if prog_name.endswith(".py"):  # Fallback if running via python -m
                prog_name = "apt-pac"

            console.print(
                f"\n[yellow]{_('W:')}[/yellow] {_('You have {count} pending system upgrades.').format(count=num_updates)}",
                highlight=False,
            )
            console.print(
                _(
                    "Performing partial upgrades is [bold]unsupported[/bold] on Arch Linux and may break your system."
                )
            )
            console.print(
                f"[dim]{_('It is recommended to run')} [bold white]'{prog_name} upgrade'[/bold white] {_('first.')}[/dim]\n"
            )

            if not auto_confirm:
                prompt = Text(
                    f"{_('Proceed with partial operation?')} [Y/n] ",
                    style="bold yellow",
                )
                if not _confirm_yes(prompt):
                    print_info(_("Aborted."))
                    sys.exit(0)

    # Handle --fix-broken flag
    if "--fix-broken" in extra_args or "-f" in extra_args:
        extra_args = [a for a in extra_args if a not in ["--fix-broken", "-f"]]
        print_reading_status()
        console.print(f"[info]{_('Correcting dependencies...')}[/info]\n")

        subprocess.run(["pacman", "-Dk"], check=False)
        console.print(
            f"[info]{_('Attempting to resolve broken dependencies via system upgrade...')}[/info]"
        )
        if os.getuid() == 0:
            subprocess.run(["pacman", "-Syu", "--noconfirm"], check=False)
            console.print(f"\n[green]{_('Done')}[/green]")
        else:
            console.print(
                f"[yellow]{_('W:')}[/yellow] {_('Run as root to attempt automatic fixes')}"
            )
        return

    # Handle --no-install-recommends flag
    if "--no-install-recommends" in extra_args:
        extra_args = [a for a in extra_args if a != "--no-install-recommends"]
        if apt_cmd == "install":
            msg = f"[magenta]{_('N:')}[/magenta] " + _(
                "Pacman doesn't install optional dependencies by default"
            )
            console.print(f"[info]{msg}[/info]")

    # Handle --only-upgrade flag
    only_upgrade = "--only-upgrade" in extra_args
    if only_upgrade:
        extra_args = [a for a in extra_args if a != "--only-upgrade"]
        if apt_cmd == "install":
            pkgs_to_upgrade = []
            for pkg in extra_args:
                if alpm_helper.get_local_package(pkg) is not None:
                    pkgs_to_upgrade.append(pkg)
                else:
                    console.print(
                        f"[info]{_('Skipping')} {escape(str(pkg))} ({_('not installed')})[/info]"
                    )

            if not pkgs_to_upgrade:
                print_info(
                    _("0 upgraded, 0 newly installed, 0 to remove and 0 not upgraded.")
                )
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
        console.print(_('..."Have you mooed today?"...'))
        return

    if apt_cmd == "pacman":
        # Cool Pacman!
        console.print("")
        if ui.is_linux_console(console):
            console.print("    C.... o  o  o")
        else:
            console.print("    ᗧ···· ᗣ  ᗣ  ᗣ")
        console.print("")
        console.print(_("...Waka waka!..."))
        return

    # Check safeguards before doing anything destructive
    if not is_simulation:
        check_safeguards(
            apt_cmd, extra_args, is_simulation=is_simulation, auto_confirm=auto_confirm
        )

    # Handle privilege check (Strict APT style) - skip in simulation mode
    if apt_cmd in NEED_SUDO and os.getuid() != 0 and not is_simulation:
        if apt_cmd == "update":
            console.print(
                f"[red]{_('E:')}[/red] {_('Could not open lock file /var/lib/pacman/db.lck - open (13: Permission denied)')}"
            )
            console.print(
                f"[red]{_('E:')}[/red] {_('Unable to lock directory /var/lib/pacman/')}"
            )
        else:
            console.print(
                f"[red]{_('E:')}[/red] {_('Could not open lock file /var/lib/pacman/db.lck - open (13: Permission denied)')}"
            )
            console.print(
                f"[red]{_('E:')}[/red] {_('Unable to lock the administration directory (/var/lib/pacman/), are you root?')}"
            )
        sys.exit(100)

    # Handle apt list with all options
    if apt_cmd == "list":
        # Show help with all list options
        if "--help" in extra_args or "-h" in extra_args:
            console.print(f"[bold]{_('Usage:')}[/bold] apt list [{_('options')}]")
            console.print(f"\n[bold]{_('Options:')}[/bold]")
            opts_table = Table.grid(padding=(0, 2))
            opts_table.add_column(style="bold green", no_wrap=True)
            opts_table.add_column(overflow="fold")
            opts_table.add_row("--installed", _("List installed packages with details"))
            opts_table.add_row("--upgradable", _("List upgradable packages"))
            opts_table.add_row("--manual-installed", _("List manually installed packages"))
            opts_table.add_row("--all-versions", _("List all available package versions"))
            opts_table.add_row("--repo <name>", _("List packages in a specific repository"))
            console.print(Padding(opts_table, (0, 0, 0, 2)))
            return

        import fnmatch

        pkg_patterns = []
        repo_target = None
        has_repo_flag = False
        skip_next = False
        for idx_arg, arg in enumerate(extra_args):
            if skip_next:
                skip_next = False
                continue
            if arg.startswith("--repo="):
                has_repo_flag = True
                repo_target = arg.split("=", 1)[1]
            elif arg == "--repo":
                has_repo_flag = True
                if idx_arg + 1 < len(extra_args):
                    repo_target = extra_args[idx_arg + 1]
                    skip_next = True
            elif not arg.startswith("-"):
                pkg_patterns.append(arg)

        def _matches_patterns(pkg_name: str) -> bool:
            if not pkg_patterns:
                return True
            return any(fnmatch.fnmatch(pkg_name, pat) for pat in pkg_patterns)

        def _fmt_arch(arch_val, repo_val=""):
            if arch_val == "any":
                return "all"
            if repo_val == "multilib":
                return "multilib"
            return arch_val or "unknown"

        show_output = config.get("ui", "show_output", "apt-pac")
        is_pacman_repo_mode = has_repo_flag and repo_target and show_output == "pacman"
        if quiet_level == 0 and not is_pacman_repo_mode:
            console.print(
                f"{_('Listing')}... [green]{_('Done')}[/green]",
                highlight=False,
            )

        if "--upgradable" in extra_args:
            updates = alpm_helper.get_available_updates()

            if updates:
                filtered_updates = [
                    u for u in sorted(updates, key=lambda x: x[0]) if _matches_patterns(u[0])
                ]
                if filtered_updates and quiet_level < 2:
                    console.print(
                        f"[yellow]{_('W:')}[/yellow] {_('Partial upgrades are not supported on Arch Linux.')}"
                    )
                    console.print(
                        f"[dim]{_('It is recommended to run a full system upgrade instead.')}[/dim]\n"
                    )

                import pyalpm

                for pkg_name, old_ver, new_ver in filtered_updates:
                    if quiet_level >= 2:
                        console.print(escape(pkg_name), highlight=False)
                        continue
                    sync_pkg = alpm_helper.get_package(pkg_name)
                    repo = (
                        sync_pkg.db.name
                        if sync_pkg and getattr(sync_pkg, "db", None)
                        else "unknown"
                    )
                    raw_arch = getattr(sync_pkg, "arch", "") if sync_pkg else ""
                    arch = _fmt_arch(raw_arch, repo) if raw_arch else ""
                    is_downgrade = pyalpm.vercmp(new_ver, old_ver) < 0
                    ver_style = "bold red" if is_downgrade else "bold"
                    arch_part = f" {escape(arch)}" if arch else ""
                    console.print(
                        f"[bold green]{escape(pkg_name)}[/bold green]/[bold blue]{escape(repo)}[/bold blue] "
                        f"[{ver_style}]{escape(new_ver)}[/{ver_style}]{arch_part} "
                        f"[cyan]\\[{_('upgradable from:')} {escape(old_ver)}][/cyan]",
                        highlight=False,
                    )
            else:
                if quiet_level < 2:
                    console.print(_("All packages are up to date."))

            return

        elif "--installed" in extra_args:
            import pyalpm

            installed_pkgs = [
                p
                for p in sorted(alpm_helper.get_installed_packages(), key=lambda p: p.name)
                if _matches_patterns(p.name)
            ]
            if quiet_level >= 2:
                for pkg in installed_pkgs:
                    console.print(escape(pkg.name), highlight=False)
                return

            orphans = {pkg.name for pkg in alpm_helper.get_orphan_packages()}
            aur_outdated = set()
            if hasattr(aur, "check_updates"):
                try:
                    aur_updates = aur.check_updates(verbose=False)
                    aur_outdated = {u["name"] for u in aur_updates}
                except Exception:
                    pass

            for pkg in installed_pkgs:
                sync_pkg = alpm_helper.get_package(pkg.name)
                repo = (
                    sync_pkg.db.name
                    if sync_pkg and getattr(sync_pkg, "db", None)
                    else "local"
                )
                arch = _fmt_arch(pkg.arch, repo)

                name_repo = (
                    f"[bold green]{escape(pkg.name)}[/bold green]/[bold blue]{escape(repo)}[/bold blue]"
                )

                if pkg.name in orphans:
                    orphan_label = _("orphan")
                    install_type = (
                        f"[dim]\\[{_('installed')}, {escape(orphan_label)}][/dim]"
                    )
                elif pkg.reason == pyalpm.PKG_REASON_DEPEND:
                    requiredby = pkg.compute_requiredby()
                    if requiredby:
                        install_type = (
                            f"[dim]\\[{_('installed by')} {escape(requiredby[0])}][/dim]"
                        )
                    else:
                        install_type = f"[green]\\[{_('installed')}][/green]"
                elif pkg.name in aur_outdated:
                    install_type = (
                        f"[yellow]\\[{_('installed')}, {escape(_('outdated'))}][/yellow]"
                    )
                else:
                    install_type = f"[green]\\[{_('installed')}][/green]"

                console.print(
                    f"{name_repo} [bold]{escape(pkg.version)}[/bold] {escape(arch)} {install_type}",
                    highlight=False,
                )
            return

        elif "--manual-installed" in extra_args:
            explicit_pkgs = [
                p
                for p in sorted(
                    alpm_helper.get_installed_packages(explicit_only=True),
                    key=lambda p: p.name,
                )
                if _matches_patterns(p.name)
            ]

            for pkg in explicit_pkgs:
                if quiet_level >= 2:
                    console.print(escape(pkg.name), highlight=False)
                    continue
                sync_pkg = alpm_helper.get_package(pkg.name)
                repo = (
                    sync_pkg.db.name
                    if sync_pkg and getattr(sync_pkg, "db", None)
                    else "local"
                )
                arch = _fmt_arch(getattr(pkg, "arch", ""), repo)
                console.print(
                    f"[bold green]{escape(pkg.name)}[/bold green]/[bold blue]{escape(repo)}[/bold blue] "
                    f"[bold]{escape(pkg.version)}[/bold] {escape(arch)} [green]\\[{_('installed')}][/green]",
                    highlight=False,
                )
            return

        elif "--all-versions" in extra_args:
            all_packages = [
                p
                for p in sorted(alpm_helper.get_all_repo_packages(), key=lambda p: p.name)
                if _matches_patterns(p.name)
            ]
            local_versions = (
                {p.name: p.version for p in alpm_helper.get_installed_packages()}
                if quiet_level < 2
                else {}
            )

            for pkg in all_packages:
                if quiet_level >= 2:
                    console.print(escape(pkg.name), highlight=False)
                    continue
                repo = pkg.db.name if getattr(pkg, "db", None) else "unknown"
                arch = _fmt_arch(pkg.arch, repo)
                inst_suffix = (
                    f" [green]\\[{_('installed')}][/green]"
                    if local_versions.get(pkg.name) == pkg.version
                    else ""
                )
                console.print(
                    f"[bold green]{escape(pkg.name)}[/bold green]/[bold blue]{escape(repo)}[/bold blue] "
                    f"[bold]{escape(pkg.version)}[/bold] {escape(arch)}{inst_suffix}",
                    highlight=False,
                )
            return

        elif has_repo_flag:
            if not repo_target:
                print_error(f"[bold red]{_('E:')}[/bold red] {_('No repository specified')}")
                sys.exit(1)

            if show_output == "pacman":
                if shutil.which("paclist"):
                    pacman_cmd = ["paclist", repo_target]
                else:
                    pacman_cmd = ["pacman", "-Sl", repo_target]
            else:
                handle = alpm_helper.get_handle()
                target_db = next(
                    (db for db in handle.get_syncdbs() if db.name == repo_target), None
                )
                if target_db is None:
                    print_error(
                        f"[bold red]{_('E:')}[/bold red] {_('Repository')} '{escape(repo_target)}' {_('not found')}"
                    )
                    sys.exit(1)

                installed_names = (
                    {p.name for p in alpm_helper.get_installed_packages()}
                    if quiet_level < 2
                    else set()
                )
                repo_pkgs = [
                    p
                    for p in sorted(target_db.pkgcache, key=lambda p: p.name)
                    if _matches_patterns(p.name)
                ]
                for pkg in repo_pkgs:
                    if quiet_level >= 2:
                        console.print(escape(pkg.name), highlight=False)
                        continue
                    arch = _fmt_arch(pkg.arch, repo_target)
                    inst_suffix = (
                        f" [green]\\[{_('installed')}][/green]"
                        if pkg.name in installed_names
                        else ""
                    )
                    console.print(
                        f"[bold green]{escape(pkg.name)}[/bold green]/[bold blue]{escape(repo_target)}[/bold blue] "
                        f"[bold]{escape(pkg.version)}[/bold] {escape(arch)}{inst_suffix}",
                        highlight=False,
                    )
                return

        else:
            installed_pkgs = [
                p
                for p in sorted(alpm_helper.get_installed_packages(), key=lambda p: p.name)
                if _matches_patterns(p.name)
            ]

            for pkg in installed_pkgs:
                if quiet_level >= 2:
                    console.print(escape(pkg.name), highlight=False)
                    continue
                sync_pkg = alpm_helper.get_package(pkg.name)
                repo = (
                    sync_pkg.db.name
                    if sync_pkg and getattr(sync_pkg, "db", None)
                    else "local"
                )
                arch = _fmt_arch(pkg.arch, repo)
                console.print(
                    f"[bold green]{escape(pkg.name)}[/bold green]/[bold blue]{escape(repo)}[/bold blue] "
                    f"[bold]{escape(pkg.version)}[/bold] {escape(arch)} [green]\\[{_('installed')}][/green]",
                    highlight=False,
                )

            return
    elif apt_cmd == "install":
        is_local_install = False
        # Check if we are installing a local file
        # We check content (.PKGINFO in tar) to be sure
        if any(aur.is_valid_package(a) for a in extra_args):
            is_local_install = True
            pacman_cmd = ["pacman", "-U"] + extra_args
        else:
            # Check for AUR packages
            official_pkgs = []
            pacman_flags = []
            aur_pkgs = []

            for pkg in extra_args:
                if pkg.startswith("-"):
                    # Pass flags through to pacman
                    pacman_flags.append(pkg)
                    continue

                if aur.is_in_official_repos(pkg):
                    official_pkgs.append(pkg)
                elif aur.get_aur_info([pkg]):
                    # Check if it exists in AUR (exact match via info)
                    aur_pkgs.append(pkg)
                else:
                    # Not found in either
                    console.print(
                        f"[bold red]E:[/bold red] {_('Unable to locate package')} {escape(pkg)}"
                    )
                    sys.exit(100)

            if aur_pkgs:
                if is_simulation:
                    if official_pkgs:
                        show_summary(
                            apt_cmd,
                            pacman_flags + official_pkgs,
                            auto_confirm=True,
                            aur_new=[(p, "AUR") for p in aur_pkgs],
                        )
                    else:
                        show_summary(
                            apt_cmd,
                            [],
                            auto_confirm=True,
                            aur_new=[(p, "AUR") for p in aur_pkgs],
                            skip_official=True,
                        )
                    return

                # If we have official packages, install them first
                if official_pkgs:
                    console.print(
                        f"[bold]{_('Installing official packages:')}[/bold] {escape(' '.join(official_pkgs))}"
                    )
                    cmd = ["pacman", "-S"] + pacman_flags + official_pkgs
                    if force_colors and "--color=always" not in cmd:
                        cmd.append("--color=always")
                    if download_only:
                        cmd.append("-w")
                    if auto_confirm:
                        cmd.append("--noconfirm")
                    try:
                        res = subprocess.run(cmd)
                    except OSError as e:
                        print_error(
                            f"[bold red]{_('E:')}[/bold red] {_('Failed to execute pacman: ')}{escape(str(e))}"
                        )
                        sys.exit(1)
                    if isinstance(res.returncode, int) and res.returncode != 0:
                        sys.exit(res.returncode)

                # Then install AUR packages
                installer = aur.AurInstaller()
                try:
                    installer.install(
                        aur_pkgs, verbose=verbose, auto_confirm=auto_confirm
                    )
                except KeyboardInterrupt:
                    print_error(_("\nInterrupted."))
                    sys.exit(130)
                except Exception as e:
                    print_error(
                        f"[bold red]{_('E:')}[/bold red] {_('AUR Installation failed: ')}{escape(str(e))}"
                    )
                    sys.exit(1)
                return  # Exit after AUR install handling

            # If no AUR packages, just proceed with normal pacman -S
            pacman_cmd = ["pacman", "-S"] + pacman_flags + official_pkgs
    elif apt_cmd == "depends":
        targets = [a for a in extra_args if not a.startswith("-")]
        if not targets:
            print_error(f"[bold red]{_('E')}[/bold red]: {_('No package specified')}")
            sys.exit(1)

        use_tree = "--tree" in extra_args or "-t" in extra_args
        if use_tree:
            if shutil.which("pactree"):
                for pkgname in targets:
                    tree_cmd = ["pactree"]
                    if ui.is_linux_console(console):
                        tree_cmd.append("-a")
                    tree_cmd.append(pkgname)
                    subprocess.run(tree_cmd, check=False)
                return
            console.print(
                f"[yellow]{_('W:')}[/yellow] {_('pactree (pacman-contrib) not found; showing flat dependency list.')}",
                highlight=False,
            )

        for pkgname in targets:
            pkg = alpm_helper.get_local_package(pkgname)
            if not pkg:
                pkg = alpm_helper.get_package(pkgname)

            if pkg:
                console.print(f"[bold]{escape(pkgname)}[/bold]", highlight=False)
                deps_list = list(getattr(pkg, "depends", None) or [])
                optdeps_raw = getattr(pkg, "optdepends", None)
                optdeps_list = (
                    list(optdeps_raw)
                    if isinstance(optdeps_raw, (list, tuple, set))
                    else []
                )
                for dep in deps_list:
                    console.print(
                        f"  [cyan]{_('Depends:')}[/cyan] {escape(str(dep))}",
                        highlight=False,
                    )
                for optdep in optdeps_list:
                    console.print(
                        f"  [dim]{_('Suggests:')}[/dim] {escape(str(optdep))}",
                        highlight=False,
                    )
                if not deps_list and not optdeps_list:
                    console.print(f"  {_('(no dependencies)')}", highlight=False)
            else:
                print_error(
                    f"[bold red]{_('E:')}[/bold red] {_('Unable to locate package')} {escape(pkgname)}"
                )
                sys.exit(1)
        return
    elif apt_cmd == "rdepends":
        targets = [a for a in extra_args if not a.startswith("-")]
        if not targets:
            print_error(f"[bold red]{_('E')}[/bold red]: {_('No package specified')}")
            sys.exit(1)

        use_tree = "--tree" in extra_args or "-t" in extra_args
        if use_tree:
            if shutil.which("pactree"):
                for pkgname in targets:
                    tree_cmd = ["pactree", "-r"]
                    if ui.is_linux_console(console):
                        tree_cmd.append("-a")
                    tree_cmd.append(pkgname)
                    subprocess.run(tree_cmd, check=False)
                return
            console.print(
                f"[yellow]{_('W:')}[/yellow] {_('pactree (pacman-contrib) not found; showing flat reverse dependency list.')}",
                highlight=False,
            )

        for pkgname in targets:
            pkg = alpm_helper.get_local_package(pkgname)
            if pkg:
                console.print(f"[bold]{escape(pkgname)}[/bold]", highlight=False)
                rdeps = (
                    list(pkg.compute_requiredby() or [])
                    if hasattr(pkg, "compute_requiredby")
                    else []
                )
                optfor_raw = (
                    pkg.compute_optionalfor()
                    if hasattr(pkg, "compute_optionalfor")
                    else []
                )
                optfor = (
                    list(optfor_raw)
                    if isinstance(optfor_raw, (list, tuple, set))
                    else []
                )
                if rdeps:
                    console.print(f"  {_('Reverse Depends:')}", highlight=False)
                    for r in rdeps:
                        console.print(f"    {escape(str(r))}", highlight=False)
                if optfor:
                    console.print(f"  [dim]{_('Optional For:')}[/dim]", highlight=False)
                    for opt in optfor:
                        console.print(f"    {escape(str(opt))}", highlight=False)
                if not rdeps and not optfor:
                    console.print(
                        f"  {_('(no reverse dependencies)')}", highlight=False
                    )
            else:
                print_error(f"{_('Package not installed:')} {escape(pkgname)}")
                sys.exit(1)
        return
    elif apt_cmd == "scripts":
        if shutil.which("pacscripts"):
            pacman_cmd = ["pacscripts"] + extra_args
        else:
            pacman_cmd = ["pacman", "-Qii"] + extra_args
    elif apt_cmd == "reinstall":
        pacman_cmd = ["pacman", "-S"] + extra_args
    elif apt_cmd == "clean":
        # 1. Fix for "download-*" directories in pacman cache (FIRST to avoid pacman errors)
        pacman_cache = Path("/var/cache/pacman/pkg/")
        if pacman_cache.exists():
            try:
                for d in pacman_cache.glob("download-*"):
                    if d.is_dir():
                        shutil.rmtree(d)
            except PermissionError:
                pass

        # 2. Run pacman clean
        try:
            subprocess.run(["pacman", "-Scc"], check=False)
        except OSError as e:
            print_error(
                f"[bold red]{_('E:')}[/bold red] {_('Failed to execute pacman: ')}{escape(str(e))}"
            )
            sys.exit(1)

        # 3. Clean apt-pac cache
        cache_dir = config.cache_dir
        if cache_dir and cache_dir.exists():
            print_info(
                f"\n[bold]{_('Cleaning apt-pac cache')} ({escape(str(cache_dir))})...[/bold]"
            )
            sources_dir = cache_dir / "sources"
            if sources_dir.exists():
                try:
                    shutil.rmtree(sources_dir)
                    print_info(
                        f"[green]{_('Removed')} {escape(str(sources_dir))}[/green]"
                    )
                except OSError as e:
                    print_error(
                        f"[bold red]{_('E:')}[/bold red] {_('Failed to remove cache directory: ')}{escape(str(e))}"
                    )
        return
    elif apt_cmd == "autoclean":
        # Use native python implementation replacing paccache -rk3
        if is_simulation:
            print_info(
                _(
                    "Simulation: cleaning up package cache (keeping latest 3 versions)..."
                )
            )
        else:
            print_info(_("Cleaning up package cache (keeping latest 3 versions)..."))
        try:
            freed = alpm_helper.clean_cache(
                keep=3, dry_run=is_simulation, verbose=(quiet_level == 0)
            )
            size_str = fmt_adaptive_size(freed)
            if is_simulation:
                print_info(f"{_('Simulation: would free')} {size_str}")
            else:
                print_success(f"{_('Cleaned up cache.')} {_('Freed space:')} {size_str}")
        except Exception as e:
            print_error(
                f"[bold red]{_('E:')}[/bold red] {_('Failed to clean cache:')} {escape(str(e))}"
            )
        return
    elif apt_cmd == "policy":
        # Simulate apt-cache policy: show installed version and repo versions
        targets = [a for a in extra_args if not a.startswith("-")]
        handle = alpm_helper.get_handle()
        dbs = handle.get_syncdbs()

        # Calculate priorities based on order (Arch behavior)
        # Starting at 500, decreasing by 5 per repo
        db_priorities = {}
        curr_prio = 500
        for db in dbs:
            db_priorities[db.name] = curr_prio
            curr_prio -= 5

        if targets:
            for pkg in targets:
                console.print(f"{escape(pkg)}:", highlight=False)

                local_pkg = alpm_helper.get_local_package(pkg)
                if local_pkg:
                    console.print(
                        f"  {_('Installed:')} {escape(local_pkg.version)}",
                        highlight=False,
                    )
                else:
                    console.print(f"  {_('Installed:')} ({_('none')})", highlight=False)

                matches = []
                for db in dbs:
                    db_pkg = db.get_pkg(pkg)
                    if db_pkg:
                        matches.append((db.name, db_pkg))

                if matches:
                    console.print(
                        f"  {_('Candidate:')} {escape(matches[0][1].version)}",
                        highlight=False,
                    )
                    console.print(f"  {_('Version table:')}", highlight=False)
                    local_ver = local_pkg.version if local_pkg else None
                    merged_local = False

                    if local_ver and not any(
                        db_pkg.version == local_ver for _, db_pkg in matches
                    ):
                        console.print(f" *** {escape(local_ver)} 100", highlight=False)
                        console.print("        100 /var/lib/pacman/local", highlight=False)
                        merged_local = True

                    for repo_name, db_pkg in matches:
                        prio = db_priorities.get(repo_name, 500)
                        if local_ver and not merged_local and db_pkg.version == local_ver:
                            console.print(
                                f" *** {escape(db_pkg.version)} {prio}",
                                highlight=False,
                            )
                            console.print(
                                f"        {prio} {escape(repo_name)}",
                                highlight=False,
                            )
                            console.print(
                                "        100 /var/lib/pacman/local",
                                highlight=False,
                            )
                            merged_local = True
                        else:
                            console.print(
                                f"     {escape(db_pkg.version)} {prio}",
                                highlight=False,
                            )
                            console.print(
                                f"        {prio} {escape(repo_name)}",
                                highlight=False,
                            )
                else:
                    console.print(f"  {_('Candidate:')} ({_('none')})", highlight=False)
                    if local_pkg:
                        console.print(f"  {_('Version table:')}", highlight=False)
                        console.print(
                            f" *** {escape(local_pkg.version)} 100",
                            highlight=False,
                        )
                        console.print("        100 /var/lib/pacman/local", highlight=False)
            return
        else:
            print_info(_("Package files:"))
            for dbname, prio in db_priorities.items():
                console.print(f"  {prio} {escape(dbname)}", highlight=False)

            console.print("  100 /var/lib/pacman/local", highlight=False)
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
            msg = f"[magenta]{_('N:')}[/magenta] " + _(
                "Arch handles 'hold' via IgnorePkg in /etc/pacman.conf."
            )
            print_info(msg)
            print_info(_("Consider adding these packages to IgnorePkg manually."))
            return
        else:
            print_info(f"{_('Subcommand ')}{sub}{_(' not yet implemented.')}")
            return
    elif apt_cmd == "check":
        print_reading_status()

        try:
            result_db = subprocess.run(["pacman", "-Dk"], capture_output=True, text=True)
        except OSError as e:
            print_error(f"[bold red]{_('E:')}[/bold red] {_('Failed to execute pacman: ')}{escape(str(e))}")
            sys.exit(1)

        if result_db.returncode == 0:
            console.print(f"{_('Database integrity:')} [green]{_('OK')}[/green]")
        else:
            console.print(
                f"[error]{_('E')}:[/error] {_('Database errors')}:\n{escape(result_db.stdout)}"
            )

        try:
            result_deps = subprocess.run(["pacman", "-Qk"], capture_output=True, text=True)
        except OSError as e:
            print_error(f"[bold red]{_('E:')}[/bold red] {_('Failed to execute pacman: ')}{escape(str(e))}")
            sys.exit(1)
        dep_issues = [
            line
            for line in result_deps.stdout.splitlines()
            if "warning" in line.lower()
        ]
        if dep_issues:
            console.print(f"\nW: {len(dep_issues)} {_('package warnings found')}")
        else:
            console.print(f"{_('All packages:')} [green]{_('OK')}[/green]")

        # Library check is slow, allow skipping
        skip_lddd = "--no-lddd" in extra_args
        if skip_lddd:
            console.print(f"[dim]{_('Library links check skipped.')}[/dim]")
            return

        if shutil.which("lddd"):
            console.print(
                f"\n[yellow]{_('W:')}[/yellow] {_('Checking library links (lddd) can take several minutes.')}"
            )
            console.print(f"[dim]{_('Use --no-lddd to skip this check.')}[/dim]")
            with ui.status(f"[blue]{_('Checking library links (lddd)...')}[/blue]"):
                try:
                    result_lddd = subprocess.run(
                        ["lddd"], capture_output=True, text=True, check=False
                    )
                    if result_lddd.returncode == 0:
                        if result_lddd.stdout.strip():
                            console.print(f"\nW: {_('Broken libraries detected')}")
                        else:
                            console.print(
                                f"{_('Library links:')} [green]{_('OK')}[/green]"
                            )
                except (FileNotFoundError, OSError):
                    # lddd not actually available, skip check silently
                    pass
        return

    elif apt_cmd == "pkgnames":
        all_pkgs = sorted(alpm_helper.get_all_repo_packages(), key=lambda p: p.name)
        targets = [a for a in extra_args if not a.startswith("-")]

        if targets:
            prefix = targets[0]
            if quiet_level >= 2:
                for pkg in all_pkgs:
                    if pkg.name.startswith(prefix):
                        console.print(escape(pkg.name), highlight=False)
                return

            matching = [
                f"[bold]{escape(prefix)}[/bold]{escape(pkg.name[len(prefix) :])} [dim]{escape(pkg.version)}[/dim]"
                for pkg in all_pkgs
                if pkg.name.startswith(prefix)
            ]

            if matching:
                console.print(f"\n{_('Packages matching search:')}")
                print_columnar_list(matching, "default")
            else:
                console.print(
                    f"{_('No packages found matching')} [bold]{escape(prefix)}[/bold]"
                )
        else:
            if quiet_level >= 2:
                for pkg in all_pkgs:
                    console.print(escape(pkg.name), highlight=False)
                return

            if not all_pkgs:
                console.print(f"  {_('No packages found.')}")
                return

            console.print(f"\n{_('All available packages:')}")
            all_formatted = [
                f"{escape(pkg.name)} [dim]{escape(pkg.version)}[/dim]"
                for pkg in all_pkgs
            ]
            print_columnar_list(all_formatted, "default")
        return

    elif apt_cmd == "stats":
        console.print(f"\n[bold]{_('Package Statistics:')}[/bold]\n")

        all_repo_pkgs = alpm_helper.get_all_repo_packages()
        installed_pkgs = alpm_helper.get_installed_packages()
        explicit_pkgs = alpm_helper.get_installed_packages(explicit_only=True)
        deps_pkgs = alpm_helper.get_installed_packages(deps_only=True)
        orphan_pkgs = alpm_helper.get_orphan_packages()
        updates = alpm_helper.get_available_updates()

        stats_fields = [
            (_("Total packages"), str(len(all_repo_pkgs))),
            (_("Installed packages"), str(len(installed_pkgs))),
            (_("Explicitly installed"), str(len(explicit_pkgs))),
            (_("Installed as deps"), str(len(deps_pkgs))),
            (_("Orphaned packages"), str(len(orphan_pkgs))),
            (_("Upgradable packages"), str(len(updates))),
        ]

        try:
            cache_dirs = [str(p) for p in alpm_helper.get_cache_dirs()]
        except Exception:
            cache_dirs = []
        if not cache_dirs:
            cache_dirs = ["/var/cache/pacman/pkg"]

        num_cached = 0
        any_cache_exists = False
        for cache_path in cache_dirs:
            if os.path.exists(cache_path):
                any_cache_exists = True
                cache_files = os.listdir(cache_path)
                num_cached += len(
                    [
                        f
                        for f in cache_files
                        if f.endswith(
                            (".pkg.tar.zst", ".pkg.tar.xz", ".pkg.tar.gz", ".pkg.tar.bz2")
                        )
                    ]
                )
        if any_cache_exists:
            stats_fields.append((_("Cached package files"), str(num_cached)))

        ui._print_kv_fields(stats_fields, indent=2)
        return

    elif apt_cmd == "news":
        url = "https://archlinux.org/feeds/news/"
        with ui.status(
            f"[bold blue]{_('Fetching Arch Linux news...')}[/bold blue]", spinner="dots"
        ):
            try:
                with urllib.request.urlopen(url, timeout=10) as response:
                    xml_content = response.read()
            except Exception as e:
                print_error(
                    f"[bold red]{_('E:')}[/bold red] {_('Failed to fetch news:')} {escape(str(e))}"
                )
                sys.exit(1)

        try:
            root = ET.fromstring(xml_content)
            channel = root.find("channel")
            items = channel.findall("item") if channel is not None else []
        except Exception as e:
            print_error(
                f"[bold red]{_('E:')}[/bold red] {_('Failed to parse news feed:')} {escape(str(e))}"
            )
            sys.exit(1)

        if not items:
            print_info(_("No news found."))
            return

        term_width = ui.get_terminal_width(console)
        sep = "-" * min(max(20, term_width - 2), 72)

        output_lines = [
            f"[bold yellow]{_('Latest Arch Linux News')}[/bold yellow]\n"
        ]

        parsed_items = []
        for item in items:
            pubDateStr = item.findtext("pubDate", "")
            try:
                pubDate = parsedate_to_datetime(pubDateStr)
                if pubDate.tzinfo is None:
                    pubDate = pubDate.replace(tzinfo=timezone.utc)
                parsed_items.append((pubDate, item))
            except (TypeError, ValueError):
                continue

        parsed_items.sort(key=lambda x: x[0], reverse=True)

        cutoff = datetime.now(timezone.utc) - timedelta(days=6 * 30)
        filtered_items = [item for date, item in parsed_items if date > cutoff]

        if not filtered_items and parsed_items:
            filtered_items = [parsed_items[0][1]]

        if not filtered_items:
            print_info(_("No news found."))
            return

        for item in filtered_items:
            title = escape(item.findtext("title", "No Title"))
            link = escape(item.findtext("link", ""))
            pubDate = escape(item.findtext("pubDate", ""))
            desc = item.findtext("description", "")

            desc_clean = re.sub(r"<[^>]+>", "", desc)
            desc_clean = escape(html.unescape(desc_clean).strip())

            output_lines.append(f"[bold yellow]{title}[/bold yellow]")
            output_lines.append(f"[cyan]{pubDate}[/cyan]")
            output_lines.append(f"[blue underline]{link}[/blue underline]")
            output_lines.append(f"{desc_clean}")
            output_lines.append(f"[dim]{sep}[/dim]")

        full_text = "\n".join(output_lines)

        use_pager = True
        pager_cmd = ["less", "-R"]
        pager_env = os.environ.get("PAGER")

        if shutil.which("less"):
            pass
        elif pager_env:
            pager_cmd = pager_env.split()
        else:
            use_pager = False

        if use_pager:
            try:
                from io import StringIO
                from rich.console import Console as RichConsole

                buf = StringIO()
                str_console = RichConsole(
                    file=buf,
                    force_terminal=True,
                    width=term_width,
                    color_system=console.color_system,
                )
                str_console.print(full_text, highlight=False)
                rendered = buf.getvalue()

                proc = subprocess.Popen(pager_cmd, stdin=subprocess.PIPE)
                proc.communicate(input=rendered.encode("utf-8"))
            except Exception:
                console.print(full_text, highlight=False)
        else:
            console.print(
                f"[dim]{_('Note: No pager defined, printing to stdout')}[/dim]"
            )
            console.print(full_text, highlight=False)

        return

    elif apt_cmd == "source":
        from .sources import handle_apt_source

        if not extra_args:
            print_error(
                f"[red]{_('E:')}[/red] {_('No packages specified for source download')}"
            )
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
        if shutil.which("pactree"):
            pacman_cmd = ["pactree", "-g"] + extra_args
        else:
            print_error(_("pactree (pacman-contrib) is required for dotty."))
            sys.exit(1)

    elif apt_cmd == "add-repository":
        text = Text()
        text.append(
            _("Adding repositories in Arch Linux differs from Debian/Ubuntu.") + "\n",
            style="bold",
        )
        text.append(
            _("You need to edit /etc/pacman.conf and add a [section].") + "\n\n"
        )

        text.append(f"{_('Example')} (Chaotic AUR):\n", style="bold green")
        text.append("[chaotic-aur]\n")
        text.append("Include = /etc/pacman.d/chaotic-mirrorlist\n\n")

        text.append(f"{_('Example (Generic)')}:\n", style="bold green")
        text.append("[repo-name]\n")
        text.append("Server = https://example.com/$arch\n")
        text.append("SigLevel = Required DatabaseOptional\n\n")

        text.append(
            f"{_('N:')} {_('You may need to import GPG keys first using apt-key (pacman-key).')}\n",
            style="magenta",
        )

        panel_box = box.ASCII if ui.is_linux_console(console) else box.ROUNDED
        console.print(
            Panel(
                text,
                title=_("How to add a repository"),
                border_style="blue",
                box=panel_box,
            )
        )

        if _confirm_yes(f"\n{_('Do you want to edit /etc/pacman.conf now?')} [Y/n] "):
            editor = get_editor()
            if os.getuid() == 0:
                cmd = [editor, "/etc/pacman.conf"]
            else:
                cmd = aur.get_privilege_command("root", [editor, "/etc/pacman.conf"])

            print_command(f"Running: {' '.join(cmd)}")
            try:
                subprocess.run(cmd, check=True)
            except (subprocess.CalledProcessError, OSError) as e:
                if isinstance(e, OSError):
                    print_error(
                        f"[bold red]{_('E:')}[/bold red] {_('Failed to launch editor: ')}{escape(str(e))}"
                    )
                sys.exit(1)
        return

    elif apt_cmd == "madison":
        targets = [a for a in extra_args if not a.startswith("-")]
        if not targets:
            print_error(f"[red]{_('E:')}[/red] {_('No package specified')}")
            return

        rows = []
        for pkg in targets:
            local_pkg = alpm_helper.get_local_package(pkg)
            if local_pkg:
                rows.append((pkg, local_pkg.version, "installed"))

            remote_pkg = alpm_helper.get_package(pkg)
            if remote_pkg:
                repo = (
                    remote_pkg.db.name
                    if hasattr(remote_pkg, "db") and remote_pkg.db
                    else "unknown"
                )
                rows.append((pkg, remote_pkg.version, repo))

        if not rows:
            for pkg in targets:
                console.print(f"[bold]{escape(pkg)}:[/bold]", highlight=False)
            return

        term_width = ui.get_terminal_width(console)
        if term_width < 60:
            for pkg_name, ver_val, src_val in rows:
                console.print(
                    f"[bold green]{escape(pkg_name)}[/bold green] | [bold]{escape(ver_val)}[/bold] | [blue]{escape(src_val)}[/blue]",
                    highlight=False,
                    overflow="fold",
                )
        else:
            madison_table = Table.grid(padding=(0, 1), pad_edge=False)
            madison_table.add_column(style="bold green", no_wrap=True)
            madison_table.add_column(style="dim", no_wrap=True)
            madison_table.add_column(style="bold", no_wrap=True)
            madison_table.add_column(style="dim", no_wrap=True)
            madison_table.add_column(style="blue", overflow="fold")
            for pkg_name, ver_val, src_val in rows:
                madison_table.add_row(pkg_name, "|", ver_val, "|", src_val)
            console.print(madison_table, highlight=False)
        return

    elif apt_cmd == "config":
        # Get program name from arguments, default to pacman
        program = extra_args[0] if extra_args else "pacman"

        found_configs = []

        # Special handling for specific programs
        if program == "pacman":
            if os.path.exists("/etc/pacman.conf"):
                found_configs.append("/etc/pacman.conf")
        elif program in ["apt-pac", "aptpac"]:
            # Show apt-pac's own config files
            if os.path.exists("/etc/apt-pac/config.toml"):
                found_configs.append("/etc/apt-pac/config.toml")
            user_config = (
                str(config.user_config_path)
                if getattr(config, "user_config_path", None)
                else os.path.expanduser("~/.config/apt-pac/config.toml")
            )
            if os.path.exists(user_config):
                found_configs.append(user_config)
        else:
            # Generic search for other programs
            search_paths = [
                f"/etc/{program}.conf",
                f"/etc/{program}/config",
                f"/etc/{program}/{program}.conf",
                os.path.expanduser(f"~/.config/{program}/config.toml"),
                os.path.expanduser(f"~/.config/{program}/config"),
                os.path.expanduser(f"~/.config/{program}/{program}.conf"),
                os.path.expanduser(f"~/.{program}rc"),
                os.path.expanduser(f"~/.{program}.conf"),
            ]

            # For hyphenated programs (e.g., pacman-mirrorlist), check {base}.d/{suffix}
            if "-" in program:
                parts = program.split("-", 1)
                base, suffix = parts[0], parts[1]
                search_paths.extend(
                    [
                        f"/etc/{base}.d/{suffix}",
                        f"/etc/{base}.d/{suffix}.conf",
                    ]
                )

            for path in search_paths:
                if os.path.exists(path):
                    found_configs.append(path)

        # Display results
        if found_configs:
            console.print(
                f"{_('Configuration files for')} [bold]{escape(str(program))}[/bold]"
            )
            console.print()
            for config_path in found_configs:
                console.print(f"    {escape(str(config_path))}")
            console.print()
            console.print(f"{_('Use your favorite editor to edit them.')}")
        else:
            # Check if program is installed
            is_installed = bool(shutil.which(program))

            if not is_installed:
                console.print(
                    f"{_('Program')} [bold]{escape(str(program))}[/bold] {_('is not installed')}"
                )
            else:
                console.print(
                    f"{_('No configuration file found for')} [bold]{escape(str(program))}[/bold]"
                )

        return

    elif apt_cmd in ["apt-key", "key"]:
        if not extra_args:
            console.print(
                f"\n[bold]{_('Usage:')}[/bold] apt-key [add|list|del|adv] ...\n"
            )
            console.print(f"[bold]{_('Examples:')}[/bold]")
            console.print(f"  apt-key add <keyfile>     - {_('Import GPG key')}")
            console.print(f"  apt-key list              - {_('List all keys')}")
            console.print(f"  apt-key del <keyid>       - {_('Remove key')}\n")
            console.print(
                f"[magenta]{_('N:')}[/magenta] {_('This is a wrapper for pacman-key')}"
            )
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
            # Pass arguments through to pacman-key (stripping literal 'adv')
            pacman_cmd = ["pacman-key"] + extra_args[1:]
        else:
            print_error(
                f"[red]{_('E:')}[/red] {_('Unknown apt-key command: ')}{escape(str(sub))}"
            )
            return

        # For add/del, apt-key only prints "OK" on success
        if sub in ["add", "del", "delete", "remove"]:
            try:
                subprocess.run(pacman_cmd, check=True, capture_output=True)
                print("OK")
            except subprocess.CalledProcessError as e:
                if isinstance(e.stderr, bytes):
                    err_msg = e.stderr.decode("utf-8", errors="replace")
                elif e.stderr:
                    err_msg = str(e.stderr)
                else:
                    err_msg = f"Error running {' '.join(pacman_cmd)}\n"
                sys.stderr.write(err_msg)
                if not err_msg.endswith("\n"):
                    sys.stderr.write("\n")
                sys.exit(e.returncode)
            except OSError as e:
                print_error(
                    f"[bold red]{_('E:')}[/bold red] {_('Failed to execute pacman-key: ')}{escape(str(e))}"
                )
                sys.exit(1)
        else:
            # list/adv pass through directly
            try:
                subprocess.run(pacman_cmd)
            except OSError as e:
                print_error(
                    f"[bold red]{_('E:')}[/bold red] {_('Failed to execute pacman-key: ')}{escape(str(e))}"
                )
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
        if not shutil.which("man"):
            print_error(_("E: man is not installed"))
            print_info(_("Install man-db or man-pages to use this feature"))
            sys.exit(1)

        # Try to show manpage for package
        try:
            result = subprocess.run(["man", package_name], capture_output=False)
        except OSError as e:
            print_error(
                f"[bold red]{_('E:')}[/bold red] {_('Failed to launch man: ')}{escape(str(e))}"
            )
            sys.exit(1)
        if result.returncode != 0:
            # Manpage not found
            console.print(
                f"[yellow]W:[/yellow] {_('No manual entry for')} {escape(str(package_name))}"
            )
            console.print(f"{_('Try:')} apt-pac show {escape(str(package_name))}")
            sys.exit(1)
        return

    elif apt_cmd == "edit-sources":
        editor = get_editor()
        cmd = [editor, "/etc/pacman.conf"]
        print_command(f"Running: {' '.join(cmd)}")
        try:
            subprocess.run(cmd, check=True)
            return
        except (subprocess.CalledProcessError, OSError) as e:
            if isinstance(e, OSError):
                print_error(
                    f"[bold red]{_('E:')}[/bold red] {_('Failed to launch editor: ')}{escape(str(e))}"
                )
            sys.exit(1)

    # If pacman_cmd was not set by a special handler above, set it now
    if "pacman_cmd" not in locals():
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

        if apt_cmd == "search":
            queries = [arg for arg in extra_args if not arg.startswith("-")]
            if not queries:
                print_error(
                    f"[bold red]{_('E:')}[/bold red] {_('You must give at least one search pattern')}"
                )
                return

        # Official Search
        if scope in ["both", "official"] and apt_cmd == "search":
            # Use native pyalpm search instead of subprocess

            # Extract query from extra_args
            queries = [arg for arg in extra_args if not arg.startswith("-")]
            if queries:
                query = queries[0] if len(queries) == 1 else " ".join(queries)
                try:
                    results = alpm_helper.search_packages(query)
                    if results:
                        if show_output in ["apt-pac", "apt"]:
                            # Get installed packages once for efficient lookup
                            installed_pkgs = set(
                                pkg.name for pkg in alpm_helper.get_installed_packages()
                            )

                            # Convert pyalpm results to pacman -Ss format for format_search_results
                            pacman_style_output = []
                            for pkg in results:
                                repo = pkg.db.name if hasattr(pkg, "db") else "unknown"
                                is_installed = pkg.name in installed_pkgs
                                status = " [installed]" if is_installed else ""

                                header = f"{repo}/{pkg.name} {pkg.version}{status}"
                                desc = f"    {pkg.desc}"

                                pacman_style_output.append(header)
                                pacman_style_output.append(desc)

                            format_search_results("\n".join(pacman_style_output))
                        else:
                            # Pacman-style output
                            installed_pkgs = set(
                                pkg.name for pkg in alpm_helper.get_installed_packages()
                            )
                            for pkg in results:
                                repo = pkg.db.name if hasattr(pkg, "db") else "unknown"
                                is_installed = pkg.name in installed_pkgs
                                status = " [installed]" if is_installed else ""
                                print(f"{repo}/{pkg.name} {pkg.version}{status}")
                                print(f"    {pkg.desc}")
                except Exception as e:
                    print_error(
                        f"[bold red]{_('E:')}[/bold red] {_('Search error:')} {escape(str(e))}"
                    )

        # AUR Search
        if scope in ["both", "aur"] and apt_cmd == "search":
            queries = [arg for arg in extra_args if not arg.startswith("-")]
            if queries:
                query = queries[0] if len(queries) == 1 else " ".join(queries)
                with ui.status("[magenta]Searching AUR...[/magenta]", spinner="dots"):
                    matches = aur.search_aur(query)
                if matches:
                    format_aur_search_results(matches)

        # Show Command (Official -> Local -> AUR)
        if apt_cmd == "show":
            queries = [arg for arg in extra_args if not arg.startswith("-")]
            if not queries:
                print_error(_("No package specified"))
                return

            missing_official = []
            for pkgname in queries:
                formatted, source = alpm_helper.get_package_info_formatted(pkgname)
                if formatted:
                    if show_output in ["apt-pac", "apt"]:
                        format_show(formatted)
                    else:
                        print(formatted)
                else:
                    missing_official.append(pkgname)

            if missing_official:
                with ui.status(
                    "[magenta]Checking AUR...[/magenta]", spinner="dots"
                ):
                    aur_info = aur.get_aur_info(missing_official)

                found_aur_names = set()
                if aur_info:
                    from .ui import format_aur_info

                    format_aur_info(aur_info)
                    found_aur_names = {pkg.get("Name") for pkg in aur_info}

                still_missing = [
                    p for p in missing_official if p not in found_aur_names
                ]
                if still_missing:
                    print_error(
                        f"[bold red]{_('E:')}[/bold red] {_('Package')} '{escape(' '.join(still_missing))}' {_('not found in repositories, local database, or')} AUR."
                    )

        return

    show_output_mode = config.get("ui", "show_output", "apt-pac")

    # Show summary for install (skip for local files where pacman -Sp doesn't apply)
    if apt_cmd in ["install"] and (is_simulation or show_output_mode != "pacman"):
        if is_simulation:
            if locals().get("is_local_install", False):
                print_info(f"Simulation: pacman -U {' '.join(extra_args)}")
            else:
                show_summary(apt_cmd, extra_args, auto_confirm=True)
            return
        if not locals().get("is_local_install", False):
            summary_result = show_summary(
                apt_cmd, extra_args, auto_confirm=auto_confirm
            )

            if (summary_result or auto_confirm) and "--noconfirm" not in pacman_cmd:
                pacman_cmd.append("--noconfirm")
        elif auto_confirm and "--noconfirm" not in pacman_cmd:
            pacman_cmd.append("--noconfirm")

    if is_simulation:
        if apt_cmd == "update":
            print_info("Simulation: pacman -Sy")
            if config.get("defaults", "always_sync_files", True):
                print_info("Simulation: pacman -Fy")
            return
        if apt_cmd in ["remove", "purge", "autoremove"]:
            check_safeguards(apt_cmd, extra_args, is_simulation=False, auto_confirm=True)
            return
        if apt_cmd not in ["upgrade", "dist-upgrade", "full-upgrade"]:
            print_info(f"Simulation: {' '.join(pacman_cmd)}")
            return

    # Apply download-only flag
    if download_only and apt_cmd in [
        "install",
        "upgrade",
        "dist-upgrade",
        "full-upgrade",
    ]:
        if "-S" in pacman_cmd or "-Syu" in pacman_cmd or "-Sy" in pacman_cmd:
            pacman_cmd.append("-w")

    # Check if user wants to see the pacman command
    if config.get("ui", "show_pacman_command", False) or verbose:
        print_command(f"Running: {' '.join(pacman_cmd)}")

    # Apply quiet flags to pacman
    if quiet_level >= 1:
        pacman_cmd.append("-q")
    if quiet_level >= 2:
        pacman_cmd.append("-q")

    # Apply force_colors only to pacman commands (never to extra_args)
    if force_colors and pacman_cmd and pacman_cmd[0] == "pacman":
        if "--color=always" not in pacman_cmd:
            pacman_cmd.append("--color=always")

    # Apply auto-confirm to pacman
    if auto_confirm:
        if apt_cmd in [
            "install",
            "reinstall",
            "upgrade",
            "dist-upgrade",
            "full-upgrade",
            "remove",
            "purge",
            "autoremove",
        ]:
            if "--noconfirm" not in pacman_cmd:
                pacman_cmd.append("--noconfirm")

    if apt_cmd in ["remove", "purge", "autoremove"]:
        if not is_simulation:
            if "--noconfirm" not in pacman_cmd:
                pacman_cmd.append("--noconfirm")

    try:
        current_cmd = list(pacman_cmd)
        if apt_cmd in [
            "install",
            "reinstall",
            "upgrade",
            "dist-upgrade",
            "full-upgrade",
            "remove",
            "purge",
            "autoremove",
        ]:
            if "--noconfirm" in pacman_cmd:
                pass
            elif auto_confirm:
                current_cmd.append("--noconfirm")

        # Special case for update and upgrade: sync files as well
        if apt_cmd == "update":
            if show_output_mode == "pacman":
                try:
                    res = subprocess.run(current_cmd, check=False)
                except OSError as e:
                    print_error(
                        f"[bold red]{_('E:')}[/bold red] {_('Failed to execute pacman: ')}{escape(str(e))}"
                    )
                    sys.exit(1)
                if isinstance(res.returncode, int) and res.returncode != 0:
                    sys.exit(res.returncode)
                alpm_helper.reset_handle()
                if config.get("defaults", "always_sync_files", True):
                    sync_cmd = ["pacman", "-Fy"]
                    if force_colors:
                        sync_cmd.append("--color=always")
                    if quiet_level >= 1:
                        sync_cmd.append("-q")
                    try:
                        subprocess.run(sync_cmd, check=False)
                    except OSError:
                        pass
                return

            sync_databases(
                pacman_cmd, quiet=quiet_level, include_aur=not only_official
            )
            alpm_helper.reset_handle()

            # Run the file sync pacman -Fy
            if config.get("defaults", "always_sync_files", True):
                sync_cmd = ["pacman", "-Fy"]
                if force_colors:
                    sync_cmd.append("--color=always")
                if quiet_level >= 1:
                    sync_cmd.append("-q")
                run_pacman_with_apt_output(sync_cmd, show_hooks=False, quiet=quiet_level)

            console.print(
                f"\n{_('Reading package lists')}... [green]{_('Done')}[/green]",
                highlight=False,
            )
            if only_aur:
                msg = (
                    f"[magenta]{_('N:')}[/magenta] "
                    + _("'update --aur' simply checks official DBs as")
                    + " AUR "
                    + _("has no central DB to sync.")
                )
                print_info(msg)
            return

        elif apt_cmd in ["upgrade", "dist-upgrade", "full-upgrade"]:
            # Smart logic for flags
            run_official = True
            run_aur = True

            if apt_cmd in ["dist-upgrade", "full-upgrade"]:
                run_official = True
                run_aur = True
                if only_official or only_aur:
                    print_info(
                        f"{_('Ignoring selective flags for')} {apt_cmd}: {_('performing full system upgrade.')}"
                    )
            else:
                if only_official:
                    run_aur = False
                if only_aur:
                    run_official = False

            if show_output_mode == "pacman" and not is_simulation:
                if run_official:
                    try:
                        res = subprocess.run(current_cmd, check=False)
                    except OSError as e:
                        print_error(
                            f"[bold red]{_('E:')}[/bold red] {_('Failed to execute pacman: ')}{escape(str(e))}"
                        )
                        sys.exit(1)
                    if isinstance(res.returncode, int) and res.returncode != 0:
                        sys.exit(res.returncode)
                    alpm_helper.reset_handle()
                    if config.get("defaults", "always_sync_files", True):
                        sync_cmd = ["pacman", "-Fy"]
                        if force_colors:
                            sync_cmd.append("--color=always")
                        if quiet_level >= 1:
                            sync_cmd.append("-q")
                        try:
                            subprocess.run(sync_cmd, check=False)
                        except OSError:
                            pass
                if run_aur:
                    try:
                        aur_updates = aur.check_updates(verbose=verbose)
                        if aur_updates:
                            aur_candidates = [u["name"] for u in aur_updates]
                            aur.AurInstaller().install(
                                aur_candidates, verbose=verbose, auto_confirm=auto_confirm
                            )
                    except Exception as e:
                        print_error(
                            f"[bold red]{_('E:')}[/bold red] "
                            + _("AUR Upgrade failed: {error}").format(
                                error=escape(str(e))
                            )
                        )
                        sys.exit(1)
                return

            aur_new = []
            aur_upgrades = []
            aur_candidates = []
            aur_build_queue = []
            official_deps_for_aur = []

            if run_official and not is_simulation:
                # 1. Sync DB first, then refresh pyalpm handle
                sync_databases(quiet=quiet_level, include_aur=run_aur)
                alpm_helper.reset_handle()

            # Check for AUR updates EARLY (Pre-calc)
            if run_aur:
                try:
                    aur_updates = aur.check_updates(verbose=verbose)

                    if aur_updates:
                        aur_candidates = [u["name"] for u in aur_updates]
                        resolver = aur.AurResolver()
                        with ui.status(
                            f"[blue]{_('Resolving')} AUR {_('dependencies...')}[/blue]",
                            spinner="dots",
                        ):
                            aur_build_queue = resolver.resolve(aur_candidates)

                        official_deps_for_aur = resolver.official_deps
                        full_aur_info = aur.get_resolved_package_info(
                            aur_build_queue, resolver.official_deps
                        )

                        candidate_set = set(aur_candidates)
                        for name, ver in full_aur_info:
                            if name in candidate_set:
                                old_ver = _("unknown")
                                for u in aur_updates:
                                    if u["name"] == name:
                                        old_ver = u.get("current", _("unknown"))
                                        break
                                aur_upgrades.append((name, old_ver, ver))
                            else:
                                aur_new.append((name, ver))
                    else:
                        console.print(f"{_('All')} AUR {_('packages are up to date.')}")
                except Exception as e:
                    print_error(
                        f"[bold red]{_('E:')}[/bold red] {_('Failed to check')} AUR {_('updates:')} {escape(str(e))}"
                    )
                    aur_candidates = []

            # 2. Show Summary (Unified)
            user_confirmed_summary = False
            proceed = show_summary(
                apt_cmd,
                extra_args,
                auto_confirm=True if is_simulation else auto_confirm,
                aur_new=aur_new,
                aur_upgrades=aur_upgrades,
                skip_official=not run_official,
            )
            if is_simulation:
                return
            if not proceed:
                return
            user_confirmed_summary = True

            if "--noconfirm" not in current_cmd:
                current_cmd.append("--noconfirm")

            # 3. Simulate Download Output (Get: ...)
            sim_cmd = ["pacman", "-Su"]
            total_pkgs = 0
            if not is_simulation and run_official:
                count = simulate_apt_download_output(sim_cmd, config)
                if count:
                    total_pkgs = count

            # 4. Execute Upgrade (Official)
            if run_official:
                exec_cmd = ["pacman", "-Su"]
                for arg in extra_args:
                    if arg not in ["-Syu", "-Sy", "-u"]:
                        exec_cmd.append(arg)

                if (
                    user_confirmed_summary
                    or auto_confirm
                    or "--noconfirm" in current_cmd
                ):
                    if "--noconfirm" not in exec_cmd:
                        exec_cmd.append("--noconfirm")
                if force_colors and "--color=always" not in exec_cmd:
                    exec_cmd.append("--color=always")
                if verbose:
                    exec_cmd.append("--verbose")
                if quiet_level > 0:
                    exec_cmd.append("-q")

                success = run_pacman_with_apt_output(
                    exec_cmd,
                    show_hooks=True,
                    total_pkgs=total_pkgs,
                    quiet=quiet_level,
                )
                if not success:
                    print_error(_("Upgrade failed"))
                    sys.exit(1)
            else:
                if not run_aur:
                    console.print(
                        f"[dim]{_('Skipping official packages upgrade (--aur provided)')}[/dim]"
                    )

            # 5. Execute Upgrade (AUR)
            if run_aur and aur_candidates:
                try:
                    installer = aur.AurInstaller()
                    installer.install(
                        aur_candidates,
                        verbose=verbose,
                        auto_confirm=auto_confirm,
                        build_queue=aur_build_queue,
                        official_deps=official_deps_for_aur,
                        skip_summary=True,
                        confirm_pacman=True,
                    )
                except Exception as e:
                    print_error(
                        f"[bold red]{_('E:')}[/bold red] "
                        + _("AUR Upgrade failed: {error}").format(
                            error=escape(str(e))
                        )
                    )

            if not run_aur:
                console.print(
                    f"\n[dim]{_('Skipping')} AUR {_('updates (--official provided)')}[/dim]"
                )

            # Sync file database if configured
            if run_official and config.get("defaults", "always_sync_files", True):
                console.print(
                    f"\n{_('Updating package file list (pacman -Fy)...')}",
                    highlight=False,
                )
                sync_cmd = ["pacman", "-Fy"]
                if force_colors:
                    sync_cmd.append("--color=always")
                if quiet_level >= 1:
                    sync_cmd.append("-q")
                run_pacman_with_apt_output(sync_cmd, show_hooks=False, quiet=quiet_level)
            return

        else:
            # For install/reinstall/remove/purge/autoremove: use APT-style output unless show_output == "pacman"
            if (
                apt_cmd in ["install", "reinstall", "remove", "purge", "autoremove"]
                and show_output_mode != "pacman"
            ):
                total_pkgs = None
                if (
                    apt_cmd in ["install", "reinstall"]
                    and not is_simulation
                    and not locals().get("is_local_install", False)
                ):
                    count = simulate_apt_download_output(current_cmd, config)
                    if isinstance(count, int) and count > 0:
                        total_pkgs = count
                success = run_pacman_with_apt_output(
                    current_cmd,
                    show_hooks=True,
                    total_pkgs=total_pkgs,
                    quiet=quiet_level,
                )
                if not success:
                    sys.exit(1)
            else:
                # Run directly without output capture - shows pacman's normal output
                try:
                    res = subprocess.run(current_cmd, check=False)
                except OSError as e:
                    print_error(
                        f"[bold red]{_('E:')}[/bold red] {_('Failed to execute command: ')}{escape(str(e))}"
                    )
                    sys.exit(1)
                if isinstance(res.returncode, int) and res.returncode != 0:
                    sys.exit(res.returncode)

    except subprocess.CalledProcessError:
        sys.exit(1)
