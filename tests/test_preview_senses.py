import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import copy
import unittest
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import QApplication
from wordcel.dictionary.library import Entry
from wordcel.dictionary.search import SearchResult
from wordcel.gui.quick_lookup import LocalDictionaryBrowser, render_result


def node(tag, content, kind=""):
    return dict(tag=tag, content=content, data={"content": kind})


def definition(content):
    return dict(type="structured-content", content=content)


class PreviewSenseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.browser = LocalDictionaryBrowser(selection_lookup=False)
        self.browser.resize(400, 500)
        self.browser.show()

    def tearDown(self):
        self.browser.close()
        self.browser.deleteLater()
        self.app.processEvents()

    def render(self, definitions, **options):
        value = SearchResult("word", "en", "en", (
            Entry("fixture", "word", "", "Fixture", "en", tuple(definitions)),))
        self.browser.setHtml(render_result(value, **options))
        self.app.processEvents()
        return self.browser.toPlainText()

    def test_sense_budget_is_shared_across_groups_and_preserves_full_view(self):
        groups = [definition(node("ol", [node("li", f"Meaning {i}") for i in indices], "glosses"))
                  for indices in ((1, 2, 3), (4, 5, 6))]
        original = copy.deepcopy(groups)
        for compact in (False, True):
            with self.subTest(compact=compact):
                text = self.render(groups, preview=True, compact=compact, preview_definitions=4)
                for i in range(1, 5):
                    self.assertIn(f"Meaning {i}", text)
                for i in (5, 6):
                    self.assertNotIn(f"Meaning {i}", text)
        for options in ({}, {"preview": True, "preview_definitions": 0}):
            text = self.render(groups, **options)
            self.assertIn("Meaning 6", text)
        self.assertEqual(groups, original)

    def test_all_means_all_senses_without_leaking_examples_or_related_words(self):
        content = [node("ol", [node("li", [f"Meaning {i}",
                   node("div", "Example sentence", "examples")]) for i in range(1, 4)], "glosses"),
                   node("div", node("div", node("ul", [node("li", f"Synonym {i}")
                        for i in range(1, 4)], "synonyms-list"), "synonyms"), "related-words"),
                   node("div", "Spelling variant", "forms")]
        for maximum in (0, 2):
            with self.subTest(maximum=maximum):
                text = self.render([definition(content)], preview=True, preview_definitions=maximum)
                self.assertIn("Meaning 2", text)
                self.assertEqual("Meaning 3" in text, maximum == 0)
                for extra in ("Example sentence", "Synonym", "Spelling variant"):
                    self.assertNotIn(extra, text)
        for options in ({}, {"preview": True, "compact": False, "preview_definitions": 2}):
            text = self.render([definition(content)], **options)
            self.assertIn("Example sentence", text)
            self.assertIn("Synonyms", text)
            self.assertIn("Synonym 3", text)

    def test_gap_separates_senses_but_not_wrapped_lines(self):
        long = ("A long first meaning with several words " * 3).strip()
        for definitions in ((long, "Second meaning"),
                            (definition(node("ol", [node("li", node("div", long)),
                                                     node("li", node("div", "Second meaning"))])),)):
            with self.subTest(structured=isinstance(definitions[0], dict)):
                self.render(definitions, preview=True)
                doc = self.browser.document()
                first, second = doc.find(long).block(), doc.find("Second meaning").block()
                self.assertGreater(first.layout().lineCount(), 1)
                self.assertGreater(second.blockFormat().topMargin(), first.blockFormat().topMargin())
                self.assertLessEqual(second.blockFormat().topMargin(), self.browser.fontMetrics().height() / 2)
                self.assertEqual(self.browser.cursorRect(QTextCursor(first)).left(),
                                 self.browser.cursorRect(QTextCursor(second)).left())

    def test_numbered_and_marked_senses_share_the_same_limit(self):
        variants = [node("div", [node("div", [f"{i}. Meaning {i}"]) for i in range(1, 4)]),
                    node("div", [dict(tag="div", data={"meaning": ""}, content=f"Meaning {i}")
                                 for i in range(1, 4)]),
                    node("div", [node("div", f"Meaning {i}", "sense") for i in range(1, 4)], "sense-group")]
        for content in variants:
            for maximum in (0, 1, 2):
                with self.subTest(content=content, maximum=maximum):
                    text = self.render([definition(content)], preview=True, preview_definitions=maximum)
                    for i in range(1, 4):
                        self.assertEqual(f"Meaning {i}" in text, maximum == 0 or i <= maximum)
                    self.assertNotIn("1. Meaning", text)

    def test_related_list_without_a_wrapper_is_excluded(self):
        for kind in ("synonyms-list", "antonyms-list", "related-words"):
            with self.subTest(kind=kind):
                text = self.render([definition(node("ul", [node("li", "Related term")], kind)),
                                    "First meaning", "Second meaning"], preview=True, preview_definitions=2)
                self.assertNotIn("Related term", text)
                self.assertIn("Second meaning", text)
                text = self.render([definition(node("ul", [node("li", "Related term")], kind)),
                                    "First meaning", "Second meaning"], preview=True, compact=False, preview_definitions=2)
                self.assertIn("Related term", text)
                self.assertIn("Second meaning", text)

    def test_legacy_jmdict_forms_are_not_counted_as_meanings(self):
        definitions = (definition([node("span", "other surface forms and readings", "tag"), "Variant A"]),
                       "Variant B", "Variant C")
        from wordcel.gui.gloss_content import normalize_definitions
        normalized = normalize_definitions(definitions, "JMdict")
        self.assertNotIn("Variant", self.render(normalized, preview=True, preview_definitions=0))
        text = self.render(normalized)
        self.assertIn("Forms", text)
        for variant in ("Variant A", "Variant B", "Variant C"):
            block = self.browser.document().find(variant).block()
            self.assertTrue(block.isValid())
            self.assertIsNone(block.textList())

    def test_named_monolingual_senses_use_shared_limits_and_example_filtering(self):
        for name, number in (("語義", "語義番号"), ("語義G", "語義Gnum")):
            def named(tag, label, content):
                return dict(tag=tag, data={"name": label}, content=content)
            content = [named("span", "見出部", "Repeated heading"),
                       named("div", "解説部", [named("div", name, [
                           named("span", number, f"{i}."), named("span", "語釈", f"Meaning {i}"),
                           named("div", "用例G", "Example sentence")]) for i in range(1, 4)])]
            original = copy.deepcopy(content)
            with self.subTest(name=name):
                text = self.render([definition(content)], preview=True, preview_definitions=2)
                self.assertIn("Meaning 1", text)
                self.assertIn("Meaning 2", text)
                for hidden in ("Meaning 3", "Example sentence", "Repeated heading", "1."):
                    self.assertNotIn(hidden, text)
                text = self.render([definition(content)])
                self.assertIn("Meaning 3", text)
                self.assertIn("Example sentence", text)
                self.assertEqual(content, original)

    def test_info_glossary_can_be_the_only_definition(self):
        text = self.render([definition(node("ul", node("li", "Voiced repetition mark"), "infoGlossary"))],
                           preview=True, preview_definitions=1)
        self.assertIn("Voiced repetition mark", text)

    def test_cross_references_do_not_consume_the_meaning_budget(self):
        definitions = (definition([node("ul", node("li", "Pork"), "glossary"),
                                  node("ul", [node("li", "See meat"), node("li", "See pig")], "references")]),
                       "Second meaning", "Third meaning")
        for compact in (False, True):
            text = self.render(definitions, preview=True, compact=compact, preview_definitions=2)
            self.assertIn("Pork", text)
            self.assertIn("Second meaning", text)
            self.assertNotIn("Third meaning", text)
            self.assertEqual("See meat" in text, not compact)
        self.assertIn("See pig", self.render(definitions))

    def test_legacy_form_notation_is_preserved_and_explained_without_leading_space(self):
        definitions = (definition([node("span", "other surface forms and readings", "tag"),
                                   " ", "〈寿司〉（★）"]), "鮨", "鮓（🅁）", "麥（⛬）", "異形（⚠）")
        original = copy.deepcopy(definitions)
        self.render(definitions)
        doc = self.browser.document()
        for text, description in (("〈寿司〉", "Ateji"), ("★", "Common form"), ("🅁", "Rare form"),
                                  ("⛬", "Outdated form"), ("⚠", "Irregular form")):
            cursor = doc.find(text)
            self.assertFalse(cursor.isNull())
            self.assertEqual(cursor.charFormat().toolTip(), description)
            self.assertFalse(cursor.charFormat().isAnchor())
        self.assertEqual(doc.find("〈寿司〉").block().text(), "〈寿司〉（★）")
        self.assertEqual(definitions, original)
        self.render(("Ordinary text ★ 〈word〉 🅁",))
        for text in ("★", "〈word〉", "🅁"):
            self.assertEqual(self.browser.document().find(text).charFormat().toolTip(), "")

    def test_homonym_forms_stay_with_their_own_definitions(self):
        def forms(*spellings):
            return (definition([node("span", "other surface forms and readings", "tag"), " ", spellings[0]]),
                    *spellings[1:])
        entries = tuple(Entry(str(i), "ブタ", "ブタ", "JMdict", "ja", definitions)
                        for i, definitions in enumerate((("Card-game meaning",), forms("ぶた", "ブタ"),
                                                          ("Pig",), ("Pork",), forms("豚（★）", "豕（🅁）", "ブタ"))))
        value = SearchResult("buta", "ja", "en", entries)
        self.browser.setHtml(render_result(value))
        text = self.browser.toPlainText()
        first, second = text.index("Forms"), text.rindex("Forms")
        self.assertLess(text.index("Card-game meaning"), first)
        self.assertLess(first, text.index("ぶた"))
        self.assertLess(text.index("ぶた"), text.index("Pig"))
        self.assertLess(text.index("Pork"), second)
        self.assertLess(second, text.index("豚（★）"))
        self.browser.setHtml(render_result(value, preview=True, preview_definitions=2))
        text = self.browser.toPlainText()
        self.assertIn("Pig", text)
        self.assertNotIn("Pork", text)
        self.assertNotIn("Forms", text)


if __name__ == "__main__":
    unittest.main()
