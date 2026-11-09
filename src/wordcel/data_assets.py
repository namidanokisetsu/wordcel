"""Inventory and removal of app-owned downloads without loading NLP or OCR models."""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
from uuid import uuid4


@dataclass(frozen=True)
class DataAsset:
    key: str
    title: str
    language: str = ""
    kind: str = ""
    value: object = ""
    paths: tuple = ()
    size: int = 0
    status: str = "Not installed"
    removable: bool = True
    identity: str = ""
    source: str = ""
    revision: str = ""
    origin: str = ""


def _roots(data_root, cache_root):
    from wordcel.utils.paths import paths
    return Path(data_root or paths.data_dir).resolve(), Path(cache_root or paths.cache_dir).resolve()


def _size(path):
    try:
        if path.is_symlink():
            return 0
        if path.is_file():
            return path.stat().st_size
    except OSError:
        return 0
    total = 0
    for folder, _, files in os.walk(path, followlinks=False):
        for name in files:
            item = Path(folder) / name
            try:
                if not item.is_symlink():
                    total += item.stat().st_size
            except OSError:
                pass
    return total


def _pending_paths(data, cache):
    parents = [data, data / "translation", data / "translation/models", data / "fonts",
               data / "engines",
               cache / "huggingface", cache / "huggingface/hub", cache / "paddlex/official_models"]
    parents.extend((data / "languages").glob("*"))
    for parent in parents:
        for path in parent.glob(".wordcel-removed-*"):
            if not re.fullmatch(r"\.wordcel-removed-[0-9a-f]{32}", path.name):
                continue
            resolved = path.resolve()
            if not path.is_symlink() and any(resolved != root and resolved.is_relative_to(root) for root in (data, cache)):
                yield path


def cleanup_removed_data(*, data_root=None, cache_root=None):
    data, cache = _roots(data_root, cache_root)
    for path in _pending_paths(data, cache):
        try:
            shutil.rmtree(path) if path.is_dir() else path.unlink()
        except OSError:
            pass


def inventory(directory, profiles=(), *, data_root=None, cache_root=None, screenai=""):
    from wordcel.dictionary.library import Library
    from wordcel.scripts.translation_server import MODELS, RELEASE, _platform_key, installation
    from wordcel.translation_models import custom_models
    from wordcel.language.support import STANZA_LANGUAGES
    from wordcel.utils.stroke_order_font import PACKAGE
    data, cache = _roots(data_root, cache_root)
    assets, languages, installed_packs = [], set(profiles), []

    def add(key, title, language="", kind="", value="", paths=(), *, removable=True, status=None,
            identity="", source="", revision="", origin=""):
        paths = tuple(Path(path) for path in paths)
        size = sum(_size(path) for path in paths) if removable else 0
        present = size > 0 if removable else any(path.exists() for path in paths)
        assets.append(DataAsset(key, title, language, kind, value, paths, size,
                                status or ("Installed" if present else "Not installed"), removable, identity, source, revision, origin))

    from wordcel.optional_runtimes import (
        manifest as engine_manifest, runtime_root, source_runtime_root, ready as engine_ready,
    )
    engine_config = engine_manifest()
    if engine_config:
        for feature in engine_config["features"]:
            root = runtime_root(feature, data)
            state = "Installed" if engine_ready(feature, data) else "Incomplete" if root.exists() else "Not installed"
            title = {"paddle": "Paddle OCR engine", "arabic": "Arabic morphology engine",
                     "arabic-context": "Arabic context engine"}.get(feature, "Word-form engine")
            add("engine:" + feature, title, "ar" if feature.startswith("arabic") else "",
                kind="engine", value=feature, paths=(root,), status=state)
    else:
        root = source_runtime_root("paddle", data)
        state = "Installed" if engine_ready("paddle", data) else "Incomplete" if root.exists() else "Not installed"
        add("engine:paddle", "Paddle OCR engine", kind="engine", value="paddle", paths=(root,), status=state)
        from wordcel.optional_runtimes import arabic_manifest
        try:
            arabic_manifest()
            for feature, title in (("arabic", "Arabic morphology engine"), ("arabic-context", "Arabic context engine")):
                root = source_runtime_root(feature, data)
                add("engine:" + feature, title, "ar", "engine", feature, (root,),
                    status="Installed" if engine_ready(feature, data) else "Incomplete" if root.exists() else "Not installed")
        except RuntimeError:
            pass
    from wordcel.language.arabic_resources import model_root as arabic_root, model_ready as arabic_ready
    for kind, title in (("morphology", "Arabic morphology · CALIMA MSA"), ("context", "Contextual Arabic analysis")):
        root = arabic_root(kind, data)
        add("arabic:" + kind, title, "ar", "morphology", "ar-context" if kind == "context" else "ar", (root,),
            status="Installed" if arabic_ready(kind, data) else "Incomplete" if root.exists() else "Not installed", source="CAMeL Tools")
    if (cache / "arabic-downloads").exists():
        add("cache:arabic", "Arabic download cache", kind="cache", paths=(cache / "arabic-downloads",))

    model_catalog = dict(MODELS)
    try:
        model_catalog.update(custom_models(installation(data / "translation")))
    except ValueError:
        # A malformed registry is reported by the installer/bundle importer;
        # inventory still lists the pinned built-ins and remains usable.
        pass
    for name, model in model_catalog.items():
        path = data / "translation/models" / model["file"]
        state = None if not path.exists() else "Installed" if path.stat().st_size == model["size"] else "Incomplete"
        add("translation:" + name, model.get("name", name),
            kind="translation", value=name, paths=(path,), status=state,
            origin=model.get("source", ""), source=model.get("repo_id", "Local GGUF" if model.get("source") == "local" else ""))
    runtimes = set((data / "translation").glob("runtime-*"))
    try:
        platform_key = _platform_key()
        for backend in (("cpu", "vulkan", "cuda") if platform_key.startswith("win-") else ("native",)):
            suffix = platform_key + "-" + backend if backend != "native" else platform_key
            runtimes.add(data / "translation" / f"runtime-{RELEASE}-{suffix}")
    except RuntimeError:
        pass
    for runtime in sorted(runtimes):
        ready = any(runtime.rglob("llama-server.exe")) or any(runtime.rglob("llama-server"))
        state = None if not runtime.exists() else "Installed" if ready else "Incomplete"
        add("runtime:" + runtime.name, "Translation runtime · " + runtime.name.removeprefix("runtime-"),
            kind="runtime", value="runtime", paths=(runtime,), status=state)
    meiki = tuple(
        cache / "huggingface/hub" / name for name in (
            "models--rtr46--meiki.text.detect.v0", "models--rtr46--meiki.txt.recognition.v0"))
    required = ((meiki[0], "meiki.text.detect.v0.1.960x544.onnx"),
                (meiki[1], "meiki.text.rec.v0.960x32.onnx"), (meiki[1], "meiki.text.rec.v0.vertical.32x480.onnx"))
    ready = all(any(path.glob("snapshots/*/" + name)) for path, name in required)
    state = "Installed" if ready else "Incomplete" if any(path.exists() for path in meiki) else None
    add("ocr:meikiocr", "MeikiOCR", kind="ocr", value="meikiocr", paths=meiki, status=state)
    from wordcel.ocr.turkish_paddle import MODELS as PADDLE_MODELS, PADDLE_FILES
    paddle = data / "languages/tr/paddle/3.7.0"
    try:
        manifest = json.loads((paddle / "manifest.json").read_text(encoding="utf-8"))
        ready = engine_ready("paddle", data) and manifest.get("models") == PADDLE_MODELS and all(
            (paddle / name / filename).is_file() for name in PADDLE_MODELS.values() for filename in PADDLE_FILES)
    except (OSError, ValueError):
        ready = False
    state = "Installed" if ready else "Incomplete" if paddle.parent.exists() else None
    add("ocr:paddle", "PaddleOCR", kind="ocr", value="paddle", paths=(
        paddle.parent, *(cache / "paddlex/official_models" / name for name in PADDLE_MODELS.values())), status=state)
    from wordcel.ocr.providers.screenai.component import find_in_directory
    ready = find_in_directory(data / "screen_ai") is not None
    state = "Installed" if ready else "Incomplete" if (data / "screen_ai").exists() else None
    add("ocr:screenai", "Chrome Screen AI", kind="ocr", value="screenai", paths=(data / "screen_ai",), status=state)
    if screenai and not Path(screenai).resolve().is_relative_to(data / "screen_ai"):
        add("ocr:screenai-external", "Chrome Screen AI", kind="external", paths=(Path(screenai),),
            removable=False, status="Linked")
    if (cache / "huggingface/xet").exists():
        add("cache:downloads", "Model download cache", kind="cache", paths=(cache / "huggingface/xet",))
    if (cache / "engine-wheels").exists():
        add("cache:engines", "Engine download cache", kind="cache", paths=(cache / "engine-wheels",))
    if (data / "translation/downloads").exists():
        add("cache:translation", "Translation download cache", kind="cache", paths=(data / "translation/downloads",))
    for path in _pending_paths(data, cache):
        assets.append(DataAsset("pending:" + str(path), "Removed files", kind="pending", paths=(path,),
                                size=_size(path), status="Clears after restart", removable=False))
    library = Library(directory)
    try:
        for path, meta, _ in library.packs:
            installed_packs.append(meta)
            code = meta["language"]
            languages.add(code)
            add("dictionary:" + path.name, meta["title"], code, "dictionary", path.name,
                (path, path.with_suffix(".assets")), status="Enabled" if meta["enabled"] else "Disabled",
                identity=meta["resource_id"], source=meta.get("source", "") or meta.get("index_url", ""),
                revision=meta.get("revision", ""), origin=meta.get("origin", ""))
    finally:
        library.close()
    for path in (data / "languages").glob("*/stanza"):
        languages.add(path.parent.name)
    if (data / "fonts" / PACKAGE).exists():
        languages.add("ja")
    for code in sorted(languages):
        # Profile codes never supply unchecked filesystem paths.
        from wordcel.dictionary.library import language_code
        try:
            valid = language_code(code) == code
        except ValueError:
            valid = False
        if not valid:
            continue
        from wordcel.dictionary.catalog import recommendations
        for recommended in recommendations(code):
            if not any(recommended.matches(meta) for meta in installed_packs):
                add("recommended:" + code + ":" + recommended.title, recommended.title, code,
                    "recommended", recommended, removable=False)
        model = data / "languages" / code / "stanza"
        if code in STANZA_LANGUAGES and code not in {"ja", "tr"}:
            from wordcel.language.stanza_analyzer import model_status, RESOURCES_VERSION
            state = None if not model.exists() else (
                "Installed" if model_status(code, model / RESOURCES_VERSION) == "Installed" else "Incomplete")
            add("stanza:" + code, "Stanza morphology", code,
                "morphology", code, (model,), status=state)
        if code in {"ja", "tr"}:
            add("builtin:" + code, "Japanese word forms" if code == "ja" else "Zeyrek morphology", code,
                status="Built in", removable=False)
        if code == "ja":
            from wordcel.utils.stroke_order_font import font_ready
            path = data / "fonts" / PACKAGE
            state = None if not path.exists() else "Installed" if font_ready(data) else "Incomplete"
            add("font:ja", "Kanji stroke-order font", "ja", "fonts", paths=(path,), status=state)
    return tuple(assets)


def resource_usage(settings, asset):
    from wordcel.config.profiles import dictionary_preferences, profile_ids, profile_language
    from wordcel.dictionary.translation import load_profile_settings
    from wordcel.language.support import default_ocr_provider
    using = []
    for identity in profile_ids(settings):
        language = profile_language(settings, identity)
        prefix = f"profiles/{identity}/"
        selected = False
        if asset.kind == "dictionary" and asset.language == language:
            preferences = dictionary_preferences(settings, identity)
            selected = preferences is None or asset.identity not in preferences["disabled"]
        elif asset.kind in {"translation", "runtime"}:
            try:
                options = load_profile_settings(settings, identity)
                selected = options.provider == "server" and options.profile == asset.value
                if options.provider == "server" and asset.kind == "runtime" and asset.paths:
                    from wordcel.scripts.translation_server import installation, _runtime_entry
                    root = asset.paths[0].parent
                    registry = installation(root)
                    runtime = _runtime_entry(registry, options.backend, root)
                    executable = str(runtime.get("executable", "")).replace("\\", "/")
                    selected = executable.split("/", 1)[0] == asset.paths[0].name
            except ValueError:
                pass
        elif asset.kind == "ocr":
            selected = settings.value(prefix + "ocr_provider", default_ocr_provider(language)) == asset.value
        elif asset.kind == "engine":
            from wordcel.language.support import STANZA_LANGUAGES
            selected = (language == "ar" if asset.value.startswith("arabic") else
                        settings.value(prefix + "ocr_provider", default_ocr_provider(language)) == "paddle"
                        if asset.value == "paddle" else language in STANZA_LANGUAGES and language not in {"ja", "tr"})
        elif asset.kind in {"fonts", "morphology"} or asset.key.startswith("builtin:"):
            selected = asset.language == language
        if selected:
            using.append(identity)
    return tuple(using)


def remove_asset(key, directory, refresh, cancelled, *, data_root=None, cache_root=None):
    if cancelled.is_set():
        raise InterruptedError("Removal cancelled.")
    data, cache = _roots(data_root, cache_root)
    assets = inventory(directory, data_root=data, cache_root=cache)
    asset = next((asset for asset in assets if asset.key == key), None)
    if asset is None or not asset.removable:
        raise ValueError("Choose an installed download.")
    if asset.kind == "dictionary":
        from wordcel.dictionary.library import remove_dictionary
        remove_dictionary(directory, asset.value, refresh, cancelled)
        return
    if asset.kind in {"translation", "runtime"}:
        from wordcel.scripts.translation_server import shutdown_server
        shutdown_server()
    if asset.key.startswith("arabic:") or asset.value in {"arabic", "arabic-context"}:
        from wordcel.language.arabic_analyzer import close_worker
        close_worker()
    staged = []
    try:
        for path in asset.paths:
            if cancelled.is_set():
                raise InterruptedError("Removal cancelled.")
            if not path.exists():
                continue
            resolved = path.resolve()
            if path.is_symlink() or not any(resolved != root and resolved.is_relative_to(root) for root in (data, cache)):
                raise ValueError("Download is outside Wordcel's data folders.")
            temporary = path.with_name(".wordcel-removed-" + uuid4().hex)
            path.rename(temporary)
            staged.append((path, temporary))
    except Exception:
        for original, temporary in reversed(staged):
            if temporary.exists() and not original.exists():
                temporary.rename(original)
        raise
    try:
        for _, temporary in staged:
            try:
                shutil.rmtree(temporary) if temporary.is_dir() else temporary.unlink()
            except PermissionError:
                # Mapped Windows files are collected after their process exits.
                pass
    finally:
        refresh()


def remove_language_data(language, directory, refresh, cancelled, *, data_root=None, cache_root=None):
    if cancelled.is_set():
        raise InterruptedError("Removal cancelled.")
    assets = inventory(directory, (language,), data_root=data_root, cache_root=cache_root)
    for asset in assets:
        if asset.language == language and asset.removable and any(path.exists() for path in asset.paths):
            remove_asset(asset.key, directory, refresh, cancelled, data_root=data_root, cache_root=cache_root)
