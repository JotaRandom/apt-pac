from rich.console import Console
from rich.theme import Theme
from rich.table import Table
from rich.panel import Panel
from rich.padding import Padding
from .i18n import _
from rich.text import Text
import contextlib

custom_theme = Theme(
    {
        "info": "bold blue",
        "error": "bold red",
        "success": "bold green",
        "command": "italic cyan",
        "pkg": "bold white",
        "desc": "italic grey70",
        "header": "bold yellow",
    }
)

console = Console(theme=custom_theme)


def set_force_colors(force: bool):
    """Update console to force terminal output (colors) if requested."""
    if force:
        # Re-initialize to strictly force it, or just set option if supported
        global console
        console = Console(
            theme=custom_theme, force_terminal=True, force_interactive=True
        )


def print_info(text):
    """Print info message (no prefix - APT style)."""
    console.print(text, highlight=False)


def print_error(text):
    """Print error message (no prefix - APT style)."""
    try:
        console.print(text, highlight=False)
    except Exception:
        # Fallback if markup fails (e.g. text contains unmatched tags)
        console.print(text, highlight=False, markup=False)


def print_command(text):
    console.print(f"[command]{text}[/command]")


def print_success(text):
    """Print success message."""
    console.print(f"[success]{text}[/success]")


def print_reading_status():
    """Print standard APT-style reading/building status messages."""
    console.print(
        f"\n{_('Reading package lists')}... [green]{_('Done')}[/green]", highlight=False
    )
    console.print(
        f"{_('Building dependency tree...')} [green]{_('Done')}[/green]",
        highlight=False,
    )
    console.print(
        f"{_('Reading state information...')} [green]{_('Done')}[/green]",
        highlight=False,
    )


@contextlib.contextmanager
def status(msg, spinner="dots"):
    """
    Simulates console.status but just prints the message once (no spinner).
    Useful for adhering to 'no ugly spinners' rule.
    """
    console.print(msg, highlight=False)
    yield


def print_apt_download_line(index, total, url, filename, size_str="", action="Get"):
    """
    Prints a line like: Get:1 http://mirror.../pkg.tar.zst core/package [123 kB]
    Now with proper coloring:
    - Action (Get/Hit) in cyan bold
    - Index in white (default color)
    - URL in blue
    - Filename and size in default color
    """
    size_part = f" [{size_str}]" if size_str else ""
    console.print(
        f"[bold cyan]{action}:[/bold cyan]{index} [blue]{url}[/blue] {filename}{size_part}",
        highlight=False,
    )


def format_search_results(output):
    """
    Format pacman -Ss output to look like apt search.
    Pacman: repo/pkgname pkgver (groups) [installed]
    APT:    pkgname/repo pkgver [installed, ...]
    """
    table = Table(show_header=False, box=None, padding=(0, 1))
    lines = output.strip().split("\n")

    for i in range(0, len(lines), 2):
        if i + 1 >= len(lines):
            break

        # Line 1: extra/firefox 120.0-1 (gnome) [installed]
        header_line = lines[i]

        # Split repo from the rest
        try:
            repo_part, rest = header_line.split("/", 1)
            # rest is 'pkgname pkgver (groups) [installed]'
            # split by spaces
            parts = rest.split()
            pkgname = parts[0]
            pkgver = parts[1]

            # Reconstruct meta (groups/status)
            meta = " ".join(parts[2:]) if len(parts) > 2 else ""
            # Escape markup characters in meta
            from rich.markup import escape

            meta = escape(meta)

            # APT Style: pkgname/repo
            # We color pkgname in specific apt-like color (usually green or bold)
            apt_style_header = f"[bold green]{pkgname}[/bold green]/[bold blue]{repo_part}[/bold blue] [bold]{pkgver}[/bold] {meta}"
        except ValueError:
            # Fallback if format is unexpected
            apt_style_header = header_line

        desc = lines[i + 1].strip()

        table.add_row(apt_style_header)
        table.add_row(f"  {desc}")
        table.add_row("")  # Spacer

    console.print(table)


def format_aur_search_results(results):
    if not results:
        return

    table = Table(show_header=False, box=None, padding=(0, 1))

    for pkg in results:
        name = pkg.get("Name", "unknown")
        ver = pkg.get("Version", "unknown")
        desc = pkg.get("Description", "") or "No description"
        votes = pkg.get("NumVotes", 0)

        # APT Style: pkgname/aur
        apt_style_header = f"[bold green]{name}[/bold green]/[bold magenta]aur[/bold magenta] [bold]{ver}[/bold] [desc](Votes: {votes})[/desc]"

        table.add_row(apt_style_header)
        table.add_row(f"  {desc}")
        table.add_row("")  # Spacer

    console.print(table)


def format_show(output):
    """
    Format pacman -Si/Qi output to look like apt show.
    Maps Pacman keys to APT keys.
    Handles multi-line fields like Optional Deps.
    """
    lines = output.strip().split("\n")
    text = Text()

    # APT Mapping (pacman output forced to English with LC_ALL=C)
    # APT Mapping (pacman output forced to English with LC_ALL=C)
    key_map = {
        "Name": _("Package"),
        "Version": _("Version"),
        "Description": _("Description"),
        "Architecture": _("Architecture"),
        "URL": _("Homepage"),
        "Licenses": _("Section"),
        "Groups": _("Tag"),
        "Provides": _("Provides"),
        "Depends On": _("Depends"),
        "Optional Deps": _("Suggests"),
        "Required By": _("Reverse-Depends"),
        "Conflicts With": _("Conflicts"),
        "Replaces": _("Replaces"),
        "Download Size": _("Download-Size"),
        "Installed Size": _("Installed-Size"),
        "Packager": _("Maintainer"),
        "Build Date": _("Build-Date"),
        "Install Date": _("Install-Date"),
        "Install Reason": _("APT-Manual-Installed"),
        "Repository": _("Section"),
    }

    current_key = None
    current_val = ""

    for line in lines:
        # Check if line starts with non-whitespace (new field)
        if line and not line[0].isspace() and ":" in line:
            # Save previous field if exists
            if current_key:
                mapped_key = key_map.get(current_key, current_key)
                # Special value mapping
                if current_key == "Install Reason":
                    current_val = (
                        "yes" if "Explicitly installed" in current_val else "no"
                    )

                text.append(f"{mapped_key:<20}", style="bold cyan")
                text.append(f": {current_val}\n")

            # Start new field
            key, val = line.split(":", 1)
            current_key = key.strip()
            current_val = val.strip()
        elif line and line[0].isspace():
            # Continuation line (indented) - part of current field
            # For multi-line fields like Optional Deps, add newline to preserve formatting
            if current_key in ["Optional Deps", "Depends On", "Required By"]:
                current_val += "\n                     " + line.strip()
            else:
                current_val += " " + line.strip()
        else:
            # Empty line or other
            if current_key:
                # Save current field before empty line
                mapped_key = key_map.get(current_key, current_key)
                if current_key == "Install Reason":
                    current_val = (
                        "yes" if "Explicitly installed" in current_val else "no"
                    )

                text.append(f"{mapped_key:<20}", style="bold cyan")
                text.append(f": {current_val}\n")
                current_key = None
                current_val = ""
            text.append(f"{line}\n")

    # Don't forget last field
    if current_key:
        mapped_key = key_map.get(current_key, current_key)
        if current_key == "Install Reason":
            current_val = "yes" if "Explicitly installed" in current_val else "no"

        text.append(f"{mapped_key:<20}", style="bold cyan")
        text.append(f": {current_val}\n")

    console.print(Panel(text, title=_("Package Information"), border_style="blue"))


def format_aur_info(packages):
    if not packages:
        return

    for pkg in packages:
        text = Text()

        def add_field(label, value):
            if value:
                text.append(f"{label:<20}", style="bold cyan")
                text.append(f": {value}\n")

        # APT-like fields
        add_field(_("Package"), pkg.get("Name"))
        add_field(_("Version"), pkg.get("Version"))
        add_field(_("Priority"), "optional")  # Dummy
        add_field(_("Section"), "aur")
        add_field(_("Maintainer"), pkg.get("Maintainer"))
        add_field(_("Homepage"), pkg.get("URL"))
        add_field(_("Description"), pkg.get("Description"))
        add_field(
            _("Architecture"),
            " ".join(pkg.get("Architectures", []))
            if pkg.get("Architectures")
            else "any",
        )

        depends = pkg.get("Depends", [])
        if depends:
            add_field(_("Depends"), ", ".join(depends))

        makedeps = pkg.get("MakeDepends", [])
        if makedeps:
            add_field(_("Build-Depends"), ", ".join(makedeps))

        add_field(_("Vote-Count"), str(pkg.get("NumVotes", 0)))
        add_field(_("Popularity"), str(pkg.get("Popularity", 0)))

        console.print(
            Panel(
                text, title=f"{_('Package Information')} (AUR)", border_style="magenta"
            )
        )


def print_columnar_list(pkgs, color_tag="green"):
    """
    Prints a list of packages in columns (like ls or apt), adapting to terminal width.
    """
    if not pkgs:
        return

    width = console.size.width
    # Determine max length of package names (ignoring markup)
    # We'll use table padding for spacing, so don't add extra here
    max_len = max(Text.from_markup(p).cell_len for p in pkgs)

    # Calculate columns vs width
    # Account for: indentation (4) + minimal spacing between columns
    # Table uses padding=(0, 1) which adds 2 spaces per column
    available_width = width - 4  # Left indent

    # Calculate how many columns fit with spacing
    # Each column takes: max_len + 2 (table padding)
    col_width = max_len + 2
    cols = available_width // col_width
    if cols < 1:
        cols = 1

    # Calculate rows
    # We fill by row for readability? Or by column?
    # APT fills by row. (a b c d \n e f g h)

    table = Table(show_header=False, box=None, padding=(0, 1), pad_edge=False)
    for _idx in range(cols):
        table.add_column()

    row_buffer = []
    for pkg in pkgs:
        row_buffer.append(f"[{color_tag}]{pkg}[/{color_tag}]")
        if len(row_buffer) == cols:
            table.add_row(*row_buffer)
            row_buffer = []
    if row_buffer:
        while len(row_buffer) < cols:
            row_buffer.append("")
        table.add_row(*row_buffer)

    # Indent by 4 spaces
    console.print(Padding(table, (0, 0, 0, 4)))
    console.print()


def print_transaction_summary(
    new_pkgs: list = None,  # List of (name, version)
    upgraded_pkgs: list = None,  # List of (name, version)
    remove_pkgs: list = None,  # List of (name, version)
    explicit_names: set = None,  # Set of package names requested by user
):
    """
    Unified function to print transaction summary for installs, upgrades, and removals.
    Handles coloring, bold versions, and explicit vs dependency separation.
    """
    new_pkgs = new_pkgs or []
    upgraded_pkgs = upgraded_pkgs or []
    remove_pkgs = remove_pkgs or []
    explicit_names = explicit_names or set()

    # 1. Removals
    if remove_pkgs:
        console.print(f"\n{_('The following packages will be REMOVED:')}")
        lines = []
        for name, ver in remove_pkgs:
            lines.append(f"{name} [bold]{ver}[/bold]" if ver else name)
        print_columnar_list(sorted(lines), "red")

    # 2. Upgrades
    if upgraded_pkgs:
        # Check standard APT message? "The following packages will be upgraded:"
        # Or simple "Upgrading:" like we had?
        # Let's stick to rich text similar to APT
        console.print(f"\n[bold]{_('The following packages will be upgraded:')}[/bold]")
        lines = []
        for item in upgraded_pkgs:
            # Handle both 2-tuple (name, ver) and 3-tuple (name, old_ver, new_ver)
            if len(item) == 3:
                name, old_ver, ver = item
                # Display format: pkgname (old -> new) or just new?
                # APT often just lists them. pacman typically: pkg (1.0 -> 2.0)
                # Let's show: pkg [bold]1.0 -> 2.0[/bold]
                lines.append(f"{name} ([dim]{old_ver}[/dim] -> [bold]{ver}[/bold])")
            else:
                name, ver = item
                lines.append(f"{name} [bold]{ver}[/bold]" if ver else name)
        print_columnar_list(sorted(lines), "green")

    # 3. Installs (Split Explicit vs Extra)
    if new_pkgs:
        explicit_list = []
        extra_list = []

        for name, ver in new_pkgs:
            if name in explicit_names:
                explicit_list.append((name, ver))
            else:
                extra_list.append((name, ver))

        # Explicit First
        if explicit_list:
            console.print(
                f"[bold]{_('The following NEW packages will be installed:')}[/bold]"
            )
            lines = []
            for name, ver in explicit_list:
                lines.append(f"{name} [bold]{ver}[/bold]" if ver else name)
            print_columnar_list(sorted(lines), "green")

        # Dependencies Second
        if extra_list:
            console.print(
                f"[bold]{_('The following extra packages will be installed:')}[/bold]"
            )
            lines = []
            for name, ver in extra_list:
                lines.append(f"{name} [bold]{ver}[/bold]" if ver else name)
            print_columnar_list(sorted(lines), "green")


def show_help():
    from . import __version__

    text = Text()
    text.append(f"apt-pac {__version__} (Arch Linux)\n", style="bold")
    text.append(
        f"{_('Usage:')} apt [{_('options')}] {_('command')}\n\n", style="header"
    )

    text.append(
        f"{_('apt-pac is a commandline package manager wrapper for pacman.')}\n"
    )
    text.append(
        f"{_('It provides an APT-like experience while ensuring system safety.')}\n\n"
    )

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(_("Command"), style="success")
    table.add_column(_("Description"))

    commands = [
        ("update", _("update list of available packages (syncs -Sy and -Fy)")),
        ("upgrade", _("upgrade the system by installing/upgrading packages")),
        ("dist-upgrade", _("same as upgrade")),
        ("install", _("install packages (supports local .pkg.tar.zst files)")),
        ("reinstall", _("reinstall packages")),
        ("remove", _("remove packages")),
        ("purge", _("remove packages and their configurations")),
        ("autoremove", _("remove automatically all unused packages")),
        ("search", _("search in package descriptions (default: Official + AUR)")),
        ("show", _("show package details")),
        (
            "list",
            _(
                "list packages (--installed, --upgradable, --manual-installed, --all-versions, --repo)"
            ),
        ),
        ("depends", _("show package dependencies (uses pactree if available)")),
        ("rdepends", _("show reverse dependencies")),
        ("scripts", _("show package install/removal scripts")),
        ("changelog", _("view package changelog")),
        ("policy", _("show package version and candidate information")),
        ("apt-mark", _("mark/unmark packages as auto/manual")),
        ("check", _("verify package database and system integrity")),
        ("pkgnames", _("list all available package names")),
        ("stats", _("show package statistics")),
        ("dotty", _("generate dependency graph in GraphViz format")),
        ("madison", _("show available versions of a package")),
        ("config", _("display pacman configuration")),
        ("apt-key", _("manage GPG keys for package verification")),
        ("add-repository", _("show how to add repositories")),
        ("download", _("download packages without installing (pacman -Sw)")),
        ("source", _("download package source (uses pkgctl)")),
        ("showsrc", _("show source package information")),
        ("build-dep", _("show how to install build dependencies")),
        ("edit-sources", _("edit the pacman.conf information file")),
        ("clean", _("remove all cached package files (pacman -Scc)")),
        ("autoclean", _("erase old downloaded archives (keeps last 3)")),
        ("file-search", _("search for packages containing a file")),
    ]

    for cmd, desc in commands:
        table.add_row(cmd, _(desc))

    console.print(text)
    console.print(f"[bold]{_('Most used commands:')}[/bold]")
    console.print(table)
    console.print(
        f"\n[italic grey70]{_('This APT has Super Pacman Powers.')}[/italic grey70]"
    )

def print_showsrc_info(package_name, info, pkg_dir):
    """
    Format and print source information in APT style.
    Similar to format_show but takes a dictionary from PKGBUILD.
    """
    text = Text()

    # Map PKGBUILD keys to APT-like labels
    fields = [
        ("pkgname", _("Package")),
        ("pkgver", _("Version")),
        ("pkgrel", None),  # Combined with pkgver
        ("pkgdesc", _("Description")),
        ("url", _("Homepage")),
        ("license", _("License")),
        ("arch", _("Architecture")),
        ("depends", _("Depends")),
        ("makedepends", _("Build-Depends")),
    ]

    for key, label in fields:
        if key not in info:
            continue
        
        val = info[key]
        if isinstance(val, list):
            val = ", ".join(val)
        
        if key == "pkgver":
            rel = info.get("pkgrel", "1")
            val = f"{val}-{rel}"
        
        if label:
            text.append(f"{label+':':<20}", style="bold cyan")
            text.append(f" {val}\n")

    text.append(f"\n{_('Source Directory:')+' ':<20}", style="bold cyan")
    text.append(f" {pkg_dir}\n")

    console.print(text, highlight=False)
