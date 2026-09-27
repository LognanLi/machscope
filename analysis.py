"""Deterministic adjacent-sample rules and readable recording reports."""

from pathlib import Path

import storage


def detect_changes(samples, cpu_jump=50.0, memory_jump_percent=25.0,
                   memory_jump_mb=20.0, thread_change=5):
    """Compare each sample to its predecessor; return events in recording order."""
    events = []
    for index in range(1, len(samples)):
        before, after = samples[index - 1], samples[index]
        changes = []
        cpu_delta = after["cpu_percent"] - before["cpu_percent"]
        if cpu_delta >= cpu_jump:
            changes.append(
                f"CPU rise: {before['cpu_percent']:.1f}% -> {after['cpu_percent']:.1f}% "
                f"(+{cpu_delta:.1f} percentage points)"
            )

        memory_delta = after["memory_bytes"] - before["memory_bytes"]
        old_memory = before["memory_bytes"]
        # From zero, a relative percentage is undefined; require the MB floor.
        relative_rise = old_memory == 0 or memory_delta * 100 >= old_memory * memory_jump_percent
        if memory_delta >= memory_jump_mb * 1_000_000 and relative_rise:
            percent = f"+{memory_delta / old_memory * 100:.1f}%" if old_memory else "from zero"
            changes.append(
                f"Memory rise: {old_memory / 1_000_000:.1f} -> "
                f"{after['memory_bytes'] / 1_000_000:.1f} MB ({percent})"
            )

        thread_delta = after["thread_count"] - before["thread_count"]
        if abs(thread_delta) >= thread_change:
            changes.append(
                f"Thread change: {before['thread_count']} -> {after['thread_count']} "
                f"({thread_delta:+d})"
            )
        if changes:
            events.append({"index": index, "changes": changes})
    return events


def timeline_window(samples, index, seconds):
    """Use elapsed seconds, so wall-clock corrections cannot reorder a window."""
    center = samples[index]["elapsed_seconds"]
    return [
        (position, sample) for position, sample in enumerate(samples)
        if abs(sample["elapsed_seconds"] - center) <= seconds
    ]


def show_recordings(database):
    if not Path(database).expanduser().exists():
        print("No recordings yet. Run machscope record <name> first.")
        return 0
    with storage.open_database(database) as connection:
        rows = storage.list_recordings(connection)
    if not rows:
        print("No recordings yet.")
        return 0
    print("ID  PROCESS  PID  SAMPLES  INTERVAL  STATUS  STARTED (UTC)")
    for row in rows:
        print(
            f"{row['id']}  {row['process_name']}  {row['pid']}  "
            f"{row['sample_count']}  {row['interval_seconds']:g}s  "
            f"{row['status']}  {row['started_at']}"
        )
    if any(row["status"] == "recording" for row in rows):
        print("'recording' means active or stopped without a clean shutdown.")
    return 0


def load_recording(database, selector):
    with storage.open_database(database) as connection:
        # A read transaction keeps metadata and samples consistent during a live recording.
        connection.execute("BEGIN")
        recording = storage.get_recording(connection, selector)
        samples = storage.get_samples(connection, recording["id"])
        events = storage.get_process_events(connection, recording["id"])
    return recording, samples, events


def print_summary(recording, samples, events=()):
    print(f"Recording {recording['id']}: {recording['process_name']} (PID {recording['pid']})")
    print(f"Status: {recording['status']} | Samples: {len(samples)}")
    print(f"File and child-process changes: {len(events)}")
    print(f"Started (UTC): {recording['started_at']}")
    print(f"Sampling interval: {recording['interval_seconds']:g}s")
    print(f"Ended (UTC): {recording['ended_at'] or 'not recorded'}")
    duration = recording["duration_seconds"]
    if duration is not None:
        print(f"Duration: {duration:.1f}s")
    if recording["status"] == "recording":
        print("This recording is active or stopped without a clean shutdown.")
    if recording["error"]:
        print(f"Error: {recording['error']}")
    if not samples:
        print("No samples were captured.")
        return
    cpus = [sample["cpu_percent"] for sample in samples]
    memory = [sample["memory_bytes"] / 1_000_000 for sample in samples]
    threads = [sample["thread_count"] for sample in samples]
    print(f"CPU: {min(cpus):.1f}% min / {sum(cpus) / len(cpus):.1f}% sample mean / {max(cpus):.1f}% max")
    print(f"RSS: {min(memory):.1f}-{max(memory):.1f} MB | Threads: {min(threads)}-{max(threads)}")


def inspect_recording(database, selector):
    recording, samples, events = load_recording(database, selector)
    print_summary(recording, samples, events)
    if events:
        print("Process changes:")
        for event in events:
            target = f"PID {event['related_pid']} " if event["related_pid"] else ""
            print(f"  +{event['elapsed_seconds']:.1f}s {event['event_type']}: {target}{event['subject']}")
    return 0


def analyze_recording(database, selector, window=2.0, **thresholds):
    recording, samples, process_events = load_recording(database, selector)
    print_summary(recording, samples, process_events)
    print(
        f"\nRules: CPU rise >= {thresholds.get('cpu_jump', 50):g} pp; "
        f"memory rise >= {thresholds.get('memory_jump_percent', 25):g}% AND "
        f">= {thresholds.get('memory_jump_mb', 20):g} MB; "
        f"thread change >= {thresholds.get('thread_change', 5)}."
    )
    print("Baseline: previous sample. Flags describe changes, not their cause.")
    if len(samples) < 2:
        print("At least two samples are needed to analyze changes.")
        return 0
    events = detect_changes(samples, **thresholds)
    if not events:
        print("No changes crossed these thresholds.")
        return 0
    print(f"Flagged samples: {len(events)}")
    for event in events:
        index = event["index"]
        print(f"\nChange at +{samples[index]['elapsed_seconds']:.1f}s:")
        for change in event["changes"]:
            print(f"  {change}")
        print(f"  Timeline (+/- {window:g}s; UTC timestamps; * = flagged sample):")
        for position, sample in timeline_window(samples, index, window):
            marker = "*" if position == index else " "
            print(
                f"  {marker} +{sample['elapsed_seconds']:5.1f}s {sample['timestamp']}  "
                f"CPU {sample['cpu_percent']:5.1f}%  "
                f"RSS {sample['memory_bytes'] / 1_000_000:6.1f} MB  "
                f"Threads {sample['thread_count']}"
            )
        start = samples[index]["elapsed_seconds"] - window
        end = samples[index]["elapsed_seconds"] + window
        for event in process_events:
            if start <= event["elapsed_seconds"] <= end:
                target = f"PID {event['related_pid']} " if event["related_pid"] else ""
                print(
                    f"    +{event['elapsed_seconds']:5.1f}s {event['timestamp']}  "
                    f"{event['event_type']}: {target}{event['subject']}"
                )
    return 0
