import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication

from wordcel.config.inheritance import PreferenceSettings, migrate_defaults, overridden, set_override
from wordcel.config.profiles import create_profile


class PreferenceInheritanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.raw = QSettings(str(self.root / "settings.ini"), QSettings.Format.IniFormat)
        self.raw.setValue("profiles_version", 1)
        self.raw.setValue("profile", "ja")
        self.raw.setValue("profiles/ja/language", "ja")
        self.raw.setValue("profiles/ja/font_size_header", 24)
        self.raw.setValue("profiles/ja/hotkey", "")
        self.raw.setValue("profiles/tr/language", "tr")
        self.raw.setValue("profiles/tr/font_size_header", 30)
        migrate_defaults(self.raw)
        self.settings = PreferenceSettings(self.raw)

    def test_conversion_preserves_differences_and_is_idempotent(self):
        self.assertFalse(overridden(self.settings, "ja", "appearance"))
        self.assertTrue(overridden(self.settings, "tr", "appearance"))
        before = {key: self.raw.value(key) for key in self.raw.allKeys()}
        migrate_defaults(self.settings)
        self.assertEqual(before, {key: self.raw.value(key) for key in self.raw.allKeys()})
        self.raw.setValue("defaults/appearance/font_size_header", 28)
        self.assertEqual(self.settings.value("profiles/ja/font_size_header", 0, int), 28)
        self.assertEqual(self.settings.value("profiles/tr/font_size_header", 0, int), 30)

    def test_snapshot_and_restore_custom_values_across_restart(self):
        self.raw.setValue("defaults/appearance/font_size_header", 28)
        set_override(self.settings, "ja", "appearance", True)
        self.assertEqual(self.settings.value("profiles/ja/font_size_header", 0, int), 28)
        self.settings.setValue("profiles/ja/font_size_header", 32)
        set_override(self.settings, "ja", "appearance", False)
        self.raw.setValue("defaults/appearance/font_size_header", 20)
        self.assertEqual(self.settings.value("profiles/ja/font_size_header", 0, int), 20)
        self.raw.sync()
        reopened = PreferenceSettings(QSettings(self.raw.fileName(), QSettings.Format.IniFormat))
        set_override(reopened, "ja", "appearance", True)
        self.assertEqual(reopened.value("profiles/ja/font_size_header", 0, int), 32)

    def test_new_profiles_inherit_and_duplicate_preserves_overrides(self):
        fresh = create_profile(self.settings, "ja")
        self.assertFalse(overridden(self.settings, fresh, "appearance"))
        self.assertEqual(self.settings.value(f"profiles/{fresh}/font_size_header", 0, int), 24)
        duplicate = create_profile(self.settings, "tr", duplicate="tr")
        self.assertTrue(overridden(self.settings, duplicate, "appearance"))
        self.settings.setValue(f"profiles/{duplicate}/font_size_header", 40)
        self.assertEqual(self.settings.value("profiles/tr/font_size_header", 0, int), 30)

    def test_shortcuts_resolve_without_overwriting_retained_custom_bindings(self):
        from wordcel.gui.popup_shortcuts import popup_bindings
        set_override(self.settings, "ja", "shortcuts", True)
        self.settings.setValue("profiles/ja/popup/copy_shortcut", "Alt+C")
        set_override(self.settings, "ja", "shortcuts", False)
        self.settings.setValue("profiles/ja/popup/copy_shortcut", "Shift+C")
        self.assertEqual(popup_bindings(self.settings, "ja")["copy"], "Shift+C")
        set_override(self.settings, "ja", "shortcuts", True)
        self.assertEqual(popup_bindings(self.settings, "ja")["copy"], "Alt+C")
        self.assertEqual(self.settings.value("profiles/ja/hotkey"), "")

    def test_group_disclosure_and_global_navigation_reuse_panels(self):
        from wordcel.gui.dictionary_manager import SetupDialog
        dialog = SetupDialog(self.root / "library", self.settings, Mock())
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.audio_sources.shutdown)
        dialog.show()
        self.app.processEvents()
        inherit, content = dialog.preference_groups.controls["appearance"]
        self.assertTrue(inherit.isChecked())
        self.assertFalse(content.isEnabled())
        size = dialog.size()
        with patch.object(dialog, "reload") as reload_library:
            inherit.setChecked(False)
            self.app.processEvents()
            reload_library.assert_not_called()
        self.assertTrue(content.isEnabled())
        dialog.appearance.controls["font_size_header"].setValue(35)
        inherit.setChecked(True)
        self.assertFalse(content.isEnabled())
        dialog.scope.setCurrentIndex(0)
        dialog.tabs.setCurrentWidget(dialog.popup_tab)
        self.assertEqual(dialog.settings.editing_global, "popup_all")
        self.assertTrue(inherit.isHidden())
        self.assertTrue(content.isEnabled())
        dialog.appearance.controls["font_size_header"].setValue(22)
        self.assertEqual(self.raw.value("defaults/appearance/font_size_header", 0, int), 22)
        dialog.scope.setCurrentIndex(dialog.scope.findData("ja"))
        inherit.setChecked(False)
        self.assertEqual(dialog.appearance.controls["font_size_header"].value(), 35)
        self.assertEqual(dialog.size(), size)
        self.assertEqual(self.raw.value("profile"), "ja")

    def test_global_shortcut_validation_and_reopening_preserve_scope(self):
        from wordcel.gui.dictionary_manager import SetupDialog
        dialog = SetupDialog(self.root / "library", self.settings, Mock())
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.audio_sources.shutdown)
        dialog.scope.setCurrentIndex(0)
        dialog.tabs.setCurrentWidget(dialog.shortcuts_tab)
        self.raw.setValue("next_profile_hotkey", "<ctrl>+<f9>")
        with self.assertRaises(ValueError):
            dialog.validate_text_binding("hotkey", "<ctrl>+<f9>")
        dialog.rebuild_profiles()
        self.assertEqual(dialog.settings.editing_global, "shortcuts")
        self.assertTrue(dialog.profile_details.isHidden())
        self.assertIs(dialog.tabs.currentWidget(), dialog.shortcuts_tab)
        self.assertTrue(dialog.scan_key.isEnabled())

    def test_popup_scope_search_and_profile_switch_keep_custom_values(self):
        from wordcel.gui.dictionary_manager import SetupDialog
        dialog = SetupDialog(self.root / "library", self.settings, Mock())
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.audio_sources.shutdown)
        dialog.show()
        dialog.tabs.setCurrentWidget(dialog.popup_tab)
        dialog.scope.setCurrentIndex(dialog.scope.findData("tr"))
        self.assertIs(dialog.tabs.currentWidget(), dialog.popup_tab)
        self.assertEqual(dialog.appearance.controls["font_size_header"].value(), 30)
        dialog.scope.setCurrentIndex(0)
        dialog.appearance.controls["font_size_header"].setValue(26)
        dialog.close_on_cursor_leave.setChecked(True)
        self.assertEqual(self.raw.value("defaults/appearance/font_size_header", 0, int), 26)
        self.assertTrue(self.raw.value("defaults/popup/close_on_cursor_leave", False, bool))
        self.assertEqual(self.raw.value("profiles/tr/font_size_header", 0, int), 30)
        dialog.scope.setCurrentIndex(dialog.scope.findData("tr"))
        self.assertEqual(dialog.appearance.controls["font_size_header"].value(), 30)
        self.assertEqual(self.raw.value("profile"), "ja")
        dialog.tabs.setCurrentWidget(dialog.lookup_tab)
        self.assertFalse(dialog.screen_section.toggle.isVisible())
        self.assertTrue(dialog.current_ocr_control().isVisible())
        dialog.search.setText("definitions")
        self.assertGreater(dialog.search_results.count(), 0)
        result = dialog.search_results.item(0)
        self.assertIn("Popup", result.text())
        dialog.open_search_result(result)
        self.assertIs(dialog.tabs.currentWidget(), dialog.popup_tab)
        self.assertEqual(dialog.search.text(), "")
        self.assertEqual(self.raw.value("settings/page"), "Popup")
        dialog.scope.setCurrentIndex(0)
        self.assertTrue(dialog.appearance.action_controls["translate"].isEnabled())
        reopened = SetupDialog(self.root / "library", self.settings, Mock())
        self.addCleanup(reopened.deleteLater)
        self.addCleanup(reopened.audio_sources.shutdown)
        self.assertEqual(reopened.scope.currentData(), "shared")
        self.assertEqual(reopened.settings.editing_global, "popup_all")
        self.assertIs(reopened.tabs.currentWidget(), reopened.popup_tab)


if __name__ == "__main__":
    unittest.main()
