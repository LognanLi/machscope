"""Notice sampled file and direct-child changes for one recorded process."""

import psutil


class ProcessStateTracker:
    """Compare two accessible snapshots; never turn a permission error into a close."""

    def __init__(self):
        # None means the first readable snapshot has not arrived yet.
        self.open_files = None
        self.children = None
        self.warned = set()
        self.new_warnings = []

    def _read_files(self, process):
        try:
            return {(item.fd, item.path) for item in process.open_files()}
        except (psutil.AccessDenied, PermissionError):
            self._warn_once("open files")
            return None

    def _read_children(self, process):
        try:
            children = {}
            for child in process.children():
                try:
                    children[(child.pid, child.create_time())] = child.name()
                except (psutil.NoSuchProcess, psutil.ZombieProcess):
                    continue
            return children
        except (psutil.AccessDenied, PermissionError):
            self._warn_once("child processes")
            return None

    def _warn_once(self, source):
        if source not in self.warned:
            self.warned.add(source)
            self.new_warnings.append(f"MachScope: cannot read {source}; preserving last snapshot.")

    def poll(self, process):
        """Return state changes observed between readable snapshots."""
        events = []
        files = self._read_files(process)
        if files is not None:
            if self.open_files is not None:
                for fd, path in sorted(files - self.open_files):
                    events.append({"event_type": "file_opened", "related_pid": None,
                                   "subject": f"fd {fd}: {path}"})
                for fd, path in sorted(self.open_files - files):
                    events.append({"event_type": "file_closed", "related_pid": None,
                                   "subject": f"fd {fd}: {path}"})
            self.open_files = files

        children = self._read_children(process)
        if children is not None:
            if self.children is not None:
                for identity, name in sorted(children.items()):
                    if identity not in self.children:
                        events.append({"event_type": "child_started", "related_pid": identity[0],
                                       "subject": name})
                for identity, name in sorted(self.children.items()):
                    if identity not in children:
                        events.append({"event_type": "child_exited", "related_pid": identity[0],
                                       "subject": name})
            self.children = children
        warnings, self.new_warnings = self.new_warnings, []
        return events, warnings


def sample_events(process, tracker, elapsed_seconds, timestamp):
    changes, warnings = tracker.poll(process)
    events = [
        {**change, "elapsed_seconds": elapsed_seconds, "timestamp": timestamp}
        for change in changes
    ]
    return events, warnings
