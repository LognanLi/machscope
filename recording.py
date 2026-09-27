"""Record the existing collector's measurements, committing each sample."""

from pathlib import Path
import sqlite3
import sys
import time

import psutil

from observe import ensure_running, read_sample, select_process
from event_tracker import ProcessStateTracker, sample_events
import storage


def record(database, name=None, pid=None, interval=1.0):
    if interval < 0.1:
        print("MachScope: sampling interval must be at least 0.1 seconds.", file=sys.stderr)
        return 2
    try:
        process = select_process(name=name, pid=pid)
        ensure_running(process)
        process_name = process.name()
        created_at = process.create_time()
    except (psutil.NoSuchProcess, psutil.AccessDenied, PermissionError) as error:
        print(f"MachScope: unable to select process: {error}", file=sys.stderr)
        return 1

    with storage.open_database(database, create=True) as connection:
        started = time.monotonic()
        recording_id = storage.start_recording(
            connection, process.pid, process_name, created_at, storage.utc_now(), interval
        )
        count = 0
        status = "error"
        detail = "Recording ended unexpectedly."
        tracker = ProcessStateTracker()
        try:
            print(f"Recording {recording_id}: {process_name} (PID {process.pid})", flush=True)
            print(f"Database: {Path(database).expanduser().resolve()}", flush=True)
            print(f"Sampling every {interval:g}s. Press Ctrl-C to save and stop.", flush=True)
            while True:
                sample = read_sample(process, interval=interval)
                elapsed = time.monotonic() - started
                timestamp = storage.utc_now()
                storage.add_sample(
                    connection, recording_id, count + 1, timestamp, elapsed, sample
                )
                events, warnings = sample_events(
                    process, tracker, elapsed, timestamp
                )
                storage.add_process_events(connection, recording_id, events)
                count += 1
                print(
                    f"+{elapsed:6.1f}s  CPU: {sample['cpu_percent']:5.1f}%  "
                    f"RSS: {sample['memory_bytes'] / 1_000_000:6.1f} MB  "
                    f"Threads: {sample['thread_count']}", flush=True,
                )
                for event in events:
                    print(
                        f"  {event['event_type']}: "
                        f"{event['related_pid'] or ''} {event['subject']}".rstrip(),
                        flush=True,
                    )
                for warning in warnings:
                    print(warning, file=sys.stderr, flush=True)
        except KeyboardInterrupt:
            status, detail = "interrupted", None
        except psutil.NoSuchProcess:
            status, detail = "process_exited", None
        except (psutil.AccessDenied, PermissionError) as error:
            status, detail = "access_denied", str(error)
        except (sqlite3.Error, OSError) as error:
            status, detail = "error", str(error)
        finally:
            storage.finish_recording(
                connection, recording_id, status, storage.utc_now(),
                time.monotonic() - started, detail,
            )

        print(f"\nRecording {recording_id} saved: {count} samples; {status}.")
        if detail:
            print(f"MachScope: {detail}", file=sys.stderr)
        return 0 if status in ("interrupted", "process_exited") else 1
