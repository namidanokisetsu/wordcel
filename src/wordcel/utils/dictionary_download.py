"""Bounded dictionary archive transport; callers own import and update validation."""
from pathlib import Path
from urllib.request import Request

from wordcel import USER_AGENT
from wordcel.utils.progress import content_length, download_progress


def download_archive(url, destination, title, progress, cancelled, opener, *, cancel_message="Download cancelled."):
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with opener(request, timeout=30) as response, Path(destination).open("wb") as output:
        size, received = content_length(response), 0
        progress(download_progress(title, received, size))
        while chunk := response.read(1024 * 1024):
            if cancelled.is_set():
                raise InterruptedError(cancel_message)
            received += len(chunk)
            if received > 2 * 1024**3:
                raise ValueError("Dictionary download exceeds 2 GB.")
            output.write(chunk)
            progress(download_progress(title, received, size))
