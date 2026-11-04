import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from unittest.mock import patch

from PyQt6.QtGui import QFontMetricsF, QTextCursor, QTextFormat
from PyQt6.QtWidgets import QApplication

from wordcel.dictionary.library import Entry
from wordcel.dictionary.pitch import PITCH_OBJECT, Pitch
from wordcel.dictionary.search import SearchResult
from wordcel.gui.quick_lookup import LocalDictionaryBrowser, render_result
from wordcel.gui.typography import document_font
from wordcel.config.config import config


def result(definitions, source="Fixture"):
    return SearchResult("word", "ja", "en", (
        Entry("fixture", "word", "", source, "ja", tuple(definitions)),))


class DictionaryPresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.browser = LocalDictionaryBrowser(selection_lookup=False)
        self.browser.resize(480, 230)
        self.browser.show()

    def tearDown(self):
        self.browser.close()
        self.browser.deleteLater()
        self.app.processEvents()

    def render(self, value, **kwargs):
        self.browser.setHtml(render_result(value, **kwargs))
        self.app.processEvents()
        return self.browser.toPlainText()

    def test_list_markers_fit_at_large_text_sizes_and_multi_digit_counts(self):
        for size in (14, 28, 48):
            self.browser.setFont(document_font("Noto Sans JP", size, "ja"))
            for count in (2, 12, 101):
                with self.subTest(size=size, count=count), patch.object(config, "font_size_definitions", size):
                    self.render(result(tuple(f"Meaning {index}" for index in range(count))))
                    block = self.browser.document().begin()
                    while block.isValid():
                        text_list = block.textList()
                        if text_list is not None:
                            metrics = QFontMetricsF(block.charFormat().font())
                            marker_width = metrics.horizontalAdvance(text_list.itemText(block))
                            left = self.browser.cursorRect(QTextCursor(block)).left()
                            self.assertGreaterEqual(left - marker_width, self.browser.document().documentMargin())
                        block = block.next()

    def test_bunpro_preview_keeps_meaning_and_expansion_separates_sections(self):
        definition = {"type": "structured-content", "content": [
            "【 Meaning 】", {"tag": "div", "content": "Persistently"},
            "【 Explanation 】", {"tag": "div", "content": "Explanation body " * 30},
            "【 Example sentences 】", {"tag": "ol", "content": [
                {"tag": "li", "content": "Example one"}]}]}
        footer = {"type": "structured-content", "content": [
            {"tag": "a", "href": "https://example.test", "content": "Link to Bunpro"}]}
        value = result((definition, footer), "Bunpro Dictionary")
        text = self.render(value, preview=True)
        self.assertIn("Persistently", text)
        self.assertNotIn("Explanation", text)
        self.assertNotIn("Example one", text)
        self.assertNotIn("Link to Bunpro", text)
        self.assertNotIn("<ol>", render_result(value, preview=True))
        text = self.render(value, expanded=("Bunpro Dictionary",))
        self.assertIn("Persistently\nExplanation\nExplanation body", text)
        self.assertIn("Example sentences\n", text)
        self.assertIn("Example one", text)
        self.assertNotIn("Link to Bunpro", text)
        self.assertEqual(definition["content"][0], "【 Meaning 】")

    def test_grammar_preview_selects_meaning_and_expansion_preserves_examples(self):
        source = "日本語文法辞典(全集)"
        value = result(("文法項目 | という | 基本\n [解説]\n Explanation\n\n [意味]\n Called\n\n"
                        " [例文A]\n Japanese example\n English example",), source)
        self.assertIn("Called", self.render(value, preview=True))
        self.assertNotIn("Explanation", self.browser.toPlainText())
        text = self.render(value, expanded=(source,))
        self.assertIn("基本", text)
        self.assertIn("Japanese example", text)
        self.assertIn("English example", text)
        self.assertNotIn("\n\n\n", text)

    def test_forms_are_supplements_not_numbered_senses(self):
        for kind in ("forms", "formsTable", "forms-list"):
            with self.subTest(kind=kind):
                value = result(("Meaning", {"type": "structured-content", "content": {
                    "tag": "div", "data": {"content": kind}, "content": "Alternative spelling"}}))
                self.assertNotIn("Alternative spelling", self.render(value, preview=True))
                html = render_result(value, expanded=("Fixture",))
                self.assertNotIn("<ol>", html)
                self.assertIn("Forms", html)
                self.assertIn("Alternative spelling", self.render(value, expanded=("Fixture",)))

    def test_jitendex_tags_share_first_meaning_line_and_forms_label_is_not_repeated(self):
        definition = {"type": "structured-content", "content": [
            {"tag": "div", "data": {"content": "sense-group"}, "content": [
                {"tag": "span", "data": {"class": "tag", "content": "part-of-speech-info"},
                 "content": "noun"},
                {"tag": "div", "data": {"content": "sense"}, "content": [
                    {"tag": "ul", "data": {"content": "glossary"},
                     "content": {"tag": "li", "content": "Tokyo"}},
                    {"tag": "div", "content": "Example sentence"}]},
                {"tag": "div", "data": {"content": "sense"}, "content": "Second meaning"}]},
            {"tag": "div", "data": {"content": "forms"}, "content": [
                {"tag": "span", "data": {"class": "tag", "content": "forms-label"},
                 "content": "forms"},
                {"tag": "table", "content": {"tag": "tr", "content": [
                    {"tag": "td", "content": "東京"}, {"tag": "td", "content": "東亰"}]}}]}]}
        text = self.render(result((definition,)), expanded=("Fixture",))
        self.assertIn("[noun]\nTokyo\nExample sentence\nSecond meaning", text)
        self.assertEqual(text.lower().count("forms"), 1)
        self.assertIn("東亰", text)
        self.assertEqual(definition["content"][0]["content"][1]["tag"], "div")

    def test_compact_tags_keep_full_descriptions_on_hover(self):
        descriptions = ("noun (common) (futsuumeishi)",
                        "noun or participle which takes the aux. verb suru", "transitive verb")
        nodes = [{"tag": "span", "data": {"content": "tag"}, "content": text}
                 for text in descriptions]
        definition = {"type": "structured-content", "content": [*nodes, "prayer"]}
        text = self.render(result((definition,)))
        self.assertIn("[noun · suru · transitive]\nprayer", text)
        cursor = self.browser.document().find("noun · suru")
        self.assertEqual(cursor.charFormat().toolTip(), " · ".join(descriptions))
        self.assertFalse(cursor.charFormat().isAnchor())
        self.assertEqual([node["content"] for node in nodes], list(descriptions))

    def test_jmdict_sense_numbers_do_not_become_definition_labels(self):
        descriptions = ("JMdict Sense #1", "noun")
        nodes = [{"tag": "span", "data": {"class": "tag"}, "content": text}
                 for text in descriptions]
        text = self.render(result(({"type": "structured-content", "content": [*nodes, "meaning"]},)))
        self.assertIn("[noun]\nmeaning", text)
        self.assertNotIn("JMdict Sense", text)
        self.assertIn("JMdict Sense #1", self.browser.document().find("noun").charFormat().toolTip())

    def test_semantic_meanings_collapse_without_discarding_full_content(self):
        value = result(({"type": "structured-content", "content": {"tag": "div", "content": [
            {"tag": "div", "data": {"meaning": ""}, "content": f"Sense {i}"}
            for i in range(1, 7)]}},))
        text = self.render(value, preview=True, preview_definitions=2)
        self.assertIn("Sense 2", text)
        self.assertNotIn("Sense 3", text)
        self.assertIn("Sense 6", self.render(value))

    def test_unstructured_japanese_preview_is_bounded(self):
        value = result(("長い意味" * 200,))
        text = self.render(value, preview=True)
        self.assertLess(len(text), 270)
        self.assertIn("…", text)
        self.assertIn("長い意味" * 200, self.render(value, expanded=("Fixture",)))

    def test_all_readings_are_visible_without_expanding(self):
        value = SearchResult("生", "ja", "en", tuple(
            Entry(str(i), "生", reading, "Fixture", "ja", (f"Meaning {i}",))
            for i, reading in enumerate(("なま", "せい", "しょう", "き", "いき"))))
        text = self.render(value)
        self.assertIn("Meaning 0", text)
        self.assertNotIn("Other readings", text)
        for i in range(5):
            self.assertIn(f"Meaning {i}", text)

    def test_pitch_and_plain_readings_keep_the_same_size(self):
        value = SearchResult("猫", "ja", "en", (
            Entry("cat", "猫", "ねこ", "Fixture", "ja", ("cat",),
                  pitches=(Pitch("Pitch", "ねこ", 1),)),))
        for header, definitions, reading in ((14, 24, 10), (18, 14, 21), (32, 12, 36)):
            for preview in (False, True):
                with self.subTest(header=header, definitions=definitions, reading=reading, preview=preview), \
                        patch.object(config, "font_size_header", header), \
                        patch.object(config, "font_size_definitions", definitions), \
                        patch.object(config, "font_size_reading", reading):
                    self.render(value, preview=preview)
                    block = self.browser.document().begin()
                    iterator = block.begin()
                    pitch_format = None
                    while not iterator.atEnd():
                        fmt = iterator.fragment().charFormat()
                        if fmt.objectType() == PITCH_OBJECT:
                            pitch_format = fmt
                            break
                        iterator += 1
                    self.assertIsNotNone(pitch_format)
                    self.render(value, preview=preview, preview_pitch=False, pinned_pitch=False)
                    plain = self.browser.document().find("[ねこ]")
                    self.assertFalse(plain.isNull())
                    self.assertEqual(plain.charFormat().font().pixelSize(), reading)
                    self.assertEqual(pitch_format.font().pixelSize(), plain.charFormat().font().pixelSize())

    def test_headword_does_not_keep_qt_relative_font_enlargement(self):
        self.render(result(("Meaning",)))
        block = self.browser.document().begin()
        self.assertFalse(block.charFormat().hasProperty(QTextFormat.Property.FontSizeAdjustment))
        self.assertFalse(block.begin().fragment().charFormat().hasProperty(QTextFormat.Property.FontSizeAdjustment))

    def test_missing_entry_shows_nonempty_scanned_text_safely(self):
        for message in ("", "No entry found."):
            with self.subTest(message=message):
                value = SearchResult("未登録 <word>\n次の行", "ja", "en", (), message=message)
                text = self.render(value, show_source=False)
                self.assertIn("未登録 <word>\n次の行", text.replace("\u2028", "\n"))
                self.assertNotIn("No entry found", text)
        text = self.render(SearchResult("", "ja", "en", ()))
        self.assertEqual(text.strip(), "")


if __name__ == "__main__":
    unittest.main()
