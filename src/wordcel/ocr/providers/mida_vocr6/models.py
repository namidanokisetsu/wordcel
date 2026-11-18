"""Explicit downloads of the exact models supported by the upstream decoder."""
from importlib.util import find_spec
from pathlib import Path
import sys

from wordcel.utils.paths import paths


PROVIDER = "mida_vocr6"
MODELS = (
    ("mida_ocr_l.onnx", 1751881, "9f72bce58b50b1837bb16e81c5c035d32d9cd45d84dcef56f0b6fb2ef25e8aed",
     "https://huggingface.co/rtr46/mida/resolve/5f43c02b48bfa8ed11778a0b52cf4fe6d572fc54/mida_l_alpha_v0.0.1.onnx"),
    ("VOCR6.2_L_fast.onnx", 2525242, "3084fb3bd1332832c872009d869d267d5acd1bd69d26c80f742aa2f31a80c938",
     "https://github.com/bee-san/vita-vn-ocr/releases/download/v0.5.1-onnx.2/VOCR6.2_L_fast.onnx"),
)


def root(data_root=None):
    return Path(data_root or paths.data_dir) / "mida_vocr6"


def needs_engine():
    return sys.platform == "darwin" and getattr(sys, "frozen", False)


def available():
    if needs_engine():
        from wordcel.optional_runtimes import manifest
        return PROVIDER in (manifest() or {}).get("features", {})
    return all(find_spec(package) is not None for package in ("cv2", "onnxruntime"))


def ready(data_root=None):
    if needs_engine():
        from wordcel.optional_runtimes import ready as engine_ready
        if not engine_ready(PROVIDER, data_root):
            return False
    try:
        return all((root(data_root) / name).stat().st_size == size for name, size, _, _ in MODELS)
    except OSError:
        return False


def install(progress, cancelled):
    from wordcel.optional_runtimes import download_verified, install as install_engine

    if needs_engine():
        install_engine(PROVIDER, progress, cancelled)
    directory = root()
    for name, size, digest, url in MODELS:
        download_verified(url, directory / name, digest, progress, cancelled, size, name)
