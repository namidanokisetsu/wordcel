"""Resource readiness and explicit downloads beside each feature."""
import json
from functools import lru_cache
from pathlib import Path
import threading
from wordcel.scripts import translation_server as _translation_server

from PyQt6.QtCore import QObject, QSignalBlocker, Qt, pyqtSignal
from PyQt6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QMenu, QPushButton, QVBoxLayout, QWidget


def ocr_ready(provider, component_directory=""):
    if provider == "windows":
        from wordcel.ocr.windows_native import supported_languages
        try:
            return bool(supported_languages())
        except RuntimeError:
            return False
    if provider == "vision":
        import sys
        return sys.platform == "darwin"
    if provider == "screenai":
        from wordcel.ocr.providers.screenai.component import find_component_directory
        try:
            return bool(find_component_directory(component_directory or None))
        except RuntimeError:
            return False
    if provider == "paddle":
        from wordcel.optional_runtimes import ready
        if not ready("paddle"):
            return False
        from wordcel.ocr.turkish_paddle import MODELS, PADDLE_FILES, model_root
        root = model_root()
        try:
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            return manifest.get("models") == MODELS and all(
                (root / name / filename).is_file() and (root / name / filename).stat().st_size > 0
                for name in MODELS.values() for filename in PADDLE_FILES)
        except (OSError, ValueError):
            return False
    if provider == "meikiocr":
        from huggingface_hub import try_to_load_from_cache
        models = (("rtr46/meiki.text.detect.v0", "meiki.text.detect.v0.1.960x544.onnx"),
                  ("rtr46/meiki.txt.recognition.v0", "meiki.text.rec.v0.960x32.onnx"),
                  ("rtr46/meiki.txt.recognition.v0", "meiki.text.rec.v0.vertical.32x480.onnx"))
        try:
            files = [try_to_load_from_cache(repo, filename) for repo, filename in models]
            return all(isinstance(file, str) and Path(file).is_file() and Path(file).stat().st_size > 0 for file in files)
        except (OSError, ValueError):
            return False
    return False


def translation_ready(profile, backend="automatic"):
    from wordcel.dictionary.translation import model_installed
    return model_installed(profile) if backend == "automatic" else model_installed(profile, backend)


@lru_cache(maxsize=8)
def managed_translation_available(model, backend="automatic"):
    return translation_ready(model) if backend == "automatic" else translation_ready(model, backend)


def profile_translation_available(settings, identity):
    from wordcel.config.profiles import profile_language
    from wordcel.dictionary.translation import load_profile_settings, local_endpoint
    from wordcel.language.support import translation_supported
    if not settings.value(f"profiles/{identity}/translation_enabled", True, bool):
        return False
    try:
        options = load_profile_settings(settings, identity)
        prefix = f"profiles/{identity}/"
        source = settings.value(prefix + "translation_source", "auto")
        target = settings.value(prefix + "translation_target", "auto")
        source = profile_language(settings, identity) if source == "auto" else source
        target = settings.value(prefix + "target", "en") if target == "auto" else target
        from wordcel.translation_models import is_custom_profile
        language_provider = "custom" if is_custom_profile(options.profile) else options.provider
        if not (translation_supported(source, language_provider) and translation_supported(target, language_provider)):
            return False
        if options.provider == "custom":
            return bool(local_endpoint(options.endpoint) and options.model.strip())
        return managed_translation_available(options.profile) if options.backend == "automatic" else managed_translation_available(options.profile, options.backend)
    except (ValueError, TypeError):
        return False


class ResourcesPanel(QWidget):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.hide()
        self.downloads, self.model_rows = {}, {}
        self.font_install = owner.appearance.font_install
        self.font_install.clicked.connect(lambda: owner.begin_operation([], fonts=True))

        self.dictionary_section = QWidget(self)
        layout = QVBoxLayout(self.dictionary_section)
        layout.setContentsMargins(0, 0, 0, 0)
        self.dictionary_status = QLabel()
        layout.addWidget(self.dictionary_status)
        self.dictionary_install = QPushButton("Download missing recommendations")
        self.dictionary_install.clicked.connect(self.install_dictionaries)
        layout.addWidget(self.dictionary_install, alignment=Qt.AlignmentFlag.AlignLeft)
        self.dictionary_choose = QPushButton("Choose recommendation…")
        self.dictionary_choose.setMenu(QMenu(self.dictionary_choose))
        layout.addWidget(self.dictionary_choose, alignment=Qt.AlignmentFlag.AlignLeft)
        self.base_status = QLabel()
        layout.addWidget(self.base_status)
        self.base_install = QPushButton("Download word-form support")
        self.base_install.setToolTip("Recognize inflected words using an optional offline model")
        self.base_install.clicked.connect(lambda: owner.begin_operation([], morphology=owner.editing_language))
        layout.addWidget(self.base_install, alignment=Qt.AlignmentFlag.AlignLeft)

        self.ocr_section = QWidget(self)
        layout = QHBoxLayout(self.ocr_section)
        layout.setContentsMargins(0, 0, 0, 0)
        self.ocr_install = QPushButton()
        self.ocr_install.clicked.connect(lambda: owner.begin_operation([], ocr=owner.current_ocr_control().currentData()))
        layout.addWidget(self.ocr_install)
        layout.addStretch()

        self.translation_section = QWidget(self)
        layout = QVBoxLayout(self.translation_section)
        layout.setContentsMargins(0, 0, 0, 0)
        self.translation_layout = layout
        self.ensure_model_rows()
        for control in (owner.translation_partner, owner.translation_source, owner.translation_target):
            control.currentIndexChanged.connect(self.refresh)
        self.refresh()

    def ensure_model_rows(self):
        from wordcel.translation_models import model_catalog
        for name in model_catalog():
            if name in self.downloads:
                continue
            widget = QWidget()
            row = QHBoxLayout(widget)
            row.setContentsMargins(0, 0, 0, 0)
            download = QPushButton("Download model")
            download.setToolTip("Installed models are shared by all languages")
            download.clicked.connect(lambda checked=False, name=name: self.install_model(name))
            self.downloads[name] = download
            self.model_rows[name] = widget
            row.addWidget(download)
            row.addStretch()
            self.translation_layout.addWidget(widget)

    def install_model(self, identity):
        from wordcel.translation_models import model_catalog
        spec = model_catalog().get(identity, {})
        if spec.get("source") == "local":
            self.owner.import_translation_model()
        else:
            self.owner.begin_operation([], profile=identity)

    def install_dictionaries(self):
        if self.missing_dictionaries:
            self.owner.begin_operation([], recommended=self.missing_dictionaries)

    def refresh(self):
        owner = self.owner
        code = owner.editing_language
        if not code:
            return
        from wordcel.dictionary.library import Library
        library = Library(owner.directory)
        try:
            from wordcel.config.profiles import dictionary_preferences
            library.set_preferences(dictionary_preferences(owner.settings, owner.profile.currentData()))
            packs = [meta for path, meta, db in library.packs if meta['language'] == code]
        finally:
            library.close()
        from wordcel.dictionary.catalog import recommendations
        dictionaries = recommendations(code)
        self.missing_dictionaries = tuple(item for item in dictionaries if not any(item.matches(meta) for meta in packs))
        self.dictionary_install.setVisible(bool(self.missing_dictionaries))
        self.dictionary_install.setEnabled(bool(self.missing_dictionaries) and not owner.operation_busy("dictionaries"))
        self.dictionary_install.setToolTip("\n".join(item.title for item in self.missing_dictionaries))
        menu = self.dictionary_choose.menu()
        menu.clear()
        for item in self.missing_dictionaries:
            menu.addAction(item.title, lambda checked=False, item=item: owner.begin_operation([], recommended=item))
        self.dictionary_choose.setVisible(bool(self.missing_dictionaries))
        self.dictionary_choose.setEnabled(bool(self.missing_dictionaries) and not owner.operation_busy("dictionaries"))
        enabled = sum(bool(meta["enabled"]) for meta in packs)
        self.dictionary_status.setText(f"Dictionaries: {len(packs)} installed, {enabled} enabled" if packs else "No dictionaries installed")
        owner.combine_frequencies.setVisible(sum(int(meta.get("frequencies", 0)) > 0 for meta in packs if meta["enabled"]) > 1)
        has_packs = bool(packs)
        owner.packs.setVisible(has_packs)
        for control in (owner.up, owner.down):
            control.setVisible(has_packs)
        provider = owner.current_ocr_control()
        from wordcel.language.support import ocr_supported, translation_supported
        item = provider.model().item(provider.currentIndex())
        available = bool(provider.currentData() and item is not None and item.isEnabled()
                         and ocr_supported(code, provider.currentData()))
        ready = available and ocr_ready(provider.currentData(), owner.screenai_directory.text())
        downloadable = available and not ready and provider.currentData() not in {"screenai", "vision", "windows"}
        self.ocr_install.setText("Download " + provider.currentText().split(" (")[0] if available else "Download OCR")
        self.ocr_section.setVisible(downloadable)
        self.ocr_install.setVisible(downloadable)
        self.ocr_install.setEnabled(downloadable and not owner.operation_busy("ocr"))
        from wordcel.language.stanza_analyzer import model_status
        from wordcel.language.support import STANZA_LANGUAGES
        supported = code in STANZA_LANGUAGES and code not in {"ja", "tr"}
        ready = supported and model_status(code) == "Installed"
        from wordcel.language.turkish_analyzer import available
        turkish = code == "tr" and available()
        engines = [name for name, installed in (("Zeyrek", turkish), ("Stanza", ready)) if installed]
        self.base_status.setText("Word forms: " + " + ".join(engines))
        self.base_status.setVisible(bool(engines))
        self.base_status.setToolTip("Offline Turkish morphology" if turkish else
                                   "Offline base-form lookup")
        self.base_install.setText("Download word-form support")
        self.base_install.setVisible(supported and not ready)
        self.dictionary_section.show()
        self.base_install.setEnabled(not owner.operation_busy("morphology"))
        if code == "ar":
            from wordcel.language.arabic_resources import available, transfer_size
            from wordcel.optional_runtimes import arabic_manifest, manifest
            camel = available()
            try:
                supported = "arabic" in manifest()["features"] if manifest() else bool(arabic_manifest())
            except RuntimeError:
                supported = False
            self.base_status.setText("Word forms: " + " + ".join(
                name for name, installed in (("CALIMA MSA", camel), ("Stanza", ready)) if installed))
            self.base_status.setVisible(camel or ready)
            size = transfer_size()
            self.base_install.setText("Download Arabic morphology" + (f" ({size / 1e6:.1f} MB)" if size is not None else ""))
            self.base_install.setVisible(supported and not camel)
        self.refresh_translation()
        self.refresh_actions()

    def refresh_translation(self):
        owner = self.owner
        code = owner.editing_language
        from wordcel.language.support import translation_supported
        source = owner.translation_source.currentData()
        target = owner.translation_target.currentData()
        source = code if source == "auto" else source
        target = owner.translation_partner.currentData() if target == "auto" else target
        from wordcel.translation_models import is_custom_profile
        language_provider = "custom" if is_custom_profile(owner.translation_mode.currentData()) else "server"
        supported = (owner.translation_mode.currentData() != "custom"
                     and translation_supported(source, language_provider) and translation_supported(target, language_provider))
        self.ensure_model_rows()
        from wordcel.translation_models import model_catalog
        catalog = model_catalog()
        for name in self.downloads:
            ready = supported and translation_ready(name, owner.translation_backend.currentData())
            selected = owner.translation_mode.currentData() == name
            self.model_rows[name].setVisible(supported and selected and not ready)
            cost = translation_transfer_size(name, owner.translation_backend.currentData(), owner.translation_capabilities,
                                             owner.translation_verified)
            local = catalog.get(name, {}).get("source") == "local"
            self.downloads[name].setText("Import model" if local else "Download model" + (f" ({cost / 1e6:.0f} MB)" if cost is not None else ""))
            self.downloads[name].setVisible(supported and not ready)
            self.downloads[name].setEnabled(supported and not ready and not owner.operation_busy("translation"))
        self.translation_section.setVisible(any(not row.isHidden() for row in self.model_rows.values()))

    def refresh_actions(self):
        owner = self.owner
        from wordcel.utils.stroke_order_font import font_ready
        owner.appearance.content_form.setRowVisible(self.font_install, owner.appearance.japanese_controls and not font_ready())
        self.font_install.setEnabled(not owner.operation_busy("fonts"))
        ready = profile_translation_available(owner.settings, owner.profile.currentData())
        owner.appearance.set_translation_available(ready)
        owner.translation_shortcut.setToolTip("" if ready else "Set up Translation to use this shortcut")


_preparation_lock = threading.Lock()
_prepared_capabilities = None
_verified_downloads = {}


class ResourcePreparation(QObject):
    """One worker prepares driver capability and verified cache costs."""
    finished = pyqtSignal(object, object)

    def __init__(self, parent):
        super().__init__(parent)
        import threading
        self.thread = threading.Thread(target=self.run, daemon=True, name="resource-capabilities")

    def run(self):
        from wordcel.translation_hardware import detect_capabilities
        RUNTIMES, _sha256, translation_path = _translation_server.RUNTIMES, _translation_server._sha256, _translation_server.translation_path
        global _prepared_capabilities
        with _preparation_lock:
            if _prepared_capabilities is None:
                _prepared_capabilities = detect_capabilities()
            capabilities, verified = _prepared_capabilities, set()
            root = translation_path()
            artifacts = [(root / "downloads" / name, name, digest)
                         for name, digest in set(asset for assets in RUNTIMES.values() for asset in assets)]
            from wordcel.translation_models import model_catalog
            for identity, model in model_catalog(root).items():
                repo = model.get("repo") or model.get("repo_id", "").replace("/", "--")
                if repo and model.get("revision"):
                    source_file = model.get("source_file", model["file"])
                    artifacts.append((root / "downloads/huggingface" / repo / model["revision"] / source_file,
                                      model["file"], model["sha256"]))
            for path, name, digest in artifacts:
                try:
                    stat = path.stat()
                    signature = stat.st_size, stat.st_mtime_ns, digest
                    cached = _verified_downloads.get(path)
                    if cached is None or cached[0] != signature:
                        cached = signature, _sha256(path) == digest
                        _verified_downloads[path] = cached
                    if cached[1]:
                        verified.add(name)
                except OSError:
                    pass
        try:
            self.finished.emit(capabilities, verified)
        except RuntimeError:
            pass


def translation_transfer_size(profile, backend="automatic", capabilities=None, verified=(), directory=None):
    """None denotes an unknown runtime cost, never an estimated completion time."""
    MODELS, RUNTIMES = _translation_server.MODELS, _translation_server.RUNTIMES
    RUNTIME_SIZES, RELEASE = _translation_server.RUNTIME_SIZES, _translation_server.RELEASE
    _platform_key = _translation_server._platform_key
    installation, translation_path = _translation_server.installation, _translation_server.translation_path
    from wordcel.translation_models import model_catalog
    root = translation_path(directory)
    model = model_catalog(root).get(profile)
    if model is None:
        return None
    installed = installation(root)
    entry = installed.get("models", {}).get(profile, {})
    target = root / "models" / model["file"]
    size = 0 if model["file"] in verified or (entry.get("size") == model["size"] and target.is_file() and target.stat().st_size == model["size"]) else model["size"]
    try:
        platform_key = _platform_key()
        if platform_key.startswith("win-"):
            if capabilities is None:
                return None
            backend = capabilities.select(backend)
            key = platform_key + "-" + backend
        else:
            backend, key = "native", platform_key
        runtime = root / f"runtime-{RELEASE}-{key}"
        if backend == "cuda" and (root / f"runtime-{RELEASE}-{platform_key}").is_dir():
            runtime = root / f"runtime-{RELEASE}-{platform_key}"
        if any(runtime.rglob("llama-server.exe")) or any(runtime.rglob("llama-server")):
            return size
        for name, digest in RUNTIMES[key]:
            if name not in verified:
                if name not in RUNTIME_SIZES:
                    return None
                size += RUNTIME_SIZES[name]
        return size
    except (RuntimeError, KeyError):
        return None


def transfer_label(known, unknown=False):
    return (f"Download: {known / 1e6:.1f} MB" + (" + unknown" if unknown else "")) if known else \
        ("Download size unknown" if unknown else "No download needed")
