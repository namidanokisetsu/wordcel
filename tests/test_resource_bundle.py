from contextlib import closing
import hashlib
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


class TranslationBundleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source, self.destination = self.root / "source", self.root / "destination"
        self.archive = self.root / "translation.zip"
        self.cancelled = threading.Event()
        self.model = dict(name="Fixture model", repo="fixture", revision="r1", file="model.gguf", size=5,
                          sha256=hashlib.sha256(b"model").hexdigest())

    def kwargs(self, root):
        return dict(data_root=root / "data", cache_root=root / "cache")

    def make_runtime(self, root, backend, *, legacy=False):
        data = root / "data"
        platform_name = "win-x64"
        suffix = platform_name if legacy else platform_name + "-" + backend
        runtime = data / "translation" / ("runtime-b11146-" + suffix)
        executable = runtime / "llama-server.exe"
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.write_bytes(b"server-" + backend.encode())
        metadata = dict(release="b11146", platform=platform_name, backend=backend,
                        executable=executable.relative_to(data / "translation").as_posix())
        if not legacy:
            (runtime / "runtime.json").write_text(json.dumps(metadata), encoding="utf-8")
        return runtime, metadata

    def make_translation(self, *, backend="cpu", legacy=False, shared=False):
        data = self.source / "data"
        runtimes = {}
        if shared:
            for selected in ("cpu", "vulkan"):
                _, metadata = self.make_runtime(self.source, selected)
                runtimes[selected] = metadata
            selected_metadata = runtimes[backend]
        else:
            _, selected_metadata = self.make_runtime(self.source, backend, legacy=legacy)
            if not legacy:
                runtimes[backend] = selected_metadata
        model_path = data / "translation/models/model.gguf"
        model_path.parent.mkdir(parents=True, exist_ok=True)
        model_path.write_bytes(b"model")
        manifest = dict(release="b11146", platform="win-x64", backend=backend,
                        executable=selected_metadata["executable"],
                        models={"lightweight": dict(path="models/model.gguf",
                                                      sha256=self.model["sha256"], size=5,
                                                      url="https://example.test/model.gguf")})
        if runtimes:
            manifest["runtimes"] = runtimes
        (data / "translation").mkdir(parents=True, exist_ok=True)
        (data / "translation/installation.json").write_text(json.dumps(manifest), encoding="utf-8")

    def export(self):
        with patch("wordcel.scripts.translation_server.MODELS", {"lightweight": self.model}), \
                patch("wordcel.translation_catalog.MODELS", {"lightweight": self.model}):
            from wordcel.data_assets import inventory
            export_bundle(self.archive, self.source / "library", lambda text: None, self.cancelled,
                          **self.kwargs(self.source))

    def import_archive(self):
        with patch("wordcel.scripts.translation_server.MODELS", {"lightweight": self.model}), \
                patch("wordcel.translation_catalog.MODELS", {"lightweight": self.model}):
            import_bundle(self.archive, self.destination / "library", lambda text: None, self.cancelled,
                          **self.kwargs(self.destination))

    def test_cpu_and_vulkan_runtime_metadata_round_trip_with_shared_model(self):
        for backend in ("cpu", "vulkan"):
            with self.subTest(backend=backend):
                self.source = self.root / (backend + "-source")
                self.destination = self.root / (backend + "-destination")
                self.archive = self.root / (backend + ".zip")
                self.make_translation(backend=backend)
                self.export()
                self.import_archive()
                installed = json.loads((self.destination / "data/translation/installation.json").read_text())
                self.assertEqual(installed["backend"], backend)
                self.assertEqual(installed["runtimes"][backend]["backend"], backend)
                self.assertEqual(installed["models"]["lightweight"]["path"], "models/model.gguf")
                self.assertEqual((self.destination / "data/translation/models/model.gguf").read_bytes(), b"model")
                from wordcel.scripts.translation_server import _installed_paths
                executable, model_path = _installed_paths("lightweight", self.destination / "data/translation", backend)
                self.assertTrue(executable.is_file())
                self.assertEqual(model_path.read_bytes(), b"model")

    def test_legacy_cuda_bundle_reconstructs_metadata_when_old_export_omitted_it(self):
        self.make_translation(backend="cuda", legacy=True)
        self.export()
        with zipfile.ZipFile(self.archive) as bundle:
            files = {item.filename: bundle.read(item) for item in bundle.infolist()}
        manifest = json.loads(files["manifest.json"])
        removed = next(unit for unit in manifest["units"] if unit["path"] == "translation/installation.json")
        index = manifest["units"].index(removed)
        manifest["units"].remove(removed)
        files.pop(f"resources/{index}/file")
        files["manifest.json"] = json.dumps(manifest).encode()
        with zipfile.ZipFile(self.archive, "w") as bundle:
            for name, data in files.items():
                bundle.writestr(name, data)
        self.import_archive()
        installed = json.loads((self.destination / "data/translation/installation.json").read_text())
        self.assertEqual(installed["backend"], "cuda")
        self.assertEqual(installed["runtimes"]["cuda"]["backend"], "cuda")
        self.assertEqual(installed["models"]["lightweight"]["size"], 5)
        from wordcel.scripts.translation_server import _installed_paths
        self.assertTrue(_installed_paths("lightweight", self.destination / "data/translation", "cuda")[0].is_file())

    def test_invalid_backend_metadata_rolls_back_runtime_and_model(self):
        self.make_translation(backend="cpu")
        self.export()
        with zipfile.ZipFile(self.archive) as bundle:
            files = {item.filename: bundle.read(item) for item in bundle.infolist()}
        manifest = json.loads(files["manifest.json"])
        unit = next(unit for unit in manifest["units"] if unit["path"] == "translation/installation.json")
        name = f"resources/{manifest['units'].index(unit)}/file"
        metadata = json.loads(files[name])
        metadata["backend"] = "metal"
        files[name] = json.dumps(metadata).encode()
        unit["files"][0]["size"] = len(files[name])
        unit["files"][0]["sha256"] = hashlib.sha256(files[name]).hexdigest()
        files["manifest.json"] = json.dumps(manifest).encode()
        with zipfile.ZipFile(self.archive, "w") as bundle:
            for archive_name, data in files.items():
                bundle.writestr(archive_name, data)
        with self.assertRaisesRegex(ValueError, "backend"):
            self.import_archive()
        self.assertFalse((self.destination / "data/translation/models/model.gguf").exists())
        self.assertFalse(list((self.destination / "data/translation").glob("runtime-*")))
