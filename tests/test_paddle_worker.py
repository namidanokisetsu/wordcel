from multiprocessing import get_all_start_methods, get_context
from multiprocessing.connection import Listener
import json
import os
from pathlib import Path
import tempfile
from types import ModuleType
import unittest
import sys
from unittest.mock import patch

from wordcel.ocr import paddle_worker


def ocr_result(*texts):
    return {"rec_texts": list(texts), "text_word": [[text] for text in texts],
            "text_word_boxes": [[[0, 0, 50, 20]] for _ in texts]}


class PaddleWorkerTests(unittest.TestCase):
    """Exercise the request boundary without downloading Paddle models."""

    @unittest.skipUnless("fork" in get_all_start_methods(), "requires a fork fixture")
    def test_serial_requests_error_and_shutdown_use_each_runtime_order(self):
        fake_paddleocr = ModuleType("paddleocr")

        class PaddleOCR:
            def __init__(self, **options):
                import cv2
                self.owner = cv2.OWNER

            def predict(self, pixels):
                if pixels == "error":
                    raise RuntimeError("fixture inference error")
                return [ocr_result(self.owner, pixels)]

        fake_paddleocr.PaddleOCR = PaddleOCR
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            runtimes = []
            for owner in ("headless", "contrib"):
                site = base / owner
                package = site / "cv2"
                package.mkdir(parents=True)
                (package / "__init__.py").write_text(f"OWNER = {owner!r}\n")
                runtimes.append(site)

            with patch.dict("sys.modules", {"paddleocr": fake_paddleocr}), \
                    patch("wordcel.ocr.turkish_paddle.prepare_environment"):
                for runtime in runtimes:
                    # Keep the fixture equivalent to the real parent, which
                    # never imports either OpenCV distribution.
                    sys.modules.pop("cv2", None)
                    authkey = b"fixture-auth"
                    listener = Listener(("127.0.0.1", 0), authkey=authkey)
                    process = get_context("fork").Process(
                        target=paddle_worker.serve,
                        args=(f"{listener.address[0]}:{listener.address[1]}", authkey,
                              base, False, runtime),
                    )
                    process.start()
                    connection = listener.accept()
                    listener.close()
                    expected = runtime.name
                    self.assertEqual(connection.recv()[0], "ready")
                    connection.send(("predict", expected))
                    self.assertEqual(connection.recv(), ("result", [ocr_result(expected, expected)]))
                    connection.send(("predict", expected + "-again"))
                    self.assertEqual(connection.recv(), ("result", [ocr_result(expected, expected + "-again")]))
                    connection.send(("close", None))
                    self.assertEqual(connection.recv()[0], "closed")
                    connection.close()
                    process.join(3)
                    self.assertEqual(process.exitcode, 0)

    @unittest.skipUnless("fork" in get_all_start_methods(), "requires a fork fixture")
    def test_worker_reports_inference_errors_to_parent(self):
        fake_paddleocr = ModuleType("paddleocr")

        class PaddleOCR:
            def __init__(self, **options):
                pass

            def predict(self, pixels):
                if pixels == "error":
                    raise RuntimeError("fixture inference error")
                return [ocr_result(pixels)]

        fake_paddleocr.PaddleOCR = PaddleOCR
        with tempfile.TemporaryDirectory() as temporary, patch.dict("sys.modules", {"paddleocr": fake_paddleocr}), \
                patch("wordcel.ocr.turkish_paddle.prepare_environment"):
            authkey = b"fixture-auth"
            listener = Listener(("127.0.0.1", 0), authkey=authkey)
            process = get_context("fork").Process(
                target=paddle_worker.serve,
                args=(f"{listener.address[0]}:{listener.address[1]}", authkey, temporary, False, temporary),
            )
            process.start()
            connection = listener.accept()
            listener.close()
            self.assertEqual(connection.recv()[0], "ready")
            connection.send(("predict", "error"))
            kind, detail = connection.recv()
            self.assertEqual(kind, "error")
            self.assertIn("fixture inference error", detail)
            connection.send(("predict", "retry"))
            self.assertEqual(connection.recv(), ("result", [ocr_result("retry")]))
            connection.send(("close", None))
            self.assertEqual(connection.recv()[0], "closed")
            connection.close()
            process.join(3)
            self.assertEqual(process.exitcode, 0)

    def test_real_worker_command_uses_isolated_runtime_and_recovers(self):
        """Exercise the CLI boundary with fresh imports and no model files."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data"
            cache = root / "cache"
            environment = {
                "HOME": str(root / "home"), "USERPROFILE": str(root / "home"),
                "PYTHONPATH": os.pathsep.join((str(root / "headless"), str(Path(__file__).resolve().parents[1] / "src"))),
                "XDG_DATA_HOME": str(data), "XDG_CACHE_HOME": str(cache),
                "LOCALAPPDATA": str(data), "APPDATA": str(data),
            }
            base_site = root / "headless"
            base_cv2 = base_site / "cv2"
            base_cv2.mkdir(parents=True)
            (base_cv2 / "__init__.py").write_text("OWNER = 'headless'\n", encoding="utf-8")

            parent_cv2 = ModuleType("cv2")
            parent_cv2.OWNER = "parent-headless"
            with patch.dict(os.environ, environment, clear=False), patch.dict(sys.modules, {"cv2": parent_cv2}):
                from wordcel.optional_runtimes import SOURCE_PADDLE_MARKER, source_runtime_root
                runtime = source_runtime_root("paddle")
                site = runtime / "site"
                (site / "cv2").mkdir(parents=True)
                (site / "cv2/__init__.py").write_text("OWNER = 'contrib'\n", encoding="utf-8")
                (site / "cv2/cv2.fixture.dylib").write_bytes(b"fixture")
                paddleocr = site / "paddleocr"
                paddleocr.mkdir()
                (paddleocr / "__init__.py").write_text(
                    "import cv2\n"
                    "import numpy as np\n"
                    "from paddlex.utils.fonts import Font\n"
                    "class PaddleOCR:\n"
                    "    def __init__(self, **options): self.owner = cv2.OWNER\n"
                    "    def predict(self, pixels):\n"
                    "        if pixels == 'error': raise RuntimeError('fixture inference error')\n"
                    "        return [{'rec_texts': [self.owner, pixels],\n"
                    "                 'text_word': [[self.owner], [pixels]],\n"
                    "                 'text_word_boxes': [np.array([[0, 0, 50, 20]])] * 2,\n"
                    "                 'vis_fonts': [Font()],\n"
                    "                 'input_img': np.zeros((20, 80, 3), dtype=np.uint8)}]\n",
                    encoding="utf-8",
                )
                for package in ("paddle", "paddlex"):
                    (site / package).mkdir()
                    (site / package / "__init__.py").write_text("\n", encoding="utf-8")
                fonts = site / "paddlex/utils"
                fonts.mkdir()
                (fonts / "__init__.py").write_text("\n", encoding="utf-8")
                (fonts / "fonts.py").write_text("class Font: pass\n", encoding="utf-8")
                for distribution, version in {
                        "opencv_contrib_python": "4.10.0.84", "paddlepaddle": "3.2.2",
                        "paddleocr": "3.7.0", "paddlex": "3.7.2"}.items():
                    metadata = site / f"{distribution}-{version}.dist-info/METADATA"
                    metadata.parent.mkdir()
                    metadata.write_text(f"Name: {distribution}\nVersion: {version}\n", encoding="utf-8")
                (runtime / "complete.json").write_text(json.dumps(SOURCE_PADDLE_MARKER), encoding="utf-8")
                worker = paddle_worker.PaddleWorker(root / "models", False, site, startup_timeout=10)
                self.addCleanup(worker.close)
                self.assertEqual(worker.predict("first"), [ocr_result("contrib", "first")])
                with self.assertRaisesRegex(RuntimeError, "fixture inference error") as raised:
                    worker.predict("error")
                self.assertNotIn("Traceback", str(raised.exception))
                self.assertEqual(worker.predict("retry"), [ocr_result("contrib", "retry")])
                worker.close()
                self.assertIs(sys.modules["cv2"], parent_cv2)
                self.assertNotIn("paddlex.utils.fonts", sys.modules)

    def test_quick_lookup_worker_hook_forwards_runtime_site(self):
        from wordcel.scripts import quick_lookup
        with patch("wordcel.utils.windowed_processes.configure_windowed_helpers"), \
                patch("wordcel.utils.model_cache.configure_model_cache"), \
                patch("wordcel.utils.startup.hold_installer_mutex"), \
                patch("wordcel.ocr.paddle_worker.run_worker", return_value=0) as run:
            self.assertEqual(quick_lookup.main([
                "--paddle-worker", "--paddle-address", "127.0.0.1:1234",
                "--paddle-auth", "aa", "--paddle-model-dir", "/models",
                "--paddle-runtime", "/runtime", "--paddle-onnx", "1",
            ]), 0)
        self.assertEqual(run.call_args.args[0:2], ("127.0.0.1:1234", b"\xaa"))
        self.assertEqual(run.call_args.args[2:], (Path("/models"), True, Path("/runtime")))
