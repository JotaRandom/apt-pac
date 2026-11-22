"""
Source package management for apt-pac.

Handles downloading and managing PKGBUILDs from official Arch repositories
using the Arch Build System (ABS) via pkgctl (from devtools package).

Handles downloading and managing PKGBUILDs from official Arch repositories
using the Arch Build System (ABS) and the AUR.
"""

import shutil
import subprocess
from pathlib import Path

from rich.markup import escape

from .config import get_config
from .i18n import _
from .ui import console, print_error, print_info, print_showsrc_info

_SRCINFO_LIST_KEYS = {
    "pkgname",
    "arch",
    "license",
    "depends",
    "makedepends",
    "checkdepends",
    "optdepends",
    "provides",
    "conflicts",
    "replaces",
    "source",
}

_SRCINFO_SCALAR_KEYS = {"pkgbase", "pkgver", "pkgrel", "epoch", "pkgdesc", "url"}


def _parse_srcinfo(srcinfo_path: Path) -> dict | None:
    """
    Parse a .SRCINFO file safely in pure Python without executing bash.
    Returns parsed metadata dict or None if missing/unreadable/empty.
    """
    if not srcinfo_path.is_file():
        return None
    try:
        text = srcinfo_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    info: dict = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip()
        if not val:
            continue

        base_key = key.split("_", 1)[0]
        if base_key in _SRCINFO_LIST_KEYS and key == base_key:
            info.setdefault(key, [])
            if val not in info[key]:
                info[key].append(val)
        elif key in _SRCINFO_SCALAR_KEYS:
            info[key] = val

    if not info:
        return None
    return info


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
    try:
        result = subprocess.run(
            ["pacman", "-Si", package_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return result.returncode == 0
    except OSError:
        return False


def download_source(package_name, verbose=False):
    """
    Download PKGBUILD for a package from official repos using pkgctl.

    Returns the path to the downloaded source directory, or None on failure.
    """
    if verbose:
        console.print(f"[dim]{_('Checking for pkgctl availability...')}[/dim]")

    if not check_pkgctl_available():
        return None

    sources_dir = get_sources_dir()
    if not sources_dir:
        return None

    # Check if package exists
    if not check_package_in_repos(package_name):
        print_error(
            f"[red]{_('E:')}[/red] {_('Unable to find a source package for {pkg}').format(pkg=escape(str(package_name)))}"
        )
        return None

    pkg_dir = sources_dir / package_name

    # Remove old version if exists
    if pkg_dir.exists():
        print_info(f"{_('Updating source for')} {escape(str(package_name))}...")
        shutil.rmtree(pkg_dir)
    else:
        print_info(f"{_('Getting source for')} {escape(str(package_name))}...")

    # Use pkgctl to clone the git repository
    try:
        result = subprocess.run(
            ["pkgctl", "repo", "clone", "--protocol", "https", package_name],
            cwd=sources_dir,
            capture_output=True,
            text=True,
        )
    except OSError as e:
        print_error(
            f"[red]{_('E:')}[/red] {_('Failed to download source for {pkg}: {err}').format(pkg=escape(str(package_name)), err=escape(str(e)))}"
        )
        return None

    if result.returncode != 0:
        print_error(
            f"[red]{_('E:')}[/red] {_('Failed to download source for {pkg}').format(pkg=escape(str(package_name)))}"
        )
        if result.stderr:
            print_error(escape(result.stderr.strip()))
        return None

    if pkg_dir.exists() and (pkg_dir / "PKGBUILD").exists():
        console.print(f"{_('Source downloaded to:')} {escape(str(pkg_dir))}")
        return pkg_dir
    else:
        print_error(
            f"[red]{_('E:')}[/red] {_('Source download incomplete for {pkg}').format(pkg=escape(str(package_name)))}"
        )
        return None


def get_source_dir(package_name):
    """Get the source directory for a package (ABS or AUR) if it exists."""
    cache_dir = get_config().get_cache_dir()
    if not cache_dir:
        return None

    for subdir in ("abs", "aur"):
        pkg_dir = cache_dir / "sources" / subdir / package_name
        if pkg_dir.exists() and (pkg_dir / "PKGBUILD").exists():
            return pkg_dir
    return None


def parse_pkgbuild_makedepends(pkgbuild_path) -> list[str]:
    """
    Extract makedepends from .SRCINFO (safe) or PKGBUILD fallback.
    """
    srcinfo_data = _parse_srcinfo(pkgbuild_path.parent / ".SRCINFO")
    if srcinfo_data is not None:
        deps = srcinfo_data.get("makedepends", [])
        return deps if isinstance(deps, list) else [deps]

    if not pkgbuild_path.exists():
        return []

    # Fallback for PKGBUILDs without .SRCINFO: pass path safely via $1
    cmd = [
        "bash",
        "-c",
        'source "$1" && printf "%s\\n" "${makedepends[@]}"',
        "_",
        str(pkgbuild_path),
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
    Extract basic info from .SRCINFO (safe) or PKGBUILD fallback.

    Returns a dict with pkgname, pkgver, pkgrel, pkgdesc, etc.
    """
    srcinfo_data = _parse_srcinfo(pkgbuild_path.parent / ".SRCINFO")
    if srcinfo_data is not None:
        normalized = {}
        for k, v in srcinfo_data.items():
            if isinstance(v, list) and len(v) == 1:
                normalized[k] = v[0]
            else:
                normalized[k] = v
        return normalized

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

    cmd = [
        "bash",
        "-c",
        'source "$1" && ' + " && ".join(bash_commands),
        "_",
        str(pkgbuild_path),
    ]

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
    del extra_args
    if verbose:
        msg = _("Checking if {pkg} exists in repos...").format(
            pkg=escape(str(package_name))
        )
        console.print(f"[dim]{msg}[/dim]")

    # Download the source
    pkg_dir = download_source(package_name, verbose=verbose)

    if not pkg_dir:
        # Try AUR
        from .aur import download_aur_source

        if verbose:
            msg = _("Checking AUR for {pkg}...").format(
                pkg=escape(str(package_name))
            )
            console.print(f"[dim]{msg}[/dim]")
        pkg_dir = download_aur_source(package_name)

    if pkg_dir:
        print_info(_("\nYou can build this package with:"))
        print_info(f"  cd {pkg_dir}")
        print_info("  makepkg -si")
        if verbose:
            console.print(f"[dim]{_('Source directory:')} {escape(str(pkg_dir))}[/dim]")
            console.print(
                f"[dim]{_('PKGBUILD location:')} {escape(str(pkg_dir / 'PKGBUILD'))}[/dim]"
            )
        return True

    if verbose:
        print_error(
            f"[red]{_('E:')}[/red] {_('Failed to find source for {pkg} in').format(pkg=escape(str(package_name)))} ABS or AUR"
        )
    return False


def handle_build_dep(package_name, verbose=False):
    """Handle 'apt build-dep <package>' command."""
    if verbose:
        console.print(
            f"[dim]{_('Looking for source package:')} {escape(str(package_name))}[/dim]"
        )

    # First, ensure we have the source
    pkg_dir = get_source_dir(package_name)
    if not pkg_dir:
        print_info(
            f"{_('Downloading source for')} {escape(str(package_name))}..."
        )
        pkg_dir = download_source(package_name, verbose=verbose)
        if not pkg_dir:
            # Try AUR
            from .aur import download_aur_source

            pkg_dir = download_aur_source(package_name)

            if not pkg_dir:
                return False
    elif verbose:
        console.print(
            f"[dim]{_('Found cached source at')} {escape(str(pkg_dir))}[/dim]"
        )

    # Parse PKGBUILD for makedepends
    pkgbuild = pkg_dir / "PKGBUILD"

    if verbose:
        console.print(
            f"[dim]{_('Parsing PKGBUILD:')} {escape(str(pkgbuild))}[/dim]"
        )

    makedepends = parse_pkgbuild_makedepends(pkgbuild)

    if not makedepends:
        console.print(
            f"[green]{_('No build dependencies required for')} {escape(str(package_name))}[/green]"
        )
        if verbose:
            console.print(
                f"[dim]{_('Checked PKGBUILD makedepends array - empty')}[/dim]"
            )
        return True

    console.print(f"\n[bold]{_('The following packages will be installed:')}[/bold]")
    console.print(f"  {escape(' '.join(makedepends))}\n")

    if verbose:
        msg = _("Found {count} build dependencies").format(count=len(makedepends))
        console.print(f"[dim]{msg}[/dim]")
        for dep in makedepends:
            console.print(f"[dim]  - {escape(str(dep))}[/dim]")

    # Install makedepends using apt-pac install
    from .commands import execute_command

    try:
        if verbose:
            console.print(f"[dim]{_('Installing build dependencies...')}[/dim]")
        execute_command("install", makedepends)
        return True
    except Exception as e:
        print_error(
            _("Failed to install build dependencies: {error}").format(
                error=escape(str(e))
            )
        )
        return False


def handle_showsrc(package_name, verbose=False):
    """Handle 'apt-cache showsrc <package>' command."""
    if verbose:
        console.print(
            f"[dim]{_('Looking for source info:')} {escape(str(package_name))}[/dim]"
        )

    # Try to get existing source
    pkg_dir = get_source_dir(package_name)

    if not pkg_dir:
        # Not cached, try to download
        print_info(
            f"{_('Source not cached, downloading')} {escape(str(package_name))}..."
        )
        pkg_dir = download_source(package_name, verbose=verbose)
        if not pkg_dir:
            # Try AUR
            from .aur import download_aur_source

            pkg_dir = download_aur_source(package_name)

            if not pkg_dir:
                return False
    elif verbose:
        console.print(f"[dim]{_('Using cached source:')} {escape(str(pkg_dir))}[/dim]")

    # Parse PKGBUILD info
    pkgbuild = pkg_dir / "PKGBUILD"

    if verbose:
        console.print(f"[dim]{_('Parsing PKGBUILD info...')}[/dim]")

    info = parse_pkgbuild_info(pkgbuild)

    if not info:
        print_error(f"[red]{_('E:')}[/red] {_('Failed to parse PKGBUILD')}")
        return False

    # Display info in APT style
    print_showsrc_info(package_name, info, pkg_dir)

    return True
