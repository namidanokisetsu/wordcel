"""Check the Windows capture paths against controlled windows, without OCR or app settings."""
import argparse
import ctypes
from dataclasses import replace
from importlib.metadata import PackageNotFoundError, version
import logging
from pathlib import Path
from queue import Queue
import sys
import threading
from time import perf_counter

from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal, PYQT_VERSION_STR, qVersion
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QApplication, QDialog

from wordcel.utils.capture import CaptureRequest, RegionCapture, exclude_from_capture
from wordcel.utils.window_capture import window_bounds


BACKGROUND = (20, 200, 80)
POPUP = (220, 40, 40)


def error_details(error):
    """Keep native codes and failing operations, without exception text or local paths."""
    details, seen = [], set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        frames, trace = [], error.__traceback__
        while trace is not None:
            frames.append(f"{Path(trace.tb_frame.f_code.co_filename).name}:"
                          f"{trace.tb_frame.f_code.co_name}:{trace.tb_lineno}")
            trace = trace.tb_next
        details.append(f"{type(error).__name__} winerror={getattr(error, 'winerror', None)} "
                       f"errno={getattr(error, 'errno', None)} operations={'/'.join(frames)}")
        error = error.__cause__ or (None if error.__suppress_context__ else error.__context__)
    return " <- ".join(details)


def sample_matches(image, point, expected):
    x, y = point
    if not (1 <= x < image.width - 1 and 1 <= y < image.height - 1):
        raise ValueError("Fixture sample lies outside capture")
    # Several interior pixels avoid relying on a single pixel or rounded edge.
    return all(max(abs(a - b) for a, b in zip(image.getpixel((x + dx, y + dy)), expected)) <= 8
               for dx in (-1, 0, 1) for dy in (-1, 0, 1))


class Fixture(QDialog):
    def __init__(self, color, translucent=False):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.color = QColor(*color)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, translucent)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.color)
        painter.drawRoundedRect(self.rect(), 12, 12)


class Probe(QObject):
    completed = pyqtSignal(str, bool)

    def __init__(self, app, report):
        super().__init__()
        self.app, self.report = app, report
        self.source = Fixture(BACKGROUND)
        self.popups = [Fixture(POPUP), Fixture(POPUP, translucent=True)]
        area = app.primaryScreen().availableGeometry()
        self.source.setGeometry(area.center().x() - 240, area.center().y() - 140, 480, 280)
        for popup in self.popups:
            popup.setGeometry(area.center().x() - 80, area.center().y() - 50, 160, 100)
        self.steps = iter([
            ("opaque_control", 0, False, False, False),
            ("opaque_exclusion", 0, True, False, False),
            ("opaque_restored", 0, False, False, False),
            ("translucent_control", 1, False, False, False),
            ("translucent_exclusion", 1, True, False, False),
            ("masked_desktop", 1, False, True, False),
            ("source_window", 1, False, False, True),
        ])
        self.jobs = Queue()
        self.worker = threading.Thread(target=self.capture, name="capture-probe", daemon=True)
        self.completed.connect(self.advance)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.timeout)
        self.finished = False
        self.failures = 0

    def start(self):
        self.worker.start()
        self.source.show()
        self.advance("", True)

    def advance(self, previous, passed):
        if self.finished:
            return
        self.timer.stop()
        if previous:
            self.failures += not passed
            self.report.info("case=%s result=%s", previous, "PASS" if passed else "FAIL")
        step = next(self.steps, None)
        if step is None:
            self.finish()
            return
        name, index, exclusion, masked, source = step
        self.active_case = name
        try:
            for popup in self.popups:
                popup.hide()
            popup = self.popups[index]
            popup.show()
            accepted = exclude_from_capture(popup, exclusion)
            self.report.info("case=%s exclusion_requested=%s affinity_call_accepted=%s",
                             name, exclusion, accepted)
            screen = self.source.screen()
            request = CaptureRequest(1, screen.name(), screen.geometry().getRect(),
                                     self.source.geometry().getRect(), screen.devicePixelRatio(), 1,
                                     source_window=int(self.source.winId()) if source else 0,
                                     mask_window=int(popup.winId()) if masked else 0)
            self.report.info("case=%s scale=%s", name, request.scale)
            expected = (0, 0, 0) if masked else BACKGROUND if exclusion or source else POPUP
            # Dispatch after Qt's pending paints; the worker then waits for DWM.
            QTimer.singleShot(0, lambda: self.jobs.put((name, request, int(popup.winId()), expected)))
            self.timer.start(10000)
        except Exception as error:
            self.report.info("case=%s error=%s", name, error_details(error))
            QTimer.singleShot(0, lambda: self.advance(name, False))

    def capture(self):
        backend = RegionCapture()
        try:
            while (job := self.jobs.get()) is not None:
                name, request, popup_handle, expected = job
                passed = True
                try:
                    ctypes.WinDLL("dwmapi").DwmFlush()
                    for attempt in range(2):
                        started = perf_counter()
                        frame = backend.capture(replace(request, revision=attempt + 1))
                        image = frame.image()
                        left, top, *_ = frame.physical_crop
                        x, y, w, h = window_bounds(popup_handle)
                        covered = (x + w // 2 - left, y + h // 2 - top)
                        background_ok = sample_matches(image, (image.width // 8, image.height // 8), BACKGROUND)
                        covered_ok = sample_matches(image, covered, expected)
                        passed &= background_ok and covered_ok
                        self.report.info("case=%s attempt=%s background_ok=%s covered_ok=%s elapsed_ms=%.2f",
                                         name, attempt + 1, background_ok, covered_ok,
                                         (perf_counter() - started) * 1000)
                except Exception as error:
                    passed = False
                    self.report.info("case=%s error=%s", name, error_details(error))
                self.completed.emit(name, passed)
        finally:
            try:
                backend.close()
            except Exception as error:
                self.report.info("cleanup_error=%s", error_details(error))

    def timeout(self):
        self.failures += 1
        self.report.info("case=%s result=TIMEOUT; remaining cases not run", self.active_case)
        self.finish()

    def finish(self):
        self.finished = True
        self.timer.stop()
        self.jobs.put(None)
        self.report.info("finished failed_cases=%s", self.failures)
        self.app.quit()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    default = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path.cwd()
    parser.add_argument("--output", type=Path, default=default / "wordcel-capture-report.txt")
    args = parser.parse_args(argv)
    if sys.platform != "win32":
        parser.error("This diagnostic requires Windows.")
    report = logging.getLogger("wordcel.capture_probe")
    report.setLevel(logging.INFO)
    report.propagate = False
    handler = logging.FileHandler(args.output, encoding="utf-8", mode="w")
    handler.setFormatter(logging.Formatter("%(message)s"))
    report.addHandler(handler)
    timing = logging.getLogger("wordcel.timing")
    previous_level = timing.level
    timing.setLevel(logging.DEBUG)
    timing.addHandler(handler)
    probe = None
    try:
        report.info("Wordcel capture diagnostic v1; baseline=47587db")
        report.info("No screenshots, recognized text, window titles, or app settings are recorded.")
        report.info("windows_build=%s python=%s qt=%s pyqt=%s frozen=%s",
                    sys.getwindowsversion().build, sys.version.split()[0], qVersion(),
                    PYQT_VERSION_STR, getattr(sys, "frozen", False))
        for package in ("mss", "Pillow", "winrt-runtime", "winrt-Windows.Graphics.Capture"):
            try:
                installed = version(package)
            except PackageNotFoundError:
                installed = "metadata-unavailable"
            report.info("package=%s version=%s", package, installed)
        app = QApplication.instance() or QApplication([sys.argv[0]])
        app.setQuitOnLastWindowClosed(False)
        probe = Probe(app, report)
        QTimer.singleShot(0, probe.start)
        app.exec()
        if not probe.finished:
            report.info("result=INTERRUPTED")
            return 2
        probe.worker.join(timeout=1)
        return int(bool(probe.failures))
    except Exception as error:
        report.info("fatal_error=%s", error_details(error))
        return 2
    finally:
        if probe is not None:
            probe.jobs.put(None)
            for window in [*probe.popups, probe.source]:
                window.close()
        timing.removeHandler(handler)
        timing.setLevel(previous_level)
        report.removeHandler(handler)
        handler.close()


if __name__ == "__main__":
    raise SystemExit(main())
