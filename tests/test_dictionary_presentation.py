import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
import json
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

    def test_numbered_lists_only_reserve_marker_width(self):
        for size in (14, 28, 48):
            self.browser.setFont(document_font("Noto Sans JP", size, "ja"))
            for structured in (False, True):
                for count in (2, 12, 101):
                    with self.subTest(size=size, structured=structured, count=count):
                        meanings = tuple(f"Meaning {i}" for i in range(count))
                        definitions = ({"type": "structured-content", "content": {
                            "tag": "ol", "content": [{"tag": "li", "content": text}
                                                       for text in meanings]}},) if structured else meanings
                        self.render(result(definitions))
                        doc = self.browser.document()
                        block = doc.find(meanings[-1]).block()
                        metrics = QFontMetricsF(block.charFormat().font().resolve(doc.defaultFont()))
                        marker = block.textList().itemText(block)
                        left = self.browser.cursorRect(QTextCursor(block)).left()
                        self.assertGreaterEqual(left, metrics.horizontalAdvance(marker))
                        self.assertLessEqual(left, metrics.horizontalAdvance(marker + " ") + 1)

    def test_list_continuations_align_and_nested_margins_do_not_accumulate(self):
        definition = {"type": "structured-content", "content": {"tag": "ol", "content": [
            {"tag": "li", "content": ["Label", {"tag": "div", "content": "Meaning"},
                {"tag": "ul", "content": [{"tag": "li", "content": "Explanation"}]}]}]}}
        for size in (14, 28, 48):
            for preview in (False, True):
                with self.subTest(size=size, preview=preview):
                    self.browser.setFont(document_font("Noto Sans JP", size, "ja"))
                    self.render(result((definition,)), preview=preview, compact=False)
                    doc = self.browser.document()
                    def left(text):
                        return self.browser.cursorRect(QTextCursor(doc.find(text).block())).left()
                    self.assertEqual(left("Label"), left("Meaning"))
                    metrics = QFontMetricsF(doc.find("Label").block().charFormat().font().resolve(doc.defaultFont()))
                    self.assertLessEqual(left("Meaning"), metrics.horizontalAdvance("1. ") + 1)
                    bullet_inset = metrics.lineSpacing() / 3 + metrics.horizontalAdvance(" ")
                    self.assertGreaterEqual(left("Explanation") - left("Meaning"), bullet_inset)
                    self.assertLessEqual(left("Explanation") - left("Meaning"), bullet_inset + 1)

    def test_unrelated_long_list_does_not_widen_short_list(self):
        short = Entry("short", "word", "", "Short", "ja", ("First", "Second"))
        long = Entry("long", "word", "", "Long", "ja", tuple(f"Other {i}" for i in range(101)))
        self.render(SearchResult("word", "ja", "en", (short,)))
        def left(text):
            return self.browser.cursorRect(QTextCursor(self.browser.document().find(text).block())).left()
        original = left("First")
        self.render(SearchResult("word", "ja", "en", (short, long)))
        self.assertEqual(left("First"), original)
        self.assertGreater(left("Other 100"), original)

    def test_rtl_list_markers_and_continuations_use_right_inset(self):
        self.browser.setHtml('<div dir="rtl"><ol><li>معنى<div>شرح</div>'
                             '<ul><li>تفصيل</li></ul></li></ol></div>')
        self.app.processEvents()
        doc = self.browser.document()
        def right(text):
            block = doc.find(text).block()
            self.assertEqual(block.blockFormat().leftMargin(), 0)
            return self.browser.cursorRect(QTextCursor(block)).right()
        self.assertEqual(right("معنى"), right("شرح"))
        self.assertLess(right("تفصيل"), right("معنى"))
        block = doc.find("معنى").block()
        metrics = QFontMetricsF(block.charFormat().font().resolve(doc.defaultFont()))
        self.assertGreaterEqual(block.blockFormat().rightMargin(), metrics.horizontalAdvance("1. "))

    def test_compact_meanings_are_unindented_and_keep_grammar_preferences(self):
        groups = tuple({"type": "structured-content", "content": [
            {"tag": "span", "data": {"content": "tag"}, "content": label},
            {"tag": "ol", "content": [{"tag": "li", "content": text} for text in meanings]}]}
            for label, meanings in (("adjective", ("Ready to do something.", "Second sense.")),
                                    ("noun", ("The execution of a will.",))))
        value = SearchResult("willing", "en", "en", (
            Entry("fixture", "willing", "", "Fixture", "en", groups),))
        for grammar in (False, True):
            with self.subTest(grammar=grammar):
                text = self.render(value, preview=True, preview_definitions=0, grammar=grammar)
                self.assertIn("Adjective", text)
                self.assertIn("Noun", text)
                doc = self.browser.document()
                heading_x = self.browser.cursorRect(QTextCursor(doc.begin())).left()
                for meaning in ("Ready to do something.", "Second sense.", "The execution of a will."):
                    block = doc.find(meaning).block()
                    self.assertTrue(block.isValid())
                    self.assertIsNone(block.textList())
                    self.assertEqual(self.browser.cursorRect(QTextCursor(block)).left(), heading_x)
        for options in ({}, {"preview": True, "compact": False}):
            with self.subTest(options=options):
                self.render(value, grammar=False, preview_definitions=0, **options)
                doc = self.browser.document()
                for meaning in ("Ready to do something.", "The execution of a will."):
                    text_list = doc.find(meaning).block().textList()
                    self.assertEqual(text_list.format().indent(), 1)

    def test_compact_plain_meanings_keep_limits_without_numbering(self):
        value = result(("First meaning", "Second meaning", "Third meaning"))
        text = self.render(value, preview=True, preview_definitions=2)
        self.assertIn("First meaning\nSecond meaning", text)
        self.assertNotIn("Third meaning", text)
        doc = self.browser.document()
        for meaning in ("First meaning", "Second meaning"):
            block = doc.find(meaning).block()
            self.assertIsNone(block.textList())
            self.assertEqual(self.browser.cursorRect(QTextCursor(block)).left(), 0)
        self.render(value)
        self.assertEqual(self.browser.document().find("Third meaning").block().textList().count(), 3)

    def test_wiktionary_legacy_pos_headings_separate_numbered_entries_with_grammar_hidden(self):
        def definitions(meanings):
            return ({"type": "structured-content", "content": {"tag": "ol", "content": [
                {"tag": "li", "content": meaning} for meaning in meanings]}},)
        entries = (
            Entry("adj", "sovereign", "", "wty-en-en", "en", definitions(("Rule.", "Royal.")), ("adj",)),
            Entry("noun", "sovereign", "", "wty-en-en", "en", definitions(("A monarch.", "A coin.")), ("n",)))
        value = SearchResult("sovereign", "en", "en", entries)
        original = json.dumps([entry.definitions for entry in entries])
        for grammar in (False, True):
            for preview, compact in ((False, False), (True, False), (True, True)):
                with self.subTest(grammar=grammar, preview=preview, compact=compact):
                    text = self.render(value, grammar=grammar, preview=preview, compact=compact,
                                       preview_definitions=0, hidden_sections={"wty-en-en": {"grammar", "etymology"}})
                    self.assertLess(text.index("Adjective"), text.index("Rule."))
                    self.assertLess(text.index("Royal."), text.index("Noun"))
                    self.assertLess(text.index("Noun"), text.index("A monarch."))
                    self.assertEqual(text.count("Adjective"), 1)
                    self.assertEqual(text.count("Noun"), 1)
                    doc = self.browser.document()
                    self.assertIsNone(doc.find("Adjective").block().textList())
                    self.assertIsNone(doc.find("Noun").block().textList())
                    if not compact:
                        first = doc.find("Rule.").block()
                        second = doc.find("A monarch.").block()
                        self.assertEqual(first.textList().itemText(first), "1.")
                        self.assertEqual(second.textList().itemText(second), "1.")
                        self.assertNotEqual(first.textList().objectIndex(), second.textList().objectIndex())
                    self.assertEqual(render_result(value, grammar=grammar, preview=preview, compact=compact,
                                                   preview_definitions=0).count('<hr style='), 1)
        self.assertEqual(json.dumps([entry.definitions for entry in entries]), original)
        text = self.render(value, preview=True, preview_definitions=2, grammar=False)
        self.assertIn("Adjective", text)
        self.assertNotIn("Noun", text)
        self.assertNotIn("A monarch.", text)

    def test_plain_dictionary_pos_is_outside_numbering_and_usage_stays_optional(self):
        definition = {"type": "structured-content", "content": [
            {"tag": "span", "data": {"content": "tag", "category": "partOfSpeech"}, "content": "noun"},
            {"tag": "span", "data": {"content": "tag", "category": "usage"}, "content": "archaic"},
            "First meaning"]}
        value = SearchResult("word", "en", "en", (
            Entry("word", "word", "", "Custom", "en", (definition, "Second meaning")),))
        for grammar in (False, True):
            text = self.render(value, grammar=grammar)
            self.assertEqual(text.count("Noun"), 1)
            self.assertEqual("archaic" in text, grammar)
            doc = self.browser.document()
            self.assertIsNone(doc.find("Noun").block().textList())
            first = doc.find("archaic" if grammar else "First meaning").block()
            self.assertEqual(first.textList().itemText(first), "1.")
            self.assertEqual(first.textList().count(), 2)

    def test_preview_pos_headings_have_equal_gaps_without_resetting_meaning_budget(self):
        entries = tuple(Entry(str(index), "right-to-left", "", "wty-en-en", "en",
                              ({"type": "structured-content", "content": {"tag": "ol", "content": [
                                  {"tag": "li", "content": meaning}]}},), (rule,))
                        for index, (rule, meaning) in enumerate((("adj", "Written in reverse."),
                                                                ("adv", "From right to left."))))
        value = SearchResult("right-to-left", "en", "en", entries)
        for size in (14, 28, 48):
            with self.subTest(size=size), patch.object(config, "font_size_definitions", size):
                self.browser.setFont(document_font(config.font_family, size, "en"))
                self.render(value, preview=True, grammar=False, preview_definitions=0)
                doc = self.browser.document()
                layout = doc.documentLayout()
                gaps = [layout.blockBoundingRect(doc.find(meaning).block()).top()
                        - layout.blockBoundingRect(doc.find(label).block()).bottom()
                        for label, meaning in (("Adjective", "Written in reverse."),
                                               ("Adverb", "From right to left."))]
                self.assertAlmostEqual(*gaps, delta=1)
        text = self.render(value, preview=True, preview_definitions=1)
        self.assertIn("Written in reverse.", text)
        self.assertNotIn("From right to left.", text)

    def test_transitivity_details_follow_grammar_setting_without_becoming_pos_headings(self):
        for detail in ("vt", "vi", "transitive verb", "intransitive verb"):
            definition = {"type": "structured-content", "content": {"tag": "ol", "content": [
                {"tag": "li", "content": "To finish."},
                {"tag": "li", "content": [
                    {"tag": "div", "data": {"content": "tags"}, "content": [
                        {"tag": "span", "data": {"content": "tag", "category": "partOfSpeech"},
                         "content": detail}]}, "To make whole."]}]}}
            value = SearchResult("complete", "en", "en", (
                Entry("verb", "complete", "", "wty-en-en", "en", (definition,), ("v",)),))
            for grammar in (False, True):
                for parts in (False, True):
                    with self.subTest(detail=detail, grammar=grammar, parts=parts):
                        text = self.render(value, preview=True, preview_definitions=0,
                                           grammar=grammar, parts_of_speech=parts)
                        self.assertEqual("\nVerb\n" in text, parts)
                        label = "intransitive" if detail in ("vi", "intransitive verb") else "transitive"
                        self.assertEqual("[" + label + "]" in text, grammar)
                        self.assertNotIn("\nVt\n", text)
                        self.assertNotIn("\nVi\n", text)
                        self.assertIn("To finish.", text)
                        self.assertIn("To make whole.", text)

    def test_transitivity_changes_do_not_insert_separators_when_pos_is_hidden(self):
        definition = {"type": "structured-content", "content": {"tag": "ol", "content": [
            {"tag": "li", "content": [
                {"tag": "div", "data": {"content": "tags"}, "content": [
                    {"tag": "span", "title": title, "data": {"content": "tag", "category": "partOfSpeech"},
                     "content": label}]}, meaning]}
            for title, label, meaning in (("transitive verb", "vt", "To make something better."),
                                          ("intransitive verb", "vi", "To become better."))]}}
        value = SearchResult("improve", "en", "en", (
            Entry("verb", "improve", "", "wty-en-en", "en", (definition,), ("v",)),))
        for parts in (False, True):
            with self.subTest(parts=parts):
                options = dict(preview=True, grammar=False, parts_of_speech=parts)
                text = self.render(value, **options)
                self.assertNotIn("transitive", text.lower())
                self.assertNotIn("\nVt", text)
                self.assertNotIn("\nVi", text)
                self.assertIn("To make something better.", text)
                self.assertIn("To become better.", text)
                self.assertEqual(render_result(value, **options).count('<hr'), 0)

    def test_hidden_pos_keeps_entry_separators_and_numbering(self):
        entries = tuple(Entry(str(index), "sovereign", "", "wty-en-en", "en",
                              ({"type": "structured-content", "content": {"tag": "ol", "content": [
                                  {"tag": "li", "content": meaning}]}},), (rule,))
                        for index, (rule, meaning) in enumerate((("adj", "Royal."), ("n", "A monarch."))))
        for language in ("en", "tr", "ru"):
            value = SearchResult("sovereign", language, "en", entries)
            for grammar in (False, True):
                for preview, compact in ((False, False), (True, False), (True, True)):
                    with self.subTest(language=language, grammar=grammar, preview=preview, compact=compact):
                        options = dict(grammar=grammar, preview=preview, compact=compact,
                                       preview_definitions=0, parts_of_speech=False)
                        text = self.render(value, **options)
                        self.assertNotIn("Adjective", text)
                        self.assertNotIn("Noun", text)
                        self.assertLess(text.index("Royal."), text.index("A monarch."))
                        self.assertEqual(render_result(value, **options).count('<hr style='), 1)
                        if not compact:
                            for meaning in ("Royal.", "A monarch."):
                                block = self.browser.document().find(meaning).block()
                                self.assertEqual(block.textList().itemText(block), "1.")

    def test_hidden_japanese_pos_keeps_sense_groups_and_optional_usage_labels(self):
        groups = [{"tag": "div", "data": {"content": "sense-group"}, "content": [
            {"tag": "span", "data": {"class": "tag", "content": "part-of-speech-info"}, "content": label},
            {"tag": "span", "data": {"content": "tag", "category": "usage"}, "content": "archaic"},
            {"tag": "div", "data": {"content": "sense"}, "content": meaning}]}
            for label, meaning in (("noun", "First meaning"), ("adverb", "Second meaning"))]
        value = result(({"type": "structured-content", "content": groups},), "Jitendex")
        for grammar in (False, True):
            for preview in (False, True):
                with self.subTest(grammar=grammar, preview=preview):
                    options = dict(grammar=grammar, preview=preview, preview_definitions=0, parts_of_speech=False)
                    text = self.render(value, **options)
                    self.assertNotIn("noun", text)
                    self.assertNotIn("adverb", text)
                    self.assertEqual("archaic" in text, grammar)
                    self.assertLess(text.index("First meaning"), text.index("Second meaning"))
                    self.assertEqual(render_result(value, **options).count('<hr style='), 1)
        entries = tuple(Entry(str(index), "word", "", "Jitendex", "ja",
                              ({"type": "structured-content", "content": group},))
                        for index, group in enumerate(groups))
        value = SearchResult("word", "ja", "en", entries)
        text = self.render(value, parts_of_speech=False)
        self.assertIn("First meaning", text)
        self.assertIn("Second meaning", text)
        self.assertEqual(render_result(value, parts_of_speech=False).count('<hr style='), 1)

    def test_pos_scope_is_preserved_for_japanese_sense_groups_with_grammar_off(self):
        groups = [{"tag": "div", "data": {"content": "sense-group"}, "content": [
            {"tag": "span", "data": {"class": "tag", "content": "part-of-speech-info"}, "content": label},
            {"tag": "div", "data": {"content": "sense"}, "content": meaning}]}
            for label, meaning in (("noun", "First meaning"), ("adverb", "Second meaning"))]
        value = result(({"type": "structured-content", "content": groups},), "Jitendex")
        text = self.render(value, grammar=False)
        self.assertLess(text.index("[noun]"), text.index("First meaning"))
        self.assertLess(text.index("First meaning"), text.index("[adverb]"))
        self.assertLess(text.index("[adverb]"), text.index("Second meaning"))

    def test_pos_fallback_is_exporter_specific_and_explicit_tags_take_priority(self):
        definition = {"type": "structured-content", "content": [
            {"tag": "span", "data": {"content": "tag"}, "content": "proper noun"}, "A name."]}
        for source in ("wty-en-en", "Custom"):
            value = SearchResult("word", "en", "en", (
                Entry("word", "word", "", source, "en", (definition,), ("n",)),))
            text = self.render(value, grammar=False)
            self.assertIn("Proper noun", text)
            self.assertNotIn("\nNoun\n", text)
        unknown = SearchResult("word", "en", "en", (
            Entry("1", "word", "", "Custom", "en", ("A noun in an example.",), ("n",)),
            Entry("2", "word", "", "Custom", "en", ("An adjective in prose.",), ("adj",))))
        html = render_result(unknown, grammar=False)
        self.assertNotIn('<p class="part-of-speech">', html)
        self.assertEqual(html.count('<hr style='), 1)

    def test_explicit_pos_categories_and_jmdict_classes_stay_visible_without_guessing_from_topics(self):
        for language, label, data, expected in (
                ("en", "classifier", {"content": "tag", "category": "partOfSpeech"}, "Classifier"),
                ("ja", "Godan verb with 'ru' ending", {"class": "tag"}, "[verb]"),
                ("ja", "noun (common) (futsuumeishi)", {"content": "tag"}, "[noun]")):
            with self.subTest(language=language, label=label):
                definition = {"type": "structured-content", "content": [
                    {"tag": "span", "data": data, "content": label}, "Meaning"]}
                value = SearchResult("word", language, "en", (
                    Entry("word", "word", "", "Custom", language, (definition,)),))
                text = self.render(value, grammar=False)
                self.assertIn(expected, text)
                self.assertIn("Meaning", text)
        definition = {"type": "structured-content", "content": [
            {"tag": "span", "data": {"content": "tag", "category": "topic"}, "content": "noun"}, "Meaning"]}
        value = SearchResult("word", "en", "en", (Entry("word", "word", "", "Custom", "en", (definition,)),))
        self.assertNotIn("noun", self.render(value, grammar=False).lower())

    def test_compact_preview_omits_subdefinitions_and_keeps_top_level_sense_limit(self):
        definition = {"type": "structured-content", "content": {"tag": "ol", "content": [
            {"tag": "li", "content": ["First meaning", {"tag": "ul", "content": [
                {"tag": "li", "content": "Subdefinition"}]}]},
            {"tag": "li", "content": "Second meaning"},
            {"tag": "li", "content": "Third meaning"}]}}
        text = self.render(result((definition,)), preview=True, preview_definitions=2)
        self.assertIn("First meaning\nSecond meaning", text)
        self.assertNotIn("Subdefinition", text)
        self.assertNotIn("Third meaning", text)
        doc = self.browser.document()
        for meaning in ("First meaning", "Second meaning"):
            block = doc.find(meaning).block()
            self.assertIsNone(block.textList())
            self.assertEqual(self.browser.cursorRect(QTextCursor(block)).left(), 0)
        for options in ({}, {"preview": True, "compact": False, "preview_definitions": 2}):
            text = self.render(result((definition,)), **options)
            self.assertIn("Subdefinition", text)
            self.assertIsNotNone(self.browser.document().find("Subdefinition").block().textList())

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

    def test_unstructured_japanese_preview_keeps_complete_meanings(self):
        value = result(("長い意味" * 200,))
        text = self.render(value, preview=True)
        self.assertNotIn("…", text)
        self.assertIn("長い意味" * 200, text)
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
