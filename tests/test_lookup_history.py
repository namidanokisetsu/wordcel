import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import Mock
import zipfile

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication, QPushButton, QTextBrowser, QWidget

from wordcel.dictionary.library import Entry
from wordcel.dictionary.search import SearchResult
from wordcel.gui.lookup_history import HistoryService, HistorySettings, HistoryWindow


def result(form="猫", headword="猫", reading="ねこ", meaning="cat", language="ja"):
    return SearchResult(form, language, "en", (Entry("1", headword, reading, "Words", language, (meaning,)),))


class HistoryRecordingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.window = QWidget()
        self.window.directory = self.temp.name
        self.window.preferred_foreign = "ja"
        self.window.active_profile = "ja"
        self.window.settings = QSettings(str(Path(self.temp.name) / "settings.ini"), QSettings.Format.IniFormat)
        self.window.settings.setValue("history/enabled", True)
        self.service = HistoryService(self.window)
        self.service._run = Mock()

    def tearDown(self):
        self.service.shutdown()
        self.window.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def display(self, mode="hover", context="猫がいる。", restored=False):
        self.service.display(result(), context, 0, 1, mode, restored=restored)

    def test_hover_refresh_keeps_deadline_and_pin_reuses_encounter(self):
        self.window.settings.setValue("history/hover", True)
        self.display()
        timer_id = self.service.timer.timerId()
        self.display()
        self.assertEqual(self.service.timer.timerId(), timer_id)
        self.service.timer.stop()
        self.service.timer.timeout.emit()
        self.service.pin()
        self.assertEqual(self.service._run.call_count, 1)
        self.assertFalse(self.service.timer.isActive())

    def test_unfinished_hover_pin_cancel_and_separate_visits(self):
        self.window.settings.setValue("history/hover", True)
        self.window.settings.setValue("history/pinned", False)
        self.display()
        self.service.pin()
        self.assertFalse(self.service.timer.isActive())
        self.service._run.assert_not_called()
        self.service.reset()
        self.display("manual")
        self.display("manual")
        self.assertEqual(self.service._run.call_count, 1)
        self.display("manual", "次の猫")
        self.display("manual")
        self.assertEqual(self.service._run.call_count, 3)

    def test_pin_records_without_hover_and_restore_never_records(self):
        self.display()
        self.assertFalse(self.service.timer.isActive())
        self.service.pin()
        self.assertEqual(self.service._run.call_count, 1)
        self.service.reset()
        self.display("manual", restored=True)
        self.service.pin()
        self.assertEqual(self.service._run.call_count, 1)

    def test_disable_cancels_without_backfill_and_preserves_choices(self):
        self.window.settings.setValue("history/hover", True)
        self.display()
        self.window.settings.setValue("history/enabled", False)
        self.service.preferences_changed.emit()
        self.assertFalse(self.service.timer.isActive())
        self.window.settings.setValue("history/enabled", True)
        self.service.preferences_changed.emit()
        self.display()
        self.service.pin()
        self.service._run.assert_not_called()
        self.assertTrue(self.service.value("hover", False))

    def test_settings_share_enable_and_hide_hover_duration(self):
        panel = HistorySettings(self.service)
        self.assertFalse(panel.layout().isRowVisible(panel.delay))
        panel.checks["hover"].setChecked(True)
        self.assertTrue(panel.layout().isRowVisible(panel.delay))
        self.window.settings.setValue("history/enabled", False)
        self.service.preferences_changed.emit()
        self.assertFalse(panel.checks["enabled"].isChecked())

    def test_cards_preserve_items_selection_scroll_and_escape_text(self):
        browser = HistoryWindow(self.service)
        rows = [dict(id=i, timestamp=1000000 + i, language="ja", form="猫", context="<猫>" * 30,
                     start=1, end=2, words=[("ja", "猫", "ねこ")], excerpt="") for i in range(30)]
        browser.resize(400, 300)
        browser.show()
        browser.receive(browser.revision, (rows, 30, ("ja",)))
        self.app.processEvents()
        item = browser.cards.item(10)
        browser.cards.setCurrentItem(item)
        browser.cards.verticalScrollBar().setValue(200)
        scroll = browser.cards.verticalScrollBar().value()
        browser.receive(browser.revision, (rows, 30, ("ja",)))
        self.assertIs(browser.cards.item(10), item)
        self.assertIs(browser.cards.currentItem(), item)
        self.assertEqual(browser.cards.verticalScrollBar().value(), scroll)
        self.assertIn("&lt;<b>猫</b>&gt;", browser.cards.item(1).text())
        browser.close()

    def test_open_card_shows_sentence_and_lookup_is_explicit(self):
        browser = HistoryWindow(self.service)
        row = dict(id=1, timestamp=1000000, language="ja", form="?", context="?????",
                   start=0, end=1, words=[("ja", "?", "??")], excerpt="")
        self.window.restore_encounter = Mock()
        browser.receive(browser.revision, ([row], 1, ("ja",)))
        browser.open_card(browser.cards.item(1))
        self.window.restore_encounter.assert_not_called()
        self.assertEqual(browser.detail.findChild(QTextBrowser).toPlainText(), row["context"])
        browser.detail.findChild(QPushButton, "").click()
        self.window.restore_encounter.assert_called_once_with(row)
        browser.close()

    def test_worker_records_multiple_pins_and_refreshes_unfiltered_cards(self):
        self.service._run = HistoryService._run.__get__(self.service)
        failures = []
        self.service.failed.connect(failures.append)
        self.service.open()
        for term in ("温泉", "現代", "人生", "解説"):
            self.service.reset()
            self.service.display(result(term, term), term, 0, len(term), "hover")
            self.service.pin()
            self.service.executor.submit(lambda: None).result(timeout=3)
            self.app.processEvents()
        self.service.executor.submit(lambda: None).result(timeout=3)
        self.app.processEvents()
        self.assertEqual(failures, [])
        self.assertEqual(len(self.service.browser.rows), 4)
        self.assertEqual(self.service.browser.cards.count(), 5)
        self.assertEqual({row["form"] for row in self.service.browser.rows.values()}, {"温泉", "現代", "人生", "解説"})

    def test_worker_reuses_japanese_analysis_and_romaji_without_sentence_prefixes(self):
        from wordcel.dictionary.library import import_yomitan
        archive = Path(self.temp.name) / "words.zip"
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr("index.json", json.dumps(dict(title="Fixture", revision="1", format=3)))
            zipped.writestr("term_bank_1.json", json.dumps([
                ["食べる", "たべる", "", "v1", 0, ["eat"], 0, ""],
                ["温泉", "おんせん", "", "", 0, ["hot spring"], 1, ""],
                ["温", "ぬく", "", "", 0, ["warm"], 2, ""]]))
        import_yomitan(archive, self.temp.name, "ja")
        self.service._run = HistoryService._run.__get__(self.service)
        failures, responses = [], []
        self.service.failed.connect(failures.append)
        self.service.results.connect(lambda revision, response: responses.append(response))
        for term, reading in (("食べる", "たべる"), ("温泉", "おんせん"), ("温", "ぬく")):
            self.service.display(result(term, term, reading), term, 0, len(term), "manual")
        for revision, query, expected in ((1, "食べました", "食べる"), (2, "onsen", "温泉"), (3, "温泉に行く", None)):
            self.service.search(revision, query, "ja", 100, "ja")
            self.service.executor.submit(lambda: None).result(timeout=3)
            self.app.processEvents()
            self.assertFalse(failures)
            rows = responses[-1][0]
            self.assertEqual([row["form"] for row in rows], [expected] if expected else [])
