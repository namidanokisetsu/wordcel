"""Coalesced worker updates and native, stage-specific setup progress."""
import math
import re
import threading
from time import monotonic

from PyQt6.QtCore import QObject, QTimer, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QLabel, QProgressBar, QVBoxLayout, QWidget

from wordcel.utils.progress import DownloadProgress, TransferRate


class ProgressRelay(QObject):
    updated = pyqtSignal(object)

    def __init__(self, parent):
        super().__init__(parent)
        self._lock = threading.Lock()
        self._pending = None
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.flush)

    def post(self, progress):
        # A fast downloader must not enqueue one Qt event per chunk.
        with self._lock:
            self._pending = progress

    @pyqtSlot()
    def flush(self):
        with self._lock:
            progress, self._pending = self._pending, None
        if progress is not None:
            self.updated.emit(progress)

    @pyqtSlot()
    def stop(self):
        self.timer.stop()
        self.flush()


def byte_label(amount):
    for unit in ("B", "KB", "MB", "GB"):
        if amount < 1024 or unit == "GB":
            return f"{amount:.1f} {unit}" if unit != "B" else f"{amount:.0f} B"
        amount /= 1024


def duration_label(seconds):
    if seconds < 60:
        return f"{max(5, math.ceil(seconds / 5) * 5)} sec"
    minutes = math.ceil(seconds / 60)
    return f"{minutes} min" if minutes < 60 else f"{minutes // 60} hr {minutes % 60} min"


class SetupProgress(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel()
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setWordWrap(True)
        self.bar = QProgressBar()
        self.bar.setAccessibleName("Current setup step")
        self.detail = QLabel()
        self.detail.setTextFormat(Qt.TextFormat.PlainText)
        self.detail.setWordWrap(True)
        for widget in (self.label, self.bar, self.detail):
            layout.addWidget(widget)
        self._text = ""
        self._download = None
        self._rate = TransferRate()
        self._started = monotonic()
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh_detail)
        self.bar.hide()
        self.detail.hide()

    def text(self):
        return self._text

    def begin(self, text):
        self.setText(text)
        self.bar.setRange(0, 0)
        self.bar.show()
        self.timer.start()

    def setText(self, text):
        now = monotonic()
        previous = self._download
        self._text = str(text)
        self._download = text if isinstance(text, DownloadProgress) else None
        if self._download is not None:
            if previous is None:
                self._rate = TransferRate()
            self._rate.add(text, now)
            self.label.setText("Downloading " + text.label)
            self.bar.setRange(0, 100 if text.size else 0)
            if text.size:
                self.bar.setValue(min(100, text.received * 100 // text.size))
                self.bar.setFormat("%p% downloaded")
            self.bar.show()
            self.timer.start()
        else:
            if previous is not None or self.label.text() != str(text):
                self._started = now
            self.label.setText(str(text))
            percent = re.search(r"(\d+)%$", str(text))
            busy = bool(re.match(r"^(Downloading|Installing|Verifying|Importing|Indexing|Checking|Extracting|Preparing|Removing|Exporting|Stopping|Finishing)\b", str(text)))
            self.bar.setVisible(busy or bool(percent))
            self.bar.setRange(0, 100 if percent else 0)
            if percent:
                self.bar.setValue(min(100, int(percent[1])))
                self.bar.setFormat("%p% of this step")
            if busy or percent:
                self.timer.start()
            else:
                self.timer.stop()
        self.refresh_detail()

    def refresh_detail(self):
        now = monotonic()
        progress = self._download
        if progress is None:
            elapsed = int(now - self._started)
            elapsed_text = f"{elapsed} sec" if elapsed < 60 else f"{elapsed // 60} min"
            text = f"Elapsed {elapsed_text}" if self.timer.isActive() and elapsed >= 5 else ""
        else:
            text = byte_label(progress.received)
            if progress.size:
                text += " of " + byte_label(progress.size)
            speed = self._rate.speed(now)
            if speed:
                text += " · " + byte_label(speed) + "/s"
                if progress.size > progress.received:
                    text += "\nAbout " + duration_label((progress.size - progress.received) / speed) + " left to download"
            elif self._rate.samples and now - self._rate.samples[-1][0] >= 5:
                text += " · Waiting for data…"
        self.detail.setText(text)
        self.detail.setVisible(bool(text))
