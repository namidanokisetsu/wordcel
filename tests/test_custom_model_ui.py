import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication
from wordcel.gui.translation_models import ModelDialog
from wordcel.gui.setup_operation import SetupOperation, SetupRequest


class CustomModelUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_repository_results_are_revision_scoped_and_selection_is_explicit(self):
        dialog = ModelDialog(None)
        self.addCleanup(dialog.deleteLater)
        spec = dict(file="custom.gguf", source_file="model-IQ2_XS.gguf", size=100, sha256="a" * 64)
        with patch.object(dialog.worker, "find") as find:
            dialog.repository.setText("owner/models")
            dialog.find_files()
            find.assert_called_once_with(dialog.revision, "owner/models")
        self.assertFalse(dialog.download.isEnabled())
        dialog.show_files(dialog.revision - 1, [spec], "")
        self.assertEqual(dialog.files.count(), 0)
        dialog.show_files(dialog.revision, [spec], "")
        self.assertEqual(dialog.selection, spec)
        self.assertTrue(dialog.download.isEnabled())
        dialog.invalidate()
        self.assertFalse(dialog.download.isEnabled())

    def test_local_file_hashing_and_installation_stay_on_setup_worker(self):
        operation = SetupOperation(SetupRequest("custom_model", {"local_path": "/fixture/model.gguf"}), "/unused")
        self.addCleanup(operation.deleteLater)
        digest = hashlib.sha256(b"GGUFfixture").hexdigest()
        spec = {"sha256": digest}
        with patch("wordcel.translation_models.local_model", return_value=spec) as describe, \
                patch("wordcel.scripts.translation_server.install_model") as install:
            operation._run()
        describe.assert_called_once_with("/fixture/model.gguf", operation.cancelled)
        self.assertEqual(install.call_args.kwargs["profile"], "gguf:" + digest)
        self.assertEqual(install.call_args.kwargs["local_model"], "/fixture/model.gguf")
        self.assertEqual(operation.resource, "translation")

    def test_model_added_to_recommendations_without_changing_saved_choice(self):
        from wordcel.gui.dictionary_manager import SetupDialog
        from wordcel.translation_catalog import MODELS
        identity = "gguf:" + "a" * 64
        catalog = dict(MODELS, **{identity: dict(name="Model IQ2_XS", size=100, source="hf", file="custom-" + "a" * 64 + ".gguf")})
        with tempfile.TemporaryDirectory() as directory:
            settings = QSettings(str(Path(directory) / "settings.ini"), QSettings.Format.IniFormat)
            settings.setValue("profiles/ja/target", "en")
            with patch("wordcel.translation_models.model_catalog", return_value=catalog), \
                    patch("wordcel.dictionary.translation.model_installed", return_value=False):
                dialog = SetupDialog(directory, settings, Mock())
                self.addCleanup(dialog.deleteLater)
                original = dialog.translation_mode.currentData()
                self.assertGreaterEqual(dialog.translation_mode.findData(identity), 0)
                dialog.reload_translation_models()
                self.assertEqual(dialog.translation_mode.currentData(), original)
                dialog.translation_mode.setCurrentIndex(dialog.translation_mode.findData(identity))
                from wordcel.dictionary.translation import load_profile_settings
                self.assertEqual(load_profile_settings(settings, "ja").profile, identity)
                self.assertTrue(dialog.translation_endpoint.isHidden())
                self.assertFalse(dialog.resources.model_rows[identity].isHidden())

    def test_resource_suggestions_preserve_saved_custom_model(self):
        from PyQt6.QtWidgets import QWidget
        from wordcel.gui.first_run import LanguageSuggestion
        from wordcel.dictionary.translation import TranslationSettings, save_profile_settings
        from wordcel.translation_catalog import MODELS
        identity = "gguf:" + "a" * 64
        catalog = dict(MODELS, **{identity: dict(name="My GGUF", size=100, source="hf", file="custom.gguf")})
        with tempfile.TemporaryDirectory() as directory:
            window = QWidget()
            self.addCleanup(window.deleteLater)
            window.settings = QSettings(str(Path(directory) / "settings.ini"), QSettings.Format.IniFormat)
            window.directory, window.preferred_foreign = directory, "ja"
            save_profile_settings(window.settings, "ja", TranslationSettings(profile=identity))
            with patch("wordcel.translation_models.model_catalog", return_value=catalog), \
                    patch("wordcel.gui.resources.translation_ready", return_value=False), \
                    patch("wordcel.gui.resources.ocr_ready", return_value=False):
                dialog = LanguageSuggestion(window)
                self.addCleanup(dialog.deleteLater)
                self.assertEqual(dialog.translation.currentData(), identity)

    def test_storage_repairs_local_models_through_import(self):
        from wordcel.data_assets import DataAsset
        from wordcel.gui.data_manager import DataPanel
        panel = Mock()
        asset = DataAsset("translation:fixture", "Local model", kind="translation", value="gguf:" + "a" * 64, origin="local")
        DataPanel._download(panel, asset)
        panel.owner.import_translation_model.assert_called_once_with()
        panel.owner.begin_operation.assert_not_called()

    def test_late_capabilities_ignore_a_removed_settings_profile(self):
        from wordcel.config.profiles import create_profile
        from wordcel.gui.dictionary_manager import SetupDialog
        from wordcel.translation_hardware import Capabilities
        with tempfile.TemporaryDirectory() as directory:
            settings = QSettings(str(Path(directory) / "settings.ini"), QSettings.Format.IniFormat)
            identity = create_profile(settings, "ja")
            settings.setValue("profile", identity)
            dialog = SetupDialog(directory, settings, Mock())
            self.addCleanup(dialog.deleteLater)
            settings.remove(f"profiles/{identity}/language")
            with patch.object(dialog.resources, "refresh_translation") as refresh:
                dialog.prepared_translation(Capabilities(memory=8 * 1024**3), set())
                refresh.assert_not_called()
            settings.clear()
            with patch.object(dialog, "update_translation_languages") as refresh:
                dialog.prepared_translation(Capabilities(memory=8 * 1024**3), set())
                refresh.assert_not_called()
