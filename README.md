# MachScope

A learning project for macOS process observability. It selects one process,
records CPU, resident memory, thread count, open-file changes, and child-process
changes in SQLite, then flags large metric changes with deterministic rules.

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
The install also provides the `machscope` command.

## Run

Open the application you want to observe, then run:

```bash
python -m machscope observe Spotify
```

Record measurements to a local SQLite database:

```bash
machscope record Spotify
machscope record Spotify --interval 0.5
```

Recordings are saved under `.machscope/recordings.sqlite3` in the current
directory. You can choose a PID or another database file:

```bash
machscope record --pid 12345 --db ~/Desktop/demo.sqlite3
```

Press **Ctrl-C** to stop cleanly; all saved samples stay in the database. If the
process exits or access is lost, the recording is closed with that reason.
Each sample commits separately. A forced quit or machine shutdown can leave the
last recording marked `recording`, but already committed samples remain usable.

List or summarize recordings:

```bash
machscope recordings
machscope inspect latest
machscope inspect 1
```

Find changes and show nearby samples:

```bash
machscope analyze latest
machscope analyze 1 --cpu-jump 40 --memory-jump-percent 20 \
    --memory-jump-mb 15 --thread-change 4 --window 3
```

CPU is flagged when it rises by at least 50 **percentage points** from the
previous sample. Memory must rise by at least 25% **and** 20 MB. Thread count
changes are flagged in either direction when the absolute change is at least
5. You can adjust all four thresholds. The timeline shows samples within two
elapsed seconds before and after each flagged sample by default.

Recording also polls the selected process's regular open files and direct
children between metric samples. The first readable scan establishes a
baseline; later opens, closes, child starts, and exits are stored as separate
events. Permission failures produce one warning and retain the last accessible
snapshot. These polls are snapshots, so a file or child that appears and exits
between two polls can be missed.

Try the self-contained demo:

```bash
python demo.py
```

It records a temporary Python workload that changes memory, thread count, open
files, child processes, and CPU usage; then it lists and analyzes the resulting
real recording. It writes
`.machscope/demo.sqlite3` and `.machscope/demo-latest.txt` so you can inspect the
database and keep a terminal transcript. The demo workload belongs to the demo
script and stops automatically.

For a repeatable observer-effect benchmark, run:

```bash
python benchmark.py
```

It compares the same 80-million-iteration Python integer task in three baseline
runs and three monitored runs at each of 0.1, 0.5, and 1.0 second intervals.
It pairs each monitored run with that repetition's baseline, reports median
observed runtime differences and sample counts, and saves the database size.
Other computer activity can still skew results. Each invocation writes a new
database under `.machscope/`; the workload is CPU-bound but completes on its own.

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

While recording, MachScope also polls the selected process for its open regular
files and direct child processes. It stores observed opens, closes, starts, and
exits in the same timeline. The first successful scan establishes a baseline;
changes that happened before that scan aren’t reported. Scans happen between
samples, so brief changes can be missed. If macOS denies a scan, MachScope warns
once and keeps the previous state instead of inventing a burst of closes. Other
process permissions vary with ownership and macOS privacy protections.

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

## How recording and analysis work

SQLite is a local database in a single file, built into Python. MachScope keeps
one `recordings` row for process identity, start/end times, duration, and stop
reason. The `samples` table holds ordered rows for that recording:

| Field | Meaning |
| --- | --- |
| `recording_id`, `sequence` | Which recording and sample order |
| `timestamp` | UTC wall-clock time for a human-readable timeline |
| `elapsed_seconds` | Monotonic elapsed time from recording start |
| `cpu_percent` | CPU use during the sample interval |
| `memory_bytes` | Resident memory, in bytes |
| `thread_count` | Threads at the sample time |

The `process_events` table separately stores the event time, kind, related PID,
and file path or process name. File descriptors identify which open file entry
changed; they can be reused after a close.

An SQL transaction groups a database change so it is either committed together
or rolled back after an error. MachScope commits each sample as it arrives, so
a later interruption doesn’t discard earlier samples. Wall-clock time helps
answer *when*; monotonic elapsed time remains orderly if the Mac clock changes.
These Python standard-library [SQLite](https://docs.python.org/3/library/sqlite3.html)
and [time](https://docs.python.org/3/library/time.html#time.monotonic) interfaces
provide those pieces.

The analyzer compares every sample with its immediate predecessor; it doesn’t
use the beginning of the recording as a permanent baseline. Rules are
deterministic and configurable. A flagged change means only that the values
moved near each other in time; it does not prove one caused another. Repeated
nearby samples can create repeated flags, and one-second sampling can miss a
short spike. There is no moving-average baseline or automatic diagnosis yet.

The [psutil documentation](https://psutil.io/7.2/) describes process sampling.

## Native macOS experiment

Compare psutil's executable path with Apple's `libproc` path query for a PID:

```bash
machscope native-path --pid 12345
```

This calls `proc_pidpath` through Python `ctypes` and reports whether its path
matches `psutil.Process.exe()`. It is an educational experiment separate from
the recorder. Apple's [XNU `libproc.h` header](https://github.com/apple-oss-distributions/xnu/blob/main/libsyscall/wrappers/libproc/libproc.h)
labels these interfaces private and subject to change. macOS privacy and
permissions can also reject another process's path. The current-process PID is
a useful first check.

## Code and tests

- `machscope.py`: command-line arguments, the original `ps` snapshot, and Ctrl-C.
- `observe.py`, `recording.py`: process selection, sampling, and recording lifecycle.
- `storage.py`: SQLite tables, sample writes, and queries.
- `event_tracker.py`: sampled open-file and direct-child changes.
- `analysis.py`: change rules, summaries, and timelines.
- `benchmark.py`: paired measurements of the recorder's runtime overhead.
- `native.py`: isolated macOS `libproc` experiment.
- `demo.py`: controlled demonstration workload and walkthrough.
- `test_*.py`: standard-library `unittest` tests for CLI, lifecycle, storage, and rules.

Run from this directory with the virtual environment active:

```bash
python -m unittest -v
```

Tests use simulated process objects so changing live PIDs, permissions, and
timings cannot make them flaky. For a manual macOS check, observe an application,
confirm several measurement lines appear, then press Ctrl-C. Repeat and quit
the observed application to check that observation finishes cleanly.

Before moving on, be able to explain the difference between wall-clock and
monotonic time, how a committed sample survives process exit, why one sampling
run cannot establish benchmark performance, and why an anomaly flag doesn’t
prove one event caused another.
