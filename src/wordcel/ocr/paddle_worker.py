"""The process boundary for PaddleOCR's contrib OpenCV runtime.

This module deliberately keeps Paddle and OpenCV imports inside the worker.
The desktop process can therefore keep the headless OpenCV distribution used
by the Japanese provider loaded in its own interpreter.
"""
from base64 import b16encode
from collections.abc import Mapping
import logging
from multiprocessing.connection import Client, Listener
import os
from pathlib import Path
import subprocess
import sys
import threading
import time


_LOGGER = logging.getLogger(__name__)


def _address(value):
    host, port = value.rsplit(":", 1)
    return host, int(port)


def _engine(root, use_onnx):
    # This import is intentionally below the worker process boundary.
    from paddleocr import PaddleOCR
    from .turkish_paddle import MODELS

    options = {"engine": "onnxruntime", "engine_config": {
        "intra_op_num_threads": 4, "inter_op_num_threads": 1, "log_severity_level": 3,
    }} if use_onnx else {"enable_mkldnn": True, "cpu_threads": 4}
    return PaddleOCR(
        text_detection_model_name=MODELS["det"], text_detection_model_dir=str(Path(root) / MODELS["det"]),
        text_recognition_model_name=MODELS["rec"], text_recognition_model_dir=str(Path(root) / MODELS["rec"]),
        use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False,
        return_word_box=True, device="cpu", **options,
    )


def _plain(value):
    """Convert PaddleX result wrappers and arrays to connection-safe values."""
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if hasattr(value, "to_dict"):
        return _plain(value.to_dict())
    if hasattr(value, "tolist"):
        return _plain(value.tolist())
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    return value


def serve(address, authkey, root, use_onnx, runtime_site=None):
    """Connect to a parent and serve serialized OCR requests until closed."""
    if runtime_site:
        site = str(Path(runtime_site).resolve())
        sys.path[:] = [entry for entry in sys.path
                       if str(Path(entry).resolve()) != site]
        sys.path.insert(0, site)
    # A forked test process or an embedding host can have imported the base
    # distribution already. The real desktop process does not, but removing
    # this module makes the ownership rule explicit in either case.
    sys.modules.pop("cv2", None)
    # The worker must set this before PaddleX is imported.
    os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
    connection = Client(_address(address), authkey=authkey)
    try:
        from .turkish_paddle import prepare_environment
        prepare_environment()
        engine = _engine(root, use_onnx)
        connection.send(("ready", None))
        while True:
            command, payload = connection.recv()
            if command == "close":
                connection.send(("closed", None))
                return
            if command != "predict":
                connection.send(("error", f"Unknown Paddle worker command: {command}"))
                continue
            try:
                # PaddleX also returns images and Font objects. Unpickling a
                # Font would import PaddleX into the isolated desktop process.
                result = [_plain({key: item.get(key, []) for key in
                                  ("rec_texts", "text_word", "text_word_boxes")})
                          for item in engine.predict(payload)]
            except Exception as error:
                _LOGGER.exception("Paddle OCR inference failed")
                connection.send(("error", f"{type(error).__name__}: {error}"))
                continue
            connection.send(("result", result))
    except EOFError:
        return
    except Exception as error:
        _LOGGER.exception("Paddle OCR worker failed")
        try:
            connection.send(("error", f"{type(error).__name__}: {error}"))
        except (BrokenPipeError, EOFError, OSError):
            pass
    finally:
        connection.close()


def run_worker(address, authkey, root, use_onnx, runtime_site=None):
    """CLI entry point used by the source and frozen worker command."""
    serve(address, authkey, root, use_onnx, runtime_site)
    return 0


def _worker_command(address, authkey, root, use_onnx, runtime_site):
    executable = Path(sys.executable)
    if executable.name.lower() == "pythonw.exe":
        executable = executable.with_name("python.exe")
    arguments = ["--paddle-worker", "--paddle-address", address,
                 "--paddle-auth", b16encode(authkey).decode("ascii"),
                 "--paddle-model-dir", str(root), "--paddle-onnx", "1" if use_onnx else "0"]
    if runtime_site:
        arguments += ["--paddle-runtime", str(runtime_site)]
    if getattr(sys, "frozen", False):
        if sys.platform == "win32":
            console = executable.with_name("wordcel-cli.exe")
            if console.exists():
                executable = console
        return [str(executable), *arguments]
    return [str(executable), "-m", "wordcel.scripts.quick_lookup", *arguments]


class PaddleWorker:
    """Synchronous request client for one isolated Paddle process."""

    def __init__(self, root, use_onnx, runtime_site=None, startup_timeout=30):
        authkey = os.urandom(32)
        listener = Listener(("127.0.0.1", 0), authkey=authkey)
        self._listener = listener
        self._process = None
        self._connection = None
        self._lock = threading.Lock()
        address = listener.address
        address_text = f"{address[0]}:{address[1]}"
        command = _worker_command(address_text, authkey, root, use_onnx, runtime_site)
        try:
            self._process = subprocess.Popen(
                command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            deadline = time.monotonic() + startup_timeout
            accepted = None
            while time.monotonic() < deadline:
                if self._process.poll() is not None:
                    raise RuntimeError("Paddle OCR worker exited during startup.")
                # Listener.accept() has no public timeout. Accept on a daemon
                # thread so a failed child cannot block the OCR worker forever.
                if accepted is None:
                    result = []
                    thread = threading.Thread(target=self._accept, args=(result,), daemon=True)
                    thread.start()
                    while not result and time.monotonic() < deadline:
                        if self._process.poll() is not None:
                            raise RuntimeError("Paddle OCR worker exited during startup.")
                        time.sleep(0.02)
                    accepted = result[0] if result else None
                if accepted is not None:
                    break
            if accepted is None:
                raise RuntimeError("Paddle OCR worker did not connect.")
            self._connection = accepted
            if not self._connection.poll(max(0, deadline - time.monotonic())):
                raise RuntimeError("Paddle OCR worker did not become ready.")
            kind, detail = self._connection.recv()
            if kind == "error":
                raise RuntimeError(f"Paddle OCR worker failed to start:\n{detail}")
            if kind != "ready":
                raise RuntimeError(f"Unexpected Paddle worker response: {kind}")
        except Exception:
            self.close()
            raise
        finally:
            listener.close()
            self._listener = None

    def _accept(self, result):
        try:
            result.append(self._listener.accept())
        except (OSError, EOFError):
            pass

    @property
    def closed(self):
        return self._connection is None

    def predict(self, pixels):
        with self._lock:
            if self._connection is None:
                raise RuntimeError("Paddle OCR worker is closed.")
            try:
                self._connection.send(("predict", pixels))
                if not self._connection.poll(30):
                    self.close()
                    raise RuntimeError("Paddle OCR worker timed out.")
                kind, payload = self._connection.recv()
            except (EOFError, OSError) as error:
                self.close()
                raise RuntimeError("Paddle OCR worker stopped.") from error
            if kind == "error":
                raise RuntimeError(f"Paddle OCR worker failed:\n{payload}")
            if kind != "result":
                raise RuntimeError(f"Unexpected Paddle worker response: {kind}")
            return payload

    def close(self):
        connection, self._connection = self._connection, None
        if connection is not None:
            try:
                connection.send(("close", None))
                if connection.poll(2):
                    connection.recv()
            except (EOFError, OSError):
                pass
            connection.close()
        process, self._process = self._process, None
        if process is not None:
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
