import argparse
import sys

def parse_args():
    parser = argparse.ArgumentParser(
        description="APT-style wrapper for pacman",
        add_help=False # Disable default help
    )
    
    from . import __version__
    parser.add_argument("-v", "--version", action="store_true")
    parser.add_argument("-h", "--help", action="store_true")
    
    # We want to capture the command and all trailing arguments
    parser.add_argument("command", nargs="?", help="The apt command (install, remove, etc.)")
    parser.add_argument("args", nargs=argparse.REMAINDER, help="Arguments for the command")
    
    args = parser.parse_args()
    
    if args.version:
        print(f"apt-pac {__version__}")
        sys.exit(0)
        
    if args.help or not args.command:
        from .ui import show_help
        show_help()
        sys.exit(0)
        
    return args
