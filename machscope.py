"""Display one snapshot of macOS processes and their PIDs."""

import subprocess
import sys


def main():
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


if __name__ == "__main__":
    sys.exit(main())
