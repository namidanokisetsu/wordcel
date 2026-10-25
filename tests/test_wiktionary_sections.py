from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtWidgets import QApplication, QCheckBox, QComboBox, QListWidget, QListWidgetItem

from wordcel.dictionary.library import Entry
from wordcel.dictionary.search import SearchResult
from wordcel.dictionary.wiktionary_sections import pack_sections, sections_in
from wordcel.gui.dictionary_manager import SetupDialog
from wordcel.gui.quick_lookup import render_result


def detail(label, marked=True):
    node = dict(tag="details", content=[dict(tag="summary", content=label), label + " body"])
    if marked:
        node["data"] = dict(content="details-entry-" + label)
    return node


class WiktionarySectionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def result(self, source="wty-tr-en"):
        definition = dict(type="structured-content", content=[
            detail("Grammar"), detail("Etymology"), detail("Examples", False), "cigarette"])
        entry = Entry("1", "sigara", "", source, "tr", (definition,))
        return SearchResult("sigara", "tr", "en", entries=(entry,))

    def test_independent_filters_keep_definitions_and_stable_disclosures(self):
        result = self.result()
        original = json.dumps(result.entries[0].definitions)
        default = render_result(result, details_expanded=("0:0:0", "0:0:1"))
        self.assertIn("Grammar body", default)
        self.assertIn("Etymology body", default)
        for hidden, kept in (("grammar", "Etymology"), ("etymology", "Grammar")):
            html = render_result(result, hidden_sections={"wty-tr-en": {hidden}},
                                 details_expanded=("0:0:0", "0:0:1", "0:0:2"))
            self.assertNotIn(hidden.title(), html)
            self.assertIn(kept + " body", html)
            self.assertIn("Examples body", html)
            self.assertIn("cigarette", html)
            self.assertIn("details:0:0:2", html)
        self.assertEqual(json.dumps(result.entries[0].definitions), original)
        self.assertIn("Grammar body", " ".join(result.entries[0].glosses()))

    def test_other_dictionaries_and_unmarked_sections_unchanged(self):
        result = self.result("Japanese dictionary")
        self.assertEqual(render_result(result), render_result(result, hidden_sections={
            "Japanese dictionary": {"grammar", "etymology"}}))
        self.assertEqual(sections_in([detail("Grammar", False), detail("Etymology", False)]), set())

    def test_pack_capabilities_are_cached_by_file_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pack.sqlite3"
            with closing(sqlite3.connect(path)) as db, db:
                db.execute("CREATE TABLE terms(definitions TEXT)")
                db.execute("INSERT INTO terms VALUES(?)", (json.dumps([detail("Grammar")]),))
            self.assertEqual(pack_sections(path, 1, 1), {"grammar"})
            with closing(sqlite3.connect(path)) as db, db:
                db.execute("INSERT INTO terms VALUES(?)", (json.dumps([detail("Etymology")]),))
            self.assertEqual(pack_sections(path, 1, 1), {"grammar"})
            self.assertEqual(pack_sections(path, 2, 2), {"grammar", "etymology"})

    def test_controls_follow_pack_capabilities_and_profile_preferences(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = QSettings(str(Path(directory) / "settings.ini"), QSettings.Format.IniFormat)
            packs, profile, display = QListWidget(), QComboBox(), QComboBox()
            profile.addItem("Turkish", "tr")
            profile.addItem("Other", "other")
            display.addItem("Shown", "expanded")
            display.addItem("Collapsed", "collapsed")
            controls = {kind: QCheckBox() for kind in ("grammar", "etymology")}
            parent = SimpleNamespace(active_profile="tr", _render=Mock())
            owner = SimpleNamespace(packs=packs, profile=profile, dictionary_display=display,
                                    section_controls=controls, editing_language="tr", settings=settings,
                                    _section_capabilities={"pack": {"grammar"}}, _loading=False,
                                    parent=lambda: parent)
            item = QListWidgetItem("wty-tr-en")
            for offset, value in enumerate(("pack", "tr", "wty-tr-en", True, "resource-id")):
                item.setData(Qt.ItemDataRole.UserRole + offset, value)
            packs.addItem(item)
            packs.setCurrentItem(item)
            SetupDialog.update_dictionary_display(owner)
            self.assertFalse(controls["grammar"].isHidden())
            self.assertTrue(controls["etymology"].isHidden())
            self.assertTrue(controls["grammar"].isChecked())
            SetupDialog.save_dictionary_section(owner, "grammar", False)
            self.assertEqual(settings.value("profiles/tr/hidden_grammar_dictionaries"), ["resource-id"])
            parent._render.assert_called_once_with(static=True, preserve_scroll=True)
            SetupDialog.update_dictionary_display(owner)
            self.assertFalse(controls["grammar"].isChecked())
            profile.setCurrentIndex(1)
            SetupDialog.update_dictionary_display(owner)
            self.assertTrue(controls["grammar"].isChecked())
            owner._section_capabilities.clear()
            SetupDialog.update_dictionary_display(owner)
            self.assertTrue(all(control.isHidden() for control in controls.values()))
