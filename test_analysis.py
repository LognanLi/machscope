"""Synthetic recordings have known changes, independent of live system noise."""

from pathlib import Path
import tempfile
import unittest

import analysis
import machscope
import storage
from test_observe import capture_call


def sample(elapsed, cpu=12.0, memory_mb=80.0, threads=10):
    return {"elapsed_seconds": elapsed, "timestamp": f"time-{elapsed}",
            "cpu_percent": cpu, "memory_bytes": int(memory_mb * 1_000_000),
            "thread_count": threads}


class RuleTests(unittest.TestCase):
    def test_known_three_metric_jump(self):
        rows = [sample(1, 12, 410, 17), sample(2, 91, 690, 31)]
        events = analysis.detect_changes(rows)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["index"], 1)
        self.assertEqual(events[0]["changes"], [
            "CPU rise: 12.0% -> 91.0% (+79.0 percentage points)",
            "Memory rise: 410.0 -> 690.0 MB (+68.3%)",
            "Thread change: 17 -> 31 (+14)",
        ])
        self.assertEqual(analysis.detect_changes(rows), events)

    def test_empty_single_sample_and_stable_series(self):
        for rows in ([], [sample(1)], [sample(1), sample(2), sample(3)]):
            with self.subTest(rows=rows):
                self.assertEqual(analysis.detect_changes(rows), [])

    def test_exact_thresholds_are_inclusive(self):
        events = analysis.detect_changes([sample(1), sample(2, 62, 100, 15)])
        self.assertEqual(len(events[0]["changes"]), 3)

    def test_below_thresholds_do_not_flag(self):
        self.assertEqual(analysis.detect_changes([sample(1), sample(2, 61.9, 99.9, 14)]), [])

    def test_memory_requires_both_relative_and_absolute_rise(self):
        for before, after in ((1, 2), (1_000, 1_030)):
            with self.subTest(before=before, after=after):
                self.assertEqual(analysis.detect_changes([sample(1, memory_mb=before), sample(2, memory_mb=after)]), [])

    def test_memory_zero_baseline_is_handled_without_division(self):
        events = analysis.detect_changes([sample(1, memory_mb=0), sample(2, memory_mb=20)])
        self.assertIn("from zero", events[0]["changes"][0])

    def test_falls_only_flag_thread_change(self):
        events = analysis.detect_changes([sample(1, 99, 100, 20), sample(2, 0, 10, 10)])
        self.assertEqual(events[0]["changes"], ["Thread change: 20 -> 10 (-10)"])

    def test_custom_thresholds_change_results(self):
        rows = [sample(1), sample(2, 30, 90, 12)]
        self.assertEqual(analysis.detect_changes(rows), [])
        events = analysis.detect_changes(rows, cpu_jump=10, memory_jump_percent=10,
                                         memory_jump_mb=5, thread_change=2)
        self.assertEqual(len(events[0]["changes"]), 3)

    def test_baseline_is_previous_sample_not_start_of_recording(self):
        rows = [sample(1, 0), sample(2, 40), sample(3, 80)]
        self.assertEqual(analysis.detect_changes(rows), [])

    def test_window_uses_elapsed_seconds_not_sample_count_or_wall_clock(self):
        rows = [sample(1), sample(4), sample(5), sample(6), sample(9)]
        rows[3]["timestamp"] = "clock moved backwards"
        self.assertEqual([index for index, _ in analysis.timeline_window(rows, 2, 1)], [1, 2, 3])
        self.assertEqual([index for index, _ in analysis.timeline_window(rows, 2, 0)], [2])
        self.assertEqual([index for index, _ in analysis.timeline_window(rows, 0, 1)], [0])


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "recordings.sqlite3"

    def save(self, rows):
        with storage.open_database(self.path, create=True) as connection:
            recording_id = storage.start_recording(connection, 123, "Synthetic", 100, "start")
            for index, row in enumerate(rows, 1):
                storage.add_sample(connection, recording_id, index, row["timestamp"], row["elapsed_seconds"], row)
        return recording_id

    def test_saved_analysis_is_repeatable_and_has_timeline(self):
        self.save([sample(1), sample(2, 91, 160, 20), sample(3, 91, 160, 20)])
        with storage.open_database(self.path, create=True) as connection:
            storage.add_process_events(connection, 1, [
                {"timestamp": "file-change", "elapsed_seconds": 1.5,
                 "event_type": "file_opened", "related_pid": None, "subject": "/tmp/cache.db"}
            ])
        first = capture_call(analysis.analyze_recording, self.path, "latest")
        self.assertEqual(capture_call(analysis.analyze_recording, self.path, "latest"), first)
        self.assertEqual(first[0], 0)
        self.assertIn("Flagged samples: 1", first[1])
        self.assertIn("Timeline", first[1])
        self.assertIn("time-1", first[1])
        self.assertIn("time-3", first[1])
        self.assertIn("file_opened", first[1])
        self.assertIn("active or stopped without a clean shutdown", first[1])

    def test_empty_recording_has_readable_summary(self):
        self.save([])
        status, stdout, stderr = capture_call(analysis.analyze_recording, self.path, "latest")
        self.assertEqual(status, 0)
        self.assertEqual(stderr, "")
        self.assertIn("No samples", stdout)
        self.assertIn("At least two", stdout)

    def test_missing_list_does_not_create_database(self):
        status, stdout, _ = capture_call(analysis.show_recordings, self.path)
        self.assertEqual(status, 0)
        self.assertIn("No recordings yet", stdout)
        self.assertFalse(self.path.exists())

    def test_cli_inspects_lists_and_handles_unknown_id(self):
        self.save([sample(1)])
        for arguments, expected in ((["inspect", "latest"], "Samples: 1"),
                                    (["recordings"], "Synthetic")):
            status, stdout, stderr = capture_call(machscope.main, arguments + ["--db", str(self.path)])
            self.assertEqual(status, 0)
            self.assertEqual(stderr, "")
            self.assertIn(expected, stdout)
        status, _, stderr = capture_call(machscope.main, ["inspect", "999", "--db", str(self.path)])
        self.assertEqual(status, 1)
        self.assertIn("not found", stderr)

    def test_cli_reports_missing_and_corrupt_databases_without_traceback(self):
        arguments = ["inspect", "latest", "--db", str(self.path)]
        self.assertEqual(capture_call(machscope.main, arguments)[0], 1)
        self.path.write_text("not a database")
        status, _, stderr = capture_call(machscope.main, arguments)
        self.assertEqual(status, 1)
        self.assertIn("not a database", stderr)


if __name__ == "__main__":
    unittest.main()
