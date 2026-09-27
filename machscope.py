"""List macOS processes or observe one process about once per second."""

import argparse
import subprocess
import sys


def snapshot():
    """Print the snapshot and return an exit status: 0 for success, 1 for failure."""
    try:
        # ps is a child process: a separate program started by this Python process.
        # -A includes all processes; -c shows executable names without arguments.
        # -o selects the columns and their headings. ps handles their formatting.
        result = subprocess.run(
            ["/bin/ps", "-A", "-c", "-o", "pid=PID", "-o", "comm=COMMAND"],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as error:
        # check=True raises this exception when ps reports a nonzero exit status.
        detail = (error.stderr or "").strip() or f"ps exited with status {error.returncode}"
        print(f"MachScope: unable to read processes: {detail}", file=sys.stderr)
        return 1
    except OSError as error:
        print(f"MachScope: unable to start ps: {error}", file=sys.stderr)
        return 1

    print(result.stdout, end="")
    return 0


def positive_pid(value):
    """Accept a positive PID that fits macOS's signed 32-bit process ID."""
    try:
        pid = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("PID must be a positive integer") from None
    if not 1 <= pid <= 2**31 - 1:
        raise argparse.ArgumentTypeError("PID must be between 1 and 2147483647")
    return pid


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command")
    observer = commands.add_parser("observe", help="watch one running process")
    target = observer.add_mutually_exclusive_group(required=True)
    target.add_argument("name", nargs="?", help="exact executable name (case-insensitive)")
    target.add_argument("--pid", type=positive_pid, help="select a specific process ID")
    args = parser.parse_args(argv)

    try:
        if args.command is None:
            return snapshot()

        # The original snapshot and --help still work without this dependency.
        try:
            from observe import observe
        except ModuleNotFoundError as error:
            if error.name != "psutil":
                raise
            print(
                "MachScope: observing requires psutil. Activate your virtual "
                "environment and run: python -m pip install -r requirements.txt",
                file=sys.stderr,
            )
            return 1
        return observe(name=args.name, pid=args.pid)
    except KeyboardInterrupt:
        print("\nStopped observing.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
