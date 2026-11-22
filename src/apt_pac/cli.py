import argparse
import sys
import subprocess


def _print_version(version_option: str):
    """Print apt-pac and/or pacman version and exit."""
    from . import __version__
    from .i18n import _

    pacman_version = None
    try:
        result = subprocess.run(
            ["pacman", "--version"], capture_output=True, text=True
        )
        if result.returncode == 0:
            first_line = result.stdout.strip().split("\n")[0]
            if "Pacman v" in first_line:
                start_idx = first_line.find("Pacman v")
                clean_line = first_line[start_idx:]
                pacman_version = clean_line.replace(" - ", "\n")
            else:
                pacman_version = first_line
    except Exception:
        pacman_version = "unknown"

    if version_option == "default":
        print(f"apt-pac {__version__} (All)")
    elif version_option == "full":
        print(f"apt-pac {__version__} (All)")
        print(pacman_version if pacman_version else "pacman: unknown")
    elif version_option == "pacman":
        print(pacman_version if pacman_version else "pacman: unknown")
    else:
        print(f"apt-pac {__version__}")
        print(f"{_('Unknown version option:')} {version_option}", file=sys.stderr)

    sys.exit(0)


def parse_args(argv=None):
    tokens = list(sys.argv[1:] if argv is None else argv)
    leading_flags = []

    while tokens and tokens[0].startswith("-"):
        tok = tokens.pop(0)
        if tok in ("-h", "--help"):
            from .ui import show_help

            show_help()
            sys.exit(0)
        if tok in ("-v", "--version"):
            if tokens and tokens[0] in ("full", "pacman"):
                ver_opt = tokens.pop(0)
            elif len(tokens) == 1 and not tokens[0].startswith("-"):
                from .commands import COMMAND_MAP

                ver_opt = "default" if tokens[0] in COMMAND_MAP else tokens.pop(0)
            else:
                ver_opt = "default"
            _print_version(ver_opt)
        if tok.startswith("--version="):
            _print_version(tok.split("=", 1)[1])
        leading_flags.append(tok)

    if not tokens:
        from .ui import show_help

        show_help()
        sys.exit(0)

    command = tokens[0]
    rest_args = leading_flags + tokens[1:]
    return argparse.Namespace(command=command, args=rest_args, version=None, help=False)
