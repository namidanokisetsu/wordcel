import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtWidgets import QApplication, QMessageBox

from wordcel.config.profiles import create_profile, migrate
from wordcel.gui.dictionary_manager import SetupDialog


class SettingsNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.settings = QSettings(str(self.root / "settings.ini"), QSettings.Format.IniFormat)
        self.settings.setValue("profile", "ja")
        self.settings.setValue("profiles/ja/language", "ja")
        self.settings.setValue("profiles/ja/hotkey", "")
        migrate(self.settings, self.root / "library")

    def dialog(self):
        dialog = SetupDialog(self.root / "library", self.settings, Mock())
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.audio_sources.shutdown)
        self.addCleanup(dialog.close)
        return dialog

    def test_pages_and_single_profile_management(self):
        dialog = self.dialog()
        self.assertEqual({dialog.tabs.tabText(i) for i in range(dialog.tabs.count())},
                         {"General", "Lookup", "Dictionaries", "Shortcuts", "Appearance", "Audio", "Translation", "Anki"})
        self.assertEqual(dialog.scope.count(), 1)
        self.assertTrue(dialog.scope.isHidden())
        self.assertIn("Rename…", [action.text() for action in dialog.profile_menu.actions()])
        self.assertIn("Reset profile settings…", [action.text() for action in dialog.profile_menu.actions()])
        self.assertFalse(dialog.appearance.isHidden())
        dialog.tabs.setCurrentWidget(dialog.app_tab)
        self.assertTrue(dialog.scope.isHidden())

    def test_duplicate_is_selected_for_editing_without_activation(self):
        dialog = self.dialog()
        dialog.duplicate_profile()
        duplicate = dialog.profile.currentData()
        self.assertNotEqual(duplicate, "ja")
        self.assertEqual(dialog.scope.currentData(), duplicate)
        self.assertEqual(self.settings.value("profile"), "ja")
        self.assertIn("Active:", dialog.editing_status.text())
        dialog.appearance.controls["font_size_header"].setValue(35)
        self.assertEqual(self.settings.value(f"profiles/{duplicate}/font_size_header", 0, int), 35)
        self.assertFalse(self.settings.contains("profiles/ja/font_size_header"))

    def test_search_opens_advanced_section_and_preserves_page_geometry(self):
        dialog = self.dialog()
        dialog.show()
        self.app.processEvents()
        geometry = dialog.geometry()
        dialog.search.setText("passage size")
        self.assertGreater(dialog.search_results.count(), 0)
        dialog.open_search_result(dialog.search_results.item(0))
        self.app.processEvents()
        self.assertIs(dialog.tabs.currentWidget(), dialog.translation_tab)
        self.assertFalse(dialog.translation_chunk_size.isHidden())
        self.assertTrue(dialog.translation_chunk_size.isVisibleTo(dialog.translation_tab))
        self.assertEqual(dialog.geometry(), geometry)

    def test_page_reset_confirmation_is_scoped_and_cancel_does_nothing(self):
        dialog = self.dialog()
        dialog.tabs.setCurrentWidget(dialog.popup_tab)
        dialog.appearance.controls["font_size_header"].setValue(39)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No) as question:
            dialog.restore_page_defaults()
        self.assertIn("Appearance for " + dialog.profile.currentText(), question.call_args.args[2])
        self.assertEqual(self.settings.value("profiles/ja/font_size_header", 0, int), 39)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes), \
                patch.object(dialog, "reload") as reload_library, \
                patch.object(dialog.audio_sources, "load") as reload_audio, \
                patch.object(dialog.anki, "load") as reload_anki:
            dialog.restore_page_defaults()
        reload_library.assert_not_called()
        reload_audio.assert_not_called()
        reload_anki.assert_not_called()
        self.assertFalse(self.settings.contains("profiles/ja/font_size_header"))
        self.assertEqual(self.settings.value("profiles/ja/hotkey"), "")

    def test_profile_reset_preserves_identity_and_other_profile(self):
        duplicate = create_profile(self.settings, "ja", "Anime", duplicate="ja")
        self.settings.setValue(f"profiles/{duplicate}/font_size_header", 40)
        self.settings.setValue("profiles/ja/font_size_header", 35)
        dialog = self.dialog()
        dialog.scope.setCurrentIndex(dialog.scope.findData(duplicate))
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes) as question:
            dialog.restore_profile_defaults()
        self.assertIn("Anime", question.call_args.args[2])
        self.assertEqual(self.settings.value(f"profiles/{duplicate}/name"), "Anime")
        self.assertEqual(self.settings.value("profiles/ja/font_size_header", 0, int), 35)
        self.assertEqual(self.settings.value("profile"), "ja")

    def test_mixed_shortcuts_have_separate_app_reset(self):
        dialog = self.dialog()
        dialog.tabs.setCurrentWidget(dialog.shortcuts_tab)
        self.assertFalse(dialog.reset_app_shortcuts.isHidden())
        self.settings.setValue("next_profile_hotkey", "")
        self.settings.setValue("profiles/ja/hotkey", "<alt>+d")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes) as question:
            dialog.restore_switching_defaults()
        self.assertIn("all profiles", question.call_args.args[2])
        self.assertEqual(self.settings.value("profiles/ja/hotkey"), "<alt>+d")
        self.assertEqual(self.settings.value("next_profile_hotkey", ""), "")
        dialog.tabs.setCurrentWidget(dialog.app_tab)
        self.assertTrue(dialog.reset_app_shortcuts.isHidden())
        self.assertTrue(dialog.scope.isHidden())

    def test_translation_disable_preserves_options_and_availability(self):
        from wordcel.gui.resources import profile_translation_available
        from wordcel.dictionary.translation import TranslationSettings, save_profile_settings
        save_profile_settings(self.settings, "ja", TranslationSettings(provider="custom", model="local"))
        dialog = self.dialog()
        self.assertTrue(profile_translation_available(self.settings, "ja"))
        dialog.translation_enabled.setChecked(False)
        self.assertTrue(dialog.translation_options.isHidden())
        self.assertFalse(profile_translation_available(self.settings, "ja"))
        self.assertEqual(dialog.translation_model.text(), "local")
        dialog.translation_enabled.setChecked(True)
        self.assertTrue(profile_translation_available(self.settings, "ja"))

    def test_anki_connection_edit_does_not_change_another_profile(self):
        from wordcel.anki import load_settings
        from wordcel.config.profiles import save_connection
        identity = save_connection(self.settings, "anki", {"endpoint": "http://127.0.0.1:8765", "api_key": "original"})
        self.settings.setValue("profiles/ja/anki/connection", identity)
        other = create_profile(self.settings, "ja", "Other")
        self.settings.setValue(f"profiles/{other}/anki/connection", identity)
        dialog = self.dialog()
        dialog.anki.api_key.setText("changed")
        dialog.anki._save()
        self.assertEqual(load_settings(self.settings, "ja").api_key, "changed")
        self.assertEqual(load_settings(self.settings, other).api_key, "original")

    def test_invalid_anki_connection_keeps_saved_assignment(self):
        from wordcel.anki import load_settings
        dialog = self.dialog()
        original = load_settings(self.settings, "ja").endpoint
        dialog.anki.endpoint.setText("invalid")
        dialog.anki._connection_changed()
        self.assertEqual(load_settings(self.settings, "ja").endpoint, original)
        self.assertIn("local AnkiConnect", dialog.anki.status.text())
