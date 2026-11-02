"""Compact progress for downloads with a known or unknown size."""
from collections import deque


class DownloadProgress(str):
    """Keep console text compatible while carrying bytes through worker queues."""

    def __new__(cls, label, received, size):
        received, size = max(0, int(received)), max(0, int(size or 0))
        amount = f"{min(100, received * 100 // size)}%" if size else f"{received // (1024 * 1024)} MB"
        value = super().__new__(cls, f"Downloading {label} · {amount}")
        value.label, value.received, value.size = label, received, size
        return value

    def __reduce__(self):
        return type(self), (self.label, self.received, self.size)


class TransferRate:
    def __init__(self):
        self.identity = None
        self.samples = deque()

    def add(self, progress, now):
        identity = progress.label, progress.size
        if identity != self.identity or (self.samples and progress.received < self.samples[-1][1]):
            self.samples.clear()
            self.identity = identity
        if not self.samples or progress.received != self.samples[-1][1]:
            self.samples.append((now, progress.received))
        while len(self.samples) > 2 and self.samples[1][0] < now - 8:
            self.samples.popleft()

    def speed(self, now):
        if len(self.samples) < 2 or now - self.samples[-1][0] >= 5:
            return None
        duration = now - self.samples[0][0]
        return (self.samples[-1][1] - self.samples[0][1]) / duration if duration >= 1 else None


def content_length(response):
    try:
        return max(0, int(getattr(response, "headers", {}).get("Content-Length", 0)))
    except (TypeError, ValueError):
        return 0


def download_progress(label, received, size):
    return DownloadProgress(label, received, size)
