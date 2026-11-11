"""Pinned, optional MSA assets; no toolkit imports or network at lookup time."""
import json
from pathlib import Path
import tempfile
import zipfile

from wordcel.optional_runtimes import _cancel, download_verified, file_hash, safe_member


CAMEL_VERSION = "1.6.0"
PACKAGES = {
    "morphology": dict(
        name="Arabic morphology", version="0.4.0", size=40488532,
        sha256="fe6531250c5529307627cc63ed56447cbb9968020d6ea3ab867e6ad9af94c738",
        url="https://github.com/CAMeL-Lab/camel-tools-data/releases/download/2022.03.21/morphology_db_calima-msa-r13-0.4.0.zip"),
}


def model_root(kind="morphology", data_root=None):
    if kind not in PACKAGES:
        raise ValueError("Unknown Arabic resource")
    from wordcel.utils.paths import paths
    return Path(data_root or paths.data_dir) / "languages/ar/camel" / (kind + "-" + PACKAGES[kind]["version"])


def model_ready(kind="morphology", data_root=None):
    root = model_root(kind, data_root)
    try:
        record = json.loads((root / "complete.json").read_text(encoding="utf-8"))
        return record["package"] == PACKAGES[kind]["sha256"] and bool(record["files"]) and all(
            (root / name).is_file() and (root / name).stat().st_size == value["size"]
            for name, value in record["files"].items())
    except (OSError, ValueError, KeyError, TypeError):
        return False


def available(kind="morphology", data_root=None):
    from wordcel.optional_runtimes import ready
    return kind == "morphology" and ready("arabic", data_root) and model_ready(kind, data_root)


def transfer_size(kind="morphology"):
    """Complete transfer cost from the runtime manifest, or None until resolved."""
    if kind not in PACKAGES:
        raise ValueError("Unknown Arabic resource")
    from wordcel.optional_runtimes import manifest, ready
    config = manifest()
    from wordcel.optional_runtimes import arabic_manifest
    try:
        wheels = [] if ready("arabic") else config["features"].get("arabic") if config else arabic_manifest()
    except RuntimeError:
        return None
    if wheels is None or any(not wheel.get("size") for wheel in wheels):
        return None
    size = sum(wheel["size"] for wheel in wheels)
    if not model_ready(kind):
        size += PACKAGES[kind]["size"]
    return size


def install(kind="morphology", progress=None, cancelled=None):
    if kind not in PACKAGES:
        raise ValueError("Unknown Arabic resource")
    from wordcel.optional_runtimes import install as install_engine
    progress = progress or (lambda text: None)
    install_engine("arabic", progress, cancelled)
    _install_model(kind, progress, cancelled)


def _install_model(kind, progress, cancelled):
    _cancel(cancelled)
    if model_ready(kind):
        return
    spec = PACKAGES[kind]
    root = model_root(kind)
    root.parent.mkdir(parents=True, exist_ok=True)
    from wordcel.utils.paths import paths
    cache = Path(paths.cache_dir) / "arabic-downloads"
    cache.mkdir(parents=True, exist_ok=True)
    archive = download_verified(spec["url"], cache / (spec["sha256"] + ".zip"), spec["sha256"],
                                progress, cancelled, size=spec["size"], label=spec["name"])
    with tempfile.TemporaryDirectory(prefix=".install-", dir=root.parent) as temporary:
        stage = Path(temporary) / "model"
        stage.mkdir()
        files = {}
        with zipfile.ZipFile(archive) as bundle:
            for item in bundle.infolist():
                _cancel(cancelled)
                relative = safe_member(item.filename)
                if item.is_dir():
                    continue
                destination = stage / relative
                if not destination.resolve().is_relative_to(stage.resolve()):
                    raise ValueError("Invalid Arabic model path")
                destination.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(item) as source, destination.open("wb") as target:
                    while chunk := source.read(1024 * 1024):
                        _cancel(cancelled)
                        target.write(chunk)
                files[relative.as_posix()] = dict(size=destination.stat().st_size, sha256=file_hash(destination))
        if not (stage / "morphology.db").is_file() or not (stage / "LICENSE").is_file():
            raise ValueError("Arabic model archive is incomplete")
        progress("Verifying " + spec["name"] + "…")
        (stage / "complete.json").write_text(json.dumps(dict(package=spec["sha256"], files=files)), encoding="utf-8")
        _cancel(cancelled)
        previous = Path(temporary) / "previous"
        if root.exists():
            root.rename(previous)
        try:
            stage.rename(root)
        except OSError:
            if previous.exists():
                previous.rename(root)
            raise
