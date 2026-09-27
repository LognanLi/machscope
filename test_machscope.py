"""Test output and errors without depending on a changing live process list."""

import io
import subprocess
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

import machscope
from test_observe import capture_call


class SnapshotTests(unittest.TestCase):
    def run_snapshot(self, **mock_options):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch("machscope.subprocess.run", **mock_options):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                status = machscope.main([])
        return status, stdout.getvalue(), stderr.getvalue()

    def test_success_displays_snapshot(self):
        snapshot = "  PID COMMAND\n  412 Safari\n  587 python3\n"
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout=snapshot)

        status, stdout, stderr = self.run_snapshot(return_value=result)

        self.assertEqual(status, 0)
        self.assertEqual(stdout, snapshot)
        self.assertEqual(stderr, "")

    def test_ps_failure_displays_error(self):
        for detail in ("permission denied\n", ""):
            with self.subTest(stderr=detail):
                error = subprocess.CalledProcessError(1, "ps", stderr=detail)

                status, stdout, stderr = self.run_snapshot(side_effect=error)

                self.assertEqual(status, 1)
                self.assertEqual(stdout, "")
                self.assertIn("MachScope: unable to read processes:", stderr)
                self.assertIn(detail.strip() or "ps exited with status 1", stderr)

    def test_missing_ps_displays_error(self):
        status, stdout, stderr = self.run_snapshot(
            side_effect=FileNotFoundError("No such file: /bin/ps")
        )

        self.assertEqual(status, 1)
        self.assertEqual(stdout, "")
        self.assertIn("MachScope: unable to start ps:", stderr)
        self.assertIn("No such file", stderr)


class CommandLineTests(unittest.TestCase):
    def test_name_is_forwarded(self):
        with patch("observe.observe", return_value=0) as monitor:
            self.assertEqual(machscope.main(["observe", "Spotify Helper"]), 0)
        monitor.assert_called_once_with(name="Spotify Helper", pid=None)

    def test_pid_is_forwarded(self):
        with patch("observe.observe", return_value=0) as monitor:
            self.assertEqual(machscope.main(["observe", "--pid", "412"]), 0)
        monitor.assert_called_once_with(name=None, pid=412)

    def test_invalid_arguments(self):
        cases = [
            ["observe"],
            ["observe", "Spotify", "--pid", "412"],
            ["observe", "--pid", "0"],
            ["observe", "--pid", "-1"],
            ["observe", "--pid", "abc"],
            ["observe", "--pid", "999999999999999999"],
            ["unknown"],
        ]
        for arguments in cases:
            with self.subTest(arguments=arguments), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    machscope.main(arguments)
                self.assertEqual(error.exception.code, 2)

    def test_ctrl_c_exits_without_a_traceback(self):
        with patch("observe.observe", side_effect=KeyboardInterrupt):
            status, stdout, stderr = capture_call(machscope.main, ["observe", "Spotify"])
        self.assertEqual(status, 0)
        self.assertEqual(stderr, "")
        self.assertIn("Stopped observing", stdout)

    def test_missing_dependency_has_install_instructions(self):
        real_import = __import__

        def import_without_psutil(name, *args, **kwargs):
            if name == "observe":
                raise ModuleNotFoundError("No module named 'psutil'", name="psutil")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=import_without_psutil):
            status, stdout, stderr = capture_call(machscope.main, ["observe", "Spotify"])
        self.assertEqual(status, 1)
        self.assertEqual(stdout, "")
        self.assertIn("pip install -r requirements.txt", stderr)


if __name__ == "__main__":
    unittest.main()
