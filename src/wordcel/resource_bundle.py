"""Transfer installed resources between offline computers without copying settings."""
import hashlib
from contextlib import closing, nullcontext
import json
import os
from pathlib import Path
import platform
import shutil
import sqlite3
import tempfile
import zipfile

from wordcel.optional_runtimes import _cancel, file_hash, safe_member


_TRANSLATION_MANIFEST = "translation/installation.json"
_TRANSLATION_BACKENDS = frozenset(("automatic", "cpu", "vulkan", "cuda", "native"))


def _managed_model_spec(profile, path=None, custom=None):
    from wordcel.translation_catalog import MODELS
    spec = MODELS.get(profile)
    if spec is None and custom:
        from wordcel.translation_models import custom_models
        spec = custom_models({"custom_models": custom}).get(profile)
    if not isinstance(spec, dict) or not isinstance(spec.get("file"), str):
        raise ValueError("Unknown managed translation model.")
    if path is not None and path != "models/" + spec["file"]:
        raise ValueError("Translation model path does not match the managed catalog.")
    return spec


def _managed_model_for_path(path, custom=None):
    from wordcel.translation_catalog import MODELS
    matches = [spec for spec in MODELS.values()
               if isinstance(spec, dict) and path == "models/" + spec.get("file", "")]
    if custom:
        from wordcel.translation_models import custom_models
        matches.extend(spec for spec in custom_models({"custom_models": custom}).values()
                      if path == "models/" + spec.get("file", ""))
    if len(matches) != 1:
        raise ValueError("Unknown managed translation model.")
    return matches[0]


def _translation_relative(value, kind):
    if not isinstance(value, str) or len(value) > 512:
        raise ValueError("Invalid translation installation metadata.")
    try:
        path = safe_member(value.replace("\\", "/"))
    except (TypeError, ValueError):
        raise ValueError("Invalid translation installation metadata.") from None
    if kind == "executable":
        if len(path.parts) < 2 or not path.parts[0].startswith("runtime-"):
            raise ValueError("Invalid translation runtime path.")
    elif len(path.parts) != 2 or path.parts[0] != "models" or not path.parts[1].endswith(".gguf"):
        raise ValueError("Invalid translation model path.")
    return path.as_posix()


def _translation_runtime(value, backend=None):
    if not isinstance(value, dict):
        raise ValueError("Invalid translation runtime metadata.")
    selected = value.get("backend", backend)
    if selected is not None and selected not in _TRANSLATION_BACKENDS:
        raise ValueError("Invalid translation backend.")
    result = {}
    for key in ("release", "platform", "backend"):
        if key in value:
            if not isinstance(value[key], str) or not value[key] or len(value[key]) > 128:
                raise ValueError("Invalid translation runtime metadata.")
            result[key] = value[key]
    if selected is not None:
        result["backend"] = selected
    if "executable" not in value:
        raise ValueError("Translation runtime metadata has no executable.")
    result["executable"] = _translation_relative(value["executable"], "executable")
    return result


def _sanitize_translation_manifest(value):
    if not isinstance(value, dict):
        raise ValueError("Invalid translation installation metadata.")
    result = {}
    for key in ("release", "platform", "backend", "automatic_backend", "executable", "profile"):
        if key not in value:
            continue
        if key == "executable":
            result[key] = _translation_relative(value[key], "executable")
        elif key in {"backend", "automatic_backend"}:
            if value[key] not in _TRANSLATION_BACKENDS:
                raise ValueError("Invalid translation backend.")
            result[key] = value[key]
        elif not isinstance(value[key], str) or not value[key] or len(value[key]) > 128:
            raise ValueError("Invalid translation installation metadata.")
        else:
            result[key] = value[key]
    custom = {}
    if "custom_models" in value:
        from wordcel.translation_models import custom_models as validate_custom_models
        try:
            custom = validate_custom_models({"custom_models": value["custom_models"]})
        except ValueError as error:
            raise ValueError("Invalid custom translation model metadata.") from error
        result["custom_models"] = custom
    for key in ("runtimes", "models"):
        if key not in value:
            continue
        if not isinstance(value[key], dict) or len(value[key]) > (32 if key == "runtimes" else 64):
            raise ValueError("Invalid translation installation metadata.")
        entries = {}
        for name, item in value[key].items():
            if not isinstance(name, str) or not name or len(name) > 128:
                raise ValueError("Invalid translation installation metadata.")
            if key == "runtimes":
                if name not in _TRANSLATION_BACKENDS:
                    raise ValueError("Invalid translation backend.")
                runtime = _translation_runtime(item, name)
                if runtime.get("backend") != name:
                    raise ValueError("Translation runtime backend does not match its key.")
                entries[name] = runtime
            else:
                if not isinstance(item, dict):
                    raise ValueError("Invalid translation model metadata.")
                path = _translation_relative(item.get("path"), "model")
                spec = _managed_model_spec(name, path, custom)
                digest = item.get("sha256")
                size = item.get("size")
                if (not isinstance(digest, str) or len(digest) != 64 or
                        any(char not in "0123456789abcdefABCDEF" for char in digest) or
                        type(size) is not int or size < 0):
                    raise ValueError("Invalid translation model metadata.")
                if digest.lower() != spec["sha256"] or size != spec["size"]:
                    raise ValueError("Translation model metadata does not match its catalog.")
                model = dict(path=path, sha256=digest.lower(), size=size)
                if "url" in item:
                    if not isinstance(item["url"], str) or len(item["url"]) > 2048:
                        raise ValueError("Invalid translation model metadata.")
                    model["url"] = item["url"]
                entries[name] = model
        result[key] = entries
    return result


def _read_translation_manifest(path):
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    if len(raw.encode("utf-8")) > 1024 * 1024:
        raise ValueError("Translation installation metadata is too large.")
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        raise ValueError("Invalid translation installation metadata.") from None
    return _sanitize_translation_manifest(value)


def _roots(directory, data_root, cache_root):
    from wordcel.data_assets import _roots as data_roots
    from wordcel.dictionary.library import default_library_path
    data, cache = data_roots(data_root, cache_root)
    return {"library": Path(directory or default_library_path()).resolve(), "cache": cache, "data": data}


def _allowed(root, relative):
    parts = safe_member(relative).parts
    if root == "library":
        return len(parts) == 1 and (parts[0].endswith(".sqlite3") or parts[0].endswith(".assets"))
    if root == "cache":
        return len(parts) == 3 and parts[:2] == ("huggingface", "hub") and parts[2] in {
            "models--rtr46--meiki.text.detect.v0", "models--rtr46--meiki.txt.recognition.v0"}
    if root != "data":
        return False
    if parts == ("screen_ai",):
        return True
    if parts == tuple(_TRANSLATION_MANIFEST.split("/")):
        return True
    if len(parts) == 2 and parts[0] in {"engines", "fonts"}:
        return True
    if len(parts) == 2 and parts[0] == "translation" and parts[1].startswith("runtime-"):
        return True
    if len(parts) == 3 and parts[:2] == ("translation", "models") and parts[2].endswith(".gguf"):
        return True
    if len(parts) == 3 and parts[0] == "languages":
        from wordcel.dictionary.library import language_code
        return language_code(parts[1]) == parts[1] and (parts[2] == "stanza" or parts[1:] == ("tr", "paddle"))
    if len(parts) == 4 and parts[:3] == ("languages", "ar", "camel"):
        from wordcel.language.arabic_resources import PACKAGES
        return parts[3] in {kind + "-" + spec["version"] for kind, spec in PACKAGES.items()}
    return False


def _unlinked(path, root):
    return all(not parent.is_symlink() for parent in (path, *path.parents) if parent != root and parent.is_relative_to(root))


def _reconstruct_translation_manifest(data_root):
    """Recover readiness metadata from older bundles without installation.json."""
    translation = data_root / "translation"
    result = {}
    runtimes = {}
    for runtime in sorted(translation.glob("runtime-*")):
        if not runtime.is_dir() or runtime.is_symlink():
            continue
        metadata_path = runtime / "runtime.json"
        if metadata_path.is_file():
            metadata = _read_translation_manifest(metadata_path)
            metadata = _translation_runtime(metadata, metadata.get("backend"))
            executable = translation / metadata["executable"]
            if not executable.is_file():
                raise ValueError("Translation runtime metadata points to a missing executable.")
            backend = metadata.get("backend")
            if backend:
                runtimes[backend] = metadata
                result.setdefault("release", metadata.get("release", ""))
                result.setdefault("platform", metadata.get("platform", ""))
                result.setdefault("backend", backend)
                result.setdefault("executable", metadata["executable"])
            continue
        name = runtime.name.removeprefix("runtime-")
        platform_name = next((value for value in ("win-x64", "mac-arm64", "mac-x64")
                              if name.endswith("-" + value) or any(name.endswith("-" + value + "-" + backend)
                                                                    for backend in ("cpu", "vulkan", "cuda"))), None)
        if not platform_name:
            continue
        backend = next((value for value in ("cpu", "vulkan", "cuda") if name.endswith("-" + platform_name + "-" + value)), None)
        if backend is None:
            backend = "cuda" if platform_name.startswith("win-") else "native"
        release = name[:-(len(platform_name) + len(backend) + 2)] if name.endswith("-" + platform_name + "-" + backend) else name[:-(len(platform_name) + 1)]
        executables = [path for path in runtime.rglob("llama-server*") if path.is_file()]
        if len(executables) != 1:
            continue
        metadata = dict(release=release, platform=platform_name, backend=backend,
                        executable=executables[0].relative_to(translation).as_posix())
        runtimes[backend] = metadata
        result.setdefault("release", release)
        result.setdefault("platform", platform_name)
        result.setdefault("backend", backend)
        result.setdefault("executable", metadata["executable"])
    if runtimes:
        result["runtimes"] = runtimes
    from wordcel.translation_catalog import MODELS
    models = {}
    for profile, model in MODELS.items():
        path = translation / "models" / model["file"]
        if not path.is_file() or path.stat().st_size != model["size"]:
            continue
        if file_hash(path) != model["sha256"]:
            continue
        models[profile] = dict(path=path.relative_to(translation).as_posix(), sha256=model["sha256"], size=model["size"],
                               url=f'https://huggingface.co/tencent/{model["repo"]}/resolve/{model["revision"]}/{model["file"]}')
    if models:
        result["models"] = models
    return _sanitize_translation_manifest(result) if result else None


def _merge_translation_manifests(existing, incoming):
    merged = dict(existing or {})
    incoming = incoming or {}
    for key in ("release", "platform", "backend", "automatic_backend", "executable", "profile"):
        if key not in merged and key in incoming:
            merged[key] = incoming[key]
    for key in ("runtimes", "models", "custom_models"):
        if key in incoming or key in merged:
            values = dict(incoming.get(key, {}))
            values.update(merged.get(key, {}))
            merged[key] = values
    return _sanitize_translation_manifest(merged)


def _write_translation_manifest(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".installation-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(value, output, ensure_ascii=False, indent=2)
            output.write("\n")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def export_bundle(destination, directory, progress, cancelled, *, data_root=None, cache_root=None):
    from wordcel.data_assets import inventory
    roots = _roots(directory, data_root, cache_root)
    destination = Path(destination).resolve()
    assets = inventory(directory, data_root=roots["data"], cache_root=roots["cache"])
    units, used, payloads = [], set(), {}
    for asset in assets:
        if asset.kind in {"cache", "pending", "external", "recommended"} or asset.status not in {"Installed", "Enabled", "Disabled"}:
            continue
        for path in asset.paths:
            if not path.exists() or path.is_symlink():
                continue
            path = path.resolve()
            for name, root in roots.items():
                if path.is_relative_to(root):
                    relative = path.relative_to(root).as_posix()
                    if _allowed(name, relative) and (name, relative) not in used:
                        if destination == path or destination.is_relative_to(path):
                            raise ValueError("Choose an export location outside the installed resources.")
                        units.append((name, relative, path))
                        used.add((name, relative))
                        break
    installation = roots["data"] / _TRANSLATION_MANIFEST
    if installation.is_file():
        metadata = _read_translation_manifest(installation)
        if metadata:
            units.append(("data", _TRANSLATION_MANIFEST, installation))
            payloads[("data", _TRANSLATION_MANIFEST)] = (json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").encode()
    if not units:
        raise ValueError("No installed resources to export.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".wordcel-export-", dir=destination.parent)
    os.close(fd)
    temporary = Path(temporary)
    try:
        manifest = {"schema": 1, "platform": f"{os.sys.platform}-{platform.machine().lower()}", "units": []}
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True) as bundle:
            for index, (root, relative, path) in enumerate(units):
                _cancel(cancelled)
                progress(f"Exporting {path.name}…")
                unit = {"root": root, "path": relative, "directory": path.is_dir(), "files": []}
                payload = payloads.get((root, relative))
                if payload is not None:
                    archive_name = f"resources/{index}/file"
                    digest = hashlib.sha256(payload).hexdigest()
                    bundle.writestr(archive_name, payload)
                    unit["directory"] = False
                    unit["files"].append({"path": "file", "size": len(payload), "sha256": digest,
                                          "executable": False})
                    manifest["units"].append(unit)
                    continue
                files = sorted(path.rglob("*")) if path.is_dir() else [path]
                for source in files:
                    _cancel(cancelled)
                    if source.is_dir():
                        if source.is_symlink():
                            raise ValueError("Linked resource directories cannot be exported.")
                        continue
                    if path.is_dir() and not source.resolve().is_relative_to(path):
                        raise ValueError("Resource links must stay inside their resource folder.")
                    name = source.relative_to(path).as_posix() if path.is_dir() else "file"
                    archive_name = f"resources/{index}/{name}"
                    digest, size = hashlib.sha256(), 0
                    # Dictionary metadata can change while the app is open.
                    snapshot_context = (tempfile.TemporaryDirectory(dir=destination.parent)
                                        if root == "library" and source.suffix == ".sqlite3" else nullcontext())
                    with snapshot_context as snapshot:
                        selected = source
                        if root == "library" and source.suffix == ".sqlite3":
                            selected = Path(snapshot) / "dictionary.sqlite3"
                            with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as db, closing(sqlite3.connect(selected)) as copy:
                                db.backup(copy)
                        with selected.open("rb") as input_file, bundle.open(archive_name, "w", force_zip64=True) as output:
                            while chunk := input_file.read(1024 * 1024):
                                _cancel(cancelled)
                                digest.update(chunk)
                                size += len(chunk)
                                output.write(chunk)
                    unit["files"].append({"path": name, "size": size, "sha256": digest.hexdigest(),
                                          "executable": bool(source.stat().st_mode & 0o111)})
                manifest["units"].append(unit)
            bundle.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        _cancel(cancelled)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def import_bundle(source, directory, progress, cancelled, *, data_root=None, cache_root=None):
    roots = _roots(directory, data_root, cache_root)
    added, stages, plans = [], [], []
    incoming_manifest = None
    has_manifest_unit = False
    manifest_path = roots["data"] / _TRANSLATION_MANIFEST
    previous_manifest = manifest_path.read_bytes() if manifest_path.is_file() else None
    manifest_written = False
    try:
        with zipfile.ZipFile(source) as bundle:
            entry = bundle.getinfo("manifest.json")
            if entry.file_size > 16 * 1024**2:
                raise ValueError("Resource manifest is too large.")
            manifest = json.loads(bundle.read(entry))
            if manifest.get("schema") != 1:
                raise ValueError("Unsupported resource archive.")
            if manifest.get("platform") != f"{os.sys.platform}-{platform.machine().lower()}":
                raise ValueError("Import resources exported for this operating system and processor.")
            # Read the signed-by-the-archive translation manifest before model
            # payloads so custom filenames can be checked against their exact
            # identity during staging.
            for manifest_index, manifest_unit in enumerate(manifest.get("units", ())):
                if (isinstance(manifest_unit, dict) and manifest_unit.get("root") == "data" and
                        manifest_unit.get("path") == _TRANSLATION_MANIFEST and
                        not manifest_unit.get("directory") and len(manifest_unit.get("files", ())) == 1 and
                        manifest_unit.get("files", [{}])[0].get("path") == "file"):
                    archive_name = f"resources/{manifest_index}/file"
                    try:
                        raw_manifest = json.loads(bundle.read(archive_name))
                    except (KeyError, OSError, TypeError, ValueError):
                        raise ValueError("Invalid translation installation metadata.") from None
                    incoming_manifest = _sanitize_translation_manifest(raw_manifest)
                    break
            names = [item.filename.casefold() for item in bundle.infolist()]
            if len(names) != len(set(names)):
                raise ValueError("Duplicate archive entries.")
            expected, targets = {"manifest.json"}, []
            for index, unit in enumerate(manifest["units"]):
                _cancel(cancelled)
                root, relative = unit["root"], unit["path"]
                if not _allowed(root, relative):
                    raise ValueError("Invalid resource destination.")
                target = roots[root] / relative
                if not target.resolve().is_relative_to(roots[root]) or not _unlinked(target, roots[root]):
                    raise ValueError("Linked resource destinations cannot be imported.")
                if root == "data" and relative.startswith("engines/"):
                    from wordcel.optional_runtimes import manifest as engine_manifest, runtime_root, source_runtime_root
                    config = engine_manifest()
                    managed = config and target in [runtime_root(feature, roots["data"]) for feature in config["features"]]
                    source = next((feature for feature in ("paddle", "arabic")
                                   if target == source_runtime_root(feature, roots["data"])), None)
                    if not managed and not source:
                        raise ValueError("This engine archive requires the same Wordcel build as the exporting computer.")
                if any(target == previous or target.is_relative_to(previous) or previous.is_relative_to(target) for previous in targets):
                    raise ValueError("Overlapping resource destinations.")
                targets.append(target)
                target.parent.mkdir(parents=True, exist_ok=True)
                stage_dir = Path(tempfile.mkdtemp(prefix=".wordcel-import-", dir=target.parent))
                stages.append(stage_dir)
                stage = stage_dir / "resource"
                if unit["directory"]:
                    stage.mkdir()
                elif len(unit["files"]) != 1 or unit["files"][0]["path"] != "file":
                    raise ValueError("Invalid file resource.")
                progress(f"Importing {target.name}…")
                for item in unit["files"]:
                    name = safe_member(item["path"]).as_posix()
                    archive_name = f"resources/{index}/{name}"
                    if archive_name in expected:
                        raise ValueError("Duplicate resource file.")
                    expected.add(archive_name)
                    info = bundle.getinfo(archive_name)
                    if info.file_size != item["size"] or (info.external_attr >> 16) & 0o170000 == 0o120000:
                        raise ValueError("Invalid resource file.")
                    output_path = stage / name if unit["directory"] else stage
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    digest = hashlib.sha256()
                    with bundle.open(info) as input_file, output_path.open("wb") as output:
                        while chunk := input_file.read(1024 * 1024):
                            _cancel(cancelled)
                            digest.update(chunk)
                            output.write(chunk)
                    if digest.hexdigest() != item["sha256"]:
                        raise ValueError("Resource checksum mismatch.")
                    if item.get("executable"):
                        output_path.chmod(output_path.stat().st_mode | 0o111)
                if root == "data" and relative == _TRANSLATION_MANIFEST:
                    try:
                        raw_manifest = json.loads(stage.read_text(encoding="utf-8"))
                    except (OSError, TypeError, ValueError):
                        raise ValueError("Invalid translation installation metadata.") from None
                    incoming_manifest = _sanitize_translation_manifest(raw_manifest)
                    has_manifest_unit = True
                if root == "data" and relative.startswith("translation/models/"):
                    model_relative = safe_member(relative).as_posix().removeprefix("translation/")
                    spec = _managed_model_for_path(model_relative,
                                                   (incoming_manifest or {}).get("custom_models"))
                    if not output_path.is_file() or output_path.stat().st_size != spec["size"]:
                        raise ValueError("Managed translation model size mismatch.")
                    if file_hash(output_path) != spec["sha256"]:
                        raise ValueError("Managed translation model checksum mismatch.")
                if root == "data" and relative.startswith("engines/"):
                    feature = next((name for name in config["features"]
                                    if target == runtime_root(name, roots["data"])), None) if config else None
                    if source:
                        from wordcel.optional_runtimes import _source_paddle_ready
                        if source == "paddle":
                            if not _source_paddle_ready(stage):
                                raise ValueError("Incomplete engine archive.")
                        else:
                            from wordcel.optional_runtimes import arabic_manifest
                            if not (stage / "site").is_dir() or json.loads(
                                    (stage / "complete.json").read_text(encoding="utf-8")) != arabic_manifest():
                                raise ValueError("Incomplete Arabic engine archive.")
                    elif (feature is None or not (stage / "site").is_dir() or
                          json.loads((stage / "complete.json").read_text(encoding="utf-8")) != config["features"][feature]):
                        raise ValueError("Incomplete engine archive.")
                if target.exists() and relative != _TRANSLATION_MANIFEST:
                    for item in unit["files"]:
                        existing = target / item["path"] if unit["directory"] else target
                        if not existing.is_file() or not _unlinked(existing, roots[root]) or file_hash(existing) != item["sha256"]:
                            raise ValueError(f"{target.name} is already installed with different contents. Remove it before importing.")
                if not target.exists() and relative != _TRANSLATION_MANIFEST:
                    plans.append((stage, target))
            if expected != set(item.filename for item in bundle.infolist()):
                raise ValueError("Unexpected files in resource archive.")
            _cancel(cancelled)
            # Publish directories before dictionary indexes; existing data is never overwritten.
            for stage, target in sorted(plans, key=lambda pair: pair[1].suffix == ".sqlite3"):
                if target.exists():
                    raise ValueError("Resources changed during import. Retry import.")
                stage.rename(target)
                added.append((target, stage))
            if not has_manifest_unit:
                incoming_manifest = _reconstruct_translation_manifest(roots["data"])
                has_manifest_unit = incoming_manifest is not None
            if has_manifest_unit or manifest_path.exists():
                existing = _read_translation_manifest(manifest_path) if manifest_path.exists() else None
                merged = _merge_translation_manifests(existing, incoming_manifest)
                if merged.get("platform", "").startswith("win-"):
                    from wordcel.translation_hardware import detect_capabilities
                    merged["automatic_backend"] = detect_capabilities().select()
                elif merged.get("platform", "").startswith("mac-"):
                    merged["automatic_backend"] = "native"
                _write_translation_manifest(manifest_path, merged)
                manifest_written = True
        from wordcel.dictionary.library import library_changed
        library_changed(roots["library"])
        from wordcel.optional_runtimes import activate
        activate()
    except Exception:
        if manifest_written:
            if previous_manifest is None:
                manifest_path.unlink(missing_ok=True)
            else:
                fd, temporary = tempfile.mkstemp(prefix=".restore-installation-", dir=manifest_path.parent)
                try:
                    with os.fdopen(fd, "wb") as output:
                        output.write(previous_manifest)
                    os.replace(temporary, manifest_path)
                finally:
                    Path(temporary).unlink(missing_ok=True)
        for target, stage in reversed(added):
            target.rename(stage)
        raise
    finally:
        for stage in stages:
            shutil.rmtree(stage, ignore_errors=True)
