"""Exercise selection and monitoring with predictable, simulated processes."""

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import Mock, patch

import psutil

import observe


def fake_process(pid, name="Spotify"):
    process = Mock(pid=pid)
    process.name.return_value = name
    process.is_running.return_value = True
    process.status.return_value = psutil.STATUS_SLEEPING
    process.memory_info.return_value.rss = 381_000_000
    process.num_threads.return_value = 24
    return process


def capture_call(function, *args, **kwargs):
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        status = function(*args, **kwargs)
    return status, stdout.getvalue(), stderr.getvalue()


class SelectionTests(unittest.TestCase):
    def test_exact_case_insensitive_match_excludes_helpers(self):
        spotify = fake_process(412)
        helper = fake_process(413, "Spotify Helper")
        with patch("observe.psutil.process_iter", return_value=[helper, spotify]):
            self.assertIs(observe.select_process(name="sPoTiFy"), spotify)

    def test_no_match_explains_how_to_find_names(self):
        with patch("observe.psutil.process_iter", return_value=[]):
            status, stdout, stderr = capture_call(observe.observe, name="Missing")
        self.assertEqual(status, 1)
        self.assertEqual(stdout, "")
        self.assertIn("No accessible process named 'Missing'", stderr)
        self.assertIn("python -m machscope", stderr)

    def test_ambiguous_name_lists_sorted_pids_without_observing(self):
        processes = [fake_process(900), fake_process(412)]
        with patch("observe.psutil.process_iter", return_value=processes):
            with patch("observe.observe_process") as monitor:
                status, stdout, stderr = capture_call(observe.observe, name="Spotify")
        self.assertEqual(status, 1)
        self.assertEqual(stdout, "")
        self.assertIn("PIDs 412, 900", stderr)
        self.assertIn("--pid", stderr)
        monitor.assert_not_called()

    def test_unreadable_and_exited_candidates_do_not_stop_selection(self):
        denied = fake_process(1)
        denied.name.side_effect = psutil.AccessDenied(1)
        exited = fake_process(2)
        exited.name.side_effect = psutil.NoSuchProcess(2)
        zombie = fake_process(3)
        zombie.name.side_effect = psutil.ZombieProcess(3)
        spotify = fake_process(412)
        with patch("observe.psutil.process_iter", return_value=[denied, exited, zombie, spotify]):
            self.assertIs(observe.select_process(name="Spotify"), spotify)

    def test_pid_selects_one_process_directly(self):
        process = fake_process(412)
        with patch("observe.psutil.Process", return_value=process) as constructor:
            self.assertIs(observe.select_process(pid=412), process)
        constructor.assert_called_once_with(412)

    def test_missing_pid_is_an_error(self):
        with patch("observe.psutil.Process", side_effect=psutil.NoSuchProcess(412)):
            status, stdout, stderr = capture_call(observe.observe, pid=412)
        self.assertEqual(status, 1)
        self.assertEqual(stdout, "")
        self.assertIn("PID 412 no longer exists", stderr)

    def test_process_list_permission_error(self):
        for error in (psutil.AccessDenied(), PermissionError("Operation not permitted")):
            with self.subTest(error=type(error).__name__):
                with patch("observe.psutil.process_iter", side_effect=error):
                    status, stdout, stderr = capture_call(observe.observe, name="Spotify")
                self.assertEqual(status, 1)
                self.assertEqual(stdout, "")
                self.assertIn("permission denied", stderr)


class ObservationTests(unittest.TestCase):
    def test_repeated_samples_keep_units_and_cpu_over_100(self):
        process = fake_process(412)
        process.cpu_percent.side_effect = [7.2, 135.5, psutil.NoSuchProcess(412)]
        process.memory_info.side_effect = [Mock(rss=381_000_000), Mock(rss=382_000_000)]
        process.num_threads.side_effect = [24, 26]
        status, stdout, stderr = capture_call(observe.observe_process, process)
        self.assertEqual(status, 0)
        self.assertEqual(stderr, "")
        self.assertIn("Process: Spotify\nPID: 412", stdout)
        self.assertIn("CPU: 7.2%   Memory (RSS): 381.0 MB   Threads: 24", stdout)
        self.assertIn("CPU: 135.5%   Memory (RSS): 382.0 MB   Threads: 26", stdout)
        self.assertEqual(stdout.count("CPU:"), 2)
        self.assertIn("exited", stdout)
        # A blocking interval avoids the meaningless first non-blocking CPU value.
        for call in process.cpu_percent.call_args_list:
            self.assertEqual(call.kwargs, {"interval": 1.0})

    def test_exit_during_any_read_does_not_print_a_partial_sample(self):
        for method in ("name", "cpu_percent", "memory_info", "num_threads"):
            with self.subTest(method=method):
                process = fake_process(412)
                getattr(process, method).side_effect = psutil.NoSuchProcess(412)
                status, stdout, stderr = capture_call(observe.observe_process, process)
                self.assertEqual(status, 0)
                self.assertEqual(stderr, "")
                self.assertNotIn("CPU:", stdout)
                self.assertIn("exited", stdout)

    def test_reused_or_exited_pid_discards_sample(self):
        process = fake_process(412)
        process.cpu_percent.return_value = 7.2
        process.is_running.side_effect = [True, True, False]
        status, stdout, stderr = capture_call(observe.observe_process, process)
        self.assertEqual(status, 0)
        self.assertEqual(stderr, "")
        self.assertNotIn("CPU:", stdout)
        self.assertIn("exited", stdout)

    def test_zombie_is_treated_as_exited(self):
        process = fake_process(412)
        process.status.return_value = psutil.STATUS_ZOMBIE
        status, stdout, stderr = capture_call(observe.observe_process, process)
        self.assertEqual(status, 0)
        self.assertEqual(stderr, "")
        self.assertIn("exited", stdout)
        process.cpu_percent.assert_not_called()

    def test_permission_denied_during_measurement_is_readable(self):
        process = fake_process(412)
        process.cpu_percent.return_value = 7.2
        process.memory_info.side_effect = psutil.AccessDenied(412)
        status, stdout, stderr = capture_call(observe.observe_process, process)
        self.assertEqual(status, 1)
        self.assertNotIn("CPU:", stdout)
        self.assertIn("permission denied for PID 412", stderr)


if __name__ == "__main__":
    unittest.main()
