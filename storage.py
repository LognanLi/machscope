"""Small SQLite storage layer: one recording has many ordered samples."""

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sqlite3


DEFAULT_DATABASE = Path(".machscope/recordings.sqlite3")

SCHEMA = """
CREATE TABLE IF NOT EXISTS recordings (
    id INTEGER PRIMARY KEY,
    pid INTEGER NOT NULL,
    process_name TEXT NOT NULL,
    process_created_at REAL NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    duration_seconds REAL,
    status TEXT NOT NULL,
    error TEXT,
    interval_seconds REAL NOT NULL DEFAULT 1.0
);
CREATE TABLE IF NOT EXISTS samples (
    recording_id INTEGER NOT NULL REFERENCES recordings(id),
    sequence INTEGER NOT NULL,
    timestamp TEXT NOT NULL,
    elapsed_seconds REAL NOT NULL CHECK (elapsed_seconds >= 0),
    cpu_percent REAL NOT NULL CHECK (cpu_percent >= 0),
    memory_bytes INTEGER NOT NULL CHECK (memory_bytes >= 0),
    thread_count INTEGER NOT NULL CHECK (thread_count >= 0),
    PRIMARY KEY (recording_id, sequence)
);
CREATE TABLE IF NOT EXISTS process_events (
    id INTEGER PRIMARY KEY,
    recording_id INTEGER NOT NULL REFERENCES recordings(id),
    timestamp TEXT NOT NULL,
    elapsed_seconds REAL NOT NULL CHECK (elapsed_seconds >= 0),
    event_type TEXT NOT NULL CHECK (event_type IN
        ('file_opened', 'file_closed', 'child_started', 'child_exited')),
    related_pid INTEGER,
    subject TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS process_events_recording_time
    ON process_events(recording_id, elapsed_seconds);
"""


def utc_now():
    """An absolute timestamp for people, separate from our elapsed-time clock."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@contextmanager
def open_database(path, create=False):
    path = Path(path).expanduser().resolve()
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
    else:
        if not path.is_file():
            raise ValueError(f"No recording database at {path}. Run machscope record first.")
        # Reading must not silently create a database at a mistyped path.
        connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        if create:
            connection.executescript(SCHEMA)
            # Existing Week 2/3 databases keep their recordings at one-second
            # intervals when the Week 5 field is introduced.
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(recordings)")}
            if "interval_seconds" not in columns:
                connection.execute(
                    "ALTER TABLE recordings ADD COLUMN interval_seconds REAL NOT NULL DEFAULT 1.0"
                )
                connection.commit()
        yield connection
    finally:
        connection.close()


def start_recording(connection, pid, name, process_created_at, started_at, interval_seconds=1.0):
    with connection:
        cursor = connection.execute(
            """INSERT INTO recordings
               (pid, process_name, process_created_at, started_at, status, interval_seconds)
               VALUES (?, ?, ?, ?, 'recording', ?)""",
            (pid, name, process_created_at, started_at, interval_seconds),
        )
    return cursor.lastrowid


def add_sample(connection, recording_id, sequence, timestamp, elapsed_seconds, sample):
    # Each small transaction is committed immediately, rather than at shutdown.
    with connection:
        connection.execute(
            "INSERT INTO samples VALUES (?, ?, ?, ?, ?, ?, ?)",
            (recording_id, sequence, timestamp, elapsed_seconds,
             sample["cpu_percent"], sample["memory_bytes"], sample["thread_count"]),
        )


def add_process_events(connection, recording_id, events):
    if not events:
        return
    with connection:
        connection.executemany(
            """INSERT INTO process_events
               (recording_id, timestamp, elapsed_seconds, event_type, related_pid, subject)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [(recording_id, event["timestamp"], event["elapsed_seconds"], event["event_type"],
              event["related_pid"], event["subject"]) for event in events],
        )


def finish_recording(connection, recording_id, status, ended_at, duration_seconds, error=None):
    with connection:
        connection.execute(
            """UPDATE recordings SET status=?, ended_at=?, duration_seconds=?, error=?
               WHERE id=?""",
            (status, ended_at, duration_seconds, error, recording_id),
        )


def list_recordings(connection):
    return connection.execute(
        """SELECT r.*, COUNT(s.sequence) AS sample_count FROM recordings AS r
           LEFT JOIN samples AS s ON s.recording_id=r.id
           GROUP BY r.id ORDER BY r.id DESC"""
    ).fetchall()


def get_recording(connection, selector):
    if selector == "latest":
        row = connection.execute("SELECT * FROM recordings ORDER BY id DESC LIMIT 1").fetchone()
    else:
        row = connection.execute("SELECT * FROM recordings WHERE id=?", (int(selector),)).fetchone()
    if row is None:
        raise ValueError(f"Recording {selector!r} was not found.")
    return dict(row)


def get_samples(connection, recording_id):
    rows = connection.execute(
        "SELECT * FROM samples WHERE recording_id=? ORDER BY sequence", (recording_id,)
    ).fetchall()
    return [dict(row) for row in rows]


def get_process_events(connection, recording_id):
    rows = connection.execute(
        """SELECT * FROM process_events WHERE recording_id=?
           ORDER BY elapsed_seconds, id""", (recording_id,)
    ).fetchall()
    return [dict(row) for row in rows]
