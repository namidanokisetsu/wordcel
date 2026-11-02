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
                         {"Startup", "History", "Storage", "Lookup", "Dictionaries", "Shortcuts", "Appearance", "Audio", "Translation", "Anki"})
        self.assertEqual(dialog.scope.count(), 1)
        self.assertFalse(dialog.scope.isHidden())
        self.assertFalse(dialog.scope_label.isHidden())
        self.assertFalse(dialog.profile_details.isHidden())
        self.assertEqual(dialog.scope.currentText(), "日本語 ✓")
        self.assertEqual(dialog.profile_language_label.text(), "日本語")
        self.assertEqual(dialog.editing_status.text(), "Active profile")
        self.assertIn("Rename…", [action.text() for action in dialog.profile_menu.actions()])
        self.assertIn("Reset profile settings…", [action.text() for action in dialog.profile_menu.actions()])
        self.assertFalse(dialog.appearance.isHidden())
        dialog.tabs.setCurrentWidget(dialog.app_tab)
        self.assertFalse(dialog.scope.isHidden())
        self.assertFalse(dialog.scope_label.isHidden())
        self.assertEqual([dialog.app_navigation.topLevelItem(i).text(0)
                          for i in range(dialog.app_navigation.topLevelItemCount())],
                         ["Startup", "History", "Storage"])

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
        dialog.profile_group.toggle.click()
        dialog.search.setText("passage size")
        self.assertGreater(dialog.search_results.count(), 0)
        dialog.open_search_result(dialog.search_results.item(0))
        self.app.processEvents()
        self.assertIs(dialog.tabs.currentWidget(), dialog.translation_tab)
        self.assertFalse(dialog.translation_chunk_size.isHidden())
        self.assertTrue(dialog.translation_chunk_size.isVisibleTo(dialog.translation_tab))
        self.assertTrue(dialog.profile_group.toggle.isChecked())
        self.assertEqual(dialog.geometry(), geometry)

    def test_groups_collapse_independently_and_preserve_page_and_geometry(self):
        self.settings.setValue("settings/page", "General")
        dialog = self.dialog()
        dialog.show()
        self.app.processEvents()
        self.assertIs(dialog.tabs.currentWidget(), dialog.app_tab)
        geometry = dialog.geometry()
        profile_layout = dialog.scope.parentWidget().layout()
        row = profile_layout.itemAt(0).geometry()
        self.assertEqual(dialog.navigation.geometry().top() - row.bottom() - 1, profile_layout.spacing())
        sidebar_width = dialog.scope.parentWidget().parentWidget().width()
        dialog.app_group.toggle.click()
        self.assertTrue(dialog.profile_group.toggle.isChecked())
        dialog.profile_group.toggle.click()
        self.app.processEvents()
        self.assertIs(dialog.tabs.currentWidget(), dialog.app_tab)
        self.assertEqual(dialog.geometry(), geometry)
        self.assertEqual(dialog.scope.parentWidget().parentWidget().width(), sidebar_width)
        dialog.rebuild_profiles()
        self.assertFalse(dialog.app_group.toggle.isChecked())
        self.assertFalse(dialog.profile_group.toggle.isChecked())
        reopened = self.dialog()
        self.assertIs(reopened.tabs.currentWidget(), reopened.app_tab)
        self.assertFalse(reopened.app_group.toggle.isChecked())
        self.assertFalse(reopened.profile_group.toggle.isChecked())

    def test_app_resets_only_change_the_selected_section(self):
        other = create_profile(self.settings, "ja", "Other")
        self.settings.setValue("initial_profile", other)
        self.settings.setValue("history/enabled", True)
        self.settings.setValue("history/delay", 3.0)
        self.settings.setValue("history/retention", 90)
        dialog = self.dialog()
        dialog.tabs.setCurrentWidget(dialog.app_tab)
        self.assertEqual(dialog.reset_button.text(), "Reset Startup…")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes) as question:
            dialog.restore_page_defaults()
        self.assertEqual(question.call_args.args[2],
                         "Reset Startup?\n\nEnabled features, connections and saved data are kept.")
        self.assertEqual(dialog.initial_profile.currentData(), "")
        self.assertEqual(self.settings.value("history/delay", 0, float), 3.0)
        self.settings.setValue("initial_profile", other)
        dialog.tabs.setCurrentWidget(dialog.history_tab)
        self.assertEqual(dialog.reset_button.text(), "Reset History…")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            dialog.restore_page_defaults()
        self.assertEqual(self.settings.value("initial_profile"), other)
        self.assertEqual(dialog.history_settings.delay.value(), 0.5)
        self.assertEqual(dialog.history_settings.retention.currentData(), 0)
        self.assertTrue(dialog.history_settings.checks["enabled"].isChecked())
        dialog.tabs.setCurrentWidget(dialog.data_tab)
        self.assertTrue(dialog.reset_button.isHidden())
        with patch.object(QMessageBox, "question") as question:
            dialog.restore_page_defaults()
        question.assert_not_called()

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
        self.assertFalse(dialog.scope.isHidden())

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

    def test_inactive_profile_popup_shortcuts_do_not_refresh_active_runtime(self):
        from wordcel.gui.quick_lookup import QuickLookupWindow
        window = QuickLookupWindow(self.root / "library", settings=self.settings)
        self.addCleanup(window.deleteLater)
        self.addCleanup(window.shutdown)
        other = create_profile(self.settings, "ja", "Other", duplicate="ja")
        dialog = SetupDialog(self.root / "library", self.settings, Mock(), window)
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.audio_sources.shutdown)
        dialog.rebuild_profiles(other)
        with patch.object(window, "reload_popup_shortcuts") as reload_keys, \
                patch.object(window, "update_anki") as update_anki:
            dialog.save_popup_shortcuts()
        reload_keys.assert_not_called()
        update_anki.assert_not_called()
        self.assertEqual(window.active_profile, "ja")

    def test_unavailable_translation_shortcut_can_still_be_disabled(self):
        self.settings.setValue("profiles/ja/translation_hotkey", "<alt>+t")
        with patch("wordcel.gui.resources.profile_translation_available", return_value=False):
            dialog = self.dialog()
        self.assertTrue(dialog.translation_shortcut.enabled.isEnabled())
        dialog.translation_shortcut.enabled.setChecked(False)
        self.assertEqual(self.settings.value("profiles/ja/translation_hotkey"), "")
