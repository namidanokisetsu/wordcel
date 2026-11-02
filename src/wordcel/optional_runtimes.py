"""Explicit, pinned wheel installation for frozen apps. Inference never downloads."""
from functools import lru_cache
import hashlib
import importlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import tempfile
import threading
from urllib.error import HTTPError
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
    if feature == "stanza" and restart_needed():
        raise RuntimeError("Restart Wordcel to use the newly installed word-form engine.")
    activate()
    _active.add(feature)


def restart_needed():
    if sys.platform == "win32" and "paddle" in sys.modules and "stanza" not in _active:
        from wordcel.ocr.turkish_paddle import _openmp
        return _openmp is None
    return False


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


_RANGE_PATTERN = re.compile(r"^bytes\s+(\d+)-(\d+)/(\d+|\*)$", re.IGNORECASE)
_UNSATISFIABLE_PATTERN = re.compile(r"^bytes\s+\*/(\d+|\*)$", re.IGNORECASE)


def _download_paths(destination):
    destination = Path(destination)
    temporary = destination.with_name(destination.name + ".part")
    return temporary, temporary.with_name(temporary.name + ".json")


def _response_status(response):
    return int(getattr(response, "status", getattr(response, "code", 200)) or 200)


def _response_header(response, name):
    headers = getattr(response, "headers", {})
    try:
        value = headers.get(name)
    except AttributeError:
        value = None
    return value.strip() if isinstance(value, str) and value.strip() else None


def _response_validators(response):
    return {name: value for name in ("etag", "last_modified")
            if (value := _response_header(response, "ETag" if name == "etag" else "Last-Modified"))}


def _parse_content_range(value, *, unsatisfiable=False):
    if not value:
        return None
    match = (_UNSATISFIABLE_PATTERN if unsatisfiable else _RANGE_PATTERN).fullmatch(value.strip())
    if not match:
        return None
    if unsatisfiable:
        return int(match.group(1)) if match.group(1) != "*" else None
    return int(match.group(1)), int(match.group(2)), int(match.group(3)) if match.group(3) != "*" else None


def _write_download_metadata(path, metadata):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="." + path.name + "-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(metadata, output, ensure_ascii=False, sort_keys=True)
            output.write("\n")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _discard_download(temporary, metadata):
    temporary.unlink(missing_ok=True)
    metadata.unlink(missing_ok=True)


def _partial_metadata(temporary, metadata, url, digest, size):
    if not temporary.is_file() or not metadata.is_file():
        if temporary.exists() or metadata.exists():
            _discard_download(temporary, metadata)
        return None
    try:
        stored = json.loads(metadata.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        _discard_download(temporary, metadata)
        return None
    expected = {"url": url, "sha256": digest, "size": size}
    if any(stored.get(key) != value for key, value in expected.items()):
        _discard_download(temporary, metadata)
        return None
    if not isinstance(stored.get("etag"), (str, type(None))) or not isinstance(stored.get("last_modified"), (str, type(None))):
        _discard_download(temporary, metadata)
        return None
    return stored


def _hash_file(path, cancelled=None):
    digest, size = hashlib.sha256(), 0
    with Path(path).open("rb") as source:
        while chunk := source.read(1024 * 1024):
            _cancel(cancelled)
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


def _publish_download(temporary, metadata, destination, digest, size, cancelled):
    received, actual = _hash_file(temporary, cancelled)
    if size is not None and received != size:
        if received > size:
            _discard_download(temporary, metadata)
        raise ValueError(f"Download verification failed: {destination.name} ({received:,} bytes received; {size:,} expected).")
    if actual != digest:
        _discard_download(temporary, metadata)
        raise ValueError(f"Download checksum verification failed: {destination.name}")
    _cancel(cancelled)
    os.replace(temporary, destination)
    metadata.unlink(missing_ok=True)
    return destination


def download_verified(url, destination, digest, progress=None, cancelled=None, size=None, label=None, opener=None):
    """Download a pinned artifact, retaining a validator-bound partial for resume.

    Only a complete file whose expected size and SHA256 match is published. Network
    failures and cancellation leave the partial and its metadata in place; a proven
    integrity failure removes both.
    """
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    label = label or destination.name
    opener = opener or urlopen
    _cancel(cancelled)
    if destination.is_file():
        try:
            if (size is None or destination.stat().st_size == size) and file_hash(destination) == digest:
                return destination
        except OSError:
            pass

    temporary, metadata_path = _download_paths(destination)
    metadata = _partial_metadata(temporary, metadata_path, url, digest, size)
    offset = temporary.stat().st_size if metadata else 0
    # A partial larger than the pinned artifact can never be resumed safely.
    if size is not None and offset > size:
        _discard_download(temporary, metadata_path)
        metadata, offset = None, 0

    from wordcel.utils.progress import download_progress
    response = None
    for attempt in range(3):
        _cancel(cancelled)
        headers = {"User-Agent": USER_AGENT}
        if offset:
            headers["Range"] = f"bytes={offset}-"
            validator = metadata.get("etag") or metadata.get("last_modified")
            if validator:
                headers["If-Range"] = validator
        try:
            response = opener(Request(url, headers=headers), timeout=30)
        except HTTPError as error:
            if error.code != 416 or not offset:
                raise
            total = _parse_content_range(_response_header(error, "Content-Range"), unsatisfiable=True)
            if total is not None and total != offset:
                _discard_download(temporary, metadata_path)
                metadata, offset = None, 0
                continue
            # A 416 at the end of a resource can mean the retained partial is
            # complete. Verify it before publishing; otherwise discard it.
            if size is None or offset == size:
                return _publish_download(temporary, metadata_path, destination, digest, size, cancelled)
            _discard_download(temporary, metadata_path)
            metadata, offset = None, 0
            continue

        status = _response_status(response)
        content_range = _parse_content_range(_response_header(response, "Content-Range"))
        validators = _response_validators(response)
        if offset:
            if status == 200:
                # The server ignored Range or If-Range. Restart from byte zero.
                response.close()
                _discard_download(temporary, metadata_path)
                metadata, offset = None, 0
                continue
            if status != 206 or content_range is None or content_range[0] != offset:
                response.close()
                _discard_download(temporary, metadata_path)
                metadata, offset = None, 0
                continue
            if any(metadata.get(key) and validators.get(key) != metadata[key]
                   for key in ("etag", "last_modified")):
                response.close()
                _discard_download(temporary, metadata_path)
                metadata, offset = None, 0
                continue
            total = content_range[2]
            if size is not None and total is not None and total != size:
                response.close()
                _discard_download(temporary, metadata_path)
                metadata, offset = None, 0
                continue
            mode, received = "ab", offset
        else:
            if status not in (200, 206):
                response.close()
                raise ValueError(f"Unexpected download response: HTTP {status}")
            if status == 206 and (content_range is None or content_range[0] != 0):
                response.close()
                raise ValueError("Download response has an invalid byte range.")
            mode, received = "wb", 0
            total = content_range[2] if content_range else None
            if total is None:
                try:
                    total = max(0, int(getattr(response, "headers", {}).get("Content-Length", 0))) or None
                except (TypeError, ValueError, AttributeError):
                    total = None
            if size is not None and total is not None and total != size:
                # The server advertised a complete artifact with a different
                # length. It is safe to discard after draining nothing.
                response.close()
                _discard_download(temporary, metadata_path)
                raise ValueError(f"Download verification failed: {destination.name} (unexpected size).")
        if size is not None:
            total = size
        stored = {"url": url, "sha256": digest, "size": size,
                  "etag": metadata.get("etag") if metadata else None,
                  "last_modified": metadata.get("last_modified") if metadata else None}
        stored.update(validators)
        _write_download_metadata(metadata_path, stored)
        try:
            with response, temporary.open(mode) as output:
                while chunk := response.read(1024 * 1024):
                    _cancel(cancelled)
                    output.write(chunk)
                    received += len(chunk)
                    if progress:
                        progress(download_progress(label, received, total or 0))
        except (InterruptedError, OSError):
            # Keep the partial and its metadata for a later setup attempt.
            raise
        except Exception:
            # A server-side/network exception is retryable. The file is still
            # bound to this URL and digest by its sidecar metadata.
            raise
        # An EOF shorter than an expected artifact is an incomplete transfer;
        # retain it so the next invocation can request the missing range.
        received = temporary.stat().st_size
        if size is not None and received < size:
            raise ValueError(f"Download incomplete: {destination.name} ({received:,} bytes received; {size:,} expected).")
        return _publish_download(temporary, metadata_path, destination, digest, size, cancelled)
    raise ValueError(f"Unable to resume download: {destination.name}")


def download(wheel, destination, progress, cancelled):
    """Cache only verified wheels while retaining interrupted transfers."""
    return download_verified(wheel["url"], destination, wheel["sha256"], progress, cancelled,
                             wheel.get("size"), wheel["name"])


def file_hash(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def validate(feature, site, cancelled=None):
    from wordcel.scripts.setup_morphology import _run
    _run(["--check-engine", feature, "--engine-directory", str(site)], cancelled)


def check_engine(feature):
    if feature == "paddle":
        import paddle
        import paddleocr
        from paddlex.utils.deps import require_extra
        require_extra("ocr-core")
        if paddle.ones([1]).item() != 1:
            raise RuntimeError("Paddle engine validation failed.")
    else:
        import stanza
        import torch
        if torch.ones(1).item() != 1:
            raise RuntimeError("Word-form engine validation failed.")


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
            progress("Checking engine…")
            validate(feature, site, cancelled)
            (stage / "complete.json").write_text(json.dumps(manifest()["features"][feature]), encoding="utf-8")
            previous = Path(temporary) / "previous"
            if root.exists():
                root.rename(previous)
            try:
                stage.rename(root)
            except OSError:
                if previous.exists():
                    previous.rename(root)
                raise
        activate()
