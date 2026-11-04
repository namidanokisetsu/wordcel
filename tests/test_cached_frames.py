import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from queue import Queue
import threading
from time import monotonic
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from PyQt6.QtCore import QPoint, QRect
from PyQt6.QtWidgets import QApplication
from wordcel.gui.unified_ocr import ScanWorker, HitWorker, UnifiedOCR
from wordcel.ocr.frames import RecognizedFrame
from wordcel.utils.capture import CaptureRequest, PixelFrame
from wordcel.dictionary.search import SearchResult
from wordcel.dictionary.library import Entry
from test_unified_ocr import recognized, FakeWindow


class RetainedHoverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = FakeWindow()
        self.window.setGeometry(500, 300, 100, 100)
        self.controller = UnifiedOCR(self.window)
        self.controller.enabled = True
        self.controller.hover_enabled = True
        screen = QApplication.primaryScreen()
        geo = screen.geometry()
        self.controller.hover_region = QRect(0, 0, 400, 200)
        self.controller.hover_screen = self.controller._screen_key(screen)
        self.controller.session.hovering = True
        request = CaptureRequest(1, screen.name(), (geo.x(), geo.y(), geo.width(), geo.height()),
                                 (0, 0, 400, 200), screen.devicePixelRatio(), self.controller.generation,
                                 mask_window=123)
        self.frame = RecognizedFrame(request, tuple(recognized()), "tr", (), 1, monotonic())
        self.controller.frame = self.frame
        self.controller.hit_worker = SimpleNamespace(queue=Queue(), stop=Mock(), join=Mock(), invalidate=Mock())
        self.pointer = patch("wordcel.gui.unified_ocr.QCursor.pos", return_value=QPoint(80, 100))
        self.pointer.start()
        self.platform = patch("wordcel.gui.unified_ocr.sys.platform", "win32")
        self.platform.start()
        self.window.show()

    def tearDown(self):
        self.controller.shutdown()
        self.window.hide()
        self.window.deleteLater()
        self.app.processEvents()
        self.platform.stop()
        self.pointer.stop()

    def deliver(self):
        from wordcel.ocr.context import hit_paragraphs
        book = Entry("book", "kitap", "", "Fixture", "tr", ("book",))
        hit = hit_paragraphs(self.frame.paragraphs, (.2, .5), "tr")
        self.controller.deliver(self.controller.generation, SearchResult("kitap", "tr", "en", (book,)),
                                (self.frame, hit), "")

    def test_retained_frame_survives_age_and_pointer_movement_without_capture(self):
        from dataclasses import replace
        self.deliver()
        self.assertIs(self.controller._hover_frame, self.frame)
        point = QPoint(280, 100)
        self.assertTrue(self.controller._valid_frame(self.frame, point, monotonic() + 60))
        self.assertFalse(self.controller._valid_frame(replace(self.frame, language="ja"), point, monotonic()))
        with patch.object(self.controller, "_request_capture") as capture:
            self.controller.scan()
            capture.assert_not_called()
        self.controller.hit_latest(point, monotonic() + 60)
        jobs = self.controller.hit_worker.queue
        self.assertEqual(jobs.get_nowait()[2].query, "kitap")
        self.assertEqual(jobs.get_nowait()[2].query, "ev")

    def test_inflight_frame_and_capture_error_cannot_replace_retained_page(self):
        from dataclasses import replace
        self.deliver()
        generation = self.controller.generation
        self.controller.busy = True
        self.controller.accept_frame(generation, replace(self.frame, paragraphs=(), scene=2), "")
        self.assertIs(self.controller.frame, self.frame)
        self.assertFalse(self.controller.busy)
        self.controller.accept_frame(generation, self.frame.request, "capture failed")
        self.assertFalse(self.controller._fallback_capture)
        self.assertIs(self.controller.frame, self.frame)
        with patch.object(self.controller, "_queue_scan") as queue:
            self.controller.capture(generation, QPoint(80, 100))
            queue.assert_not_called()

    def test_source_input_discards_page_and_rejects_old_lookup(self):
        self.deliver()
        generation = self.controller.generation
        self.controller.source_changed()
        self.assertIsNone(self.controller.frame)
        self.assertIsNone(self.controller._hover_frame)
        self.assertFalse(self.window.isVisible())
        self.assertGreater(self.controller.generation, generation)
        self.controller.accept_frame(generation, self.frame, "")
        self.assertIsNone(self.controller.frame)
        with patch.object(self.controller, "_request_capture") as capture:
            self.controller.scan()
            capture.assert_called_once()

    def test_normal_hide_and_ocr_miss_both_release_retained_frame(self):
        from dataclasses import replace
        for normal_hide in (True, False):
            with self.subTest(normal_hide=normal_hide):
                self.frame = replace(self.frame, request=replace(self.frame.request,
                                     generation=self.controller.generation))
                self.controller.frame = self.controller._hover_frame = self.frame
                self.window.show()
                if normal_hide:
                    self.window.hide()
                else:
                    self.controller.hit_latest(QPoint(380, 180), monotonic())
                self.assertIsNone(self.controller._hover_frame)
                self.assertIsNone(self.controller.frame)

    def test_only_failed_exclusion_live_desktop_hover_retains_a_frame(self):
        from dataclasses import replace
        cases = ({"excluded": True}, {"hover": False}, {"mask_window": 0},
                 {"source_window": 456}, {"frozen": True}, {"platform": "linux"})
        for case in cases:
            with self.subTest(case=case):
                self.controller._capture_excluded = case.get("excluded", False)
                self.controller.session.hovering = case.get("hover", True)
                self.controller.holding = not self.controller.session.hovering
                request = replace(self.frame.request, **{k: v for k, v in case.items()
                                                         if k in ("mask_window", "source_window", "frozen")})
                original = self.frame
                self.frame = replace(self.frame, request=request)
                self.controller.frame = self.frame
                with patch("wordcel.gui.unified_ocr.sys.platform", case.get("platform", "win32")):
                    self.deliver()
                self.assertIsNone(self.controller._hover_frame)
                self.frame = original
        self.controller._capture_excluded = False

    def test_pinning_keeps_popup_and_snapshot_but_releases_hover_capture(self):
        self.deliver()
        self.window.pin.setChecked(True)
        self.assertTrue(self.window.isVisible())
        self.assertTrue(self.window.is_pinned)
        self.assertIsNone(self.controller._hover_frame)
        self.controller.source_changed()
        self.assertTrue(self.window.isVisible())

    def test_entering_popup_outside_scan_area_keeps_it_readable(self):
        self.deliver()
        self.controller._update_hover(self.window.geometry().center())
        self.assertTrue(self.window.isVisible())
        self.assertFalse(self.controller.session.hovering)
        self.assertIsNone(self.controller._hover_frame)


class CachedFrameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_boundary_recovery_delivers_first_word_without_pointer_movement(self):
        window = FakeWindow()
        controller = UnifiedOCR(window)
        controller.enabled = controller.holding = True
        screen = self.app.primaryScreen()
        geometry = screen.geometry()
        request = CaptureRequest(1, screen.name(), (geometry.x(), geometry.y(), geometry.width(), geometry.height()),
                                 (0, 0, 400, 200), screen.devicePixelRatio(), controller.generation, True)
        frame = RecognizedFrame(request, tuple(recognized()), "tr", (), 1, monotonic())
        results = Queue()
        hit_worker = HitWorker(SimpleNamespace(emit=lambda *args: results.put(args)))
        controller.hit_worker = hit_worker
        book = Entry("book", "kitap", "", "Fixture", "tr", ("book",))
        engine = Mock()
        engine.search.return_value = SearchResult("kitap", "tr", "en", (book,))
        with patch("wordcel.dictionary.search.SearchEngine", return_value=engine), \
                patch("wordcel.gui.unified_ocr.QCursor.pos", return_value=QPoint(80, 100)), \
                patch.object(QApplication, "activeWindow", return_value=None), \
                patch("wordcel.ocr.boundaries.expanded_crop", return_value=(0, 0, 600, 300)), \
                patch.object(controller, "_request_capture") as capture:
            hit_worker.start()
            try:
                controller.accept_frame(controller.generation, frame, "")
                capture.assert_called_once_with(QPoint(80, 100))
                controller.deliver(*results.get(timeout=2))
                window.show_entries.assert_called_once()
                window.set_context.assert_called_once_with("kitap ev", 0, 5)
            finally:
                controller.shutdown()
                window.deleteLater()

    def test_cached_words_are_independent_of_slow_fresh_recognition(self):
        window = FakeWindow()
        controller = UnifiedOCR(window)
        controller.enabled = controller.holding = True
        screen = QApplication.primaryScreen()
        geometry = screen.geometry()
        request = CaptureRequest(1, screen.name(), (geometry.x(), geometry.y(), geometry.width(), geometry.height()),
                                 (0, 0, 400, 200), screen.devicePixelRatio(), controller.generation)
        frames, results = Queue(), Queue()
        sink = SimpleNamespace(emit=lambda *args: frames.put(args))
        slow, release = threading.Event(), threading.Event()
        count = 0
        def provider(image):
            nonlocal count
            count += 1
            if count == 2:
                slow.set()
                release.wait(3)
            return recognized()
        engine = Mock()
        engine.search.side_effect = lambda text, **kw: SearchResult(text, "tr", "en")
        scan = ScanWorker(Mock(), frames=sink)
        hit_worker = HitWorker(SimpleNamespace(emit=lambda *args: results.put(args)))
        controller.hit_worker = hit_worker
        with patch.object(scan, "provider", return_value=provider), patch("wordcel.dictionary.search.SearchEngine", return_value=engine):
            scan.start()
            hit_worker.start()
            try:
                for color in (0, 255):
                    frame = PixelFrame(request, (2, 2), bytes([color] * 12), monotonic())
                    scan.queue.put((controller.generation, frame, (0, 0), "tr", (), False))
                    if color == 0:
                        controller.frame = frames.get(timeout=2)[1]
                self.assertTrue(slow.wait(2))
                controller.busy = True
                for point in (QPoint(80, 100), QPoint(280, 100)):
                    controller.hit_latest(point, monotonic())
                    results.get(timeout=2)
                self.assertEqual([call.args[0] for call in engine.search.call_args_list], ["kitap", "ev"])
                controller.hit_latest(QPoint(282, 100), monotonic())
                self.assertFalse(release.is_set())
                self.assertEqual(engine.search.call_count, 2)
                controller.invalidate()
                controller.hit_latest(QPoint(80, 100), monotonic())
                self.assertEqual(engine.search.call_count, 2)
            finally:
                release.set()
                scan.stop()
                scan.join(2)
                controller.shutdown()
                window.deleteLater()

    def test_worker_frame_freezes_provider_words_and_offsets(self):
        from dataclasses import replace
        from wordcel.ocr.frames import RecognizedFrame
        paragraphs = recognized()
        frozen = tuple(replace(p, words=tuple(p.words)) for p in paragraphs)
        paragraphs[0].words.clear()
        frame = RecognizedFrame(CaptureRequest(1, "screen", (0, 0, 400, 200), (0, 0, 400, 200), 1, 1),
                                frozen, "tr", (), 1, 10)
        self.assertEqual(frame.paragraphs[0].words[1].text, "ev")
        self.assertEqual(frame.point(280, 100), (.7, .5))

    def test_latest_pointer_and_frame_validity_replace_distance_rejection(self):
        from dataclasses import replace
        from wordcel.ocr.context import hit_paragraphs
        window = FakeWindow()
        controller = UnifiedOCR(window)
        controller.enabled = controller.holding = True
        screen = QApplication.primaryScreen()
        geometry = screen.geometry()
        request = CaptureRequest(1, screen.name(), (geometry.x(), geometry.y(), geometry.width(), geometry.height()),
                                 (0, 0, 400, 200), screen.devicePixelRatio(), controller.generation)
        frame = RecognizedFrame(request, tuple(recognized()), "tr", (), 1, monotonic())
        controller.hit_worker = SimpleNamespace(queue=Queue(), stop=Mock(), join=Mock())
        try:
            with patch("wordcel.gui.unified_ocr.QCursor.pos", return_value=QPoint(280, 100)), \
                    patch.object(QApplication, "activeWindow", return_value=None):
                controller.accept_frame(controller.generation, frame, "")
                job = controller.hit_worker.queue.get_nowait()
                self.assertEqual(job[2].query, "ev")
                old_hit = hit_paragraphs(frame.paragraphs, (.2, .5), "tr")
                book = Entry("book", "kitap", "", "Fixture", "tr", ("book",))
                house = Entry("house", "ev", "", "Fixture", "tr", ("house",))
                controller.deliver(controller.generation, SearchResult("kitap", "tr", "en", (book,)), (frame, old_hit), "")
                window.show_entries.assert_not_called()
                controller.deliver(controller.generation, SearchResult("ev", "tr", "en", (house,)), (frame, job[2]), "")
                window.show_entries.assert_called_once()
            point = QPoint(280, 100)
            for invalid in (replace(frame, captured_at=monotonic()-3), replace(frame, language="ja"),
                            replace(frame, request=replace(request, screen="other")),
                            replace(frame, request=replace(request, generation=-1))):
                self.assertFalse(controller._valid_frame(invalid, point, monotonic()))
        finally:
            controller.shutdown()
            window.deleteLater()
