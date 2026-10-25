from types import SimpleNamespace
import sys
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from wordcel.language.support import default_ocr_provider, ocr_supported
from wordcel.ocr.context import hit_paragraphs
from wordcel.ocr.windows_native import WindowsOCR, _language_id, _paragraph


def word(text, x, y=10, width=40, height=20):
    return SimpleNamespace(text=text, bounding_rect=SimpleNamespace(x=x, y=y, width=width, height=height))


class WindowsOCRTests(unittest.TestCase):
    def test_language_matching_keeps_explicit_script_and_installed_region(self):
        self.assertEqual(_language_id("en", ("en-US", "ja")), "en-US")
        self.assertEqual(_language_id("cmn", ("zh-Hans-CN",)), "zh-Hans-CN")
        self.assertEqual(_language_id("zh-tw", ("zh-Hans-CN", "zh-Hant-TW")), "zh-Hant-TW")
        with self.assertRaisesRegex(RuntimeError, "Windows Settings"):
            _language_id("zh-hant", ("zh-Hans-CN",))

    def test_system_languages_gate_selection_without_changing_defaults(self):
        with patch("wordcel.ocr.windows_native.supported_languages", return_value=("en-US", "ja", "tr")):
            self.assertTrue(ocr_supported("tr", "windows", "win32"))
            self.assertFalse(ocr_supported("ru", "windows", "win32"))
            self.assertFalse(ocr_supported("ja", "windows", "darwin"))
            self.assertEqual(default_ocr_provider("ja", "win32"), "meikiocr")
            self.assertEqual(default_ocr_provider("ru", "win32"), "screenai")

    def test_lines_keep_repeated_words_whitespace_and_exact_offsets(self):
        line = SimpleNamespace(text="  bir  kitap bir kitap. ",
                               words=[word("bir", 10), word("kitap", 60), word("bir", 110), word("kitap.", 160)])
        paragraph = _paragraph(line, (220, 60))
        self.assertEqual(paragraph.full_text, "bir  kitap bir kitap.")
        self.assertEqual([w.source_start for w in paragraph.words], [0, 5, 11, 15])
        self.assertEqual("".join(w.text + w.separator for w in paragraph.words), paragraph.full_text)
        self.assertFalse(paragraph.is_vertical)
        self.assertAlmostEqual(paragraph.words[0].box.center_x, 30 / 220)

    def test_japanese_reuses_character_hit_lookup_and_vertical_centers(self):
        line = SimpleNamespace(text="日本語", words=[word("日本", 10, 10, 20, 40), word("語", 10, 50, 20, 20)])
        paragraph = _paragraph(line, (100, 100))
        self.assertTrue(paragraph.is_vertical)
        hit = hit_paragraphs([paragraph], (.2, .4), "ja")
        self.assertEqual(hit.query, "本語")
        self.assertEqual(hit.start, 1)

    def test_text_box_mismatch_retains_complete_text(self):
        paragraph = _paragraph(SimpleNamespace(text="whole line", words=[word("changed", 0)]), (100, 50))
        self.assertEqual(paragraph.words[0].text, "whole line")
        self.assertEqual(paragraph.words[0].source_start, 0)

    def test_repeated_scans_reuse_engine_resize_and_always_close_bitmap(self):
        native = WindowsOCR.__new__(WindowsOCR)
        native.max_dimension = 100
        native.engine = Mock()
        bitmap = Mock()
        factory = Mock(return_value=bitmap)
        imaging = SimpleNamespace(SoftwareBitmap=SimpleNamespace(create_copy_with_alpha_from_buffer=factory),
                                  BitmapPixelFormat=SimpleNamespace(BGRA8=1), BitmapAlphaMode=SimpleNamespace(IGNORE=0))
        native.engine.recognize_async.return_value.get.return_value = SimpleNamespace(lines=[])
        with patch.dict(sys.modules, {"winrt.windows.graphics.imaging": imaging}):
            image = Image.new("RGB", (200, 100))
            self.assertEqual(native.scan(image), [])
            self.assertEqual(native.scan(image), [])
            self.assertEqual(factory.call_args.args[2:4], (100, 50))
            self.assertEqual(bitmap.close.call_count, 2)
            native.engine.recognize_async.side_effect = OSError("fixture")
            with self.assertRaises(OSError):
                native.scan(image)
            self.assertEqual(bitmap.close.call_count, 3)

    def test_shared_worker_keeps_windows_and_screenai_routes_separate(self):
        from wordcel.gui.unified_ocr import ScanWorker
        provider = Mock()
        with patch("wordcel.language.support.ocr_supported", return_value=True), \
                patch("wordcel.ocr.windows_native.WindowsOCR", return_value=provider) as native, \
                patch("wordcel.ocr.providers.screenai.provider.ScreenAiOcr", return_value=provider) as screenai:
            self.assertEqual(ScanWorker.provider("ja", "windows"), provider.scan)
            native.assert_called_once_with("ja")
            screenai.assert_not_called()
            self.assertEqual(ScanWorker.provider("ja", "screenai", "component"), provider.scan)
            screenai.assert_called_once_with("component", language="ja")
