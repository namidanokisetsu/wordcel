"""Resource readiness and explicit downloads beside each feature."""
import json
from functools import lru_cache
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QMenu, QPushButton, QVBoxLayout, QWidget


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


def translation_ready(profile):
    from wordcel.dictionary.translation import model_installed
    return model_installed(profile)


@lru_cache(maxsize=8)
def managed_translation_available(model):
    return translation_ready(model)


def profile_translation_available(settings, identity):
    from wordcel.config.profiles import profile_language
    from wordcel.dictionary.translation import load_profile_settings, local_endpoint
    from wordcel.language.support import translation_supported
    try:
        options = load_profile_settings(settings, identity)
        prefix = f"profiles/{identity}/"
        source = settings.value(prefix + "translation_source", "auto")
        target = settings.value(prefix + "translation_target", "auto")
        source = profile_language(settings, identity) if source == "auto" else source
        target = settings.value(prefix + "target", "en") if target == "auto" else target
        if not (translation_supported(source, options.provider) and translation_supported(target, options.provider)):
            return False
        if options.provider == "custom":
            return bool(local_endpoint(options.endpoint) and options.model.strip())
        return managed_translation_available(options.profile)
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
        for name in ("lightweight", "quality"):
            widget = QWidget()
            row = QHBoxLayout(widget)
            row.setContentsMargins(0, 0, 0, 0)
            download = QPushButton("Download model")
            download.setToolTip("Installed models are shared by all languages")
            download.clicked.connect(lambda checked=False, name=name: owner.begin_operation([], profile=name))
            self.downloads[name] = download
            self.model_rows[name] = widget
            row.addWidget(download)
            row.addStretch()
            layout.addWidget(widget)
        for control in (owner.translation_partner, owner.translation_source, owner.translation_target):
            control.currentIndexChanged.connect(self.refresh)
        self.refresh()

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
        source = owner.translation_source.currentData()
        target = owner.translation_target.currentData()
        source = code if source == "auto" else source
        target = owner.translation_partner.currentData() if target == "auto" else target
        supported = (owner.translation_mode.currentData() != "custom"
                     and translation_supported(source) and translation_supported(target))
        for name in self.downloads:
            ready = supported and translation_ready(name)
            selected = owner.translation_mode.currentData() == name
            self.model_rows[name].setVisible(supported and selected and not ready)
            self.downloads[name].setVisible(supported and not ready)
            self.downloads[name].setEnabled(supported and not ready and not owner.operation_busy("translation"))
        self.translation_section.setVisible(any(not row.isHidden() for row in self.model_rows.values()))
        self.refresh_actions()

    def refresh_actions(self):
        owner = self.owner
        from wordcel.utils.stroke_order_font import font_ready
        owner.appearance.content_form.setRowVisible(self.font_install, owner.appearance.japanese_controls and not font_ready())
        self.font_install.setEnabled(not owner.operation_busy("fonts"))
        ready = profile_translation_available(owner.settings, owner.profile.currentData())
        global_group = getattr(owner.settings, "editing_global", None)
        owner.appearance.set_translation_available(ready or global_group in ("appearance", "popup_all"))
        ready = ready or global_group == "shortcuts"
        owner.translation_shortcut.enabled.setEnabled(ready)
        owner.translation_shortcut.recorder.setEnabled(ready and owner.translation_shortcut.enabled.isChecked())
        if hasattr(owner, "translation_connection"):
            owner.translation_form.setRowVisible(owner.translation_connection, owner.translation_mode.currentData() == "custom")
