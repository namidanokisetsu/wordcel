"""Explicit, pinned wheel installation for frozen apps. Inference never downloads."""
from functools import lru_cache
import hashlib
import importlib
import json
from pathlib import Path, PurePosixPath
import sys
import tempfile
import threading
from urllib.request import Request, urlopen
import zipfile

from wordcel import USER_AGENT

_install_lock = threading.Lock()
_active = set()


@lru_cache(maxsize=1)
def manifest():
    from wordcel.utils.paths import paths
    source = Path(paths.get_resource_path("runtimes.json"))
    return json.loads(source.read_text(encoding="utf-8")) if source.is_file() else None


def runtime_root(feature, data_root=None):
    from wordcel.utils.paths import paths
    config = manifest()
    if not config or feature not in config["features"]:
        raise RuntimeError("This build does not provide this optional engine.")
    identity = hashlib.sha256(json.dumps([config["platform"], config["python"], config["features"][feature]],
                                        sort_keys=True).encode()).hexdigest()[:24]
    return Path(data_root or paths.data_dir) / "engines" / f"{feature}-{identity}"


def ready(feature, data_root=None):
    if not manifest():
        return not getattr(sys, "frozen", False)
    try:
        root = runtime_root(feature, data_root)
        return json.loads((root / "complete.json").read_text(encoding="utf-8")) == manifest()["features"][feature] and (root / "site").is_dir()
    except (RuntimeError, OSError, ValueError):
        return False


def activate():
    """Expose installed wheels without importing their engines or scanning model data."""
    config = manifest()
    if not config:
        return
    for feature in config["features"]:
        if ready(feature):
            site = str(runtime_root(feature) / "site")
            if site not in sys.path:
                sys.path.append(site)
                importlib.invalidate_caches()


def require(feature):
    if not ready(feature):
        raise RuntimeError("Download this feature in Settings before using it.")
    # A newly installed Torch must precede Paddle's incompatible Windows OpenMP DLL.
    if feature == "stanza" and sys.platform == "win32" and "paddle" in sys.modules and "stanza" not in _active:
        from wordcel.ocr.turkish_paddle import _openmp
        if _openmp is None:
            raise RuntimeError("Restart Wordcel to use the newly installed word-form engine.")
    activate()
    _active.add(feature)


def _cancel(cancelled):
    if cancelled and cancelled.is_set():
        raise InterruptedError("Download cancelled.")


def safe_member(name):
    path = PurePosixPath(name)
    if (not name or "\\" in name or ":" in name or path.is_absolute()
            or any(not part or part.endswith((".", " ")) or part.split(".")[0].upper() in
                   {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
                   for part in name.split("/"))):
        raise ValueError("Unsafe archive path.")
    return path


def extract_wheel(archive, target, cancelled=None):
    with zipfile.ZipFile(archive) as bundle:
        for item in bundle.infolist():
            relative = safe_member(item.filename.rstrip("/"))
            if (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("Archive links are not supported.")
            if item.is_dir():
                continue
            if relative.parts[0].endswith(".data"):
                if len(relative.parts) < 3 or relative.parts[1] not in {"purelib", "platlib"}:
                    continue
                relative = PurePosixPath(*relative.parts[2:])
            destination = target.joinpath(*relative.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(item) as source, destination.open("wb") as output:
                while chunk := source.read(1024 * 1024):
                    _cancel(cancelled)
                    output.write(chunk)


def download(wheel, destination, progress, cancelled):
    """Cache only verified wheels; interrupted transfers are retried on the next setup."""
    if destination.is_file() and file_hash(destination) == wheel["sha256"]:
        return
    temporary = destination.with_suffix(".part")
    try:
        digest = hashlib.sha256()
        with urlopen(Request(wheel["url"], headers={"User-Agent": USER_AGENT}), timeout=30) as response, temporary.open("wb") as output:
            from wordcel.utils.progress import content_length, download_progress
            size, received = content_length(response), 0
            while chunk := response.read(1024 * 1024):
                _cancel(cancelled)
                output.write(chunk)
                digest.update(chunk)
                received += len(chunk)
                progress(download_progress(wheel["name"], received, size))
        if digest.hexdigest() != wheel["sha256"]:
            raise ValueError("Engine download checksum mismatch. Retry setup.")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def file_hash(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def install(feature, progress=None, cancelled=None):
    if not getattr(sys, "frozen", False):
        return
    progress = progress or (lambda text: None)
    _cancel(cancelled)
    with _install_lock:
        if ready(feature):
            activate()
            return
        root = runtime_root(feature)
        root.parent.mkdir(parents=True, exist_ok=True)
        from wordcel.utils.paths import paths
        cache = Path(paths.cache_dir) / "engine-wheels"
        cache.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".install-", dir=root.parent) as temporary:
            stage = Path(temporary) / "engine"
            site = stage / "site"
            site.mkdir(parents=True)
            for wheel in manifest()["features"][feature]:
                archive = cache / (wheel["sha256"] + ".whl")
                download(wheel, archive, progress, cancelled)
                progress("Installing " + wheel["name"] + "…")
                extract_wheel(archive, site, cancelled)
            _cancel(cancelled)
            (stage / "complete.json").write_text(json.dumps(manifest()["features"][feature]), encoding="utf-8")
            if root.exists():
                root.rename(Path(temporary) / "previous")
            stage.rename(root)
        activate()
