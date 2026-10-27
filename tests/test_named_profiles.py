import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtWidgets import QApplication

from wordcel.config.profiles import (create_profile, delete_profile, dictionary_preferences, migrate,
                                     profile_ids, profile_language, profile_name)
from wordcel.dictionary.library import Library, import_yomitan, save_preferences
from wordcel.dictionary.translation import TranslationSettings, load_profile_settings, save_profile_settings


class NamedProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.settings = QSettings(str(self.root / "settings.ini"), QSettings.Format.IniFormat)
        self.directory = self.root / "library"
        archive = self.root / "words.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("index.json", json.dumps(dict(title="Words", format=3, sourceLanguage="ja")))
            bundle.writestr("term_bank_1.json", json.dumps([["猫", "ねこ", "", "", 0, ["cat"]]]))
        self.pack = import_yomitan(archive, self.directory)
        self.settings.setValue("profile", "ja")
        self.settings.setValue("profiles/ja/target", "en")
        self.settings.setValue("profiles/ja/theme_name", "Light")
        self.settings.setValue("profiles/ja/collapsed_dictionaries", ["Words"])

    def test_conversion_is_backed_up_idempotent_and_preserves_distinct_connections(self):
        self.settings.setValue("hotkey", "<ctrl>+d")
        self.settings.setValue("profiles/tr/target", "en")
        self.settings.setValue("profiles/ja/anki/endpoint", "http://127.0.0.1:8765")
        self.settings.setValue("profiles/tr/anki/endpoint", "http://127.0.0.1:8767")
        save_profile_settings(self.settings, "ja", TranslationSettings(provider="custom", model="one"))
        save_profile_settings(self.settings, "tr", TranslationSettings(provider="custom", model="two", endpoint="http://127.0.0.1:9000/v1"))
        save_preferences(self.directory, [self.pack.name], [self.pack.name])
        migrate(self.settings, self.directory)
        before = {key: self.settings.value(key) for key in self.settings.allKeys()}
        migrate(self.settings, self.directory)
        self.assertEqual(before, {key: self.settings.value(key) for key in self.settings.allKeys()})
        self.assertTrue((self.root / "settings.ini.profiles-backup.ini").exists())
        self.assertEqual(profile_language(self.settings, "ja"), "ja")
        self.assertEqual(self.settings.value("profiles/tr/hotkey"), "<ctrl>+d")
        self.assertEqual(load_profile_settings(self.settings, "tr").model, "two")
        self.assertNotEqual(self.settings.value("profiles/ja/anki/connection"), self.settings.value("profiles/tr/anki/connection"))
        self.assertTrue(dictionary_preferences(self.settings, "ja")["disabled"])
        self.assertNotEqual(self.settings.value("profiles/ja/collapsed_dictionaries"), ["Words"])
        self.assertEqual(self.settings.value("initial_profile", ""), "")

    def test_startup_profile_defaults_to_last_used_and_preserves_selection(self):
        from wordcel.gui.dictionary_manager import SetupDialog
        migrate(self.settings, self.directory)
        duplicate = create_profile(self.settings, "ja", "Anime")
        dialog = SetupDialog(self.directory, self.settings, Mock())
        self.addCleanup(dialog.deleteLater)
        self.assertEqual(dialog.initial_profile.currentText(), "Last used")
        dialog.initial_profile.setCurrentIndex(dialog.initial_profile.findData(duplicate))
        dialog.rebuild_profiles()
        self.assertEqual(self.settings.value("initial_profile"), duplicate)
        self.assertEqual(dialog.initial_profile.currentData(), duplicate)
        dialog.initial_profile.setCurrentIndex(0)
        self.assertEqual(self.settings.value("initial_profile"), "")

    def test_duplicate_and_delete_share_files_but_settings_are_independent(self):
        migrate(self.settings, self.directory)
        duplicate = create_profile(self.settings, "ja", "Anime", duplicate="ja")
        self.settings.setValue(f"profiles/{duplicate}/theme_name", "Dark")
        self.settings.setValue(f"profiles/{duplicate}/name", "Renamed")
        self.assertEqual(profile_language(self.settings, duplicate), "ja")
        self.assertIn(duplicate, profile_ids(self.settings))
        self.assertEqual(self.settings.value("profiles/ja/theme_name"), "Light")
        self.assertEqual(len(list(self.directory.glob("*.sqlite3"))), 1)
        self.settings.setValue("profile", duplicate)
        self.assertEqual(delete_profile(self.settings, duplicate), "ja")
        self.assertTrue(self.pack.exists())

    def test_editing_does_not_activate_and_activation_invalidates_requests(self):
        from wordcel.gui.quick_lookup import QuickLookupWindow
        from wordcel.gui.dictionary_manager import SetupDialog
        window = QuickLookupWindow(self.directory, settings=self.settings)
        self.addCleanup(window.deleteLater)
        self.addCleanup(window.shutdown)
        duplicate = create_profile(self.settings, "ja", "Anime", duplicate="ja")
        window.update_languages()
        dialog = SetupDialog(self.directory, self.settings, Mock(), window)
        window._setup = dialog
        self.addCleanup(dialog.deleteLater)
        dialog.sync_profile(duplicate)
        dialog.appearance.theme.setCurrentText("Dark")
        self.assertEqual(window.active_profile, "ja")
        self.assertEqual(self.settings.value("profiles/ja/theme_name"), "Light")
        revision = window.revision
        dialog.activate_profile()
        self.assertEqual(window.active_profile, duplicate)
        self.assertEqual(window.preferred_foreign, "ja")
        self.assertGreater(window.revision, revision)
        dialog.sync_profile("ja")
        self.assertEqual(window.active_profile, duplicate)

    def test_reopening_global_settings_preserves_page_and_hides_profile_details(self):
        from wordcel.gui.dictionary_manager import SetupDialog
        migrate(self.settings, self.directory)
        duplicate = create_profile(self.settings, "ja", "Anime", duplicate="ja")
        dialog = SetupDialog(self.directory, self.settings, Mock())
        self.addCleanup(dialog.deleteLater)
        for page in (dialog.app_tab, dialog.history_tab, dialog.data_tab):
            for identity in ("ja", duplicate):
                with self.subTest(page=dialog.tabs.indexOf(page), profile=identity):
                    item = next(dialog.navigation.topLevelItem(i) for i in range(dialog.navigation.topLevelItemCount())
                                if dialog.navigation.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole) == (None, dialog.tabs.indexOf(page)))
                    dialog.navigation.setCurrentItem(item)
                    dialog.close()
                    dialog.sync_profile(identity)
                    self.assertIs(dialog.navigation.currentItem(), item)
                    self.assertIs(dialog.tabs.currentWidget(), page)
                    self.assertTrue(dialog.profile_details.isHidden())
                    self.assertEqual(dialog.profile.currentData(), identity)
        dialog.navigation.setCurrentItem(dialog.navigation.topLevelItem(0))
        self.assertIs(dialog.tabs.currentWidget(), dialog.lookup_tab)
        self.assertFalse(dialog.profile_details.isHidden())

    def test_usage_follows_profile_dictionary_choices_and_external_resources(self):
        from wordcel.data_assets import inventory, resource_usage, DataAsset
        migrate(self.settings, self.directory)
        duplicate = create_profile(self.settings, "ja", duplicate="ja")
        assets = inventory(self.directory, ("ja",), data_root=self.root / "data", cache_root=self.root / "cache")
        asset = next(asset for asset in assets if asset.kind == "dictionary")
        self.assertEqual(set(resource_usage(self.settings, asset)), {"ja", duplicate})
        self.settings.setValue(f"profiles/{duplicate}/dictionaries/disabled", [asset.identity])
        self.assertEqual(resource_usage(self.settings, asset), ("ja",))
        external = DataAsset("external", "Linked", kind="external", removable=False)
        self.assertFalse(external.removable)

    def test_translation_availability_preserves_choice_and_custom_server_needs_no_download(self):
        from wordcel.gui.resources import managed_translation_available, profile_translation_available
        migrate(self.settings, self.directory)
        save_profile_settings(self.settings, "ja", TranslationSettings(profile="quality"))
        with patch("wordcel.gui.resources.translation_ready", side_effect=lambda name: name == "lightweight"):
            managed_translation_available.cache_clear()
            self.assertFalse(profile_translation_available(self.settings, "ja"))
        with patch("wordcel.gui.resources.translation_ready", return_value=True):
            managed_translation_available.cache_clear()
            self.assertTrue(profile_translation_available(self.settings, "ja"))
        with patch("wordcel.gui.resources.translation_ready", return_value=False):
            managed_translation_available.cache_clear()
            self.assertFalse(profile_translation_available(self.settings, "ja"))
            save_profile_settings(self.settings, "ja", TranslationSettings(provider="custom", model="offline"))
            self.assertTrue(profile_translation_available(self.settings, "ja"))
        managed_translation_available.cache_clear()


if __name__ == "__main__":
    unittest.main()
