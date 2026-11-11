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
        # Imports, installs and removal can use different item identities while
        # mutating the same library or runtime registry.
        categories = {"dictionary": "dictionaries", "dictionary-import": "dictionaries",
                      "translation": "translation", "runtime": "translation",
                      "stanza": "morphology", "arabic": "morphology", "ocr": "ocr", "font": "fonts"}
        resources = []
        for key in keys:
            prefix = key.split(":", 1)[0]
            resource = ("ocr" if key == "engine:paddle" else "morphology") if prefix == "engine" else categories.get(prefix)
            if resource:
                resources.append(resource)
        keys = tuple(dict.fromkeys((*keys, *resources)))
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
        changed = False
        with self._lock:
            for key, (job, cancelled, prior) in self._jobs.items():
                if job is owner and (text != prior or getattr(text, "received", None) != getattr(prior, "received", None)):
                    self._jobs[key] = job, cancelled, text
                    changed = True
        if changed:
            self.changed.emit()

    def finish(self, owner):
        with self._lock:
            self._jobs = {key: value for key, value in self._jobs.items() if value[0] is not owner}
        self.changed.emit()


jobs = ResourceJobs()


def task_key(task):
    if task.kind == "morphology" and task.value == "ar":
        return "arabic:morphology"
    if task.kind == "dictionary":
        return "dictionary:" + task.value.identity
    return {"morphology": "stanza", "fonts": "font"}.get(task.kind, task.kind) + ":" + str(task.value)
