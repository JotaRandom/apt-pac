import sys
from .cli import parse_args
from .commands import execute_command
from .ui import print_error
from .i18n import _

def main():
    try:
        args = parse_args()
        if not args.command:
            print(_("Usage: apt <command> [arguments]"))
            sys.exit(0)
            
        execute_command(args.command, args.args)
    except KeyboardInterrupt:
        print(_("Aborted."))
        sys.exit(1)
    except Exception as e:
        print_error(str(e))
        sys.exit(1)

if __name__ == "__main__":
    main()
