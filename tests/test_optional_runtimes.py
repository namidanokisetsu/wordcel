import hashlib
import io
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from urllib.error import HTTPError
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

    def test_interrupted_wheel_download_resumes_with_range_and_validator(self):
        content = b"x" * (1024 * 1024 + 137) + b"tail"
        digest = hashlib.sha256(content).hexdigest()
        destination = self.root / "cache" / "fixture.whl"
        cancelled = threading.Event()
        requests = []

        class Response(io.BytesIO):
            def __init__(self, body, status, headers):
                super().__init__(body)
                self.status, self.headers = status, headers

        def transfer(request, timeout=0):
            requests.append(request)
            if len(requests) == 1:
                return Response(content, 200, {"Content-Length": str(len(content)), "ETag": '"fixture-v1"'})
            offset = int(request.get_header("Range").removeprefix("bytes=").removesuffix("-"))
            self.assertEqual(request.get_header("If-range"), '"fixture-v1"')
            return Response(content[offset:], 206, {
                "Content-Length": str(len(content) - offset),
                "Content-Range": f"bytes {offset}-{len(content) - 1}/{len(content)}",
                "ETag": '"fixture-v1"'})

        def stop_after_first_chunk(text):
            cancelled.set()

        with patch.object(engines, "urlopen", side_effect=transfer):
            with self.assertRaises(InterruptedError):
                engines.download_verified("https://example.invalid/fixture.whl", destination, digest,
                                          stop_after_first_chunk, cancelled, len(content))
            temporary, metadata = engines._download_paths(destination)
            self.assertEqual(temporary.stat().st_size, 1024 * 1024)
            self.assertTrue(metadata.is_file())
            cancelled.clear()
            result = engines.download_verified("https://example.invalid/fixture.whl", destination, digest,
                                               cancelled=cancelled, size=len(content))
        self.assertEqual(result, destination)
        self.assertEqual(destination.read_bytes(), content)
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[1].get_header("Range"), "bytes=1048576-")
        self.assertFalse(temporary.exists())
        self.assertFalse(metadata.exists())

    def test_ignored_range_restarts_without_duplicate_bytes(self):
        content = b"fixture content" * 100
        digest = hashlib.sha256(content).hexdigest()
        destination = self.root / "cache" / "fixture.whl"
        temporary, metadata = engines._download_paths(destination)
        temporary.parent.mkdir(parents=True)
        temporary.write_bytes(content[:20])
        metadata.write_text(json.dumps({"url": "https://example.invalid/fixture.whl", "sha256": digest,
                                        "size": len(content), "etag": '"v1"', "last_modified": None}))
        requests = []

        class Response(io.BytesIO):
            def __init__(self, body, status, headers):
                super().__init__(body)
                self.status, self.headers = status, headers

        def transfer(request, timeout=0):
            requests.append(request)
            if len(requests) <= 2:
                return Response(content, 200, {"Content-Length": str(len(content)), "ETag": '"v1"'})
            self.fail("A restart should issue one plain request")

        with patch.object(engines, "urlopen", side_effect=transfer):
            engines.download_verified("https://example.invalid/fixture.whl", destination, digest, size=len(content))
        self.assertEqual(destination.read_bytes(), content)
        self.assertEqual(len(requests), 2)
        self.assertIn("Range", requests[0].headers)
        self.assertNotIn("Range", requests[1].headers)

    def test_complete_partial_handles_416_and_corrupt_partial_is_removed(self):
        content = b"complete fixture"
        digest = hashlib.sha256(content).hexdigest()
        destination = self.root / "cache" / "fixture.whl"
        temporary, metadata = engines._download_paths(destination)
        temporary.parent.mkdir(parents=True)
        temporary.write_bytes(content)
        metadata.write_text(json.dumps({"url": "https://example.invalid/fixture.whl", "sha256": digest,
                                        "size": len(content), "etag": '"v1"', "last_modified": None}))
        error = HTTPError("https://example.invalid/fixture.whl", 416, "range", {
            "Content-Range": f"bytes */{len(content)}"}, io.BytesIO())
        with patch.object(engines, "urlopen", side_effect=error):
            self.assertEqual(engines.download_verified("https://example.invalid/fixture.whl", destination, digest,
                                                       size=len(content)), destination)
        self.assertEqual(destination.read_bytes(), content)
        self.assertFalse(temporary.exists())
        self.assertFalse(metadata.exists())
