import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PyQt6.QtCore import QPointF, QRect, Qt
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import QApplication

from wordcel.gui.region_selector import TextRegionSelector
from wordcel.gui.unified_ocr import ScanWorker, UnifiedOCR
from wordcel.ocr.interface import BoundingBox, Paragraph
from wordcel.ocr.passage import passage_text
from wordcel.utils.capture import CaptureRequest


def paragraph(text, y=.2, vertical=False, x=.5):
    return Paragraph(text, [], BoundingBox(x, y, .5, .05), vertical)


class TextCaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_wrapped_lines_and_paragraphs(self):
        self.assertEqual(passage_text([paragraph("First line\nwraps here.\n\nNew paragraph.")], "en"),
                         "First line wraps here.\n\nNew paragraph.")
        self.assertEqual(passage_text([paragraph("日本語\nの文章")], "ja"), "日本語の文章")
        self.assertEqual(passage_text([paragraph("some\nEnglish")], "ja"), "some English")

    def test_native_lines_reuse_adjacency_and_keep_separate_paragraphs(self):
        blocks = [paragraph("Last paragraph", .8), paragraph("wrapped", .27), paragraph("First", .2)]
        self.assertEqual(passage_text(blocks, "en", "windows"), "First wrapped\n\nLast paragraph")
        self.assertEqual(passage_text(blocks, "en", "paddle"), "First\n\nwrapped\n\nLast paragraph")

    def test_vertical_reading_order(self):
        self.assertEqual(passage_text([paragraph("左", vertical=True, x=.2),
                                      paragraph("右", vertical=True, x=.8)], "ja"), "右\n\n左")

    def test_selection_crops_native_pixels_in_reverse_drag(self):
        image = QPixmap(300, 150)
        image.fill(Qt.GlobalColor.white)
        image.setDevicePixelRatio(1.5)
        finish = Mock()
        overlay = TextRegionSelector(SimpleNamespace(geometry=lambda: QRect(-200, 0, 200, 100)), image, finish)
        def event(x, y, button=Qt.MouseButton.LeftButton):
            return SimpleNamespace(position=lambda: QPointF(x, y), button=lambda: button)
        try:
            overlay.mousePressEvent(event(100, 60))
            overlay.mouseReleaseEvent(event(20, 10))
            cropped = finish.call_args.args[0]
            self.assertEqual((cropped.width(), cropped.height()), (120, 75))
            finish.reset_mock()
            overlay.mousePressEvent(event(5, 5, Qt.MouseButton.RightButton))
            finish.assert_called_once_with(None)
        finally:
            overlay.deleteLater()

    def test_copy_worker_reuses_provider_without_dictionary_or_hover_invalidation(self):
        sink = Mock()
        worker = ScanWorker(Mock(), frames=sink)
        image = QImage(20, 20, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.white)
        request = CaptureRequest(-1, "", (0, 0, 20, 20), (0, 0, 20, 20), 1, -1)
        worker.invalidate(99)
        worker.copy_passage((-1, image, (0, 0), "en", ("windows", ""), False, request, 0))
        worker.queue = Mock()
        worker.queue.get.side_effect = [(100, image, (0, 0), "en", ("windows", ""), False, request, 0), None]
        worker.invalidate(100)
        scanner = Mock(return_value=[paragraph("Whole passage")])
        with patch.object(worker, "provider", return_value=scanner) as provider, \
                patch("wordcel.dictionary.search.SearchEngine") as search:
            worker.run()
        search.assert_not_called()
        provider.assert_called_once()
        self.assertEqual(sink.emit.call_args_list[0].args[0], -1)
        self.assertEqual(sink.emit.call_args_list[0].args[1].paragraphs[0].full_text, "Whole passage")
        self.assertEqual(scanner.call_count, 1)

    def test_errors_and_profile_changes_preserve_clipboard(self):
        self.app.clipboard().setText("Keep this")
        controller = SimpleNamespace(_copy_pending=(-1, "en", ("windows", "")),
            window=SimpleNamespace(preferred_foreign="en"), profile_ocr_provider="windows", screenai_directory="",
            _selecting_text=False, session=SimpleNamespace(suspended=True), _sync_timer=Mock(), _sync_pin_ready=Mock())
        controller._cancel_passage = lambda: UnifiedOCR._cancel_passage(controller)
        with patch("PyQt6.QtWidgets.QToolTip.showText"), patch("PyQt6.QtWidgets.QToolTip.hideText"):
            UnifiedOCR._accept_passage(controller, -1, None, "OCR unavailable")
            self.assertEqual(self.app.clipboard().text(), "Keep this")
            controller._copy_pending = (-2, "ja", ("windows", ""))
            UnifiedOCR._accept_passage(controller, -2, SimpleNamespace(paragraphs=[paragraph("Wrong profile")], language="ja"), "")
            self.assertEqual(self.app.clipboard().text(), "Keep this")
            controller._copy_pending = (-3, "en", ("windows", ""))
            UnifiedOCR._accept_passage(controller, -3, SimpleNamespace(paragraphs=[paragraph("Copied")], language="en"), "")
            self.assertEqual(self.app.clipboard().text(), "Copied")
