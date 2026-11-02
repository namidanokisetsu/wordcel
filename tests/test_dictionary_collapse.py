import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PyQt6.QtCore import QSettings, QUrl
from PyQt6.QtWidgets import QApplication

from wordcel.dictionary.library import Entry
from wordcel.dictionary.search import SearchResult
from wordcel.gui.quick_lookup import QuickLookupWindow


def _entry(source, definitions):
    return Entry(f"{source}:fixture", "fixture", "", source, "ja", tuple(definitions))


class DictionaryCollapseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings = QSettings(str(Path(self.temp.name) / "settings.ini"), QSettings.Format.IniFormat)
        self.settings.setValue("profile", "ja")
        self.settings.setValue("profiles/ja/target", "en")
        self.model_status_patch = patch("wordcel.language.stanza_analyzer.model_status", return_value="Model needed")
        self.model_status_patch.start()
        self.window = QuickLookupWindow(self.temp.name, lambda: None, self.settings)

    def tearDown(self):
        self.window.shutdown()
        self.window.worker._thread.join(timeout=2)
        self.window.hide()
        self.window.deleteLater()
        self.app.processEvents()
        self.model_status_patch.stop()
        self.temp.cleanup()

    def test_pinned_dictionary_label_collapses_and_restores_full_content(self):
        self.window.settings.setValue("profiles/ja/expanded_dictionaries", ["Middle-school monolingual"])
        definitions = tuple(f"Meaning {index}: " + "x" * 120 for index in range(4))
        result = SearchResult("fixture", "ja", "en", (_entry("Middle-school monolingual", definitions),))

        self.window.set_compact_preview(False)
        self.window.show_entries(result.entries, result.text, peek=True)
        self.window.pin.setChecked(True)
        self.app.processEvents()

        expanded_text = self.window.browser.toPlainText()
        self.assertIn("Meaning 3", expanded_text)
        self.assertIn('href="collapse:0:0"', self.window.browser.toHtml())

        self.window._link(QUrl("collapse:0:0"))
        self.app.processEvents()
        collapsed_text = self.window.browser.toPlainText()
        self.assertNotIn("Meaning 3", collapsed_text)
        self.assertLess(len(collapsed_text), len(expanded_text))
        self.assertIn('href="collapse:0:0"', self.window.browser.toHtml())
        self.window._link(QUrl("collapse:0:0"))
        self.assertIn("Meaning 3", self.window.browser.toPlainText())

    def test_disclosure_labels_keep_their_position(self):
        details = {"type": "structured-content", "content": {
            "tag": "details", "content": [
                {"tag": "summary", "content": "Examples"},
                {"tag": "div", "content": "An example"}]}}
        self.window.show_entries((_entry("JMdict", ("house", details)),), "ie")
        self.window.show()
        self.app.processEvents()

        def label_rect(label):
            cursor = self.window.browser.document().find(label)
            self.assertFalse(cursor.isNull())
            cursor.setPosition(cursor.selectionStart())
            return self.window.browser.cursorRect(cursor)

        for label, link in (("JMdict", "collapse:0:0"), ("Examples", "details:0:0:0")):
            with self.subTest(label=label):
                before = label_rect(label)
                geometry = self.window.geometry()
                for _ in range(2):
                    self.window._link(QUrl(link))
                    self.app.processEvents()
                    self.assertEqual(label_rect(label), before)
                    self.assertEqual(self.window.geometry(), geometry)


if __name__ == "__main__":
    unittest.main()
