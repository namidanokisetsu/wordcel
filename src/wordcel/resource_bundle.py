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
    if len(parts) == 2 and parts[0] in {"engines", "fonts"}:
        return True
    if len(parts) == 2 and parts[0] == "translation" and parts[1].startswith("runtime-"):
        return True
    if len(parts) == 3 and parts[:2] == ("translation", "models") and parts[2].endswith(".gguf"):
        return True
    if len(parts) == 3 and parts[0] == "languages":
        from wordcel.dictionary.library import language_code
        return language_code(parts[1]) == parts[1] and (parts[2] == "stanza" or parts[1:] == ("tr", "paddle"))
    return False


def _unlinked(path, root):
    return all(not parent.is_symlink() for parent in (path, *path.parents) if parent != root and parent.is_relative_to(root))


def export_bundle(destination, directory, progress, cancelled, *, data_root=None, cache_root=None):
    from wordcel.data_assets import inventory
    roots = _roots(directory, data_root, cache_root)
    destination = Path(destination).resolve()
    assets = inventory(directory, data_root=roots["data"], cache_root=roots["cache"])
    units, used = [], set()
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
                    from wordcel.optional_runtimes import manifest as engine_manifest, runtime_root
                    config = engine_manifest()
                    if not config or target not in [runtime_root(feature, roots["data"]) for feature in config["features"]]:
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
                if root == "data" and relative.startswith("engines/"):
                    feature = target.name.split("-", 1)[0]
                    if (not (stage / "site").is_dir() or
                            json.loads((stage / "complete.json").read_text(encoding="utf-8")) != config["features"][feature]):
                        raise ValueError("Incomplete engine archive.")
                if target.exists():
                    for item in unit["files"]:
                        existing = target / item["path"] if unit["directory"] else target
                        if not existing.is_file() or not _unlinked(existing, roots[root]) or file_hash(existing) != item["sha256"]:
                            raise ValueError(f"{target.name} is already installed with different contents. Remove it before importing.")
                else:
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
        from wordcel.dictionary.library import library_changed
        library_changed(roots["library"])
        from wordcel.optional_runtimes import activate
        activate()
    except Exception:
        for target, stage in reversed(added):
            target.rename(stage)
        raise
    finally:
        for stage in stages:
            shutil.rmtree(stage, ignore_errors=True)
