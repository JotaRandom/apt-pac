"""
Source package management for apt-pac.

Handles downloading and managing PKGBUILDs from official Arch repositories
using the Arch Build System (ABS) via pkgctl (from devtools package).

Handles downloading and managing PKGBUILDs from official Arch repositories
using the Arch Build System (ABS) and the AUR.
"""

import subprocess
import shutil
from .config import get_config
from .ui import print_error, print_info, console
from .i18n import _


def check_pkgctl_available():
    """Check if pkgctl tool is installed (part of devtools package)."""
    if not shutil.which("pkgctl"):
        print_error(f"[red]{_('E:')}[/red] {_('pkgctl not installed')}")
        print_info(f"{_('Install with:')} sudo pacman -S devtools")
        return False
    return True


def get_sources_dir():
    """Get the sources cache directory."""
    cache_dir = get_config().get_cache_dir()
    if not cache_dir:
        print_error(f"[red]{_('E:')}[/red] {_('Cache directory not available')}")
        print_error(
            f"[yellow]{_('W:')}[/yellow] {_('Cannot download source packages on read-only system')}"
        )
        return None

    sources_dir = cache_dir / "sources" / "abs"
    sources_dir.mkdir(parents=True, exist_ok=True)
    return sources_dir


def check_package_in_repos(package_name):
    """Check if package exists in official repositories."""
    result = subprocess.run(
        ["pacman", "-Si", package_name], capture_output=True, stderr=subprocess.DEVNULL
    )
    return result.returncode == 0


def download_source(package_name, verbose=False):
    """
    Download PKGBUILD for a package from official repos using pkgctl.

    Returns the path to the downloaded source directory, or None on failure.
    """
    if verbose:
        console.print("[dim]Checking for pkgctl availability...[/dim]")

    if not check_pkgctl_available():
        return None

    sources_dir = get_sources_dir()
    if not sources_dir:
        return None

    # Check if package exists
    if not check_package_in_repos(package_name):
        print_error(
            f"[red]{_('E:')}[/red] {_(f'Unable to find a source package for {package_name}')}"
        )
        return None

    pkg_dir = sources_dir / package_name

    # Remove old version if exists
    if pkg_dir.exists():
        print_info(f"{_('Updating source for')} {package_name}...")
        shutil.rmtree(pkg_dir)
    else:
        print_info(f"{_('Getting source for')} {package_name}...")

    # Use pkgctl to clone the git repository
    result = subprocess.run(
        ["pkgctl", "repo", "clone", package_name],
        cwd=sources_dir,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print_error(
            f"[red]{_('E:')}[/red] {_(f'Failed to download source for {package_name}')}"
        )
        if result.stderr:
            print_error(result.stderr.strip())
        return None

    if pkg_dir.exists() and (pkg_dir / "PKGBUILD").exists():
        console.print(f"{_('Source downloaded to:')} {pkg_dir}")
        return pkg_dir
    else:
        print_error(
            f"[red]{_('E:')}[/red] {_(f'Source download incomplete for {package_name}')}"
        )
        return None


def get_source_dir(package_name):
    """Get the source directory for a package if it exists."""
    sources_dir = get_sources_dir()
    if not sources_dir:
        return None

    pkg_dir = sources_dir / package_name
    if pkg_dir.exists() and (pkg_dir / "PKGBUILD").exists():
        return pkg_dir
    return None


def parse_pkgbuild_makedepends(pkgbuild_path):
    """
    Extract makedepends from PKGBUILD.

    Uses bash to source the PKGBUILD and extract the makedepends array.
    """
    if not pkgbuild_path.exists():
        return []

    # Use bash to source PKGBUILD and print makedepends
    cmd = [
        "bash",
        "-c",
        f"source '{pkgbuild_path}' && printf '%s\\n' \"${{makedepends[@]}}\"",
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)

        if result.returncode == 0 and result.stdout.strip():
            # Split by newlines and filter empty
            deps = [d.strip() for d in result.stdout.strip().split("\n") if d.strip()]
            return deps
        return []
    except (subprocess.TimeoutExpired, Exception):
        return []


def parse_pkgbuild_info(pkgbuild_path):
    """
    Extract basic info from PKGBUILD.

    Returns a dict with pkgname, pkgver, pkgrel, pkgdesc, etc.
    """
    if not pkgbuild_path.exists():
        return {}

    # Extract common variables
    vars_to_extract = [
        "pkgname",
        "pkgver",
        "pkgrel",
        "pkgdesc",
        "arch",
        "url",
        "license",
        "depends",
        "makedepends",
    ]

    # Build bash command to extract all variables
    bash_commands = []
    for var in vars_to_extract:
        bash_commands.append(
            f"echo '{var}:' && printf '%s\\n' \"${{{var}[@]}}\" && echo '---'"
        )

    cmd = ["bash", "-c", f"source '{pkgbuild_path}' && " + " && ".join(bash_commands)]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)

        if result.returncode != 0:
            return {}

        # Parse output
        info = {}
        current_var = None
        current_values = []

        for line in result.stdout.split("\n"):
            line = line.strip()
            if line.endswith(":"):
                if current_var and current_values:
                    # Save previous variable
                    if len(current_values) == 1:
                        info[current_var] = current_values[0]
                    else:
                        info[current_var] = current_values
                current_var = line[:-1]
                current_values = []
            elif line == "---":
                if current_var and current_values:
                    if len(current_values) == 1:
                        info[current_var] = current_values[0]
                    else:
                        info[current_var] = current_values
                current_var = None
                current_values = []
            elif line and current_var:
                current_values.append(line)

        return info

    except (subprocess.TimeoutExpired, Exception):
        return {}


def handle_apt_source(package_name, extra_args, verbose=False):
    """Handle 'apt source <package>' command."""
    if verbose:
        console.print(f"[dim]Checking if {package_name} exists in repos...[/dim]")

    # Download the source
    pkg_dir = download_source(package_name, verbose=verbose)

    if not pkg_dir:
        # Try AUR
        from .aur import download_aur_source

        if verbose:
            console.print(f"[dim]Checking AUR for {package_name}...[/dim]")
        pkg_dir = download_aur_source(package_name)

    if pkg_dir:
        print_info(_("\nYou can build this package with:"))
        print_info(f"  cd {pkg_dir}")
        print_info("  makepkg -si")
        if verbose:
            console.print(f"[dim]Source directory: {pkg_dir}[/dim]")
            console.print(f"[dim]PKGBUILD location: {pkg_dir / 'PKGBUILD'}[/dim]")
        return True

    if verbose:
        print_error(
            f"[red]{_('E:')}[/red] {_(f'Failed to find source for {package_name} in')} ABS or AUR"
        )
    return False


def handle_build_dep(package_name, verbose=False):
    """Handle 'apt build-dep <package>' command."""
    if verbose:
        console.print(f"[dim]Looking for source package: {package_name}[/dim]")

    # First, ensure we have the source
    pkg_dir = get_source_dir(package_name)
    if not pkg_dir:
        print_info(f"{_('Downloading source for')} {package_name}...")
        pkg_dir = download_source(package_name, verbose=verbose)
        if not pkg_dir:
            # Try AUR
            from .aur import download_aur_source

            pkg_dir = download_aur_source(package_name)

            if not pkg_dir:
                return False
    elif verbose:
        console.print(f"[dim]Found cached source at {pkg_dir}[/dim]")

    # Parse PKGBUILD for makedepends
    pkgbuild = pkg_dir / "PKGBUILD"

    if verbose:
        console.print(f"[dim]Parsing PKGBUILD: {pkgbuild}[/dim]")

    makedepends = parse_pkgbuild_makedepends(pkgbuild)

    if not makedepends:
        console.print(
            f"[green]{_('No build dependencies required for')} {package_name}[/green]"
        )
        if verbose:
            console.print("[dim]Checked PKGBUILD makedepends array - empty[/dim]")
        return True

    console.print(f"\n[bold]{_('The following packages will be installed:')}[/bold]")
    console.print(f"  {' '.join(makedepends)}\n")

    if verbose:
        console.print(f"[dim]Found {len(makedepends)} build dependencies[/dim]")
        for dep in makedepends:
            console.print(f"[dim]  - {dep}[/dim]")

    # Install makedepends using apt-pac install
    from .commands import execute_command

    try:
        if verbose:
            console.print("[dim]Installing build dependencies...[/dim]")
        execute_command("install", makedepends)
        return True
    except Exception as e:
        print_error(_(f"Failed to install build dependencies: {e}"))
        return False


def handle_showsrc(package_name, verbose=False):
    """Handle 'apt-cache showsrc <package>' command."""
    if verbose:
        console.print(f"[dim]Looking for source info: {package_name}[/dim]")

    # Try to get existing source
    pkg_dir = get_source_dir(package_name)

    if not pkg_dir:
        # Not cached, try to download
        print_info(f"{_('Source not cached, downloading')} {package_name}...")
        pkg_dir = download_source(package_name, verbose=verbose)
        if not pkg_dir:
            # Try AUR
            from .aur import download_aur_source

            pkg_dir = download_aur_source(package_name)

            if not pkg_dir:
                return False
    elif verbose:
        console.print(f"[dim]Using cached source: {pkg_dir}[/dim]")

    # Parse PKGBUILD info
    pkgbuild = pkg_dir / "PKGBUILD"

    if verbose:
        console.print("[dim]Parsing PKGBUILD info...[/dim]")

    info = parse_pkgbuild_info(pkgbuild)

    if not info:
        print_error(f"[red]{_('E:')}[/red] {_('Failed to parse PKGBUILD')}")
        return False

    # Display info in APT style
    console.print(f"[bold]Package:[/bold] {info.get('pkgname', package_name)}")
    console.print(
        f"[bold]Version:[/bold] {info.get('pkgver', 'unknown')}-{info.get('pkgrel', '1')}"
    )

    if "pkgdesc" in info:
        console.print(f"[bold]Description:[/bold] {info['pkgdesc']}")

    if "url" in info:
        console.print(f"[bold]Homepage:[/bold] {info['url']}")

    if "license" in info:
        licenses = (
            info["license"] if isinstance(info["license"], list) else [info["license"]]
        )
        console.print(f"[bold]License:[/bold] {', '.join(licenses)}")

    if "arch" in info:
        archs = info["arch"] if isinstance(info["arch"], list) else [info["arch"]]
        console.print(f"[bold]Architecture:[/bold] {', '.join(archs)}")

    if "depends" in info:
        deps = (
            info["depends"] if isinstance(info["depends"], list) else [info["depends"]]
        )
        console.print(f"[bold]Depends:[/bold] {', '.join(deps)}")

    if "makedepends" in info:
        makedeps = (
            info["makedepends"]
            if isinstance(info["makedepends"], list)
            else [info["makedepends"]]
        )
        console.print(f"[bold]Build-Depends:[/bold] {', '.join(makedeps)}")

    console.print(f"\n[bold]Source Directory:[/bold] {pkg_dir}")

    return True
