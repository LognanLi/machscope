"""Test output and errors without depending on a changing live process list."""

import io
import subprocess
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

import machscope


class SnapshotTests(unittest.TestCase):
    def run_snapshot(self, **mock_options):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch("machscope.subprocess.run", **mock_options):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                status = machscope.main()
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


if __name__ == "__main__":
    unittest.main()
