import json
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import QSettings

from wordcel.config.profiles import (APP_SHORTCUT_DEFAULTS, create_profile, ensure_private_connection,
                                     reset_app_page, reset_page, reset_profile)


class ProfilePreferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "settings.ini"
        self.settings = QSettings(str(self.path), QSettings.Format.IniFormat)
        self.settings.setValue("profile", "ja")
        self.settings.setValue("profile_order", ["ja", "tr"])
        self.settings.setValue("profiles/ja/language", "ja")
        self.settings.setValue("profiles/tr/language", "tr")

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

        self.settings.setValue("next_profile_hotkey", "<alt>+x")
        reset_app_page(self.settings, "Shortcuts")
        self.assertEqual(self.settings.value("next_profile_hotkey"), APP_SHORTCUT_DEFAULTS["next_profile_hotkey"])
        reset_app_page(self.settings, "General")
        self.assertTrue(self.settings.value("history/enabled", False, bool))
        self.assertFalse(self.settings.contains("history/delay"))
        self.assertTrue(self.settings.value("hover_scan/startup", False, bool))


if __name__ == "__main__":
    unittest.main()
