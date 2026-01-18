import argparse
import sys
import subprocess

def parse_args():
    from . import __version__
    from .i18n import _

    description = _("APT-style wrapper for pacman")
    # We can't easily translate argparse internals but we can translate our help
    parser = argparse.ArgumentParser(
        description=description,
        add_help=False 
    )
    
    parser.add_argument("-v", "--version", nargs="?", const="default", default=None)
    parser.add_argument("-h", "--help", action="store_true")
    
    parser.add_argument("command", nargs="?", help=_("The apt command (install, remove, etc.)"))
    parser.add_argument("args", nargs=argparse.REMAINDER, help=_("Arguments for the command"))
    
    args = parser.parse_args()
    
    if args.version is not None:
        # Get pacman version
        pacman_version = None
        try:
            result = subprocess.run(["pacman", "--version"], capture_output=True, text=True)
            if result.returncode == 0:
                # Extract version from first line (format: "Pacman v6.0.1 - libalpm v13.0.1")
                first_line = result.stdout.strip().split('\n')[0]
                pacman_version = first_line
        except:
            pacman_version = "unknown"
        
        # Handle different version options
        if args.version == "default":
            # Just --version (default behavior)
            print(f"apt-pac {__version__} (All)")
        elif args.version == "full":
            # --version full (show both)
            print(f"apt-pac {__version__} (All)")
            print(pacman_version if pacman_version else "pacman: unknown")
        elif args.version == "pacman":
            # --version pacman (only pacman)
            print(pacman_version if pacman_version else "pacman: unknown")
        else:
            # Unknown option
            print(f"apt-pac {__version__}")
            print(f"{_('Unknown version option:')} {args.version}", file=sys.stderr)
        
        sys.exit(0)
        
    if args.help or not args.command:
        from .ui import show_help
        show_help()
        sys.exit(0)
        
    return args
