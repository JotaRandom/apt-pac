import os
import signal
import sys
import traceback
import warnings


def main():
    if hasattr(signal, "SIGPIPE"):
        try:
            signal.signal(signal.SIGPIPE, signal.SIG_DFL)
        except (OSError, ValueError):
            pass

    debug = os.environ.get("APT_PAC_DEBUG") == "1"
    if not debug:
        warnings.filterwarnings("ignore", category=UserWarning)
        warnings.filterwarnings("ignore", category=DeprecationWarning)

    try:
        # pyrefly: ignore[missing-import]
        from rich.markup import escape

        from .cli import parse_args
        from .commands import execute_command
        from .i18n import _
        from .ui import print_error
    except (ModuleNotFoundError, ImportError) as e:
        dep_name = getattr(e, "name", None) or "unknown"
        sys.stderr.write(f"E: Missing Python dependency '{dep_name}': {e}\n")
        if dep_name in ("pyalpm", "rich"):
            sys.stderr.write(
                f"N: Check that python-{dep_name} is installed for {sys.executable}.\n"
            )
        if debug:
            traceback.print_exc()
        sys.exit(1)

    try:
        args = parse_args()
        if not args.command:
            print(_("Usage: apt <command> [arguments]"))
            sys.exit(0)

        execute_command(args.command, args.args)
    except BrokenPipeError:
        if sys.stdout is sys.__stdout__:
            try:
                devnull = os.open(os.devnull, os.O_WRONLY)
                try:
                    os.dup2(devnull, sys.stdout.fileno())
                finally:
                    os.close(devnull)
            except Exception:
                pass
        sys.exit(0)
    except KeyboardInterrupt:
        try:
            print(_("Aborted."))
        except BrokenPipeError:
            pass
        sys.exit(130)
    except EOFError:
        try:
            print(_("Aborted."))
        except BrokenPipeError:
            pass
        sys.exit(1)
    except Exception as e:
        if debug:
            traceback.print_exc()
        else:
            msg = str(e) or e.__class__.__name__
            print_error(f"[bold red]{_('E:')}[/bold red] {escape(msg)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
