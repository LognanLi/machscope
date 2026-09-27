"""Observe, record, and explain changes in a macOS process."""

import argparse
import math
import sqlite3
import subprocess
import sys

from storage import DEFAULT_DATABASE


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


def nonnegative_number(value):
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise argparse.ArgumentTypeError("value must be finite and nonnegative")
    return number


def positive_number(value):
    number = nonnegative_number(value)
    if number == 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return number


def recording_selector(value):
    if value == "latest":
        return value
    try:
        recording_id = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("use a recording ID or 'latest'") from None
    if not 1 <= recording_id <= 2**63 - 1:
        raise argparse.ArgumentTypeError("recording ID must be a positive 64-bit integer")
    return str(recording_id)


def add_target(parser):
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("name", nargs="?", help="exact executable name (case-insensitive)")
    target.add_argument("--pid", type=positive_pid, help="select a specific process ID")


def add_database(parser):
    parser.add_argument("--db", default=str(DEFAULT_DATABASE), help="SQLite file (default: %(default)s)")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command")
    observer = commands.add_parser("observe", help="watch one running process")
    add_target(observer)
    recorder = commands.add_parser("record", help="save process samples to SQLite")
    add_target(recorder)
    add_database(recorder)
    recorder.add_argument("--interval", type=positive_number, default=1.0,
                          help="sample interval in seconds (minimum 0.1; default: 1)")
    listings = commands.add_parser("recordings", help="list saved recordings")
    add_database(listings)
    inspector = commands.add_parser("inspect", help="summarize a saved recording")
    inspector.add_argument("recording", type=recording_selector, help="recording ID or latest")
    add_database(inspector)
    analyzer = commands.add_parser("analyze", help="find changes and show surrounding samples")
    analyzer.add_argument("recording", type=recording_selector, help="recording ID or latest")
    add_database(analyzer)
    analyzer.add_argument("--cpu-jump", type=positive_number, default=50.0, help="CPU rise in percentage points (default: 50)")
    analyzer.add_argument("--memory-jump-percent", type=positive_number, default=25.0, help="RSS rise in percent (default: 25)")
    analyzer.add_argument("--memory-jump-mb", type=positive_number, default=20.0, help="minimum RSS rise in MB (default: 20)")
    analyzer.add_argument("--thread-change", type=int, default=5, help="absolute thread-count change (default: 5)")
    analyzer.add_argument("--window", type=nonnegative_number, default=2.0, help="seconds before/after each flag (default: 2)")
    native_command = commands.add_parser(
        "native-path", help="experimental comparison with macOS libproc proc_pidpath"
    )
    native_command.add_argument("--pid", required=True, type=positive_pid)
    args = parser.parse_args(argv)
    if args.command == "analyze" and args.thread_change < 1:
        parser.error("--thread-change must be at least 1")
    if args.command == "record" and args.interval < 0.1:
        parser.error("--interval must be at least 0.1 seconds")

    try:
        if args.command is None:
            return snapshot()

        # Saved recordings can be inspected without live process access or psutil.
        if args.command in ("recordings", "inspect", "analyze"):
            from analysis import analyze_recording, inspect_recording, show_recordings

            if args.command == "recordings":
                return show_recordings(args.db)
            if args.command == "inspect":
                return inspect_recording(args.db, args.recording)
            return analyze_recording(
                args.db, args.recording, window=args.window, cpu_jump=args.cpu_jump,
                memory_jump_percent=args.memory_jump_percent,
                memory_jump_mb=args.memory_jump_mb, thread_change=args.thread_change,
            )

        if args.command == "native-path":
            import psutil
            from native import compare_executable_paths, proc_pidpath

            result = compare_executable_paths(
                args.pid, proc_pidpath, lambda pid: psutil.Process(pid).exe()
            )
            print(f"PID: {result['pid']}")
            print(f"libproc.proc_pidpath: {result['native_path']}")
            print(f"psutil.Process.exe(): {result['psutil_path']}")
            print(f"Paths match: {'yes' if result['match'] else 'no'}")
            return 0 if result["match"] else 1

        # The original snapshot and --help still work without this dependency.
        try:
            from observe import observe
            if args.command == "record":
                from recording import record
        except ModuleNotFoundError as error:
            if error.name != "psutil":
                raise
            print(
                "MachScope: observing and recording require psutil. Activate your virtual "
                "environment and run: python -m pip install -r requirements.txt",
                file=sys.stderr,
            )
            return 1
        if args.command == "record":
            return record(args.db, name=args.name, pid=args.pid, interval=args.interval)
        return observe(name=args.name, pid=args.pid)
    except (ValueError, sqlite3.Error, OSError) as error:
        print(f"MachScope: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nStopped observing.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
