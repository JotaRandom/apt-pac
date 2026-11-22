import contextlib
import io
import os
import re
import shutil
import sys

from rich.color import ColorSystem
from rich.console import Console
from rich.markup import escape
from rich.padding import Padding
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from .i18n import _


def is_linux_console(target_console=None) -> bool:
    """Return True when running inside a basic Linux virtual console / basic VT."""
    term = os.environ.get("TERM", "").lower()
    if term in {"linux", "vt100", "vt102", "vt220", "vt52", "dumb", "ansi"} or term.startswith(
        "linux"
    ):
        return True

    try:
        tty_name = os.ttyname(sys.stdout.fileno())
        if re.match(r"^/dev/(?:tty\d+|console)$", tty_name):
            return True
    except (OSError, ValueError, AttributeError, io.UnsupportedOperation):
        pass

    con = target_console if target_console is not None else globals().get("console")
    enc = getattr(con, "encoding", None) if con is not None else None
    if isinstance(enc, str) and enc and "utf" not in enc.lower():
        return True

    return False


def get_terminal_width(target_console=None, default=80, minimum=20) -> int:
    """Return current terminal column width cleanly clamped."""
    con = target_console if target_console is not None else globals().get("console")
    w = getattr(getattr(con, "size", None), "width", None)
    if not isinstance(w, int) or isinstance(w, bool) or w <= 0:
        try:
            w = shutil.get_terminal_size((default, 24)).columns
        except Exception:
            w = default
    return max(minimum, int(w))


def _build_theme() -> Theme:
    linux_vt = is_linux_console(None)
    return Theme(
        {
            "info": "bold blue",
            "error": "bold red",
            "success": "bold green",
            "command": "cyan" if linux_vt else "italic cyan",
            "pkg": "bold white",
            "desc": "dim" if linux_vt else "italic grey70",
            "header": "bold yellow",
        }
    )


custom_theme = _build_theme()

console = Console(theme=custom_theme, highlight=False)


def set_force_colors(force: bool):
    """Update console to force terminal output (colors) if requested."""
    if force:
        setattr(console, "_force_terminal", True)
        if is_linux_console(console):
            setattr(console, "_color_system", ColorSystem.STANDARD)
        else:
            detect = getattr(console, "_detect_color_system", None)
            if callable(detect):
                setattr(console, "_color_system", detect())


def print_info(text):
    """Print info message (no prefix - APT style)."""
    try:
        console.print(text, highlight=False)
    except Exception:
        console.print(text, highlight=False, markup=False)


def print_error(text):
    """Print error message (no prefix - APT style)."""
    try:
        console.print(text, highlight=False)
    except Exception:
        # Fallback if markup fails (e.g. text contains unmatched tags)
        console.print(text, highlight=False, markup=False)


def print_command(text):
    console.print(Text(str(text), style="command"), highlight=False)


def print_success(text):
    """Print success message."""
    try:
        console.print(Text(str(text), style="success"), highlight=False)
    except Exception:
        console.print(str(text), highlight=False, markup=False)


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
    del spinner
    try:
        console.print(msg, highlight=False)
    except Exception:
        console.print(msg, highlight=False, markup=False)
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
    del total
    safe_action = escape(str(action))
    safe_url = escape(str(url))
    safe_filename = escape(str(filename))
    size_part = f" {escape(f'[{size_str}]')}" if size_str else ""
    console.print(
        f"[bold cyan]{safe_action}:[/bold cyan]{index} [blue]{safe_url}[/blue] {safe_filename}{size_part}",
        highlight=False,
    )


def _format_search_meta(meta: str) -> str:
    """Format pacman -Ss trailing metadata with green [installed] and safe escaping."""
    if not meta:
        return ""
    tokens = []
    for tok in meta.split():
        if tok == "[installed]":
            tokens.append(f"[green]\\[{_('installed')}][/green]")
        else:
            tokens.append(escape(tok))
    return " " + " ".join(tokens)


def format_search_results(output):
    """
    Format pacman -Ss output to look like apt search.
    Pacman: repo/pkgname pkgver (groups) [installed]
    APT:    pkgname/repo pkgver [installed, ...]
    """
    lines = output.strip().split("\n")

    for i in range(0, len(lines), 2):
        if i + 1 >= len(lines):
            break

        header_line = lines[i]

        try:
            repo_part, rest = header_line.split("/", 1)
            parts = rest.split()
            pkgname = parts[0]
            pkgver = parts[1]
            meta = " ".join(parts[2:]) if len(parts) > 2 else ""

            apt_style_header = (
                f"[bold green]{escape(pkgname)}[/bold green]/"
                f"[bold blue]{escape(repo_part)}[/bold blue] "
                f"[bold]{escape(pkgver)}[/bold]{_format_search_meta(meta)}"
            )
        except (ValueError, IndexError):
            apt_style_header = escape(header_line)

        desc = lines[i + 1].strip()

        console.print(apt_style_header, highlight=False, overflow="fold")
        console.print(Padding(Text(desc, overflow="fold"), (0, 0, 0, 2)), highlight=False)
        console.print()


def format_aur_search_results(results):
    if not results:
        return

    for pkg in results:
        name = escape(str(pkg.get("Name", "unknown")))
        ver = escape(str(pkg.get("Version", "unknown")))
        desc = str(pkg.get("Description", "") or "No description")
        votes = pkg.get("NumVotes", 0)

        apt_style_header = (
            f"[bold green]{name}[/bold green]/[bold magenta]aur[/bold magenta] "
            f"[bold]{ver}[/bold] [desc](Votes: {votes})[/desc]"
        )

        console.print(apt_style_header, highlight=False, overflow="fold")
        console.print(Padding(Text(desc, overflow="fold"), (0, 0, 0, 2)), highlight=False)
        console.print()


def print_kv_fields(fields, indent=0):
    """Print key-value metadata fields with terminal-width and Linux VT adaptation."""
    if not fields:
        return

    normalized = []
    for label, value in fields:
        lbl = str(label)
        if isinstance(value, (list, tuple)):
            lines = [str(v) for v in value if str(v) != ""]
        else:
            lines = [ln for ln in str(value).splitlines() if ln != ""]
        if not lines:
            lines = [""]
        normalized.append((lbl, lines))

    width = get_terminal_width(console)
    max_label = max((Text(lbl).cell_len for lbl, _val in normalized), default=0)

    if width < 60 or max_label + indent + 22 > width:
        prefix = " " * indent
        cont_prefix = " " * (indent + 2)
        for lbl, lines in normalized:
            t = Text()
            t.append(f"{prefix}{lbl}:", style="bold cyan")
            if len(lines) == 1:
                if lines[0]:
                    t.append(f" {lines[0]}")
                console.print(t, highlight=False, overflow="fold")
            else:
                console.print(t, highlight=False, overflow="fold")
                for item in lines:
                    console.print(
                        Text(f"{cont_prefix}{item}", overflow="fold"),
                        highlight=False,
                    )
        return

    grid = Table.grid(padding=(0, 0))
    grid.add_column(style="bold cyan", no_wrap=True)
    grid.add_column(style="bold cyan", no_wrap=True)
    grid.add_column(overflow="fold")

    for lbl, lines in normalized:
        grid.add_row(lbl, " : ", Text("\n".join(lines), overflow="fold"))

    renderable = Padding(grid, (0, 0, 0, indent)) if indent > 0 else grid
    console.print(renderable)


_print_kv_fields = print_kv_fields


def format_show(output):
    """
    Format pacman -Si/Qi output to look like apt show.
    Maps Pacman keys to APT keys and adapts column alignment to console width.
    """
    lines = output.strip().split("\n")

    key_map = {
        "Name": _("Package"),
        "Version": _("Version"),
        "Description": _("Description"),
        "Architecture": _("Architecture"),
        "URL": _("Homepage"),
        "Licenses": _("License"),
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
    multiline_keys = {"Optional Deps", "Depends On", "Required By", "Optional For"}

    current_key = None
    val_lines: list[str] = []
    block_fields: list[tuple[str, list[str]]] = []

    def _flush_field():
        nonlocal current_key, val_lines
        if not current_key:
            return
        mapped_key = str(key_map.get(current_key, current_key) or current_key)
        cleaned = [ln for ln in val_lines if ln != ""]
        if current_key == "Install Reason":
            joined = " ".join(cleaned)
            cleaned = ["yes" if "Explicitly installed" in joined else "no"]
        block_fields.append((mapped_key, cleaned or [""]))
        current_key = None
        val_lines = []

    for line in lines:
        if line and not line[0].isspace() and ":" in line:
            _flush_field()
            key, val = line.split(":", 1)
            current_key = key.strip()
            v = val.strip()
            val_lines = [v] if v else []
        elif line and line[0].isspace() and current_key:
            stripped = line.strip()
            if not stripped:
                continue
            if current_key in multiline_keys or not val_lines:
                val_lines.append(stripped)
            else:
                val_lines[-1] = f"{val_lines[-1]} {stripped}"
        else:
            _flush_field()
            if block_fields:
                _print_kv_fields(block_fields)
                block_fields = []
                console.print()
            elif line.strip():
                console.print(Text(line, overflow="fold"), highlight=False)

    _flush_field()
    if block_fields:
        _print_kv_fields(block_fields)


def format_aur_info(packages):
    if not packages:
        return

    for idx, pkg in enumerate(packages):
        fields = []

        def add_field(label, value):
            if value:
                fields.append((label, value))

        add_field(_("Package"), pkg.get("Name"))
        add_field(_("Version"), pkg.get("Version"))
        add_field(_("Priority"), "optional")
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

        _print_kv_fields(fields)
        if idx < len(packages) - 1:
            console.print()


def print_columnar_list(pkgs, color_tag="green", indent=2):
    """
    Prints a list of packages in columns (like ls or apt), adapting to terminal width
    with per-column width calculation so long entries only widen their own column.
    """
    if not pkgs:
        return

    width = get_terminal_width(console)
    available_width = max(1, width - indent)

    def _to_text(raw: str) -> Text:
        try:
            t = Text.from_markup(raw)
            if color_tag and color_tag != "default":
                t.stylize(color_tag, 0, len(t))
            return t
        except Exception:
            return Text(raw, style=color_tag if color_tag != "default" else "")

    cell_texts = [_to_text(p) for p in pkgs]
    lengths = [t.cell_len for t in cell_texts]
    n = len(cell_texts)

    best_cols = 1
    min_item = min(lengths) if lengths else 1
    max_candidate = min(n, max(1, (available_width + 2) // max(1, min_item + 2)))
    for cols in range(max_candidate, 1, -1):
        col_widths = [max(lengths[i] for i in range(c, n, cols)) for c in range(cols)]
        if sum(col_widths) + 2 * (cols - 1) <= available_width:
            best_cols = cols
            break

    if best_cols == 1:
        for t in cell_texts:
            t.overflow = "fold"
            console.print(Padding(t, (0, 0, 0, indent)), highlight=False)
        console.print()
        return

    table = Table(show_header=False, box=None, padding=(0, 1), pad_edge=False)
    for _idx in range(best_cols):
        table.add_column(no_wrap=True)

    row_buffer = []
    for t in cell_texts:
        row_buffer.append(t)
        if len(row_buffer) == best_cols:
            table.add_row(*row_buffer)
            row_buffer = []
    if row_buffer:
        while len(row_buffer) < best_cols:
            row_buffer.append(Text(""))
        table.add_row(*row_buffer)

    console.print(Padding(table, (0, 0, 0, indent)))
    console.print()


def print_transaction_summary(
    new_pkgs: list | None = None,  # List of (name, version)
    upgraded_pkgs: list | None = None,  # List of (name, version)
    remove_pkgs: list | None = None,  # List of (name, version)
    explicit_names: set | None = None,  # Set of package names requested by user
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
            safe_name = escape(str(name))
            lines.append(
                f"{safe_name} [bold]{escape(str(ver))}[/bold]" if ver else safe_name
            )
        print_columnar_list(sorted(lines), "red")

    # 2. Upgrades
    if upgraded_pkgs:
        console.print(f"\n[bold]{_('The following packages will be upgraded:')}[/bold]")
        lines = []
        for item in upgraded_pkgs:
            if len(item) == 3:
                name, old_ver, ver = item
                lines.append(
                    f"{escape(str(name))} ([dim]{escape(str(old_ver))}[/dim] -> [bold]{escape(str(ver))}[/bold])"
                )
            else:
                name, ver = item
                safe_name = escape(str(name))
                lines.append(
                    f"{safe_name} [bold]{escape(str(ver))}[/bold]" if ver else safe_name
                )
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
                safe_name = escape(str(name))
                lines.append(
                    f"{safe_name} [bold]{escape(str(ver))}[/bold]" if ver else safe_name
                )
            print_columnar_list(sorted(lines), "green")

        # Dependencies Second
        if extra_list:
            console.print(
                f"[bold]{_('The following extra packages will be installed:')}[/bold]"
            )
            lines = []
            for name, ver in extra_list:
                safe_name = escape(str(name))
                lines.append(
                    f"{safe_name} [bold]{escape(str(ver))}[/bold]" if ver else safe_name
                )
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

    width = get_terminal_width(console)
    col_pad = 1 if width < 70 else 2
    table = Table(show_header=False, box=None, padding=(0, col_pad), pad_edge=False)
    table.add_column(_("Command"), style="success", no_wrap=True)
    table.add_column(_("Description"), overflow="fold")

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
        ("build-dep", _("install build dependencies for a package")),
        ("edit-sources", _("edit the pacman.conf information file")),
        ("clean", _("remove all cached package files (pacman -Scc)")),
        ("autoclean", _("erase old downloaded archives (keeps last 3)")),
        ("file-search", _("search for packages containing a file")),
        ("news", _("read the latest Arch Linux news")),
        ("help", _("show package manual page")),
    ]

    for cmd, desc in commands:
        table.add_row(cmd, desc)

    console.print(text)
    console.print(f"[bold]{_('Most used commands:')}[/bold]")
    console.print(Padding(table, (0, 0, 0, 2)))
    footer_style = "dim" if is_linux_console(console) else "italic grey70"
    console.print(
        f"\n[{footer_style}]{_('This APT has Super Pacman Powers.')}[/{footer_style}]"
    )


def print_showsrc_info(package_name, info, pkg_dir):
    """
    Format and print source information in APT style.
    Similar to format_show but takes a dictionary from PKGBUILD.
    """
    del package_name
    fields_spec = [
        ("pkgname", _("Package")),
        ("pkgver", _("Version")),
        ("pkgrel", None),
        ("pkgdesc", _("Description")),
        ("url", _("Homepage")),
        ("license", _("License")),
        ("arch", _("Architecture")),
        ("depends", _("Depends")),
        ("makedepends", _("Build-Depends")),
    ]

    kv_fields = []
    for key, label in fields_spec:
        if key not in info or not label:
            continue

        val = info[key]
        if isinstance(val, list):
            val = ", ".join(val)

        if key == "pkgver":
            rel = info.get("pkgrel", "1")
            val = f"{val}-{rel}"

        kv_fields.append((label, str(val)))

    kv_fields.append((_("Source Directory"), str(pkg_dir)))
    _print_kv_fields(kv_fields)
