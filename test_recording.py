"""Exercise recording lifecycle with real storage and simulated process reads."""

from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import psutil

import recording
import storage
from test_observe import capture_call, fake_process


SAMPLE = {"cpu_percent": 12.0, "memory_bytes": 40_000_000, "thread_count": 2}


class RecordingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "recordings.sqlite3"
        self.process = fake_process(412)
        self.process.create_time.return_value = 123.0

    def run_recording(self, reads, interval=1.0):
        with patch("recording.select_process", return_value=self.process):
            with patch("recording.read_sample", side_effect=reads):
                return capture_call(recording.record, self.path, pid=412, interval=interval)

    def load(self):
        with storage.open_database(self.path) as connection:
            return storage.get_recording(connection, "latest"), storage.get_samples(connection, 1)

    def test_exit_saves_samples_and_reason(self):
        status, stdout, stderr = self.run_recording([SAMPLE, SAMPLE, psutil.NoSuchProcess(412)])
        metadata, samples = self.load()
        self.assertEqual(status, 0)
        self.assertEqual(stderr, "")
        self.assertIn("2 samples; process_exited", stdout)
        self.assertEqual(metadata["status"], "process_exited")
        self.assertIsNotNone(metadata["ended_at"])
        self.assertEqual(len(samples), 2)

    def test_ctrl_c_preserves_committed_sample(self):
        def read_then_interrupt(_, interval=1.0):
            if not getattr(read_then_interrupt, "sampled", False):
                read_then_interrupt.sampled = True
                return SAMPLE
            # Prove the sample is already on disk before interrupting the recorder.
            self.assertEqual(len(self.load()[1]), 1)
            raise KeyboardInterrupt

        status, _, stderr = self.run_recording(read_then_interrupt)
        metadata, samples = self.load()
        self.assertEqual(status, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(metadata["status"], "interrupted")
        self.assertEqual(len(samples), 1)

    def test_exit_before_first_sample_is_valid_empty_recording(self):
        status, _, _ = self.run_recording([psutil.NoSuchProcess(412)])
        metadata, samples = self.load()
        self.assertEqual(status, 0)
        self.assertEqual(samples, [])
        self.assertEqual(metadata["status"], "process_exited")

    def test_access_denied_preserves_partial_recording(self):
        status, _, stderr = self.run_recording([SAMPLE, psutil.AccessDenied(412)])
        metadata, samples = self.load()
        self.assertEqual(status, 1)
        self.assertIn("MachScope:", stderr)
        self.assertEqual(metadata["status"], "access_denied")
        self.assertEqual(len(samples), 1)

    def test_write_error_records_failure_without_fake_sample(self):
        with patch("recording.storage.add_sample", side_effect=sqlite3.OperationalError("disk full")):
            status, _, stderr = self.run_recording([SAMPLE])
        metadata, samples = self.load()
        self.assertEqual(status, 1)
        self.assertIn("disk full", stderr)
        self.assertEqual(metadata["status"], "error")
        self.assertEqual(samples, [])

    def test_clock_correction_does_not_change_elapsed_time(self):
        with patch("recording.time.monotonic", side_effect=[100.0, 101.0, 102.0, 103.0]):
            with patch("recording.storage.utc_now", side_effect=["12:00:00", "12:00:01", "11:59:00", "11:59:01"]):
                self.run_recording([SAMPLE, SAMPLE, KeyboardInterrupt()])
        metadata, samples = self.load()
        self.assertEqual([row["elapsed_seconds"] for row in samples], [1.0, 2.0])
        self.assertEqual([row["timestamp"] for row in samples], ["12:00:01", "11:59:00"])
        self.assertEqual(metadata["duration_seconds"], 3.0)

    def test_failed_selection_creates_no_database(self):
        with patch("recording.select_process", side_effect=psutil.NoSuchProcess(412)):
            status, _, stderr = capture_call(recording.record, self.path, pid=412)
        self.assertEqual(status, 1)
        self.assertIn("unable to select", stderr)
        self.assertFalse(self.path.exists())

    def test_configurable_interval_is_saved_and_passed_to_collector(self):
        with patch("recording.sample_events", return_value=([], [])):
            with patch("recording.select_process", return_value=self.process):
                with patch("recording.read_sample", side_effect=[SAMPLE, psutil.NoSuchProcess(412)]) as read:
                    status, _, _ = capture_call(recording.record, self.path, pid=412, interval=0.2)
        metadata, _ = self.load()
        self.assertEqual(status, 0)
        self.assertEqual(metadata["interval_seconds"], 0.2)
        self.assertEqual(read.call_count, 2)
        self.assertEqual(read.call_args_list[0].kwargs, {"interval": 0.2})

    def test_state_changes_are_saved_with_sample_time(self):
        with patch("recording.sample_events", return_value=(
            [{"event_type": "child_started", "related_pid": 500, "subject": "worker",
              "elapsed_seconds": 2.0, "timestamp": "utc-sample"}], []
        )):
            status, stdout, _ = self.run_recording([SAMPLE, psutil.NoSuchProcess(412)])
        with storage.open_database(self.path) as connection:
            events = storage.get_process_events(connection, 1)
        self.assertEqual(status, 0)
        self.assertIn("child_started", stdout)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["related_pid"], 500)


if __name__ == "__main__":
    unittest.main()
