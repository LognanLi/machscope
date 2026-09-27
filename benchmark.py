"""Compare a repeatable CPU task with and without MachScope sampling."""

import argparse
import json
from pathlib import Path
import re
import statistics
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parent


def project_python(project_root=ROOT, current_python=sys.executable):
    virtual_python = project_root / ".venv" / "bin" / "python"
    return str(virtual_python) if virtual_python.is_file() else current_python


def checksum_for_work(units):
    """A fixed amount of repeatable Python integer work; return its checksum."""
    checksum = 0
    for value in range(units):
        checksum += value ^ (value >> 3)
    return checksum


def workload(units):
    """Wait for a start signal so the recorder and baseline share a start point."""
    print("READY", flush=True)
    if sys.stdin.readline() != "start\n":
        return 2
    started = time.perf_counter()
    checksum = checksum_for_work(units)
    elapsed = time.perf_counter() - started
    print(json.dumps({"elapsed_seconds": elapsed, "checksum": checksum}), flush=True)
    return 0


def launch_workload(python, units):
    process = subprocess.Popen(
        [python, str(Path(__file__).resolve()), "--workload", str(units)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )
    ready = process.stdout.readline()
    if ready.strip() != "READY":
        process.terminate()
        raise RuntimeError(f"Benchmark workload failed to start: {ready.strip()}")
    return process


def read_result(process, command):
    line = process.stdout.readline()
    status = process.wait(timeout=10)
    if status:
        raise RuntimeError(f"Workload failed: {line.strip()}")
    try:
        return json.loads(line)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"Workload returned invalid output: {line.strip()}") from error


def run_baseline(python, units):
    process = launch_workload(python, units)
    try:
        process.stdin.write("start\n")
        process.stdin.flush()
        result = read_result(process, "baseline")
        return {"runtime": result["elapsed_seconds"], **result}
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        if process.stdin and not process.stdin.closed:
            process.stdin.close()
        if process.stdout:
            process.stdout.close()


def run_monitored(python, units, interval, database):
    target = launch_workload(python, units)
    recorder = None
    try:
        recorder = subprocess.Popen(
            [python, "-m", "machscope", "record", "--pid", str(target.pid),
             "--interval", str(interval), "--db", str(database)],
            cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, bufsize=1,
        )
        recording_id = None
        sampling = False
        for line in recorder.stdout:
            if recording_id is None and line.startswith("Recording "):
                recording_id = line.split()[1].rstrip(":")
            if line.startswith("Sampling every"):
                sampling = True
                break
            if recorder.poll() is not None:
                raise RuntimeError(f"Recorder failed to start: {line.strip()}")
        if not sampling:
            raise RuntimeError("Recorder exited before its first sample.")

        target.stdin.write("start\n")
        target.stdin.flush()
        result = read_result(target, "recorded")
        runtime = result["elapsed_seconds"]

        target.stdin.close()
        target.stdout.close()
        tail = recorder.communicate(timeout=15)[0]
        if recorder.returncode or recording_id is None:
            raise RuntimeError(f"Recorder failed:\n{tail}")
        saved = re.search(r"saved: (\d+) samples", tail)
        return {"runtime": runtime, "samples": int(saved.group(1)) if saved else 0,
                "recording_id": recording_id, **result}
    finally:
        if target.poll() is None:
            target.terminate()
            target.wait(timeout=5)
        if target.stdin and not target.stdin.closed:
            target.stdin.close()
        if target.stdout and not target.stdout.closed:
            target.stdout.close()
        if recorder is not None and recorder.poll() is None:
            recorder.terminate()
            recorder.wait(timeout=5)
            if recorder.stdout:
                recorder.stdout.close()


def paired_overheads(trials):
    """Percent runtime change for each paired repetition."""
    return [((trial["monitored"]["runtime"] - trial["baseline"]["runtime"])
             / trial["baseline"]["runtime"] * 100) for trial in trials]


def new_database_path(output_dir, stamp):
    """Choose a fresh run file without replacing an earlier benchmark."""
    database = Path(output_dir) / f"benchmark-{stamp}.sqlite3"
    suffix = 1
    while database.exists():
        database = Path(output_dir) / f"benchmark-{stamp}-{suffix}.sqlite3"
        suffix += 1
    return database


def run(repeats=3, units=80_000_000, intervals=(0.1, 0.5, 1.0), output_dir=None):
    if repeats < 3:
        raise ValueError("Use at least three repetitions so the median is useful.")
    if units < 50_000_000:
        raise ValueError("Use at least 50,000,000 iterations so the one-second recorder can sample it.")
    if not intervals or any(interval < 0.1 for interval in intervals):
        raise ValueError("Every sampling interval must be at least 0.1 seconds.")
    output_dir = Path(output_dir or ROOT / ".machscope").expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    database = new_database_path(output_dir, stamp)
    python = project_python()
    trials = {interval: [] for interval in intervals}
    baselines = []
    print(f"Task: checksum of {units:,} Python integer iterations")
    print(f"Paired runs: {repeats}; sampling intervals: {', '.join(f'{x:g}s' for x in intervals)}")
    print("Order: baseline, then each interval for each repetition; report median pair overhead.")
    for repetition in range(1, repeats + 1):
        baseline = run_baseline(python, units)
        baselines.append(baseline)
        print(f"Baseline {repetition}/{repeats}: {baseline['runtime']:.3f}s")
        for interval in intervals:
            monitored = run_monitored(python, units, interval, database)
            trials[interval].append({"baseline": baseline, "monitored": monitored})
            relative = (monitored["runtime"] - baseline["runtime"]) / baseline["runtime"] * 100
            print(
                f"  {interval:g}s sampling: {monitored['runtime']:.3f}s "
                f"({relative:+.1f}% vs paired baseline); "
                f"{monitored['samples']} samples"
            )

    print("\nResults (negative overhead means that run happened to be faster):")
    print(f"Baseline median: {statistics.median(x['runtime'] for x in baselines):.3f}s")
    all_samples = sum(item["monitored"]["samples"]
                      for grouped in trials.values() for item in grouped)
    size = database.stat().st_size
    print(f"Recordings: {len(trials) * repeats}; samples: {all_samples}")
    print(f"Database size after all runs: {size:,} bytes (includes schema and recording metadata)")
    if not all_samples:
        print("No samples were saved. Longer workload runs are needed for this interval.")
    for interval, grouped in trials.items():
        overheads = paired_overheads(grouped)
        runtimes = [item["monitored"]["runtime"] for item in grouped]
        sizes = [item["monitored"]["samples"] for item in grouped]
        print(
            f"{interval:g}s: median {statistics.median(runtimes):.3f}s workload, "
            f"median paired overhead {statistics.median(overheads):+.1f}%, "
            f"{statistics.median(sizes):.0f} samples per recording"
        )
    print(f"Saved recordings: {database}")
    return database


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=3, help="paired trials per interval (default: 3)")
    parser.add_argument("--units", type=int, default=80_000_000, help="CPU loop iterations (default: 80 million)")
    parser.add_argument("--intervals", type=float, nargs="+", default=[0.1, 0.5, 1.0],
                        help="sampling intervals in seconds (default: 0.1 0.5 1.0)")
    parser.add_argument("--output-dir", help="where to save a new benchmark database")
    args = parser.parse_args(argv)
    try:
        run(args.repeats, args.units, args.intervals, args.output_dir)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"MachScope benchmark: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["--workload"]:
        sys.exit(workload(int(sys.argv[2])))
    sys.exit(main())
