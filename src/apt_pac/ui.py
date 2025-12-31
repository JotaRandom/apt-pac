from rich.console import Console
from rich.theme import Theme
from rich.table import Table
from rich.panel import Panel
from .i18n import _
from rich.text import Text

custom_theme = Theme({
    "info": "bold blue",
    "error": "bold red",
    "success": "bold green",
    "command": "italic cyan",
    "pkg": "bold white",
    "desc": "italic grey70",
    "header": "bold yellow",
})

console = Console(theme=custom_theme)

def print_info(text):
    """Print info message (no prefix - APT style)."""
    console.print(text)

def print_error(text):
    """Print error message (no prefix - APT style)."""
    console.print(text)

def print_command(text):
    console.print(f"[command]{text}[/command]")

def print_success(text):
    """Print success message."""
    console.print(f"[success]{text}[/success]")

def print_apt_download_line(index, total, url, filename, size_str=""):
    """
    Prints a line like: Get:1 http://mirror.../pkg.tar.zst core/package [123 kB]
    """
    # APT format: Get:1 URL Package [Size]
    # We try to mimic: Get:<index> <url> <filename> [<size>]
    
    # Extract shorter path from URL if possible for display? APT usually shows full URL base
    # But usually just prints: Get:1 http://archive.ubuntu.com/ubuntu jammy/main amd64 bash amd64 5.1-6ubuntu1 [123 kB]
    
    size_part = f" [{size_str}]" if size_str else ""
    console.print(f"[bold]Get:{index}[/bold] {url} {filename}{size_part}")

def format_search_results(output):
    """
    Format pacman -Ss output to look like apt search.
    Pacman: repo/pkgname pkgver (groups) [installed]
    APT:    pkgname/repo pkgver [installed, ...]
    """
    table = Table(show_header=False, box=None, padding=(0, 1))
    lines = output.strip().split('\n')
    
    for i in range(0, len(lines), 2):
        if i + 1 >= len(lines): break
        
        # Line 1: extra/firefox 120.0-1 (gnome) [installed]
        header_line = lines[i]
        
        # Split repo from the rest
        try:
             repo_part, rest = header_line.split('/', 1)
             # rest is 'pkgname pkgver (groups) [installed]'
             # split by spaces
             parts = rest.split()
             pkgname = parts[0]
             pkgver = parts[1]
             
             # Reconstruct meta (groups/status)
             meta = " ".join(parts[2:]) if len(parts) > 2 else ""
             
             # APT Style: pkgname/repo
             # We color pkgname in specific apt-like color (usually green or bold)
             apt_style_header = f"[bold green]{pkgname}[/bold green]/[bold blue]{repo_part}[/bold blue] [bold]{pkgver}[/bold] {meta}"
        except ValueError:
             # Fallback if format is unexpected
             apt_style_header = header_line

        desc = lines[i+1].strip()
        
        table.add_row(apt_style_header)
        table.add_row(f"  {desc}")
        table.add_row("") # Spacer
        
    console.print(table)

def format_aur_search_results(results):
    if not results:
        return

    table = Table(show_header=False, box=None, padding=(0, 1))
    
    for pkg in results:
        name = pkg.get('Name', 'unknown')
        ver = pkg.get('Version', 'unknown')
        desc = pkg.get('Description', '') or "No description"
        votes = pkg.get('NumVotes', 0)
        
        # APT Style: pkgname/aur
        apt_style_header = f"[bold green]{name}[/bold green]/[bold magenta]aur[/bold magenta] [bold]{ver}[/bold] [desc](Votes: {votes})[/desc]"
        
        table.add_row(apt_style_header)
        table.add_row(f"  {desc}")
        table.add_row("") # Spacer
        
    console.print(table)

def format_show(output):
    """
    Format pacman -Si/Qi output to look like apt show.
    Maps Pacman keys to APT keys.
    Handles multi-line fields like Optional Deps.
    """
    lines = output.strip().split('\n')
    text = Text()
    
    # APT Mapping
    key_map = {
        "Name": "Package",
        "Version": "Version",
        "Description": "Description",
        "Architecture": "Architecture",
        "URL": "Homepage",
        "Licenses": "Section",
        "Groups": "Tag",
        "Provides": "Provides",
        "Depends On": "Depends",
        "Optional Deps": "Suggests",
        "Required By": "Reverse-Depends",
        "Conflicts With": "Conflicts",
        "Replaces": "Replaces",
        "Download Size": "Download-Size",
        "Installed Size": "Installed-Size",
        "Packager": "Maintainer",
        "Build Date": "Build-Date",
        "Install Date": "Install-Date",
        "Install Reason": "APT-Manual-Installed",
        "Repository": "Section",
    }

    current_key = None
    current_val = ""
    
    for line in lines:
        # Check if line starts with non-whitespace (new field)
        if line and not line[0].isspace() and ':' in line:
            # Save previous field if exists
            if current_key:
                mapped_key = key_map.get(current_key, current_key)
                # Special value mapping
                if current_key == "Install Reason":
                    current_val = "yes" if "Explicitly installed" in current_val else "no"
                
                text.append(f"{mapped_key:<20}", style="bold cyan")
                text.append(f": {current_val}\n")
            
            # Start new field
            key, val = line.split(':', 1)
            current_key = key.strip()
            current_val = val.strip()
        elif line and line[0].isspace():
            # Continuation line (indented) - part of current field
            current_val += " " + line.strip()
        else:
            # Empty line or other
            if current_key:
                # Save current field before empty line
                mapped_key = key_map.get(current_key, current_key)
                if current_key == "Install Reason":
                    current_val = "yes" if "Explicitly installed" in current_val else "no"
                
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
            
    console.print(Panel(text, title="Package Information", border_style="blue"))

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
        add_field("Package", pkg.get("Name"))
        add_field("Version", pkg.get("Version"))
        add_field("Priority", "optional") # Dummy
        add_field("Section", "aur")
        add_field("Maintainer", pkg.get("Maintainer"))
        add_field("Homepage", pkg.get("URL"))
        add_field("Description", pkg.get("Description"))
        add_field("Architecture", " ".join(pkg.get("Architectures", [])) if pkg.get("Architectures") else "any")
        
        depends = pkg.get("Depends", [])
        if depends:
             add_field("Depends", ", ".join(depends))
        
        makedeps = pkg.get("MakeDepends", [])
        if makedeps:
             add_field("Build-Depends", ", ".join(makedeps))
             
        add_field("Vote-Count", str(pkg.get("NumVotes", 0)))
        add_field("Popularity", str(pkg.get("Popularity", 0)))
        
        console.print(Panel(text, title=f"Package Information (AUR)", border_style="magenta"))


def show_help():
    from . import __version__
    
    text = Text()
    text.append(f"apt-pac {__version__} (Arch Linux)\n", style="bold")
    text.append("Usage: apt [options] command\n\n", style="header")
    
    text.append("apt-pac is a commandline package manager wrapper for pacman.\n")
    text.append("It provides an APT-like experience while ensuring system safety.\n\n")
    
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Command", style="success")
    table.add_column("Description")
    
    commands = [
        ("update", "update list of available packages (syncs -Sy and -Fy)"),
        ("upgrade", "upgrade the system by installing/upgrading packages"),
        ("dist-upgrade", "same as upgrade"),
        ("install", "install packages (supports local .pkg.tar.zst files)"),
        ("reinstall", "reinstall packages"),
        ("remove", "remove packages"),
        ("purge", "remove packages and their configurations"),
        ("autoremove", "remove automatically all unused packages"),
        ("search", "search in package descriptions (default: Official + AUR)"),
        ("show", "show package details"),
        ("list", "list packages (--installed, --upgradable, --manual-installed, --all-versions, --repo)"),
        ("depends", "show package dependencies (uses pactree if available)"),
        ("rdepends", "show reverse dependencies"),
        ("scripts", "show package install/removal scripts"),
        ("changelog", "view package changelog"),
        ("policy", "show package version and candidate information"),
        ("apt-mark", "mark/unmark packages as auto/manual"),
        ("check", "verify package database and system integrity"),
        ("pkgnames", "list all available package names"),
        ("stats", "show package statistics"),
        ("dotty", "generate dependency graph in GraphViz format"),
        ("madison", "show available versions of a package"),
        ("config", "display pacman configuration"),
        ("apt-key", "manage GPG keys for package verification"),
        ("add-repository", "show how to add repositories"),
        ("download", "download packages without installing (pacman -Sw)"),
        ("source", "download package source (uses pkgctl)"),
        ("showsrc", "show source package information"),
        ("build-dep", "show how to install build dependencies"),
        ("edit-sources", "edit the pacman.conf information file"),
        ("clean", "remove all cached package files (pacman -Scc)"),
        ("autoclean", "erase old downloaded archives (keeps last 3)"),
        ("file-search", "search for packages containing a file"),
    ]
    
    for cmd, desc in commands:
        table.add_row(cmd, desc)
        
    console.print(text)
    console.print("[bold]Most used commands:[/bold]")
    console.print(table)
    console.print("\n[italic grey70]This APT has Super Pacman Powers.[/italic grey70]")
