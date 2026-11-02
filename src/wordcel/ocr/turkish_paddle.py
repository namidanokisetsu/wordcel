"""Local PaddleOCR 3.7: explicit setup, offline inference, real word boxes."""
import hashlib
import importlib
from importlib.util import find_spec
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

from wordcel.ocr.scan_cache import ScanCache
from wordcel.ocr.paddle_worker import PaddleWorker
from wordcel.pipeline import REUSE_LAST_VALUE

MODELS = {"det": "PP-OCRv6_small_det", "rec": "PP-OCRv6_small_rec"}
PADDLE_FILES = ("inference.json", "inference.pdiparams", "inference.yml")
_openmp = None


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def install_onnx_exports(source, stage):
    """Accept only complete exports of the exact staged Paddle models."""
    source = Path(source)
    info = json.loads((source / "export.json").read_text(encoding="utf-8"))
    if info.get("models") != MODELS or info.get("schema") != 1:
        raise ValueError("Incompatible ONNX export; run export_turkish_ocr again")
    for name in MODELS.values():
        for filename in PADDLE_FILES:
            relative = f"{name}/{filename}"
            if info.get("source_files", {}).get(relative) != file_hash(stage / relative):
                raise ValueError("ONNX export does not match the installed Paddle models")
        relative = f"{name}/inference.onnx"
        if info.get("files", {}).get(relative) != file_hash(source / relative):
            raise ValueError("ONNX export checksum mismatch")
        shutil.copyfile(source / relative, stage / relative)
    return info.get("exporter", {})


def model_root():
    from wordcel.utils.paths import paths
    return Path(paths.data_dir) / "languages/tr/paddle/3.7.0"


def prepare_environment():
    from wordcel.optional_runtimes import require
    require("paddle")
    os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
    global _openmp
    if sys.platform != "win32" or _openmp is not None:
        return
    spec = find_spec("torch")
    if spec is None or spec.origin is None:
        return
    library = Path(spec.origin).parent / "lib" / "libiomp5md.dll"
    if library.is_file():
        # Paddle's OpenMP lacks symbols Torch needs when morphology starts later.
        # Load only the compatible runtime, leaving Torch and its models lazy.
        import ctypes
        _openmp = ctypes.WinDLL(str(library))


def activate_paddle_runtime():
    """Prepend Paddle's complete site in a process dedicated to Paddle."""
    from wordcel.optional_runtimes import runtime_site
    site = runtime_site("paddle")
    if site is None:
        return
    site = str(Path(site).resolve())
    sys.path[:] = [entry for entry in sys.path
                   if str(Path(entry).resolve()) != site]
    sys.path.insert(0, site)
    importlib.invalidate_caches()


def setup_ocr(root=None, onnx_dir=None):
    prepare_environment()
    # Model setup runs in its own CLI process, so it may own Paddle's cv2
    # distribution without changing the desktop process's headless import.
    activate_paddle_runtime()
    from paddlex.inference.utils.official_models import official_models
    root = Path(root or model_root())
    root.parent.mkdir(parents=True, exist_ok=True)
    # Activate a new immutable directory only after both downloads are complete.
    with tempfile.TemporaryDirectory(dir=root.parent) as temporary:
        stage = Path(temporary) / "models"
        stage.mkdir()
        for name in MODELS.values():
            shutil.copytree(official_models[name], stage / name)
        exporter = install_onnx_exports(onnx_dir, stage) if onnx_dir else None
        hashes = {p.relative_to(stage).as_posix(): file_hash(p)
                  for p in stage.rglob("*") if p.is_file()}
        if not hashes:
            raise ValueError("OCR model download is empty")
        manifest = {"models": MODELS, "files": hashes}
        if exporter is not None:
            manifest["onnx_exporter"] = exporter
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        validate_models(stage)
        # Verify the bundled inference runtime before activating the new models.
        probe = LocalOCR(stage)
        probe.close()
        if root.exists():
            previous = Path(temporary) / "previous"
            root.replace(previous)
            try:
                stage.replace(root)
            except OSError:
                previous.replace(root)
                raise
        else:
            stage.replace(root)
    return str(root)


def validate_models(root):
    root = Path(root)
    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        if manifest["models"] != MODELS or not manifest["files"]:
            raise ValueError("Incompatible OCR models")
        for name in MODELS.values():
            for file in PADDLE_FILES:
                if f"{name}/{file}" not in manifest["files"]:
                    raise ValueError("Incomplete OCR models")
        onnx_files = [f"{name}/inference.onnx" in manifest["files"] for name in MODELS.values()]
        if any(onnx_files) and not all(onnx_files):
            raise ValueError("Incomplete ONNX models")
        for relative, digest in manifest["files"].items():
            path = (root / relative).resolve()
            if not path.is_relative_to(root.resolve()) or file_hash(path) != digest:
                raise ValueError("Damaged OCR models")
        return manifest
    except (OSError, KeyError, ValueError) as error:
        raise RuntimeError("Local OCR models missing or damaged. Download them in Settings > Lookup.") from error


class LocalOCR:
    def __init__(self, root=None):
        root = Path(root or model_root())
        manifest = validate_models(root)
        prepare_environment()
        use_onnx = all(f"{name}/inference.onnx" in manifest["files"] for name in MODELS.values())
        from wordcel.optional_runtimes import runtime_site
        self._worker = PaddleWorker(root, use_onnx, runtime_site("paddle"))
        self.scan_cache = ScanCache()

    def recognize(self, pixels):
        """Recognize a BGR uint8 array; returned boxes use these input pixels."""
        worker = getattr(self, "_worker", None)
        if worker is not None:
            return worker.predict(pixels)
        return list(self.engine.predict(pixels))

    def close(self):
        worker = getattr(self, "_worker", None)
        if worker is not None:
            self._worker = None
            worker.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def lookup_point(self, pixels, point):
        results = self.scan_cache.result if pixels is REUSE_LAST_VALUE else self.scan_cache.scan(pixels, self.recognize)
        for result in results or ():
            hit = hit_word(result, point)
            if hit:
                return hit
        return None


def hit_word(result, point):
    """Return complete line and source offset for the actual box under the pointer."""
    from .context import paddle_lines
    x, y = point
    for text, words in paddle_lines([result]):
        for _, start, _, box in words:
            left, top, right, bottom = box
            if left <= x <= right and top <= y <= bottom:
                return text, start
    return None
