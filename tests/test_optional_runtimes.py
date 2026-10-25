import hashlib
import io
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from wordcel import optional_runtimes as engines


class OptionalRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as wheel:
            wheel.writestr("fixture_engine/__init__.py", "VALUE = 42\n")
            wheel.writestr("fixture_engine-1.0.dist-info/METADATA", "Name: fixture-engine\nVersion: 1.0\n")
        self.wheel = archive.getvalue()
        self.descriptor = {"name": "fixture-engine", "version": "1.0", "url": "https://example.invalid/fixture.whl",
                           "sha256": hashlib.sha256(self.wheel).hexdigest()}
        self.config = {"schema": 1, "platform": "fixture", "python": "3.12", "features": {"stanza": [self.descriptor]}}
        self.enterContext(patch.object(engines, "manifest", return_value=self.config))
        self.enterContext(patch("wordcel.utils.paths.paths", SimpleNamespace(data_dir=self.root / "data", cache_dir=self.root / "cache")))
        self.enterContext(patch("sys.frozen", True, create=True))
        self.enterContext(patch.object(engines, "activate"))
        self.validate = self.enterContext(patch.object(engines, "validate"))
        self.cancelled = threading.Event()

    def test_installs_verified_wheel_once_and_preserves_other_data(self):
        with patch.object(engines, "urlopen", side_effect=lambda *a, **k: io.BytesIO(self.wheel)) as request:
            engines.install("stanza", cancelled=self.cancelled)
            engines.install("stanza", cancelled=self.cancelled)
        self.assertEqual(request.call_count, 1)
        self.assertTrue(engines.ready("stanza"))
        self.assertEqual((engines.runtime_root("stanza") / "site/fixture_engine/__init__.py").read_text(), "VALUE = 42\n")

    def test_bad_download_never_activates(self):
        with patch.object(engines, "urlopen", return_value=io.BytesIO(b"corrupt")), self.assertRaisesRegex(ValueError, "checksum"):
            engines.install("stanza", cancelled=self.cancelled)
        self.assertFalse(engines.ready("stanza"))
        self.assertFalse(list((self.root / "cache").rglob("*.part")))

    def test_cancelled_extraction_keeps_runtime_unpublished_and_verified_cache(self):
        def progress(text):
            if text.startswith("Installing"):
                self.cancelled.set()
        with patch.object(engines, "urlopen", return_value=io.BytesIO(self.wheel)), self.assertRaises(InterruptedError):
            engines.install("stanza", progress, self.cancelled)
        self.assertFalse(engines.ready("stanza"))
        self.assertTrue(list((self.root / "cache").rglob("*.whl")))
        self.cancelled.clear()
        with patch.object(engines, "urlopen", side_effect=AssertionError("Verified cache should be reused")):
            engines.install("stanza", cancelled=self.cancelled)
        self.assertTrue(engines.ready("stanza"))

    def test_manifest_change_selects_a_new_engine_directory(self):
        original = engines.runtime_root("stanza")
        self.descriptor["version"] = "2.0"
        self.assertNotEqual(original, engines.runtime_root("stanza"))

    def test_failed_engine_validation_does_not_publish(self):
        self.validate.side_effect = RuntimeError("Cannot load engine")
        with patch.object(engines, "urlopen", return_value=io.BytesIO(self.wheel)), self.assertRaises(RuntimeError):
            engines.install("stanza", cancelled=self.cancelled)
        self.assertFalse(engines.ready("stanza"))

    def test_wheel_rejects_escape_paths_and_relocates_purelib(self):
        for name in ("../escape.py", "/escape.py", "C:/escape.py", "folder\\escape.py", "folder/CON.txt"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                engines.safe_member(name)
            if "\\" in name:
                continue  # ZipInfo normalizes the host separator when writing on Windows.
            archive = io.BytesIO()
            with zipfile.ZipFile(archive, "w") as wheel:
                wheel.writestr(name, "bad")
            archive.seek(0)
            with self.subTest(name=name), self.assertRaises(ValueError):
                engines.extract_wheel(archive, self.root / "site")
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as wheel:
            wheel.writestr("fixture.data/purelib/fixture.py", "okay")
            wheel.writestr("fixture.data/scripts/ignored.exe", "ignored")
        archive.seek(0)
        engines.extract_wheel(archive, self.root / "site")
        self.assertEqual((self.root / "site/fixture.py").read_text(), "okay")
        self.assertFalse((self.root / "site/ignored.exe").exists())

    def test_settings_setup_installs_engine_before_model_worker(self):
        from wordcel.scripts.setup_morphology import install
        calls = []
        with patch.object(engines, "install", side_effect=lambda *args: calls.append("engine")), \
                patch("wordcel.scripts.setup_morphology._run", side_effect=lambda *args: calls.append("model")):
            install("ru")
        self.assertEqual(calls, ["engine", "model"])
