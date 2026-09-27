"""Test the native wrapper's buffer and ABI without depending on libproc."""

import ctypes
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import native


class NativePathTests(unittest.TestCase):
    def test_non_macos_refuses_the_experiment(self):
        with patch("native.sys.platform", "linux"):
            with self.assertRaisesRegex(RuntimeError, "macOS-only"):
                native.proc_pidpath(1)

    def test_proc_pidpath_sets_signature_and_decodes_path(self):
        calls = []

        def proc_pidpath(pid, buffer, size):
            calls.append((pid, size))
            buffer.value = b"/Applications/Example.app/Contents/MacOS/Example"
            return len(buffer.value)

        function = SimpleNamespace(proc_pidpath=proc_pidpath)
        with patch("native.sys.platform", "darwin"):
            with patch("native.ctypes.util.find_library", return_value="/usr/lib/libproc.dylib"):
                with patch("native.ctypes.CDLL", return_value=function) as load:
                    path = native.proc_pidpath(412)
        self.assertEqual(path, "/Applications/Example.app/Contents/MacOS/Example")
        self.assertEqual(calls, [(412, 4096)])
        load.assert_called_once_with("/usr/lib/libproc.dylib", use_errno=True)
        self.assertEqual(function.proc_pidpath.argtypes,
                         [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32])
        self.assertIs(function.proc_pidpath.restype, ctypes.c_int)

    def test_native_failure_returns_os_error(self):
        function = SimpleNamespace(proc_pidpath=lambda *_: 0)
        with patch("native.sys.platform", "darwin"):
            with patch("native.ctypes.util.find_library", return_value="libproc"):
                with patch("native.ctypes.CDLL", return_value=function):
                    with self.assertRaises(OSError):
                        native.proc_pidpath(999999)

    def test_comparison_reports_equal_and_different_paths(self):
        for native_path, expected in (("/bin/python", True), ("/bin/other", False)):
            with self.subTest(path=native_path):
                result = native.compare_executable_paths(
                    412, lambda _: native_path, lambda _: "/bin/python"
                )
                self.assertEqual(result["match"], expected)


if __name__ == "__main__":
    unittest.main()
