from multiprocessing import get_all_start_methods, get_context
from multiprocessing.connection import Listener
from pathlib import Path
import tempfile
from types import ModuleType
import unittest
import sys
from unittest.mock import patch

from wordcel.ocr import paddle_worker


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
                return [{"owner": self.owner, "value": pixels}]

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
                    self.assertEqual(connection.recv(), ("result", [{"owner": expected, "value": expected}]))
                    connection.send(("predict", expected + "-again"))
                    self.assertEqual(connection.recv(), ("result", [{"owner": expected, "value": expected + "-again"}]))
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
                raise RuntimeError("fixture inference error")

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
            connection.send(("predict", "pixels"))
            kind, detail = connection.recv()
            self.assertEqual(kind, "error")
            self.assertIn("fixture inference error", detail)
            connection.close()
            process.join(3)
            self.assertEqual(process.exitcode, 0)

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
