"""Run an owned synthetic workload, record it, then inspect the real samples."""

from pathlib import Path
import subprocess
import sys
import threading
import time


ROOT = Path(__file__).resolve().parent
DATABASE = ROOT / ".machscope" / "demo.sqlite3"


def select_python(project_root=ROOT, current_python=sys.executable):
    """Use the installed project environment when the launcher is system Python."""
    project_python = project_root / ".venv" / "bin" / "python"
    return str(project_python) if project_python.is_file() else current_python


def synthetic_workload():
    """Change memory, threads, files, children, and CPU in visible stages."""
    print("READY", flush=True)
    if sys.stdin.readline() != "start\n":
        return 1
    print("Demo workload: 3 seconds of baseline measurements.", flush=True)
    time.sleep(3)

    memory = bytearray(64_000_000)
    for offset in range(0, len(memory), 4096):
        memory[offset] = 1  # Touch pages so the OS actually assigns resident memory.

    stop = threading.Event()
    ready = threading.Barrier(7)
    demo_file = (ROOT / ".machscope" / "demo-open-file.txt").open("w")
    child = subprocess.Popen(
        [select_python(), str(Path(__file__).resolve()), "--child-workload"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )
    if child.stdout.readline().strip() != "CHILD_READY":
        raise RuntimeError("The demo child process did not start.")

    def wait_in_thread():
        ready.wait()
        stop.wait()

    threads = [threading.Thread(target=wait_in_thread) for _ in range(6)]
    for thread in threads:
        thread.start()
    ready.wait()
    print(
        "Demo workload: opened a file, started a child and 6 threads, "
        "increased memory, now using CPU for 3 seconds.", flush=True,
    )

    cpu_end = time.monotonic() + 3
    while time.monotonic() < cpu_end:
        sum(range(1000))

    stop.set()
    for thread in threads:
        thread.join()
    demo_file.close()
    child.stdin.write("stop\n")
    child.stdin.close()
    child_status = child.wait(timeout=3)
    child.stdout.close()
    if child_status:
        raise RuntimeError("The demo child process did not stop cleanly.")
    print("Demo workload: threads stopped; keeping memory allocated for 3 seconds.", flush=True)
    time.sleep(3)
    # Keep the allocation live through the final sample.
    assert memory[0] == 1
    return 0


def synthetic_child():
    print("CHILD_READY", flush=True)
    return 0 if sys.stdin.readline() == "stop\n" else 1


def main():
    if sys.argv[1:] == ["--workload"]:
        return synthetic_workload()
    if sys.argv[1:] == ["--child-workload"]:
        return synthetic_child()

    python = select_python()
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    record_command = [
        python, "-m", "machscope", "record", "--pid", "WORKLOAD_PID",
        "--db", str(DATABASE),
    ]
    saved_output = []

    def emit(text):
        saved_output.append(text)
        sys.stdout.write(text)
        sys.stdout.flush()

    workload = subprocess.Popen(
        [python, str(Path(__file__).resolve()), "--workload"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )
    recorder = None
    recording_id = None
    try:
        ready = workload.stdout.readline()
        if ready.strip() != "READY":
            raise RuntimeError(f"Demo workload failed to start: {ready.strip()}")

        record_command[5] = str(workload.pid)
        emit("MachScope Week 2–4 demonstration\n")
        emit(f"Database: {DATABASE}\n\n")
        recorder = subprocess.Popen(
            record_command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        started = False
        for line in recorder.stdout:
            emit(line)
            if recording_id is None and line.startswith("Recording "):
                recording_id = line.split()[1].rstrip(":")
            if not started and line.startswith("Sampling every"):
                workload.stdin.write("start\n")
                workload.stdin.flush()
                started = True
        record_status = recorder.wait()
        if workload.poll() is None:
            workload.stdin.close()
        workload_status = workload.wait(timeout=5)
        if record_status or workload_status or recording_id is None:
            raise RuntimeError("Recording or demonstration workload did not finish successfully.")

        for title, command in (
            ("Saved recordings", ["recordings"]),
            (f"Recording {recording_id}", ["inspect", recording_id]),
            (f"Changes and surrounding timeline for {recording_id}",
             ["analyze", recording_id]),
        ):
            emit(f"\n--- {title} ---\n")
            result = subprocess.run(
                [python, "-m", "machscope", *command, "--db", str(DATABASE)],
                cwd=ROOT, capture_output=True, text=True,
            )
            emit(result.stdout)
            if result.stderr:
                emit(result.stderr)
            if result.returncode:
                raise RuntimeError(f"The '{command[0]}' demo command failed.")

        transcript = DATABASE.parent / "demo-latest.txt"
        transcript.write_text("".join(saved_output))
        emit(f"\nDemo complete. Rerun: python demo.py\nTranscript: {transcript}\n")
    finally:
        if recorder is not None and recorder.poll() is None:
            recorder.terminate()
            recorder.wait(timeout=5)
        if workload.poll() is None:
            workload.terminate()
            workload.wait(timeout=5)
        if workload.stdout:
            workload.stdout.close()
        if workload.stdin and not workload.stdin.closed:
            workload.stdin.close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nDemo stopped.")
        sys.exit(0)
