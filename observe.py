"""Select one process and display its CPU, resident memory, and thread count."""

import sys

import psutil


def select_process(name=None, pid=None):
    """Return one process, or explain why the requested selection is unclear."""
    if pid is not None:
        return psutil.Process(pid)

    matches = []
    for process in psutil.process_iter():
        try:
            # Exact matching keeps Spotify separate from Spotify Helper.
            if process.name().casefold() == name.casefold():
                matches.append(process)
        except (psutil.NoSuchProcess, psutil.AccessDenied, PermissionError):
            # A process can exit or be inaccessible while we scan the list.
            continue

    if not matches:
        raise ValueError(
            f"No accessible process named {name!r}. Use an exact executable name; "
            "run python -m machscope to list processes."
        )
    if len(matches) > 1:
        pids = ", ".join(str(process.pid) for process in sorted(matches, key=lambda p: p.pid))
        raise ValueError(
            f"Multiple processes named {name!r}: PIDs {pids}. "
            "Choose one with: python -m machscope observe --pid <PID>"
        )
    return matches[0]


def ensure_running(process):
    """Reject exited processes, including a PID reused by a different process."""
    # is_running compares PID and creation time, rather than just checking the PID.
    # A zombie has finished executing but still has an entry in the process table.
    if not process.is_running() or process.status() == psutil.STATUS_ZOMBIE:
        raise psutil.NoSuchProcess(process.pid)


def read_sample(process, interval=1.0):
    """Measure one interval; discard it if the original process disappears."""
    ensure_running(process)
    # CPU use needs two readings, one second apart. RSS is stored in bytes.
    cpu = process.cpu_percent(interval=interval)
    memory = process.memory_info().rss
    threads = process.num_threads()
    ensure_running(process)
    return {"cpu_percent": cpu, "memory_bytes": memory, "thread_count": threads}


def observe_process(process):
    """Watch the selected process until it exits or the user presses Ctrl-C."""
    try:
        ensure_running(process)
        print(f"Process: {process.name()}\nPID: {process.pid}", flush=True)
        print("Updating about every second. Press Ctrl-C to stop.\n", flush=True)
        while True:
            sample = read_sample(process)
            print(
                f"CPU: {sample['cpu_percent']:.1f}%   "
                f"Memory (RSS): {sample['memory_bytes'] / 1_000_000:.1f} MB   "
                f"Threads: {sample['thread_count']}",
                flush=True,
            )
    except psutil.NoSuchProcess:
        print(f"Process {process.pid} exited; observation finished.")
        return 0
    except (psutil.AccessDenied, PermissionError):
        print(f"MachScope: permission denied for PID {process.pid}.", file=sys.stderr)
        return 1


def observe(name=None, pid=None):
    """Resolve the requested target, then begin observation."""
    try:
        process = select_process(name=name, pid=pid)
    except ValueError as error:
        print(f"MachScope: {error}", file=sys.stderr)
        return 1
    except psutil.NoSuchProcess:
        print(f"MachScope: PID {pid} no longer exists.", file=sys.stderr)
        return 1
    except (psutil.AccessDenied, PermissionError):
        print("MachScope: permission denied while selecting a process.", file=sys.stderr)
        return 1
    return observe_process(process)
