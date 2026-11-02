import json
import os
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import QSettings

from wordcel.config.inheritance import migrate_defaults
from wordcel.config.profiles import (create_profile, ensure_private_connection, reset_app_page,
                                     reset_page, reset_profile)


class IndependentProfileSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "settings.ini"
        self.settings = QSettings(str(self.path), QSettings.Format.IniFormat)
        self.settings.setValue("profile", "ja")
        self.settings.setValue("profile_order", ["ja", "tr"])
        self.settings.setValue("profiles/ja/language", "ja")
        self.settings.setValue("profiles/tr/language", "tr")

    def test_migration_materializes_effective_values_and_removes_legacy_scope(self):
        self.settings.setValue("defaults_version", 1)
        self.settings.setValue("defaults/appearance/font_size_header", 22)
        self.settings.setValue("defaults/appearance/custom/highlight", "")
        self.settings.setValue("defaults/shortcuts/popup/copy_shortcut", "")
        self.settings.setValue("profiles/ja/overrides/appearance", False)
        self.settings.setValue("profiles/ja/font_size_header", 99)
        self.settings.setValue("profiles/ja/custom/highlight", "stale")
        self.settings.setValue("profiles/tr/overrides/appearance", True)
        self.settings.setValue("profiles/tr/font_size_header", 31)
        self.settings.setValue("profiles/tr/pitch_colors", False)
        self.settings.setValue("profiles/tr/overrides/shortcuts", True)
        self.settings.setValue("profiles/tr/hotkey", "")

        self.assertTrue(migrate_defaults(self.settings))
        self.assertEqual(self.settings.value("profiles/ja/font_size_header", 0, int), 22)
        self.assertEqual(self.settings.value("profiles/ja/custom/highlight"), "")
        self.assertEqual(self.settings.value("profiles/tr/font_size_header", 0, int), 31)
        self.assertFalse(self.settings.value("profiles/tr/pitch_colors", True, bool))
        self.assertEqual(self.settings.value("profiles/tr/hotkey"), "")
        self.assertFalse(any(key.startswith("defaults/") for key in self.settings.allKeys()))
        self.assertFalse(any("/overrides/" in key for key in self.settings.allKeys()))

        before = {key: self.settings.value(key) for key in self.settings.allKeys()}
        self.assertFalse(migrate_defaults(self.settings))
        self.assertEqual(before, {key: self.settings.value(key) for key in self.settings.allKeys()})
        self.assertTrue((self.path.parent / "settings.ini.inheritance-backup.ini").exists())

    def test_migration_failure_does_not_mark_completion_and_keeps_backup(self):
        self.settings.setValue("defaults_version", 1)
        self.settings.setValue("defaults/appearance/font_size_header", 22)
        self.settings.setValue("profiles/ja/overrides/appearance", False)
        with patch("wordcel.config.inheritance._sync", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                migrate_defaults(self.settings)
        self.assertEqual(self.settings.value("defaults_version", 0, int), 1)
        backup = QSettings(str(self.path) + ".inheritance-backup.ini", QSettings.Format.IniFormat)
        self.assertEqual(backup.value("defaults/appearance/font_size_header", 0, int), 22)
        migrate_defaults(self.settings)
        self.assertEqual(self.settings.value("profiles/ja/font_size_header", 0, int), 22)

    def test_profile_settings_are_direct_after_migration(self):
        self.settings.setValue("defaults_version", 1)
        self.settings.setValue("defaults/appearance/font_size_header", 22)
        self.settings.setValue("profiles/ja/overrides/appearance", False)
        migrate_defaults(self.settings)
        self.settings.setValue("profiles/ja/font_size_header", 29)
        self.assertEqual(self.settings.value("profiles/ja/font_size_header", 0, int), 29)
        self.assertFalse(self.settings.contains("defaults/appearance/font_size_header"))

    def test_unversioned_defaults_do_not_override_local_values(self):
        self.settings.setValue("defaults/appearance/font_size_header", 22)
        self.settings.setValue("profiles/ja/font_size_header", 29)
        migrate_defaults(self.settings)
        self.assertEqual(self.settings.value("profiles/ja/font_size_header", 0, int), 29)

    def test_empty_versioned_defaults_remove_stale_local_values(self):
        self.settings.setValue("defaults_version", 1)
        self.settings.setValue("profiles/ja/audio_volume", 42)
        migrate_defaults(self.settings)
        self.assertFalse(self.settings.contains("profiles/ja/audio_volume"))

    def test_duplicate_clones_values_and_mutable_connection_records(self):
        self.settings.setValue("profiles/ja/theme_name", "Light")
        self.settings.setValue("profiles/ja/anki/enabled", True)
        self.settings.setValue("connections/anki/source/endpoint", "http://127.0.0.1:8765")
        self.settings.setValue("connections/anki/source/api_key", "secret")
        self.settings.setValue("profiles/ja/anki/connection", "source")

        duplicate = create_profile(self.settings, "ja", "Copy", duplicate="ja")
        copied_connection = self.settings.value(f"profiles/{duplicate}/anki/connection")
        self.assertNotEqual(copied_connection, "source")
        self.assertEqual(self.settings.value(f"connections/anki/{copied_connection}/api_key"), "secret")
        self.settings.setValue(f"profiles/{duplicate}/theme_name", "Dark")
        self.settings.setValue(f"connections/anki/{copied_connection}/api_key", "changed")
        self.assertEqual(self.settings.value("profiles/ja/theme_name"), "Light")
        self.assertEqual(self.settings.value("connections/anki/source/api_key"), "secret")
        self.assertEqual(self.settings.value("profile"), "ja")

    def test_connection_edit_detaches_shared_reference(self):
        self.settings.setValue("profiles/ja/anki/connection", "source")
        self.settings.setValue("profiles/tr/anki/connection", "source")
        self.settings.setValue("connections/anki/source/endpoint", "http://127.0.0.1:8765")
        private = ensure_private_connection(self.settings, "ja", "anki")
        self.assertNotEqual(private, "source")
        self.assertEqual(self.settings.value("profiles/tr/anki/connection"), "source")
        self.settings.setValue(f"connections/anki/{private}/endpoint", "http://127.0.0.1:9999")
        self.assertEqual(self.settings.value("connections/anki/source/endpoint"), "http://127.0.0.1:8765")

    def test_page_and_profile_resets_preserve_data_enablement_and_assignments(self):
        profile = "ja"
        self.settings.setValue(f"profiles/{profile}/language", "ja")
        self.settings.setValue(f"profiles/{profile}/name", "Japanese")
        self.settings.setValue(f"profiles/{profile}/selected_text", True)
        self.settings.setValue(f"profiles/{profile}/anki/enabled", True)
        self.settings.setValue(f"profiles/{profile}/anki/connection", "anki")
        self.settings.setValue(f"profiles/{profile}/translation_connection", "translation")
        self.settings.setValue(f"profiles/{profile}/audio_database", "/tmp/audio.db")
        self.settings.setValue(f"profiles/{profile}/hotkey", "")
        self.settings.setValue(f"profiles/{profile}/hotkey_preset", "Old")
        self.settings.setValue(f"profiles/{profile}/theme_name", "Custom")
        self.settings.setValue(f"profiles/{profile}/translation", json.dumps({
            "provider": "custom", "profile": "lightweight", "endpoint": "http://127.0.0.1:9999/v1",
            "model": "local", "stream": False, "keep_warm": True, "chunk_size": 300,
        }))
        self.settings.setValue("history/enabled", True)
        self.settings.setValue("history/delay", 3.0)
        self.settings.setValue("hover_scan/startup", True)

        reset_page(self.settings, profile, "Appearance")
        self.assertFalse(self.settings.contains(f"profiles/{profile}/theme_name"))
        reset_page(self.settings, profile, "Shortcuts")
        self.assertEqual(self.settings.value(f"profiles/{profile}/hotkey"), "")
        expected_preset = "Ctrl+Shift+D"
        self.assertEqual(self.settings.value(f"profiles/{profile}/hotkey_preset"), expected_preset)
        self.settings.setValue(f"profiles/{profile}/scan_bindings", "middle")
        reset_page(self.settings, profile, "Shortcuts")
        self.assertEqual(self.settings.value(f"profiles/{profile}/scan_bindings"), "middle")
        reset_page(self.settings, profile, "Translation")
        translation = json.loads(self.settings.value(f"profiles/{profile}/translation"))
        self.assertEqual((translation["provider"], translation["profile"], translation["endpoint"], translation["model"]),
                         ("custom", "lightweight", "http://127.0.0.1:9999/v1", "local"))
        self.assertEqual(translation["chunk_size"], 2000)

        reset_profile(self.settings, profile)
        self.assertEqual(self.settings.value(f"profiles/{profile}/language"), "ja")
        self.assertEqual(self.settings.value(f"profiles/{profile}/name"), "Japanese")
        self.assertTrue(self.settings.value(f"profiles/{profile}/selected_text", False, bool))
        self.assertTrue(self.settings.value(f"profiles/{profile}/anki/enabled", False, bool))
        self.assertEqual(self.settings.value(f"profiles/{profile}/anki/connection"), "anki")
        self.assertEqual(self.settings.value(f"profiles/{profile}/translation_connection"), "translation")
        self.assertEqual(self.settings.value(f"profiles/{profile}/audio_database"), "/tmp/audio.db")

        reset_app_page(self.settings, "General")
        self.assertTrue(self.settings.value("history/enabled", False, bool))
        self.assertFalse(self.settings.contains("history/delay"))
        self.assertTrue(self.settings.value("hover_scan/startup", False, bool))


if __name__ == "__main__":
    unittest.main()
