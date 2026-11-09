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
    "context": dict(
        name="Contextual Arabic analysis", version="1.0.1", size=445037325,
        sha256="95fee89f048311dafaf5cf2897f1416b3a1ef54866f75a13aab98a6973031107",
        url="https://github.com/CAMeL-Lab/camel-tools-data/releases/download/2022.04.26/disambig_bert_unfactored-msa-1.0.1.zip"),
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
    return ready("arabic", data_root) and model_ready("morphology", data_root) and (
        kind == "morphology" or ready("arabic-context", data_root) and model_ready(kind, data_root))


def transfer_size(kind="morphology"):
    """Complete transfer cost from the runtime manifest, or None until resolved."""
    from wordcel.optional_runtimes import manifest, ready
    config = manifest()
    from wordcel.optional_runtimes import arabic_manifest
    try:
        wheels = []
        for feature in (("arabic", "arabic-context") if kind == "context" else ("arabic",)):
            if not ready(feature):
                selected = config["features"].get(feature) if config else arabic_manifest(feature)
                if selected is None:
                    return None
                wheels.extend(selected)
    except RuntimeError:
        return None
    if wheels is None or any(not wheel.get("size") for wheel in wheels):
        return None
    size = sum(wheel["size"] for wheel in wheels)
    for name in (("morphology", "context") if kind == "context" else ("morphology",)):
        if not model_ready(name):
            size += PACKAGES[name]["size"]
    return size


def install(kind="morphology", progress=None, cancelled=None):
    if kind not in PACKAGES:
        raise ValueError("Unknown Arabic resource")
    from wordcel.optional_runtimes import install as install_engine
    progress = progress or (lambda text: None)
    install_engine("arabic", progress, cancelled)
    if kind == "context":
        install_engine("arabic-context", progress, cancelled)
    for name in (("morphology", "context") if kind == "context" else ("morphology",)):
        _install_model(name, progress, cancelled)


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
        required = "morphology.db" if kind == "morphology" else "pytorch_model.bin"
        if not (stage / required).is_file() or not (stage / "LICENSE").is_file():
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
