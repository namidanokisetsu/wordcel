from contextlib import closing
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

from wordcel.dictionary.library import Library, import_yomitan
from wordcel.resource_bundle import export_bundle, import_bundle


class ResourceBundleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source, self.destination = self.root / "source", self.root / "destination"
        self.archive = self.root / "resources.zip"
        self.cancelled = threading.Event()
        dictionary = self.root / "words.zip"
        with zipfile.ZipFile(dictionary, "w") as bundle:
            bundle.writestr("index.json", json.dumps({"title": "Words", "format": 3, "sourceLanguage": "en"}))
            bundle.writestr("term_bank_1.json", json.dumps([["word", "", "", "", 0, ["meaning"]]]))
        self.pack = import_yomitan(dictionary, self.source / "library")
        self.runtime = self.source / "data/translation/runtime-fixture/llama-server.exe"
        self.runtime.parent.mkdir(parents=True)
        self.runtime.write_bytes(b"fixture")
        (self.source / "data/settings.json").write_text("private settings")
        self.export()

    def kwargs(self, root):
        return dict(data_root=root / "data", cache_root=root / "cache")

    def export(self, progress=lambda text: None):
        export_bundle(self.archive, self.source / "library", progress, self.cancelled, **self.kwargs(self.source))

    def restore(self):
        import_bundle(self.archive, self.destination / "library", lambda text: None, self.cancelled, **self.kwargs(self.destination))

    def rewrite(self, transform):
        with zipfile.ZipFile(self.archive) as bundle:
            files = {item.filename: bundle.read(item) for item in bundle.infolist()}
        transform(files)
        with zipfile.ZipFile(self.archive, "w") as bundle:
            for name, data in files.items():
                bundle.writestr(name, data)

    def test_round_trip_without_network_preserves_dictionary_and_runtime(self):
        with patch("urllib.request.urlopen", side_effect=AssertionError("Offline import must not download")):
            self.restore()
            self.restore()
        with closing(Library(self.destination / "library")) as library:
            self.assertEqual(library.packs[0][1]["title"], "Words")
        self.assertEqual((self.destination / "data/translation/runtime-fixture/llama-server.exe").read_bytes(), b"fixture")
        self.assertFalse((self.destination / "data/settings.json").exists())

    def test_corrupt_resource_does_not_publish_any_files(self):
        def corrupt(files):
            key = next(name for name in files if name != "manifest.json")
            files[key] = b"x" * len(files[key])
        self.rewrite(corrupt)
        with self.assertRaisesRegex(ValueError, "checksum"):
            self.restore()
        self.assertFalse(list(self.destination.rglob("*.sqlite3")))
        self.assertFalse(list(self.destination.rglob("llama-server.exe")))

    def test_existing_different_data_is_preserved(self):
        existing = self.destination / "data/translation/runtime-fixture/llama-server.exe"
        existing.parent.mkdir(parents=True)
        existing.write_bytes(b"keep")
        with self.assertRaisesRegex(ValueError, "already installed"):
            self.restore()
        self.assertEqual(existing.read_bytes(), b"keep")
        self.assertFalse(list((self.destination / "library").glob("*.sqlite3")))

    def test_cancelled_export_preserves_previous_archive(self):
        original = self.archive.read_bytes()
        self.cancelled.set()
        with self.assertRaises(InterruptedError):
            self.export()
        self.assertEqual(self.archive.read_bytes(), original)

    def test_wrong_platform_and_path_traversal_are_rejected(self):
        for update in (lambda m: m.update(platform="other"), lambda m: m["units"][0].update(path="../escape")):
            self.export()
            def change(files):
                manifest = json.loads(files["manifest.json"])
                update(manifest)
                files["manifest.json"] = json.dumps(manifest).encode()
            self.rewrite(change)
            with self.assertRaises(ValueError):
                self.restore()
        self.assertFalse((self.root / "escape").exists())

    def test_unlisted_files_are_rejected_before_commit(self):
        self.rewrite(lambda files: files.update({"unexpected.py": b"bad"}))
        with self.assertRaisesRegex(ValueError, "Unexpected"):
            self.restore()
        self.assertFalse(list(self.destination.rglob("*.sqlite3")))
