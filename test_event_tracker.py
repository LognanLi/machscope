"""State changes are detected only between two successful OS snapshots."""

import unittest
from unittest.mock import Mock

import psutil

from event_tracker import ProcessStateTracker, sample_events


class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.process = Mock(pid=10)
        self.process.open_files.return_value = []
        self.process.children.return_value = []
        self.tracker = ProcessStateTracker()

    def test_initial_snapshot_is_baseline_then_file_and_child_changes_are_found(self):
        self.tracker.poll(self.process)  # State already present when recording began.
        self.process.open_files.return_value = [Mock(fd=8, path="/tmp/cache.db")]
        child = Mock(pid=12)
        child.create_time.return_value = 123.0
        child.name.return_value = "worker"
        self.process.children.return_value = [child]
        events, warnings = self.tracker.poll(self.process)
        self.assertEqual(warnings, [])
        self.assertEqual(events, [
            {"event_type": "file_opened", "related_pid": None, "subject": "fd 8: /tmp/cache.db"},
            {"event_type": "child_started", "related_pid": 12, "subject": "worker"},
        ])

    def test_closes_and_exits_are_observed(self):
        file_item = Mock(fd=8, path="/tmp/cache.db")
        child = Mock(pid=12)
        child.create_time.return_value = 123.0
        child.name.return_value = "worker"
        self.process.open_files.return_value = [file_item]
        self.process.children.return_value = [child]
        self.tracker.poll(self.process)
        self.process.open_files.return_value = []
        self.process.children.return_value = []
        events, _ = self.tracker.poll(self.process)
        self.assertEqual([event["event_type"] for event in events], ["file_closed", "child_exited"])

    def test_pid_reuse_is_a_child_exit_and_a_new_child(self):
        old = Mock(pid=12)
        old.create_time.return_value = 1.0
        old.name.return_value = "old worker"
        self.process.children.return_value = [old]
        self.tracker.poll(self.process)
        new = Mock(pid=12)
        new.create_time.return_value = 2.0
        new.name.return_value = "new worker"
        self.process.children.return_value = [new]
        events, _ = self.tracker.poll(self.process)
        self.assertEqual([event["event_type"] for event in events], ["child_started", "child_exited"])
        self.assertEqual({event["related_pid"] for event in events}, {12})

    def test_access_denied_preserves_state_and_recovers_without_false_events(self):
        open_file = Mock(fd=8, path="/tmp/cache.db")
        self.process.open_files.return_value = [open_file]
        self.tracker.poll(self.process)
        self.process.open_files.side_effect = psutil.AccessDenied(10)
        _, warnings = self.tracker.poll(self.process)
        self.assertEqual(len(warnings), 1)
        _, repeated = self.tracker.poll(self.process)
        self.assertEqual(repeated, [])
        self.process.open_files.side_effect = None
        self.assertEqual(self.tracker.poll(self.process), ([], []))

    def test_each_source_can_be_denied_without_inventing_closes(self):
        self.tracker.poll(self.process)
        self.process.open_files.side_effect = PermissionError("denied")
        self.process.children.side_effect = PermissionError("denied")
        events, warnings = self.tracker.poll(self.process)
        self.assertEqual(events, [])
        self.assertEqual(len(warnings), 2)
        events, warnings = self.tracker.poll(self.process)
        self.assertEqual(events, [])
        self.assertEqual(warnings, [])

    def test_disappearing_child_does_not_create_a_false_exit(self):
        vanished = Mock(pid=12)
        vanished.create_time.side_effect = psutil.NoSuchProcess(12)
        self.process.children.return_value = [vanished]
        events, _ = self.tracker.poll(self.process)
        self.assertEqual(events, [])

    def test_sample_events_get_timestamp_and_elapsed_time(self):
        self.tracker.poll(self.process)
        self.process.open_files.return_value = [Mock(fd=1, path="/tmp/a b")]
        events, warnings = sample_events(self.process, self.tracker, 2.5, "utc")
        self.assertEqual(warnings, [])
        self.assertEqual(events[0]["timestamp"], "utc")
        self.assertEqual(events[0]["elapsed_seconds"], 2.5)
        self.assertEqual(events[0]["subject"], "fd 1: /tmp/a b")


if __name__ == "__main__":
    unittest.main()
