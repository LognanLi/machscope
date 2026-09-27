# MachScope

A learning project for macOS process observability. Week 1 observes **one
process** and prints CPU use, resident memory, and thread count about once per
second. Measurements are not saved yet.

## Setup

Requires macOS and Python 3.10 or newer. From this directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

The virtual environment keeps the project's dependency separate from your
system Python. Activate it again when you open a new terminal. The only external
dependency is `psutil`, which provides Python access to OS process measurements.

## Run

Open the application you want to observe, then run:

```bash
python -m machscope observe Spotify
```

Illustrative output (your measurements will differ):

```text
Process: Spotify
PID: 12345
Updating about every second. Press Ctrl-C to stop.

CPU: 7.2%   Memory (RSS): 381.0 MB   Threads: 24
CPU: 5.1%   Memory (RSS): 382.0 MB   Threads: 24
```

The first measurement appears after about one second. Each measurement adds
a line to the terminal. Press **Ctrl-C** to stop observing; this does not stop
the process being watched. Observation also finishes when that process exits.

Names match the full executable name, ignoring letter case: `spotify` matches
`Spotify`, but not `Spotify Helper`. Quote names containing spaces:

```bash
python -m machscope observe "Spotify Helper"
```

If several processes share that name, MachScope lists their PIDs and exits
instead of choosing one. Select one explicitly:

```bash
python -m machscope observe --pid 12345
```

Use the original snapshot to discover names and PIDs:

```bash
python -m machscope
# The original invocation also still works:
python3 machscope.py
```

Run `python -m machscope observe --help` for argument help. Missing targets,
ambiguous names, and access errors produce readable errors. Some macOS processes
are protected; try an application you own if access is denied. Processes whose
names cannot be read are skipped during name selection. If the entire process
list is inaccessible, selection reports a permission error.

## Understand the measurements

- **Process:** a running instance of a program, with its own memory and OS
  resources. One app can use several processes; this tool measures only the
  selected process, not all of its helpers.
- **PID:** the numeric process ID. macOS can reuse it after a process exits.
  MachScope keeps the selected process object and checks its identity before
  and after measurements; it does not automatically follow a restarted app.
- **Thread:** a stream of execution inside a process. Threads share the
  process's memory. A thread can be waiting rather than using CPU.
- **CPU percentage:** CPU time used divided by elapsed time, multiplied by 100.
  Using 0.2 seconds of CPU time in one second is roughly 20%. One fully occupied
  logical CPU is roughly 100%; a process using multiple CPUs can exceed 100%.
- **Memory (RSS):** resident set size, the process's memory currently in RAM.
  This can include shared memory, so it is not all exclusively owned by that
  process. It is different from its full virtual address space and from Activity
  Monitor's memory accounting. Here, 1 MB means 1,000,000 bytes.
- **Userspace:** where ordinary programs such as MachScope run. `psutil` calls
  macOS interfaces to request information; the OS controls what can be read.

Measurements are samples: CPU is averaged over approximately one second, while
memory and thread count are read near the end of that interval. The values are
not an atomic view of the process, and brief changes between samples can be
missed. A sleeping process reporting 0% CPU is normal.

The [psutil documentation](https://psutil.io/7.2/) describes the underlying APIs.

## Code and tests

- `machscope.py`: command-line arguments, the original `ps` snapshot, and Ctrl-C.
- `observe.py`: process selection and the measurement loop.
- `test_machscope.py` and `test_observe.py`: standard-library `unittest` tests.

Run from this directory with the virtual environment active:

```bash
python -m unittest -v
```

Tests use simulated process objects so changing live PIDs, permissions, and
timings cannot make them flaky. For a manual macOS check, observe an application,
confirm several measurement lines appear, then press Ctrl-C. Repeat and quit
the observed application to check that observation finishes cleanly.

Before moving on, be able to explain why name selection can be ambiguous, why
CPU measurement takes time, and how a process can disappear between two reads.
