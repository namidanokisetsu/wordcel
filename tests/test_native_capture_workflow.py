"""Opt-in native workflow check: WORDCEL_NATIVE_CAPTURE_TEST=1 on Windows.

Uses real capture, installed Japanese OCR, dictionary lookup and popup rendering.
Global hook registration is disabled; key events enter through DesktopInput.key.
"""
import os
import sys

if os.environ.get("WORDCEL_NATIVE_CAPTURE_TEST") == "1":
    os.environ["QT_QPA_PLATFORM"] = "windows"
    os.environ["HF_HUB_OFFLINE"] = "1"

import json
from pathlib import Path
import tempfile
import time
import traceback
import unittest
from unittest.mock import patch
import zipfile

from PyQt6.QtCore import QEvent, QObject, QPoint, QRect, QSettings, Qt
from PyQt6.QtGui import QCursor, QFont, QPainter
from PyQt6.QtWidgets import QApplication, QWidget
from pynput import keyboard

from wordcel.gui.quick_lookup import QuickLookupWindow
from wordcel.gui.unified_ocr import UnifiedOCR
from wordcel.utils.capture import RegionCapture


class Source(QWidget):
    def __init__(self, screen):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setGeometry(screen.geometry())
        self.first = "猫がいます。"
        self.vertical = False
        self.anchor = QPoint(self.width() // 2 - 300, self.height() // 2 - 150)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.GlobalColor.white)
        font = QFont("Noto Sans JP")
        font.setPixelSize(42)
        painter.setFont(font)
        painter.setPen(Qt.GlobalColor.black)
        if self.vertical:
            for i, char in enumerate("忘れ物"):
                painter.drawText(QRect(self.anchor.x(), self.anchor.y() + i * 48, 60, 60),
                                 Qt.AlignmentFlag.AlignTop, char)
        else:
            painter.drawText(QRect(self.anchor.x(), self.anchor.y(), 380, 65),
                             Qt.AlignmentFlag.AlignTop, self.first)
            painter.drawText(QRect(self.anchor.x() + 650, self.anchor.y(), 380, 65),
                             Qt.AlignmentFlag.AlignTop, "犬がいます。")


class Visibility(QObject):
    def __init__(self, window):
        super().__init__()
        self.events = []
        window.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Show, QEvent.Type.Hide):
            self.events.append((event.type().name, time.monotonic(),
                                [frame.name for frame in traceback.extract_stack(limit=8)]))
        return False


@unittest.skipUnless(sys.platform == "win32" and os.environ.get("WORDCEL_NATIVE_CAPTURE_TEST") == "1",
                     "explicit native Windows capture check")
class NativeCaptureWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        if cls.app.platformName() != "windows":
            raise unittest.SkipTest("requires the native Windows Qt platform")
        from wordcel.gui.application_style import configure_application
        configure_application(cls.app)
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        from wordcel.dictionary.library import import_yomitan
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        bundle = self.root / "fixture.zip"
        with zipfile.ZipFile(bundle, "w") as archive:
            archive.writestr("index.json", json.dumps({"title": "Capture fixture", "format": 3,
                                                       "sourceLanguage": "ja"}))
            archive.writestr("term_bank_1.json", json.dumps([
                [term, reading, "", "", 0, [meaning], i, ""]
                for i, (term, reading, meaning) in enumerate(
                    (("猫", "ねこ", "cat"), ("犬", "いぬ", "dog"), ("忘れ物", "わすれもの", "forgotten item")))]))
        self.library = self.root / "library"
        import_yomitan(bundle, self.library)
        self.settings = QSettings(str(self.root / "settings.ini"), QSettings.Format.IniFormat)
        self.provider = os.environ.get("WORDCEL_TEST_OCR", "meikiocr")
        for key, value in {
            "profile": "ja", "profiles/ja/target": "en", "ocr/preload": False,
            "profiles/ja/ocr_provider": self.provider, "profiles/ja/audio_autoplay_mode": "off",
            "profiles/ja/scan_bindings": "shift", "history/enabled": False,
            "profiles/ja/freeze_while_held": True,
        }.items():
            self.settings.setValue(key, value)
        self.source = Source(self.app.primaryScreen())
        self.point = self.source.geometry().topLeft() + self.source.anchor + QPoint(20, 30)
        self.patches = [
            patch.object(QCursor, "pos", side_effect=lambda: QPoint(self.point)),
            patch("wordcel.gui.desktop_input.KeyboardListener"),
            patch("wordcel.gui.desktop_input.mouse.Listener"),
            patch("wordcel.utils.capture.exclude_from_capture", return_value=False),
            patch("wordcel.utils.window_capture.WindowCapture", side_effect=AssertionError("Unexpected WGC")),
        ]
        for item in self.patches:
            item.start()
        self.window = QuickLookupWindow(self.library, settings=self.settings)
        self.visibility = Visibility(self.window)
        self.controller = UnifiedOCR(self.window)
        self.frames = []
        self.errors = []
        self.controller.frame_ready.connect(self.record_frame)
        self.controller.completed.connect(lambda generation, result, hit, error:
                                          self.errors.append(error) if error else None)
        self.captures = []
        capture = RegionCapture.capture
        def observed_capture(backend, request):
            frame = capture(backend, request)
            self.captures.append((request, frame.captured_at))
            return frame
        observer = patch.object(RegionCapture, "capture", observed_capture)
        observer.start()
        self.patches.append(observer)
        self.source.show()
        self.pump(.2)
        self.assertTrue(self.controller.enabled)

    def record_frame(self, generation, frame, error):
        if error:
            self.errors.append(error)
        if frame is not None and not error:
            self.frames.append((generation, frame.request.revision))

    def tearDown(self):
        scan, hit = self.controller.worker, self.controller.hit_worker
        self.controller.shutdown()
        self.window.shutdown()
        for worker in (scan, hit, self.window.worker._thread):
            if worker is not None:
                worker.join(5)
                self.assertFalse(worker.is_alive(), "worker did not stop")
        self.window.hide()
        self.source.hide()
        self.window.deleteLater()
        self.source.deleteLater()
        self.app.processEvents()
        for item in reversed(self.patches):
            item.stop()
        self.settings.sync()
        self.temp.cleanup()

    def pump(self, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.app.processEvents()
            time.sleep(.005)

    def wait_for(self, predicate, timeout=12):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.app.processEvents()
            self.assertFalse(self.errors, self.errors)
            if predicate():
                return
            time.sleep(.005)
        frame = self.controller.frame
        self.fail(f"Timed out: visible={self.window.isVisible()} term={self.term()} "
                  f"frames={len(self.frames)} capture={len(self.captures)} "
                  f"ocr={[p.full_text for p in frame.paragraphs] if frame else None} "
                  f"visibility={self.visibility.events}")

    def term(self):
        result = self.window._result
        return result.entries[0].term if result and result.entries else None

    def stable(self, term, seconds=.8, live=False):
        self.wait_for(lambda: self.window.isVisible() and self.term() == term
                      and self.window._result_screenshot is not None)
        events = len(self.visibility.events)
        if live:
            before = len(self.frames)
            self.wait_for(lambda: len(self.frames) >= before + 4)
        else:
            self.assertIsNotNone(self.controller._hover_frame)
            self.wait_for(lambda: not self.controller.busy)
            before = len(self.captures)
            self.pump(seconds)
            self.assertEqual(len(self.captures), before)
        self.assertTrue(self.window.isVisible())
        self.assertEqual(self.term(), term)
        self.assertFalse([event for event in self.visibility.events[events:] if event[0] == "Hide"])
        self.assertFalse(self.controller._fallback_capture)

    def test_hover_transitions_pin_and_snapshot(self):
        self.controller.hover_region = self.source.geometry()
        self.controller.hover_screen = self.controller._screen_key(self.source.screen())
        self.controller.set_hover_enabled(True)
        started = time.monotonic()
        self.stable("猫", seconds=2.5)
        print(f"{self.provider}: cold hover + retained frame {(time.monotonic()-started):.2f}s", flush=True)
        snapshot = self.window._result_screenshot
        self.point += QPoint(650, 0)
        self.stable("犬")
        self.assertTrue(self.window._result_screenshot is snapshot)
        self.assertTrue(any(request.mask_window for request, _ in self.captures))
        self.window.pin.setChecked(True)
        self.pump(.2)
        before = len(self.captures)
        events = len(self.visibility.events)
        self.pump(.8)
        self.assertEqual(len(self.captures), before)
        self.assertTrue(self.window.isVisible() and self.window.is_pinned)
        self.assertEqual(len(self.visibility.events), events)
        self.assertFalse(self.errors)
        self.assertIsNone(self.controller._hover_frame)
        print(f"{self.provider}: retained hover, transitions, pin PASS", flush=True)

    def test_shift_frozen_frame_and_new_hold(self):
        inputs = self.controller.input
        inputs.key(keyboard.Key.shift, True)
        self.wait_for(lambda: self.window.isVisible() and self.term() == "猫"
                      and self.window._result_screenshot is not None)
        snapshot = self.window._result_screenshot
        self.assertTrue(snapshot.request.frozen)
        self.point += QPoint(650, 0)
        self.wait_for(lambda: self.window.isVisible() and self.term() == "犬")
        self.assertIs(self.window._result_screenshot, snapshot)
        before = len(self.captures)
        events = len(self.visibility.events)
        self.pump(.8)
        self.assertEqual(len(self.captures), before)
        self.assertEqual(len(self.visibility.events), events)
        inputs.key(keyboard.Key.shift, False)
        self.controller.dismiss()
        self.source.first = "犬がいます。"
        self.source.update()
        self.point -= QPoint(650, 0)
        self.pump(.2)
        inputs.key(keyboard.Key.shift, True)
        self.wait_for(lambda: self.window.isVisible() and self.term() == "犬"
                      and self.window._result_screenshot is not None)
        self.assertIsNot(self.window._result_screenshot, snapshot)
        self.assertFalse(self.controller._fallback_capture)
        inputs.key(keyboard.Key.shift, False)
        print(f"{self.provider}: Shift lookup, frozen reuse, release/repress PASS", flush=True)

    def test_vertical_hover_with_side_placement(self):
        self.source.vertical = True
        self.source.update()
        self.pump(.2)
        self.controller.hover_region = self.source.geometry()
        self.controller.hover_screen = self.controller._screen_key(self.source.screen())
        self.controller.set_hover_enabled(True)
        self.stable("忘れ物")
        self.assertTrue(self.window._lookup_vertical)
        print(f"{self.provider}: vertical hover beside text PASS", flush=True)

    def test_vertical_hover_without_side_placement(self):
        self.settings.setValue("profiles/ja/vertical_popup_sides", False)
        self.source.vertical = True
        self.source.update()
        self.pump(.2)
        self.controller.hover_region = self.source.geometry()
        self.controller.hover_screen = self.controller._screen_key(self.source.screen())
        self.controller.set_hover_enabled(True)
        self.stable("忘れ物", seconds=2.5)
        print(f"{self.provider}: vertical hover below text PASS", flush=True)

    def test_shift_with_normal_exclusion(self):
        self.patches[3].stop()
        self.test_shift_frozen_frame_and_new_hold()
        self.assertFalse(any(request.mask_window for request, _ in self.captures))

    def test_hover_with_normal_exclusion_keeps_refreshing(self):
        self.patches[3].stop()
        self.controller.hover_region = self.source.geometry()
        self.controller.hover_screen = self.controller._screen_key(self.source.screen())
        self.controller.set_hover_enabled(True)
        self.stable("猫", live=True)
        self.assertIsNone(self.controller._hover_frame)
        self.source.first = "犬がいます。"
        self.source.update()
        self.stable("犬", live=True)
        self.assertFalse(any(request.mask_window for request, _ in self.captures))

    def test_source_scroll_refreshes_retained_page(self):
        from types import SimpleNamespace
        self.controller.hover_region = self.source.geometry()
        self.controller.hover_screen = self.controller._screen_key(self.source.screen())
        self.controller.set_hover_enabled(True)
        self.stable("猫")
        snapshot = self.window._result_screenshot
        self.source.first = "犬がいます。"
        self.source.update()
        self.pump(.1)
        with patch("wordcel.utils.window_focus.route_popup_wheel", return_value=False):
            self.controller.input.filter_mouse(0x20A, SimpleNamespace())
        self.stable("犬")
        self.assertTrue(self.window._result_screenshot is not snapshot)
        self.point += QPoint(0, 250)
        self.wait_for(lambda: not self.window.isVisible())
        self.assertIsNone(self.controller._hover_frame)
        self.source.first = "猫がいます。"
        self.source.update()
        self.point -= QPoint(0, 250)
        self.stable("猫")


if __name__ == "__main__":
    unittest.main()
