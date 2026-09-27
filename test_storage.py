"""Verify real SQLite transactions in temporary directories."""

from pathlib import Path
import sqlite3
import tempfile
import unittest

import storage


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "recordings #1?.sqlite3"

    def start(self, connection):
        return storage.start_recording(connection, 412, "Demo's process", 123.0, "start")

    def sample(self, connection, recording_id, sequence=1):
        storage.add_sample(connection, recording_id, sequence, "timestamp", float(sequence),
                           {"cpu_percent": 130.0, "memory_bytes": 20_000_000, "thread_count": 8})

    def test_metadata_and_samples_survive_reopening(self):
        with storage.open_database(self.path, create=True) as connection:
            recording_id = self.start(connection)
            self.sample(connection, recording_id)
            storage.finish_recording(connection, recording_id, "process_exited", "end", 2.5)
        with storage.open_database(self.path) as connection:
            recording = storage.get_recording(connection, str(recording_id))
            samples = storage.get_samples(connection, recording_id)
        self.assertEqual(recording["process_name"], "Demo's process")
        self.assertEqual(recording["pid"], 412)
        self.assertEqual(recording["process_created_at"], 123)
        self.assertEqual(recording["status"], "process_exited")
        self.assertEqual(recording["duration_seconds"], 2.5)
        self.assertEqual(samples[0]["cpu_percent"], 130)
        self.assertEqual(samples[0]["memory_bytes"], 20_000_000)

    def test_independent_connection_sees_each_committed_sample(self):
        with storage.open_database(self.path, create=True) as writer:
            recording_id = self.start(writer)
            self.sample(writer, recording_id)
            with storage.open_database(self.path) as reader:
                self.assertEqual(len(storage.get_samples(reader, recording_id)), 1)

    def test_ids_latest_listing_and_sample_order(self):
        with storage.open_database(self.path, create=True) as connection:
            first = self.start(connection)
            second = self.start(connection)
            self.sample(connection, first, 2)
            self.sample(connection, first, 1)
            rows = storage.list_recordings(connection)
            self.assertNotEqual(first, second)
            self.assertEqual([row["id"] for row in rows], [second, first])
            self.assertEqual([row["sample_count"] for row in rows], [0, 2])
            self.assertEqual(storage.get_recording(connection, "latest")["id"], second)
            self.assertEqual([row["sequence"] for row in storage.get_samples(connection, first)], [1, 2])

    def test_bad_sample_rolls_back_and_keeps_previous_samples(self):
        with storage.open_database(self.path, create=True) as connection:
            recording_id = self.start(connection)
            self.sample(connection, recording_id)
            with self.assertRaises(sqlite3.IntegrityError):
                self.sample(connection, recording_id)
            with self.assertRaises(sqlite3.IntegrityError):
                self.sample(connection, recording_id + 100)
            self.assertEqual(len(storage.get_samples(connection, recording_id)), 1)

    def test_missing_reads_do_not_create_a_file(self):
        with self.assertRaisesRegex(ValueError, "No recording database"):
            with storage.open_database(self.path):
                pass
        self.assertFalse(self.path.exists())

    def test_unknown_recording_and_empty_latest(self):
        with storage.open_database(self.path, create=True) as connection:
            for selector in ("1", "latest"):
                with self.subTest(selector=selector), self.assertRaisesRegex(ValueError, "not found"):
                    storage.get_recording(connection, selector)

    def test_read_connection_cannot_write(self):
        with storage.open_database(self.path, create=True):
            pass
        with storage.open_database(self.path) as connection:
            with self.assertRaises(sqlite3.OperationalError):
                self.start(connection)

    def test_process_events_persist_and_are_ordered(self):
        with storage.open_database(self.path, create=True) as connection:
            recording_id = self.start(connection)
            events = [
                {"timestamp": "t2", "elapsed_seconds": 2.0, "event_type": "child_started",
                 "related_pid": 514, "subject": "worker"},
                {"timestamp": "t1", "elapsed_seconds": 1.0, "event_type": "file_opened",
                 "related_pid": None, "subject": "fd 8: /tmp/a.db"},
            ]
            storage.add_process_events(connection, recording_id, events)
        with storage.open_database(self.path) as connection:
            saved = storage.get_process_events(connection, recording_id)
        self.assertEqual([event["event_type"] for event in saved], ["file_opened", "child_started"])
        self.assertEqual(saved[0]["subject"], "fd 8: /tmp/a.db")

    def test_upgrade_adds_default_interval_without_losing_old_recordings(self):
        old_database = sqlite3.connect(self.path)
        try:
            old_database.execute(
                """CREATE TABLE recordings (
                    id INTEGER PRIMARY KEY, pid INTEGER NOT NULL, process_name TEXT NOT NULL,
                    process_created_at REAL NOT NULL, started_at TEXT NOT NULL,
                    ended_at TEXT, duration_seconds REAL, status TEXT NOT NULL, error TEXT)"""
            )
            old_database.execute(
                """INSERT INTO recordings
                   VALUES (1, 412, 'old run', 123, 'start', 'end', 2, 'interrupted', NULL)"""
            )
            old_database.commit()
        finally:
            old_database.close()
        with storage.open_database(self.path, create=True) as connection:
            row = storage.get_recording(connection, "1")
            self.assertEqual(row["process_name"], "old run")
            self.assertEqual(row["interval_seconds"], 1.0)

    def test_upgrade_adds_default_interval_without_losing_old_recordings(self):
        with sqlite3.connect(self.path) as old_database:
            old_database.execute(
                """CREATE TABLE recordings (
                    id INTEGER PRIMARY KEY, pid INTEGER NOT NULL, process_name TEXT NOT NULL,
                    process_created_at REAL NOT NULL, started_at TEXT NOT NULL,
                    ended_at TEXT, duration_seconds REAL, status TEXT NOT NULL, error TEXT)"""
            )
            old_database.execute(
                """INSERT INTO recordings
                   VALUES (1, 412, 'old run', 123, 'start', 'end', 2, 'interrupted', NULL)"""
            )
        with storage.open_database(self.path, create=True) as connection:
            row = storage.get_recording(connection, "1")
            self.assertEqual(row["process_name"], "old run")
            self.assertEqual(row["interval_seconds"], 1.0)

    def test_event_foreign_key_and_kind_are_checked(self):
        with storage.open_database(self.path, create=True) as connection:
            bad = {"timestamp": "t", "elapsed_seconds": 1.0, "event_type": "invented",
                   "related_pid": None, "subject": "x"}
            with self.assertRaises(sqlite3.IntegrityError):
                storage.add_process_events(connection, 999, [bad])
            recording_id = self.start(connection)
            with self.assertRaises(sqlite3.IntegrityError):
                storage.add_process_events(connection, recording_id, [bad])
            self.assertEqual(storage.get_process_events(connection, recording_id), [])


if __name__ == "__main__":
    unittest.main()
