from rich.console import Console
from rich.theme import Theme
from rich.table import Table
from rich.panel import Panel
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
    console.print(f"[info]INFO:[/info] {text}")

def print_error(text):
    console.print(f"[error]ERROR:[/error] {text}")

def print_command(text):
    console.print(f"[command]{text}[/command]")

def print_success(text):
    console.print(f"[success]SUCCESS:[/success] {text}")

def format_search_results(output):
    table = Table(show_header=False, box=None, padding=(0, 1))
    lines = output.strip().split('\n')
    
    # pacman -Ss usually gives: repo/pkgname pkgver (groups) [status] \n desc
    for i in range(0, len(lines), 2):
        if i + 1 >= len(lines): break
        
        header_line = lines[i].split(' ', 1)
        pkg_full = header_line[0] # repo/pkgname
        meta = header_line[1] if len(header_line) > 1 else ""
        desc = lines[i+1].strip()
        
        table.add_row(f"[pkg]{pkg_full}[/pkg]", f"[desc]{meta}[/desc]")
        table.add_row("", f"  {desc}")
        table.add_row("", "") # Spacer
        
    console.print(table)

def format_show(output):
    # pacman -Si/Qi output is Key : Value
    lines = output.strip().split('\n')
    text = Text()
    for line in lines:
        if ':' in line:
            key, val = line.split(':', 1)
            text.append(f"{key.strip():<20}", style="bold cyan")
            text.append(f": {val.strip()}\n")
        else:
            text.append(f"{line}\n")
            
    console.print(Panel(text, title="Package Information", border_style="blue"))

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
        ("search", "search in package descriptions"),
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
