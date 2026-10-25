"""Shared progress and cancellation for contextual setup and Storage."""
import threading
from PyQt6.QtCore import QObject, pyqtSignal


class ResourceJobs(QObject):
    changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        self._jobs = {}

    def snapshot(self):
        with self._lock:
            return dict(self._jobs)

    def claim(self, keys, owner, cancelled, title):
        with self._lock:
            if self._jobs and ("all" in keys or "all" in self._jobs):
                return False
            if any(key in self._jobs for key in keys):
                return False
            for key in keys:
                self._jobs[key] = owner, cancelled, title
        self.changed.emit()
        return True

    def progress(self, owner, text):
        with self._lock:
            for key, (job, cancelled, _) in self._jobs.items():
                if job is owner:
                    self._jobs[key] = job, cancelled, text
        self.changed.emit()

    def finish(self, owner):
        with self._lock:
            self._jobs = {key: value for key, value in self._jobs.items() if value[0] is not owner}
        self.changed.emit()


jobs = ResourceJobs()


def task_key(task):
    if task.kind == "dictionary":
        return "dictionary:" + task.value.identity
    return {"morphology": "stanza", "fonts": "font"}.get(task.kind, task.kind) + ":" + str(task.value)
