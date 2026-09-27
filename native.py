"""Week 6 experiment: ask macOS libproc for a process's executable path."""

import ctypes
import ctypes.util
import sys


def proc_pidpath(pid):
    """Return a path using Apple's libproc proc_pidpath interface."""
    if sys.platform != "darwin":
        raise RuntimeError("proc_pidpath is a macOS-only experiment.")
    library_name = ctypes.util.find_library("proc")
    if not library_name:
        raise RuntimeError("macOS libproc could not be found.")
    libproc = ctypes.CDLL(library_name, use_errno=True)
    function = libproc.proc_pidpath
    function.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    function.restype = ctypes.c_int
    # Apple's PROC_PIDPATHINFO_MAXSIZE is 4 * MAXPATHLEN, or 4096 bytes.
    buffer = ctypes.create_string_buffer(4096)
    length = function(pid, buffer, len(buffer))
    if length <= 0:
        error = ctypes.get_errno()
        raise OSError(error, "proc_pidpath could not read this process")
    return buffer.value.decode(sys.getfilesystemencoding(), errors="surrogateescape")


def compare_executable_paths(pid, native_path, psutil_path):
    """Return the two paths plus an exact comparison for the experiment report."""
    native = native_path(pid)
    psutil = psutil_path(pid)
    return {"pid": pid, "native_path": native, "psutil_path": psutil,
            "match": native == psutil}
