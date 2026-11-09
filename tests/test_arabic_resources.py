from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile

from wordcel.language import arabic_analyzer as client
from wordcel.language import arabic_resources as resources


class ArabicResourceTests(unittest.TestCase):
    def test_analysis_and_context_share_one_lazy_worker(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for kind in ("morphology", "context"):
                path = root / kind
                path.mkdir()
                (path / "complete.json").write_text("{}")
            row = client.ArabicAnalysis(0, 3, "كتب", "كَتَبَ", "كتب", "كَتَبَ", "verb")
            worker = Mock(closed=False)
            worker.analyze.return_value = [asdict(row)]
            with patch.object(resources, "available", return_value=True), \
                    patch.object(resources, "model_root", side_effect=lambda kind="morphology": root / kind), \
                    patch("wordcel.optional_runtimes.runtime_site", return_value=root), \
                    patch("wordcel.language.arabic_worker.ArabicWorker", return_value=worker) as factory:
                client.close_worker()
                try:
                    analyzer = client.ArabicAnalyzer()
                    self.assertEqual(analyzer.candidates("كتب", 0, 3), (row,))
                    self.assertEqual(analyzer.candidates("كتب", 0, 3, contextual=True), (row,))
                    self.assertEqual(factory.call_count, 1)
                finally:
                    client.close_worker()
            worker.close.assert_called_once()

    def test_cancelled_setup_does_not_replace_existing_data(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "model"
            root.mkdir()
            (root / "existing").write_text("keep")
            archive = Path(folder) / "model.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("morphology.db", "fixture")
                bundle.writestr("LICENSE", "fixture licence")
            cancelled = threading.Event()
            with patch.object(resources, "model_root", return_value=root), \
                    patch.object(resources, "download_verified", return_value=archive), \
                    patch("wordcel.utils.paths.paths", SimpleNamespace(cache_dir=Path(folder) / "cache")):
                with self.assertRaises(InterruptedError):
                    resources._install_model("morphology", lambda text: cancelled.set(), cancelled)
            self.assertEqual((root / "existing").read_text(), "keep")
            self.assertFalse((root / "complete.json").exists())

    def test_model_archive_cannot_escape_its_staging_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "model"
            archive = Path(folder) / "model.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("../escape", "invalid")
            with patch.object(resources, "model_root", return_value=root), \
                    patch.object(resources, "download_verified", return_value=archive), \
                    patch("wordcel.utils.paths.paths", SimpleNamespace(cache_dir=Path(folder) / "cache")):
                with self.assertRaises(ValueError):
                    resources._install_model("morphology", lambda text: None, threading.Event())
            self.assertFalse(root.exists())
            self.assertFalse((Path(folder) / "escape").exists())

    def test_context_setup_and_resource_removal_share_the_morphology_lock(self):
        from wordcel.gui.setup_operation import SetupRequest, setup_resource
        request = SetupRequest.from_options(morphology="ar-context")
        self.assertEqual(request.job_keys, ("arabic:context",))
        self.assertEqual(request.resource, "morphology")
        self.assertEqual(setup_resource("arabic:context"), "morphology")

    def test_optional_resources_are_metadata_without_model_weights(self):
        root = Path(__file__).resolve().parents[1]
        manifest = json.loads((root / "src/wordcel/resources/arabic-runtime-win-amd64-py312.json").read_text(encoding="utf-8"))
        self.assertLess(sum(w["size"] for w in manifest["morphology"]), 2 * 1024**2)
        self.assertFalse(any(w["name"] in {"torch", "transformers", "numpy"} for w in manifest["morphology"]))
        torch = next(w for w in manifest["context"] if w["name"] == "torch")
        self.assertIn("cpu", torch["url"])
        self.assertTrue(all(len(w["sha256"]) == 64 and w["size"] > 0 for part in manifest.values() for w in part))
        self.assertFalse(list((root / "src/wordcel/resources").rglob("*.pt")))
        self.assertFalse(list((root / "src/wordcel/resources").rglob("morphology.db")))
