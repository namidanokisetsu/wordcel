import json
import os
from pathlib import Path
import tempfile
import unittest
import zipfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import QApplication

from wordcel.anki import note_values
from wordcel.dictionary.library import Entry, Library, import_yomitan
from wordcel.dictionary.search import SearchResult
from wordcel.dictionary.structured_content import StructuredContentConverter
from wordcel.gui.lookup_render import group_headwords, render_result
from wordcel.gui.ruby import RubyBrowser
from wordcel.gui.typography import default_family, document_font
from wordcel.language.arabic import compatible_vowels, headword, spelling
from wordcel.ocr.context import fragment_paragraphs, hit_paragraphs


class ArabicSpellingTests(unittest.TestCase):
    def test_only_vowels_and_tatweel_are_ignored(self):
        self.assertEqual(spelling("كِـتَابٌ"), "كتاب")
        self.assertEqual(spelling("ا\u0654ُمّ"), "أم")
        for first, second in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ة", "ه"), ("ى", "ي")):
            self.assertNotEqual(spelling(first), spelling(second))

    def test_partial_vowels_constrain_surface(self):
        self.assertTrue(compatible_vowels("كُتب", "كُتُب"))
        self.assertFalse(compatible_vowels("كَتب", "كُتُب"))
        self.assertFalse(compatible_vowels("عَلّم", "عَلَم"))

    def test_reading_must_belong_to_the_headword(self):
        self.assertEqual(headword("كتاب", "كِتَاب"), "كِتَاب")
        self.assertEqual(headword("كتب", "يَكْتُبُونَ"), "كتب")
        self.assertEqual(headword("كتاب", "kitāb"), "كتاب")

    def test_import_aliases_and_vowel_constraints(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / "ar.zip"
            rows = [["كُتُب", "كُتُب", "", "n", 0, ["books"]],
                    ["كَتَبَ", "كَتَبَ", "", "v", 0, ["write"]],
                    ["وبالكتب", "وَبِالْكُتُبِ", "", "n", 0, [["كُتُب", ["plural"]]]]]
            with zipfile.ZipFile(archive, "w") as pack:
                pack.writestr("index.json", json.dumps(dict(title="Arabic fixture", format=3, sourceLanguage="ar")))
                pack.writestr("term_bank_1.json", json.dumps(rows))
            root = Path(folder) / "library"
            import_yomitan(archive, root)
            library = Library(root)
            try:
                self.assertEqual({e.reading for e in library.lookup("كتب", "ar")}, {"كُتُب", "كَتَبَ"})
                self.assertEqual([e.reading for e in library.lookup("كُتب", "ar")], ["كُتُب"])
                self.assertEqual([e.term for e in library.lookup("وبالكتب", "ar")], ["كُتُب"])
            finally:
                library.close()

    def test_rtl_fragment_interpolation_keeps_logical_offsets(self):
        paragraphs = fragment_paragraphs([("كتاب كتاب", [("كتاب كتاب", (0, 0, 90, 20))])], 90, 20, "ar")
        first = hit_paragraphs(paragraphs, (.8, .5), "ar")
        second = hit_paragraphs(paragraphs, (.2, .5), "ar")
        self.assertEqual((first.query, first.start, first.end), ("كتاب", 0, 4))
        self.assertEqual((second.query, second.start, second.end), ("كتاب", 5, 9))

    def test_wrapped_arabic_context_uses_right_alignment_without_crossing_columns(self):
        paragraphs = fragment_paragraphs([
            ("قرأ الطالب كتابا", [("قرأ الطالب كتابا", (120, 0, 300, 20))]),
            ("جديدا", [("جديدا", (250, 22, 300, 42))]),
            ("هذا كتاب", [("هذا كتاب", (0, 0, 80, 20))]),
        ], 300, 50, "ar")
        self.assertEqual(len(paragraphs), 2)
        joined = next(p for p in paragraphs if "الطالب" in p.full_text)
        self.assertEqual(joined.full_text, "قرأ الطالب كتابا\nجديدا")


class ArabicRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_vowelled_headings_and_independent_block_directions(self):
        entries = (Entry("1", "كتب", "كُتُب", "Dictionary", "ar", ("books (plural)",)),
                   Entry("2", "كتب", "كَتَبَ", "Dictionary", "ar", ("to write",)))
        result = SearchResult("كتب", "ar", "en", entries)
        self.assertEqual(len(group_headwords(entries)), 2)
        browser = RubyBrowser()
        try:
            browser.setFont(document_font(default_family("ar"), 22, "ar"))
            browser.setHtml(render_result(result, source_text="قرأ ٣ كتب (2026)."))
            text = browser.toPlainText()
            self.assertEqual(text.count("كُتُب"), 1)
            self.assertEqual(text.count("كَتَبَ"), 1)
            block = browser.document().begin()
            headings = []
            while block.isValid():
                if block.blockFormat().headingLevel() == 2:
                    headings.append(block.text())
                    self.assertEqual(block.blockFormat().layoutDirection(), Qt.LayoutDirection.RightToLeft)
                    self.assertTrue(block.blockFormat().alignment() & Qt.AlignmentFlag.AlignRight)
                if "to write" in block.text():
                    self.assertEqual(block.blockFormat().layoutDirection(), Qt.LayoutDirection.LeftToRight)
                block = block.next()
            self.assertEqual(headings, ["كُتُب", "كَتَبَ"])
            cursor = QTextCursor(browser.document())
            cursor.select(QTextCursor.SelectionType.Document)
            browser.setTextCursor(cursor)
            self.assertEqual(browser.createMimeDataFromSelection().text(), text)
            self.assertEqual(entries[0].term, "كتب")
            self.assertEqual(note_values(entries[:1])["expression"], "كُتُب")
            values = note_values(entries[:1], sentence="قرأت هذه الكتب.", encountered="الكتب")
            self.assertEqual(values["encountered_form"], "الكتب")
            self.assertEqual(values["dictionary_term"], "كتب")
            self.assertEqual(values["sentence"], "قرأت هذه الكتب.")
        finally:
            browser.deleteLater()

    def test_explicit_dictionary_direction_is_preserved(self):
        converter = StructuredContentConverter()
        html = converter.to_html({"type": "structured-content", "content":
                                  {"tag": "div", "dir": "rtl", "content": "123 (كتاب)"}})
        self.assertIn('dir="rtl"', html)

    def test_default_arabic_font_uses_sans_for_english_and_naskh_for_arabic(self):
        from PyQt6.QtGui import QTextLayout
        for family in ("", default_family("ar")):
            font = document_font(family, 22, "ar")
            for text, expected in (("English definitions", "Noto Sans"), ("\u0643\u062a\u0627\u0628", "Noto Naskh Arabic")):
                layout = QTextLayout(text, font)
                layout.beginLayout()
                layout.createLine()
                layout.endLayout()
                self.assertEqual({run.rawFont().familyName() for run in layout.glyphRuns()}, {expected})
        self.assertEqual(document_font("Arial", 22, "ar").families()[0], "Arial")

    def test_arabic_font_and_stacked_marks_fit_the_line(self):
        self.assertEqual(default_family("ar"), "Noto Naskh Arabic")
        browser = RubyBrowser()
        try:
            for size in (14, 28, 48):
                browser.setFont(document_font("", size, "ar"))
                browser.resize(180, 180)
                browser.setHtml('<p dir="rtl">مُدَرِّسٌ مُدَرِّسٌ</p>')
                document = browser.document()
                document.setTextWidth(170)
                document.size()
                block = document.begin()
                for index in range(block.layout().lineCount()):
                    line = block.layout().lineAt(index)
                    self.assertGreaterEqual(line.height(), size)
                    self.assertGreater(line.naturalTextWidth(), 0)
        finally:
            browser.deleteLater()
