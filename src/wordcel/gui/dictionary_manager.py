"""Explicit, offline dictionary and translation setup."""
from pathlib import Path
import sys
import threading

from PyQt6.QtCore import QObject, QSignalBlocker, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QListWidget,
    QInputDialog, QLineEdit, QListWidgetItem, QMessageBox, QPushButton, QScrollArea, QSpinBox, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from wordcel.dictionary.library import Library, default_library_path, language_code, save_preferences
from wordcel.dictionary.translation import TranslationSettings, load_settings, load_profile_settings, save_profile_settings
from wordcel.gui.quick_lookup import LANGUAGE_NAMES, language_name, default_text_shortcut, shortcut_preset, audio_autoplay_mode
from wordcel.gui.shortcut_edit import ShortcutEdit
from wordcel.gui.settings_section import SettingsSection, StatusLabel, align_form_columns
from wordcel.language.profiles import configured_profiles, default_partner, visible_profiles
from wordcel.config.profiles import (profile_ids, profile_language, profile_name, create_profile, delete_profile,
                                     dictionary_preferences, languages as profile_languages)


def setup_resource(key):
    if key.startswith("engine:"):
        return "ocr" if key == "engine:paddle" else "morphology"
    kind = key.split(":", 1)[0]
    return {"dictionary": "dictionaries", "recommended": "dictionaries", "runtime": "translation",
            "stanza": "morphology", "font": "fonts", "cache": "all"}.get(kind, kind)


class SetupOperation(QObject):
    progress = pyqtSignal(str)
    finished = pyqtSignal(str, bool)
    refresh = pyqtSignal()

    def __init__(self, paths, directory, language=None, profile=None, recommended=None, remove=None, morphology=None, ocr=None, fonts=False,
                 asset=None, remove_language=None, update=None, bundle=None, engine=None):
        super().__init__()
        self.paths = paths
        self.directory = directory
        self.language = language
        self.profile = profile
        self.recommended = recommended
        self.remove = remove
        self.morphology = morphology
        self.ocr = ocr
        self.fonts = fonts
        self.asset, self.remove_language = asset, remove_language
        self.update = update
        self.bundle, self.engine = bundle, engine
        self.resource = ("all" if remove_language or bundle else setup_resource("engine:" + engine) if engine else setup_resource(asset) if asset else
                         "translation" if profile else "ocr" if ocr else "morphology" if morphology else
                         "fonts" if fonts else "dictionaries")
        self.installed_component = ""
        self.cancelled = threading.Event()
        self.thread = threading.Thread(target=self._run, name="dictionary-setup", daemon=True)
        from wordcel.gui.resource_jobs import jobs
        self.jobs = jobs
        self.job_keys = ((asset,) if asset else ("translation:" + profile,) if profile else
                         ("ocr:" + ocr,) if ocr else ("stanza:" + morphology,) if morphology else
                         ("font:ja",) if fonts else ("dictionary:" + remove,) if remove else
                         tuple("dictionary:" + item.identity for item in recommended) if isinstance(recommended, tuple) else
                         ("dictionary:" + recommended.identity,) if recommended else
                         tuple("dictionary:" + item.identity for item in update) if isinstance(update, list) else
                         ("dictionary:" + update[1],) if update else ("dictionary-import",))
        if self.resource == "all":
            self.job_keys = ("all",)
        elif engine:
            self.job_keys = ("engine:" + engine,)

    def start(self):
        if not self.jobs.claim(self.job_keys, self, self.cancelled, "Preparing download…"):
            self.finished.emit("Resource already downloading.", False)
            return
        self.thread.start()

    def _emit(self, signal, *args):
        if signal == self.progress:
            self.jobs.progress(self, args[0])
        elif signal == self.finished:
            self.jobs.finish(self)
        try:
            signal.emit(*args)
        except RuntimeError:
            pass

    def _run(self):
        if self.bundle or self.engine:
            try:
                progress = lambda text: self._emit(self.progress, text)
                if self.engine:
                    from wordcel.optional_runtimes import install
                    install(self.engine, progress, self.cancelled)
                    status, changed = "Engine installed.", True
                    from wordcel.optional_runtimes import restart_needed
                    if self.engine == "stanza" and restart_needed():
                        status = "Engine installed. Restart Wordcel to use it."
                else:
                    from wordcel.resource_bundle import export_bundle, import_bundle
                    mode, path = self.bundle
                    operation = export_bundle if mode == "export" else import_bundle
                    operation(path, self.directory, progress, self.cancelled)
                    status, changed = ("Resources exported.", False) if mode == "export" else ("Resources imported. Restart Wordcel to use new engines.", True)
                self._emit(self.finished, status, changed)
            except Exception as error:
                self._emit(self.finished, str(error), False)
            return
        if self.update is not None:
            try:
                from wordcel.dictionary.import_job import background_import
                result = background_import([], self.directory, None, None,
                                           lambda text: self._emit(self.progress, text), self.cancelled, update=self.update)
                self._emit(self.finished, *result)
            except Exception as error:
                self._emit(self.finished, str(error), False)
            return
        if self.asset or self.remove_language:
            try:
                from wordcel.data_assets import remove_asset, remove_language_data
                remove = remove_language_data if self.remove_language else remove_asset
                remove(self.remove_language or self.asset, self.directory, lambda: self._emit(self.refresh), self.cancelled)
                self._emit(self.finished, "Data removed.", True)
            except Exception as error:
                self._emit(self.finished, str(error), False)
            return
        if self.fonts:
            try:
                from wordcel.scripts.setup_stroke_order_font import install
                install(lambda text: self._emit(self.progress, text), self.cancelled)
                self._emit(self.finished, "Stroke-order font installed.", True)
            except Exception as error:
                self._emit(self.finished, str(error), False)
            return
        if isinstance(self.recommended, tuple):
            from wordcel.dictionary.import_job import background_import
            changed, errors = False, []
            for dictionary in self.recommended:
                if self.cancelled.is_set():
                    break
                try:
                    status, installed = background_import([], self.directory, dictionary.language, dictionary,
                                                         lambda text: self._emit(self.progress, text), self.cancelled)
                    changed |= installed
                    if not installed:
                        errors.append(f"{dictionary.title}: {status}")
                except Exception as error:
                    errors.append(f"{dictionary.title}: {error}")
            status = "Download cancelled." if self.cancelled.is_set() else "Dictionaries installed."
            self._emit(self.finished, "\n".join(errors) or status, changed)
            return
        if self.paths or self.recommended:
            try:
                from wordcel.dictionary.import_job import background_import
                result = background_import(self.paths, self.directory, self.language, self.recommended,
                                           lambda text: self._emit(self.progress, text), self.cancelled)
                self._emit(self.finished, *result)
            except Exception as error:
                self._emit(self.finished, str(error), False)
            return
        if self.ocr:
            try:
                from wordcel.scripts.setup_ocr import install
                self.installed_component = install(self.ocr, lambda text: self._emit(self.progress, text), self.cancelled)
                self._emit(self.finished, "OCR ready. Scan with your selected shortcut.", True)
            except Exception as error:
                self._emit(self.finished, str(error), False)
            return
        if self.morphology:
            try:
                from wordcel.scripts.setup_morphology import install
                install(self.morphology, lambda text: self._emit(self.progress, text), self.cancelled)
                from wordcel.optional_runtimes import restart_needed
                status = "Word-form support installed. Restart Wordcel to use it." if restart_needed() else "Base-form model installed."
                self._emit(self.finished, status, True)
            except Exception as error:
                self._emit(self.finished, str(error), False)
            return
        if self.remove:
            try:
                from wordcel.dictionary.library import remove_dictionary
                remove_dictionary(self.directory, self.remove, lambda: self._emit(self.refresh), self.cancelled)
                status = "Dictionary removed."
                self._emit(self.finished, status, True)
            except Exception as error:
                self._emit(self.finished, str(error), False)
            return
        if self.profile:
            try:
                from wordcel.scripts.translation_server import install_model
                options = dict(runtime_only=True) if self.profile == "runtime" else dict(profile=self.profile)
                install_model(progress=lambda value: self._emit(self.progress, value), cancelled=self.cancelled, **options)
                self._emit(self.finished, "Model installed. Translate when ready.", True)
            except InterruptedError:
                self._emit(self.finished, "Download cancelled.", False)
            except Exception as error:
                self._emit(self.finished, str(error), False)
            return
        self._emit(self.finished, "No dictionaries selected.", False)


from wordcel.gui.settings_navigation import SettingsNavigation


class SetupDialog(SettingsNavigation, QDialog):
    dictionaries_changed = pyqtSignal()
    sections_ready = pyqtSignal(str, object)

    def __init__(self, directory, settings, apply_shortcut, parent=None):
        super().__init__(parent)
        self.directory = Path(directory or default_library_path())
        self._section_capabilities = {}
        self._section_scans = set()
        self.sections_ready.connect(self._sections_ready)
        from wordcel.config.profiles import migrate
        from wordcel.config.inheritance import PreferenceSettings, migrate_defaults, raw_settings
        migrate(raw_settings(settings), directory)
        migrate_defaults(settings)
        self.settings = settings = PreferenceSettings(settings)
        self._apply_shortcut = apply_shortcut
        self.operation = None
        self.operations = {}
        self._close_pending = False
        self._loading = True
        self._imported_languages = ()
        self.setWindowTitle("Wordcel Settings")
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.resize(700, 520)
        layout = QVBoxLayout(self)
        profile_row = QHBoxLayout()
        self.profile = QComboBox()
        self.profile.setToolTip("Profile to edit")
        for code in profile_ids(settings):
            self.profile.addItem(profile_name(settings, code), code)
        self.profile.setCurrentIndex(max(0, self.profile.findData(settings.value("profile", ""))))
        profile_row.addWidget(QLabel("Profile"))
        profile_row.addWidget(self.profile, 1)
        self.add_profile_button = QPushButton("New…")
        self.add_profile_button.clicked.connect(self.choose_profile)
        profile_row.addWidget(self.add_profile_button)
        self.remove_profile_button = QPushButton("Delete")
        self.remove_profile_button.clicked.connect(self.remove_profile)
        profile_row.addWidget(self.remove_profile_button)
        self.profile_header = QWidget()
        self.profile_header.setLayout(profile_row)
        self.activate_button = QPushButton("Activate")
        self.activate_button.clicked.connect(self.activate_profile)
        profile_row.addWidget(self.activate_button)
        self.profile_name = QLineEdit()
        self.profile_name.editingFinished.connect(self.rename_profile)
        self.profile_language_label = QLabel()
        header_form = QFormLayout()
        header_form.addRow("Name", self.profile_name)
        header_form.addRow("Lookup language", self.profile_language_label)
        self.profile_details = QWidget()
        self.profile_details.setLayout(header_form)
        layout.addWidget(self.profile_header)
        layout.addWidget(self.profile_details)
        tabs = QTabWidget()
        self.tabs = tabs
        layout.addWidget(tabs, 1)
        dictionaries = QWidget()
        dictionary_layout = QVBoxLayout(dictionaries)
        self.packs = QListWidget()
        self.packs.setAccessibleName("Installed dictionaries, in priority order")
        self.packs.setToolTip("Checked dictionaries are enabled. Higher dictionaries appear first.")
        dictionary_layout.addWidget(self.packs, 1)
        self.dictionary_display = QComboBox()
        self.dictionary_display.setAccessibleName("Default dictionary display")
        for label, value in (("Shown", "expanded"), ("Collapsed", "collapsed")):
            self.dictionary_display.addItem(label, value)
        self.dictionary_display.setToolTip("Initial display for this dictionary; pinning keeps this choice")
        self.dictionary_display.currentIndexChanged.connect(self.save_dictionary_display)
        self.packs.currentItemChanged.connect(self.update_dictionary_display)
        dictionary_layout.addWidget(self.dictionary_display)
        from wordcel.dictionary.wiktionary_sections import SECTIONS
        self.section_controls = {}
        for kind, label in SECTIONS.items():
            control = QCheckBox(label)
            control.hide()
            control.toggled.connect(lambda checked, kind=kind: self.save_dictionary_section(kind, checked))
            self.section_controls[kind] = control
            dictionary_layout.addWidget(control)
        actions = QHBoxLayout()
        self.import_button = QPushButton("Import ZIPs…")
        self.import_button.clicked.connect(self.choose_dictionaries)
        actions.addWidget(self.import_button)
        self.language = QComboBox()
        self.language.setEditable(True)
        self.language.setAccessibleName("Language for dictionaries without language metadata")
        self.language.addItem("Automatic", None)
        for code, name in LANGUAGE_NAMES.items():
            self.language.addItem(name, code)
        self.language.setToolTip("Archive language is used when available. Otherwise choose a language or type its code.")
        self.language.hide()
        self.up = QPushButton("↑")
        self.up.setToolTip("Higher priority")
        self.up.clicked.connect(lambda: self.move_pack(-1))
        actions.addWidget(self.up)
        self.down = QPushButton("↓")
        self.down.setToolTip("Lower priority")
        self.down.clicked.connect(lambda: self.move_pack(1))
        actions.addWidget(self.down)
        self.remove_pack = QPushButton("Remove")
        self.remove_pack.setToolTip("Remove the selected dictionary from all profiles")
        self.remove_pack.clicked.connect(self.remove_dictionary)
        actions.addWidget(self.remove_pack)
        actions.addStretch()
        dictionary_layout.insertLayout(0, actions)
        self.combine_frequencies = QCheckBox("Combine frequency rankings")
        self.combine_frequencies.setToolTip("Harmonic mean across enabled rank dictionaries; best matching rank per dictionary")
        self.combine_frequencies.toggled.connect(self.save_frequency_display)
        dictionary_layout.addWidget(self.combine_frequencies)
        dictionary_layout.addStretch()
        translation = QWidget()
        translation_layout = QVBoxLayout(translation)
        translation_form = QFormLayout()
        self.translation_form = translation_form
        self.translation_advanced_widget = QWidget()
        advanced_form = self.translation_advanced_form = QFormLayout(self.translation_advanced_widget)
        self.translation_pair_label = QLabel()
        self.translation_partner = QComboBox()
        translation_form.addRow(self.translation_pair_label, self.translation_partner)
        from wordcel.gui.language_strip import LanguageStrip
        self.translation_source = LanguageStrip({})
        self.translation_target = LanguageStrip({})
        for label, control in (("From", self.translation_source), ("To", self.translation_target)):
            advanced_form.addRow(label, control)
        self.translation_mode = QComboBox()
        self.translation_mode.addItem("Quality (8 GB)", "quality")
        self.translation_mode.addItem("Lightweight (1.9 GB)", "lightweight")
        self.translation_mode.addItem("Custom local server", "custom")
        self.translation_mode.setToolTip("Sizes are downloads. Running a model needs additional memory.")
        translation_form.addRow("Model", self.translation_mode)
        self.translation_endpoint = QLineEdit()
        self.translation_endpoint.setAccessibleName("Local translation server address")
        advanced_form.addRow("Address", self.translation_endpoint)
        self.translation_model = QLineEdit()
        self.translation_model.setAccessibleName("Local translation server model name")
        advanced_form.addRow("Server model", self.translation_model)
        self.translation_stream = QCheckBox("Stream translation")
        advanced_form.addRow(self.translation_stream)
        self.translation_split = QCheckBox("Side-by-side text panes")
        self.translation_split.setChecked(settings.value(f"profiles/{self.profile.currentData()}/translation_side_by_side", False, bool))
        translation_form.addRow(self.translation_split)
        self.translation_split.toggled.connect(lambda enabled: self.autosave(lambda: self.save_translation_layout(enabled)))
        self.translation_chunk_size = QSpinBox()
        self.translation_chunk_size.setRange(256, 2000)
        self.translation_chunk_size.setSuffix(" characters")
        self.translation_chunk_size.setToolTip("Split long text into passages for translation")
        advanced_form.addRow("Passage size", self.translation_chunk_size)
        self.translation_warm = QCheckBox("Keep model warm")
        self.translation_warm.setToolTip("Retains model memory after use. Changes apply on the next translation.")
        advanced_form.addRow(self.translation_warm)
        translation_layout.addLayout(translation_form)
        self.translation_advanced = QCheckBox("Advanced")
        self.translation_advanced.toggled.connect(self.translation_advanced_widget.setVisible)
        translation_layout.addWidget(self.translation_advanced)
        translation_layout.addWidget(self.translation_advanced_widget)
        self.translation_advanced_widget.hide()
        translation_layout.addStretch()
        translation_error = ""
        try:
            translation_settings = load_profile_settings(settings, self.profile.currentData())
        except ValueError as error:
            translation_settings = TranslationSettings()
            translation_error = str(error)
        self.translation_mode.setCurrentIndex(self.translation_mode.findData(
            translation_settings.profile if translation_settings.provider == "server" else "custom"))
        self.translation_endpoint.setText(translation_settings.endpoint)
        self.translation_model.setText(translation_settings.model)
        self.translation_stream.setChecked(translation_settings.stream)
        self.translation_chunk_size.setValue(translation_settings.chunk_size)
        self.translation_warm.setChecked(translation_settings.keep_warm)
        self.translation_mode.currentIndexChanged.connect(self.update_translation_controls)
        self.update_translation_controls()

        shortcuts = QWidget()
        shortcut_layout = QFormLayout(shortcuts)
        app_page = QWidget()
        app_layout = QFormLayout(app_page)
        shared_shortcuts = QWidget()
        shared_layout = QFormLayout(shared_shortcuts)
        shared_layout.setContentsMargins(0, 0, 0, 0)
        self.scan_key = QComboBox()
        for label, value in (("None", ""), ("Shift", "shift"), ("Ctrl", "ctrl"), ("Alt", "alt"),
                             ("Ctrl + Shift", "ctrl+shift"), ("Ctrl + Alt", "ctrl+alt"), ("Alt + Shift", "alt+shift")):
            self.scan_key.addItem(label, value)
        if sys.platform == "darwin":
            self.scan_key.addItem("Command", "cmd")
            self.scan_key.addItem("Command + Shift", "cmd+shift")
        self.scan_mouse = QComboBox()
        for label, value in (("None", ""), ("Middle mouse", "middle"), ("Mouse 4", "mouse4"), ("Mouse 5", "mouse5")):
            self.scan_mouse.addItem(label, value)
        shortcut_layout.addRow("Screen lookup key", self.scan_key)
        shortcut_layout.addRow("Screen lookup mouse", self.scan_mouse)
        self.block_scan_keys = QCheckBox("Block scan keys in fullscreen")
        self.block_scan_keys.setToolTip("Keep screen lookup keys from reaching fullscreen apps, including each key in a combination")
        if sys.platform == "win32":
            shortcut_layout.addRow(self.block_scan_keys)
        self.pin_shortcut = ShortcutEdit("c", "C")
        self.pin_shortcut.setMaximumWidth(190)
        self.pin_shortcut.enabled.setText("Key")
        self.pin_shortcut.enabled.setToolTip("Enable keyboard pinning")
        self.pin_shortcut.setToolTip("Pin the preview while holding the screen lookup shortcut")
        self.shortcut = ShortcutEdit(settings.value(f"profiles/{self.profile.currentData()}/hotkey", default_text_shortcut()),
                                     settings.value(f"profiles/{self.profile.currentData()}/hotkey_preset", shortcut_preset()))
        self.shortcut.setToolTip("Look up selected or copied text")
        shared_layout.addRow("Text lookup", self.shortcut)
        self.translation_shortcut = ShortcutEdit(settings.value(f"profiles/{self.profile.currentData()}/translation_hotkey", ""),
            settings.value(f"profiles/{self.profile.currentData()}/translation_hotkey_preset", "Ctrl+Shift+T"))
        shortcut_layout.addRow("Translate", self.translation_shortcut)
        self.translation_shortcut.enabled.toggled.connect(lambda _: self.autosave(self.save_translation_shortcut))
        self.translation_shortcut.recorder.editingFinished.connect(lambda: self.autosave(self.save_translation_shortcut))
        self.hover_shortcut = ShortcutEdit(settings.value(f"profiles/{self.profile.currentData()}/hover_hotkey", ""),
            settings.value(f"profiles/{self.profile.currentData()}/hover_hotkey_preset", "Ctrl+Shift+H"))
        shortcut_layout.addRow("Toggle hover scan", self.hover_shortcut)
        self.hover_shortcut.enabled.toggled.connect(lambda _: self.autosave(self.save_hover_shortcut))
        self.hover_shortcut.recorder.editingFinished.connect(lambda: self.autosave(self.save_hover_shortcut))
        self.hover_startup = QCheckBox("Enable hover scan at startup")
        self.hover_startup.setChecked(settings.value("hover_scan/startup", False, bool))
        self.hover_startup.toggled.connect(lambda enabled: settings.setValue("hover_scan/startup", enabled))
        shared_layout.addRow(self.hover_startup)
        self.close_on_cursor_leave = QCheckBox("Close popup when cursor leaves")
        self.close_on_cursor_leave.setToolTip("Includes pinned popups")
        self.close_on_cursor_leave.setChecked(settings.value(f"profiles/{self.profile.currentData()}/close_on_cursor_leave", False, bool))
        self.close_on_cursor_leave.toggled.connect(lambda enabled: self.autosave(lambda: settings.setValue(f"profiles/{self.profile.currentData()}/close_on_cursor_leave", enabled)))
        shared_layout.addRow(self.close_on_cursor_leave)
        self.cursor_close_margin = QSpinBox()
        self.cursor_close_margin.setRange(0, 300)
        self.cursor_close_margin.setSuffix(" px")
        self.cursor_close_margin.setValue(settings.value(f"profiles/{self.profile.currentData()}/cursor_close_margin", 24, int))
        self.cursor_close_margin.setEnabled(self.close_on_cursor_leave.isChecked())
        self.close_on_cursor_leave.toggled.connect(self.cursor_close_margin.setEnabled)
        self.cursor_close_margin.valueChanged.connect(lambda value: self.autosave(lambda: settings.setValue(f"profiles/{self.profile.currentData()}/cursor_close_margin", value)))
        shared_layout.addRow("Cursor grace area", self.cursor_close_margin)
        self.selected_text = QCheckBox("Look up selected text automatically")
        shortcut_layout.addRow(self.selected_text)
        self.selected_text.toggled.connect(self.save_text_triggers)
        self.selection_lookup = QCheckBox("Look up selection inside results")
        shortcut_layout.addRow(self.selection_lookup)
        self.selection_lookup.toggled.connect(lambda _: self.autosave(self.save_selection_policy))
        if sys.platform == "win32":
            from wordcel.utils.startup import is_startup_enabled
            self.start_with_windows = QCheckBox("Start with Windows")
            self.start_with_windows.setChecked(is_startup_enabled())
            self.start_with_windows.toggled.connect(self.save_startup)
            app_layout.addRow(self.start_with_windows)

        scanning = QWidget()
        scan_layout = QFormLayout(scanning)
        self.scan_layout = scan_layout
        self.freeze_while_held = QCheckBox("Freeze capture while holding the lookup key")
        self.freeze_while_held.setToolTip("One screenshot per hold. Release to refresh; the video keeps playing.")
        scan_layout.addRow(self.freeze_while_held)
        self.freeze_while_held.toggled.connect(lambda _: self.autosave(self.save_capture_settings))
        self.pin_gesture = QComboBox()
        for label, code in (("Left click", "left"), ("Middle click", "middle"),
                            ("Popup click only", "popup")):
            self.pin_gesture.addItem(label, code)
        self.pin_gesture.setCurrentIndex(max(0, self.pin_gesture.findData(settings.value("pin_gesture", "left"))))
        self.pin_gesture.setToolTip("Mouse button to pin while holding a screen lookup shortcut")
        pin_controls = QWidget()
        pin_layout = QHBoxLayout(pin_controls)
        pin_layout.setContentsMargins(0, 0, 0, 0)
        pin_layout.addWidget(self.pin_shortcut)
        pin_layout.addWidget(self.pin_gesture)
        shortcut_layout.insertRow(2, "Pin while holding lookup", pin_controls)
        self.ja_ocr_provider = QComboBox()
        self.ja_ocr_provider.addItem("MeikiOCR (CPU)", "meikiocr")
        self.ja_ocr_provider.addItem("PaddleOCR (multilingual)", "paddle")
        self.ja_ocr_provider.addItem("Chrome Screen AI (local)", "screenai")
        if sys.platform == "win32":
            self.ja_ocr_provider.addItem("Windows OCR (local)", "windows")
        if sys.platform == "darwin":
            self.ja_ocr_provider.addItem("Apple Vision", "vision")
        default_provider = "vision" if sys.platform == "darwin" else "meikiocr"
        self.ja_ocr_provider.setCurrentIndex(max(0, self.ja_ocr_provider.findData(settings.value("profiles/ja/ocr_provider", default_provider))))
        scan_layout.addRow("OCR model", self.ja_ocr_provider)
        self.tr_ocr_provider = QComboBox()
        self.tr_ocr_provider.addItem("PaddleOCR (local)", "paddle")
        self.tr_ocr_provider.addItem("Chrome Screen AI (local)", "screenai")
        if sys.platform == "win32":
            self.tr_ocr_provider.addItem("Windows OCR (local)", "windows")
        if sys.platform == "darwin":
            self.tr_ocr_provider.addItem("Apple Vision", "vision")
        tr_default = "vision" if sys.platform == "darwin" else "paddle"
        self.tr_ocr_provider.setCurrentIndex(max(0, self.tr_ocr_provider.findData(settings.value("profiles/tr/ocr_provider", tr_default))))
        scan_layout.addRow("OCR model", self.tr_ocr_provider)
        self.other_ocr_provider = QComboBox()
        self.other_ocr_provider.addItem("PaddleOCR (multilingual)", "paddle")
        self.other_ocr_provider.addItem("Chrome Screen AI (local)", "screenai")
        if sys.platform == "win32":
            self.other_ocr_provider.addItem("Windows OCR (local)", "windows")
        if sys.platform == "darwin":
            self.other_ocr_provider.addItem("Apple Vision", "vision")
        scan_layout.addRow("OCR model", self.other_ocr_provider)
        self.screenai_controls = QWidget()
        component_layout = QVBoxLayout(self.screenai_controls)
        component_layout.setContentsMargins(0, 0, 0, 0)
        folder_row = QHBoxLayout()
        self.screenai_directory = QLineEdit(settings.value("screenai_directory", ""))
        self.screenai_directory.setPlaceholderText("Find installed component automatically")
        self.screenai_directory.setToolTip("Extract the complete Google component, then choose its folder. Restart after replacing a loaded component.")
        folder_row.addWidget(self.screenai_directory, 1)
        choose_component = QPushButton("Browse…")
        choose_component.clicked.connect(self.choose_screenai)
        folder_row.addWidget(choose_component)
        component_layout.addLayout(folder_row)
        from wordcel.ocr.providers.screenai.component import component_url
        component_link = QLabel(f'<a href="{component_url()}">Get the Google component for this computer</a>')
        component_link.setOpenExternalLinks(True)
        component_layout.addWidget(component_link)
        scan_layout.addRow(self.screenai_controls)
        def show_component_controls():
            provider = self.current_ocr_control()
            item = provider.model().item(provider.currentIndex())
            self.screenai_controls.setVisible(provider.currentData() == "screenai" and item is not None and item.isEnabled())
        self.show_component_controls = show_component_controls
        self.ja_ocr_provider.currentIndexChanged.connect(show_component_controls)
        self.tr_ocr_provider.currentIndexChanged.connect(show_component_controls)
        self.other_ocr_provider.currentIndexChanged.connect(show_component_controls)
        show_component_controls()
        from wordcel.gui.profile_appearance import ProfileAppearance
        self.appearance = ProfileAppearance(settings, self.profile.currentData, self.apply_appearance)
        audio = QWidget()
        audio_layout = QVBoxLayout(audio)
        audio_playback = QWidget()
        audio_form = QFormLayout(audio_playback)
        audio_layout.addWidget(audio_playback)
        audio_details = QWidget()
        audio_detail_form = QFormLayout(audio_details)
        self.audio_autoplay = QComboBox()
        for label, mode in (("Off", "off"), ("On lookup", "lookup"), ("When pinned", "pin")):
            self.audio_autoplay.addItem(label, mode)
        audio_form.addRow("Autoplay", self.audio_autoplay)
        self.audio_volume = QSpinBox()
        self.audio_volume.setRange(0, 100)
        audio_form.addRow("Volume", self.audio_volume)
        self.audio_database = QLineEdit()
        self.audio_database.setPlaceholderText("Local Audio Server android.db")
        audio_browse = QPushButton("Browse…")
        audio_browse.clicked.connect(self.choose_audio)
        self.audio_database_row = QWidget()
        database_layout = QHBoxLayout(self.audio_database_row)
        database_layout.setContentsMargins(0, 0, 0, 0)
        database_layout.addWidget(self.audio_database, 1)
        database_layout.addWidget(audio_browse)
        self.audio_remove = QPushButton("Remove")
        self.audio_remove.setToolTip("Disconnect this database without deleting its file")
        self.audio_remove.clicked.connect(self.remove_audio_database)
        database_layout.addWidget(self.audio_remove)
        audio_detail_form.addRow("Local database", self.audio_database_row)
        from wordcel.gui.audio_sources import AudioSources
        self.audio_sources = AudioSources()
        self.audio_sources.changed.connect(lambda: self.autosave(self.save_audio))
        audio_detail_form.addRow("Source priority", self.audio_sources)
        audio_layout.addWidget(SettingsSection("Sources", audio_details))
        audio_layout.addStretch()
        self.audio_form = audio_detail_form
        self.audio_browse = audio_browse
        self.audio_tab = audio
        self.audio_autoplay.currentIndexChanged.connect(self.save_autoplay)
        from wordcel.gui.anki import AnkiSettingsPanel
        self.anki = AnkiSettingsPanel(settings)
        from wordcel.gui.popup_shortcuts import POPUP_ACTIONS
        popup_shortcuts = QWidget()
        popup_form = QFormLayout(popup_shortcuts)
        self.popup_shortcuts = {}
        row = self.anki.shortcut_form.takeRow(self.anki.shortcut)
        row.labelItem.widget().deleteLater()
        self.anki.shortcut.enabled.toggled.disconnect(self.anki._save)
        self.anki.shortcut.recorder.editingFinished.disconnect(self.anki._save)
        for action, label, default in POPUP_ACTIONS:
            control = self.anki.shortcut if action == "anki" else ShortcutEdit(default if action == "copy_text" else "", default)
            self.popup_shortcuts[action] = control
            popup_form.addRow(label, control)
            control.enabled.toggled.connect(lambda _: self.autosave(self.save_popup_shortcuts))
            control.recorder.editingFinished.connect(lambda: self.autosave(self.save_popup_shortcuts))
        popup_form.addRow("Scroll", QLabel("↑ / ↓ · Page Up / Down · Home / End"))
        popup_form.addRow("Close popup", QLabel("Esc"))
        self.appearance.side_button_scrolling.toggled.disconnect(self.appearance.save)
        self.appearance.side_button_scrolling.toggled.connect(lambda enabled: self.autosave(
            lambda: self.settings.setValue(f"profiles/{self.profile.currentData()}/side_button_scrolling", enabled)))
        self.appearance.pinned_form.takeRow(self.appearance.side_button_scrolling)
        popup_form.addRow(self.appearance.side_button_scrolling)
        if hasattr(parent, "update_anki"):
            self.anki.changed.connect(parent.update_anki)
            self.anki.changed.connect(parent.scan_settings_changed.emit)

        self.jobs_layout = QVBoxLayout()
        layout.addLayout(self.jobs_layout)
        self.status = StatusLabel()
        self.audio_sources.failed.connect(self.status.setText)
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.status)
        footer = QHBoxLayout()
        tutorial = QPushButton("Tutorial")
        tutorial.setFlat(True)
        tutorial.setStyleSheet("color: palette(mid);")
        tutorial.clicked.connect(self.show_tutorial)
        footer.addWidget(tutorial)
        footer.addStretch()
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setVisible(False)
        self.cancel_button.clicked.connect(self.cancel_operation)
        footer.addWidget(self.cancel_button)
        done = QPushButton("Close")
        done.clicked.connect(self.reject)
        footer.addWidget(done)
        layout.addLayout(footer)
        self.reload()
        self.packs.itemChanged.connect(lambda _: self.save_dictionaries())
        self.profile.currentIndexChanged.connect(self.profile_changed)
        self.profile_changed()
        self._loading = False
        for control in (self.translation_partner, self.translation_source, self.translation_target, self.translation_mode):
            control.currentIndexChanged.connect(lambda _: self.autosave(self.save_translation))
        for control in (self.translation_endpoint, self.translation_model):
            control.editingFinished.connect(lambda: self.autosave(self.save_translation))
        self.translation_stream.toggled.connect(lambda _: self.autosave(self.save_translation))
        self.translation_chunk_size.valueChanged.connect(lambda _: self.autosave(self.save_translation))
        self.translation_warm.toggled.connect(lambda _: self.autosave(lambda: self.save_translation(cancel=False)))
        for control in (self.scan_key, self.scan_mouse):
            control.currentIndexChanged.connect(lambda _: self.autosave(self.save_screen_shortcut))
        self.block_scan_keys.toggled.connect(lambda _: self.autosave(self.save_screen_shortcut))
        for control, callback in ((self.shortcut, self.save_shortcut), (self.pin_shortcut, self.save_pin_shortcut)):
            control.recorder.editingFinished.connect(lambda callback=callback: self.autosave(callback))
            control.enabled.toggled.connect(lambda _, callback=callback: self.autosave(callback))
        self.pin_gesture.currentIndexChanged.connect(lambda _: self.autosave(self.save_capture_settings))
        for control in (self.ja_ocr_provider, self.tr_ocr_provider, self.other_ocr_provider):
            control.currentIndexChanged.connect(lambda _: self.autosave(self.save_scan_settings))
        self.screenai_directory.editingFinished.connect(lambda: self.autosave(self.save_scan_settings))
        self.audio_volume.valueChanged.connect(lambda _: self.autosave(self.save_audio))
        self.audio_database.editingFinished.connect(lambda: self.autosave(self.save_audio))
        from wordcel.gui.resources import ResourcesPanel
        self.resources = ResourcesPanel(self)
        dictionary_layout.insertWidget(0, self.resources.dictionary_section)
        scan_layout.addRow(self.resources.ocr_section)
        translation_layout.insertWidget(1, self.resources.translation_section)

        # Keep one destination per task, with downloads beside the feature they enable.
        def add_page(widget, title):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            scroll.setWidget(widget)
            tabs.addTab(scroll, title)
            return scroll

        lookup = QWidget()
        lookup_layout = QVBoxLayout(lookup)
        resume = QPushButton("Resume setup")
        resume.setFlat(True)
        resume.clicked.connect(self.resume_setup)
        lookup_layout.addWidget(resume, alignment=Qt.AlignmentFlag.AlignLeft)
        for control in (self.selected_text, self.selection_lookup):
            shortcut_layout.takeRow(control)
            lookup_layout.addWidget(control)
        text_row = shared_layout.takeRow(self.shortcut)
        text_row.labelItem.widget().deleteLater()
        shortcut_layout.addRow("Text lookup", self.shortcut)
        self.screen_section = SettingsSection("Screen recognition", scanning)
        self.screen_section.toggle.setChecked(not self.resources.ocr_section.isHidden())
        lookup_layout.addWidget(self.screen_section)
        shared_layout.takeRow(self.hover_startup)
        app_layout.addRow(self.hover_startup)
        self.preload_ocr = QCheckBox("Preload OCR")
        self.preload_ocr.setChecked(settings.value("ocr/preload", True, bool))
        self.preload_ocr.setToolTip("Prepare the active OCR engine in the background")
        def save_preload(enabled):
            settings.setValue("ocr/preload", enabled)
            if self.parent() is not None:
                self.parent().scan_settings_changed.emit()
        self.preload_ocr.toggled.connect(save_preload)
        app_layout.addRow(self.preload_ocr)
        self.appearance.pinned_form.takeRow(self.appearance.snap_scrolling)
        self.appearance.snap_scrolling.toggled.disconnect(self.appearance.save)
        shared_layout.addRow(self.appearance.snap_scrolling)
        self.appearance.snap_scrolling.toggled.connect(lambda enabled: self.autosave(
            lambda: self.settings.setValue(f"profiles/{self.profile.currentData()}/snap_scrolling", enabled)))
        translation_form.takeRow(self.translation_split)
        shared_layout.addRow(self.translation_split)
        lookup_layout.addStretch()
        self.lookup_tab = add_page(lookup, "Lookup")
        shortcut_page = QWidget()
        shortcut_page_layout = QVBoxLayout(shortcut_page)
        for title, content in (("Lookup", shortcuts), ("Popup", popup_shortcuts)):
            section = SettingsSection(title, content)
            section.toggle.setChecked(True)
            shortcut_page_layout.addWidget(section)
        shortcut_page_layout.addStretch()
        from wordcel.gui.preference_groups import PreferenceGroups
        self.preference_groups = PreferenceGroups(self)
        self.shortcuts_tab = add_page(self.preference_groups.wrap("shortcuts", shortcut_page), "Shortcuts")
        align_form_columns(shortcut_layout, popup_form)
        add_page(dictionaries, "Dictionaries")
        add_page(self.preference_groups.wrap("appearance", self.appearance), "Appearance")
        add_page(self.preference_groups.wrap("popup", shared_shortcuts), "Popup")
        audio_layout.removeWidget(audio_playback)
        audio_layout.insertWidget(0, self.preference_groups.wrap("audio", audio_playback))
        self.audio_tab = add_page(audio, "Audio")
        self.translation_tab = add_page(translation, "Translation")
        self.anki_tab = add_page(self.anki, "Anki")
        from wordcel.gui.data_manager import DataPanel
        self.data = DataPanel(self)
        self.data_tab = add_page(self.data, "Storage")
        self.app_tab = add_page(app_page, "App")
        self.preference_groups.add_global_audio(add_page)
        self.initial_profile = QComboBox()
        app_layout.addRow("Start with profile", self.initial_profile)
        self.initial_profile.currentIndexChanged.connect(lambda: self.settings.setValue("initial_profile", self.initial_profile.currentData()) if not self._loading else None)
        self.cycle_shortcuts = {}
        for key, title, preset in (("next_profile", "Next profile", "Ctrl+Alt+PgDown"),
                                   ("previous_profile", "Previous profile", "Ctrl+Alt+PgUp")):
            editor = ShortcutEdit(settings.value(key + "_hotkey", ""), settings.value(key + "_hotkey_preset", preset))
            app_layout.addRow(title, editor)
            self.cycle_shortcuts[key] = editor
            editor.enabled.toggled.connect(lambda _, key=key, editor=editor: self.save_cycle_shortcut(key, editor))
            editor.recorder.editingFinished.connect(lambda key=key, editor=editor: self.save_cycle_shortcut(key, editor))
        self.connection_list = QComboBox()
        self.connection_endpoint = QLineEdit()
        self.connection_key = QLineEdit()
        self.connection_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.connection_model = QLineEdit()
        app_layout.addRow("Connection", self.connection_list)
        app_layout.addRow("Address", self.connection_endpoint)
        app_layout.addRow("API key", self.connection_key)
        app_layout.addRow("Server model", self.connection_model)
        connection_buttons = QWidget()
        connection_buttons_layout = QHBoxLayout(connection_buttons)
        connection_buttons_layout.setContentsMargins(0, 0, 0, 0)
        for kind, label in (("anki", "Add Anki connection"), ("translation", "Add translation server")):
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, kind=kind: self.add_connection(kind))
            connection_buttons_layout.addWidget(button)
        app_layout.addRow(connection_buttons)
        self.connection_list.currentIndexChanged.connect(self.load_connection)
        for editor in (self.connection_endpoint, self.connection_key, self.connection_model):
            editor.editingFinished.connect(self.save_connection)
        self.reload_connections()
        self.profile_connection = QComboBox()
        self.anki.layout().insertWidget(1, self.profile_connection)
        self.profile_connection.currentIndexChanged.connect(self.save_anki_connection)
        # Shared connection editors live only on App; profiles choose a reference.
        self.anki.connection_section.hide()
        self.translation_connection = QComboBox()
        translation_form.addRow("Server connection", self.translation_connection)
        self.translation_connection.currentIndexChanged.connect(self.select_translation_connection)
        self.translation_endpoint.hide()
        self.translation_model.hide()
        self.translation_advanced_form.setRowVisible(self.translation_endpoint, False)
        self.translation_advanced_form.setRowVisible(self.translation_model, False)
        for control in (self.close_on_cursor_leave, self.appearance.snap_scrolling, self.translation_split):
            control.toggled.connect(lambda _: self.autosave(lambda: self.preference_groups.apply("popup")))
        self.cursor_close_margin.valueChanged.connect(lambda _: self.autosave(lambda: self.preference_groups.apply("popup")))
        self.appearance.side_button_scrolling.toggled.connect(lambda _: self.autosave(self.notify_scan_settings))
        self.build_sidebar(layout, tabs)
        self.appearance.translation_hint.linkActivated.connect(lambda _: self.tabs.setCurrentWidget(self.translation_tab))
        self.rebuild_profiles()
        tabs.setCurrentWidget(self.lookup_tab)
        tabs.currentChanged.connect(lambda: self.resources.refresh())
        if translation_error:
            self.status.setText(translation_error)

    def autosave(self, callback):
        if not self._loading and self.profile.currentData():
            callback()

    def resume_setup(self):
        if self.parent() is not None:
            from wordcel.gui.first_run import offer_resources
            offer_resources(self.parent(), self.profile.currentData(), force=True, tutorial=False)

    def show_tutorial(self):
        if self.parent() is not None:
            from wordcel.gui.first_run import show_tutorial
            self.hide()
            show_tutorial(self.parent(), self.profile.currentData())

    def save_startup(self, enabled):
        from wordcel.utils.startup import set_startup_enabled
        try:
            set_startup_enabled(enabled)
        except OSError:
            with QSignalBlocker(self.start_with_windows):
                self.start_with_windows.setChecked(not enabled)
            self.status.setText("Could not change Windows startup.")
            return
        self.settings.setValue("start_with_windows", bool(enabled))

    def show_audio(self):
        self.tabs.setCurrentWidget(self.audio_tab)

    def show_anki(self):
        self.tabs.setCurrentWidget(self.anki_tab)

    def reload(self, preserve=False):
        selected = self.packs.currentItem().data(Qt.ItemDataRole.UserRole) if self.packs.currentItem() else None
        prior = {self.packs.item(i).data(Qt.ItemDataRole.UserRole): self.packs.item(i).checkState()
                 for i in range(self.packs.count())} if preserve else {}
        order = list(prior)
        library = Library(self.directory)
        try:
            blocker = QSignalBlocker(self.packs)
            self.packs.clear()
            packs = sorted(library.packs, key=lambda pack:
                           order.index(pack[0].name) if pack[0].name in order else len(order))
            self._imported_languages = tuple(dict.fromkeys(metadata["language"] for _, metadata, _ in packs))
            library.set_preferences(dictionary_preferences(self.settings, self.profile.currentData()))
            packs = list(library.packs)
            from wordcel.dictionary.wiktionary_sections import is_wiktionary
            from wordcel.dictionary.catalog import recommendations
            section_paths = []
            for path, metadata, _ in packs:
                if is_wiktionary(metadata["title"]) and path.name not in self._section_scans:
                    self._section_scans.add(path.name)
                    section_paths.append(path)
                recommended = next((rec for rec in recommendations(metadata["language"]) if rec.matches(metadata)), None)
                origin = {"recommended": "Downloaded recommendation", "imported": "Imported ZIP"}.get(
                    metadata.get("origin"), "Source unknown")
                if recommended and metadata.get("origin") != "recommended":
                    origin += "; also recommended"
                item = QListWidgetItem(f'{metadata["title"]}  ({origin})')
                item.setToolTip(f'{origin}\n{int(metadata.get("entries", 0)):,} entries')
                item.setData(Qt.ItemDataRole.UserRole, path.name)
                item.setData(Qt.ItemDataRole.UserRole + 1, metadata["language"])
                item.setData(Qt.ItemDataRole.UserRole + 2, metadata["title"])
                item.setData(Qt.ItemDataRole.UserRole + 3, int(metadata.get("entries", 0)) > 0)
                item.setData(Qt.ItemDataRole.UserRole + 4, metadata["resource_id"])
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(prior.get(path.name, Qt.CheckState.Checked if metadata["enabled"]
                                            else Qt.CheckState.Unchecked))
                self.packs.addItem(item)
                if path.name == selected:
                    self.packs.setCurrentItem(item)
                item.setHidden(metadata["language"] != self.editing_language)
            if library.errors:
                self.status.setText("\n".join(library.errors))
        finally:
            del blocker
            library.close()
        if section_paths:
            threading.Thread(target=self._scan_sections, args=(section_paths,),
                             name="dictionary-sections", daemon=True).start()
        self.update_dictionary_display()
        self.update_translation_languages()
        self.remove_profile_button.setEnabled(self.operation is None and self.profile.count() > 1)

    def _scan_sections(self, paths):
        import sqlite3
        from wordcel.dictionary.wiktionary_sections import pack_sections
        for path in paths:
            try:
                stat = path.stat()
                sections = pack_sections(path.resolve(), stat.st_mtime_ns, stat.st_size)
            except (OSError, sqlite3.Error, ValueError):
                sections = frozenset()
            try:
                self.sections_ready.emit(path.name, sections)
            except RuntimeError:
                return

    def _sections_ready(self, filename, sections):
        self._section_capabilities[filename] = sections
        self.update_dictionary_display()

    def save_dictionary_section(self, kind, shown):
        item = self.packs.currentItem()
        if self._loading or item is None or not self.section_controls[kind].isEnabled():
            return
        profile = self.profile.currentData()
        source = item.data(Qt.ItemDataRole.UserRole + 4)
        key = f"profiles/{profile}/hidden_{kind}_dictionaries"
        sources = set(self.settings.value(key, [], type=list))
        sources.discard(source)
        if not shown:
            sources.add(source)
        self.settings.setValue(key, sorted(sources))
        parent = self.parent()
        if parent is not None and parent.active_profile == profile:
            parent._render(static=True, preserve_scroll=True)

    def update_dictionary_display(self, *_):
        item = self.packs.currentItem()
        valid = (item is not None and item.data(Qt.ItemDataRole.UserRole + 1) == self.editing_language
                 and item.data(Qt.ItemDataRole.UserRole + 3))
        self.dictionary_display.setEnabled(bool(valid))
        self.dictionary_display.setVisible(bool(valid))
        capabilities = self._section_capabilities.get(item.data(Qt.ItemDataRole.UserRole), ()) if valid else ()
        for kind, control in self.section_controls.items():
            available = kind in capabilities
            control.setVisible(available)
            control.setEnabled(available)
            hidden = self.settings.value(
                f"profiles/{self.profile.currentData()}/hidden_{kind}_dictionaries", [], type=list)
            with QSignalBlocker(control):
                control.setChecked(not valid or item.data(Qt.ItemDataRole.UserRole + 4) not in hidden)
        mode = "expanded"
        if valid:
            source = item.data(Qt.ItemDataRole.UserRole + 4)
            for candidate in ("expanded", "collapsed"):
                sources = self.settings.value(f"profiles/{self.profile.currentData()}/{candidate}_dictionaries", [], type=list)
                if source in sources:
                    mode = candidate
        with QSignalBlocker(self.dictionary_display):
            self.dictionary_display.setCurrentIndex(self.dictionary_display.findData(mode))

    def save_dictionary_display(self, *_):
        item = self.packs.currentItem()
        if self._loading or item is None or not self.dictionary_display.isEnabled():
            return
        source = item.data(Qt.ItemDataRole.UserRole + 4)
        mode = self.dictionary_display.currentData()
        profile = self.profile.currentData()
        for candidate in ("expanded", "collapsed"):
            key = f"profiles/{profile}/{candidate}_dictionaries"
            sources = set(self.settings.value(key, [], type=list))
            sources.discard(source)
            if mode == candidate:
                sources.add(source)
            self.settings.setValue(key, sorted(sources))
        parent = self.parent()
        if parent is not None and parent.active_profile == profile:
            parent.set_dictionary_display(item.data(Qt.ItemDataRole.UserRole + 2), mode)

    @property
    def editing_language(self):
        return profile_language(self.settings, self.profile.currentData())

    def choose_profile(self):
        from wordcel.language.support import profile_languages as supported_languages
        from wordcel.gui.language_chooser import choose_language
        choices = {code: language_name(code) for code in supported_languages(self._imported_languages, profile_languages(self.settings))}
        code = choose_language(self, choices, title="New profile")
        if code:
            self.add_profile(code)

    def add_profile(self, code):
        identity = create_profile(self.settings, code)
        self.rebuild_profiles(identity)
        if self.parent() is not None:
            self.parent().update_languages()
            from wordcel.gui.first_run import offer_resources
            offer_resources(self.parent(), identity, tutorial=False)

    def duplicate_profile(self):
        identity = create_profile(self.settings, self.editing_language,
                                  self.profile.currentText() + " copy", self.profile.currentData())
        self.rebuild_profiles(identity)
        if self.parent() is not None:
            self.parent().update_languages()

    def rename_profile(self):
        name = self.profile_name.text().strip()
        if name:
            self.settings.setValue(f"profiles/{self.profile.currentData()}/name", name)
            self.rebuild_profiles(self.profile.currentData())
            if self.parent() is not None:
                self.parent().update_languages()

    def activate_profile(self):
        if self.parent() is not None:
            self.parent().set_mode(self.profile.currentData())
        else:
            self.settings.setValue("profile", self.profile.currentData())
        self.update_active_label()

    def update_active_label(self):
        active = self.settings.value("profile", "")
        self.highlight_active_profile(active)
        self.activate_button.setEnabled(active != self.profile.currentData())

    def remove_profile(self):
        identity = self.profile.currentData()
        if self.profile.count() < 2:
            return
        if QMessageBox.question(self, "Delete profile", f"Delete {self.profile.currentText()}? Downloaded resources will be kept.",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self._forget_profile(identity)

    def _forget_profile(self, identity):
        active = self.settings.value("profile", "")
        replacement = delete_profile(self.settings, identity)
        self.rebuild_profiles(replacement)
        if self.parent() is not None:
            window = self.parent()
            window._history = [item for item in window._history if item[2] != identity]
            window.update_languages()
            if active == identity:
                window.search.clear()
                window._mode_changed()

    def move_pack(self, offset):
        row = self.packs.currentRow()
        visible = [i for i in range(self.packs.count()) if not self.packs.item(i).isHidden()]
        position = visible.index(row) + offset if row in visible else -1
        target = visible[position] if 0 <= position < len(visible) else -1
        if row >= 0 and 0 <= target < self.packs.count():
            item = self.packs.takeItem(row)
            self.packs.insertItem(target, item)
            self.packs.setCurrentRow(target)
            self.save_dictionaries()

    def remove_dictionary(self):
        item = self.packs.currentItem()
        if item is None or item.isHidden():
            return
        title = item.data(Qt.ItemDataRole.UserRole + 2)
        if QMessageBox.question(self, "Remove dictionary", f"Remove {title} from all profiles?") == QMessageBox.StandardButton.Yes:
            self.begin_operation([], remove=item.data(Qt.ItemDataRole.UserRole))

    def save_dictionaries(self):
        items = [self.packs.item(index) for index in range(self.packs.count())]
        try:
            items = [item for item in items if item.data(Qt.ItemDataRole.UserRole + 1) == self.editing_language]
            prefix = f"profiles/{self.profile.currentData()}/dictionaries/"
            self.settings.setValue(prefix + "order", [item.data(Qt.ItemDataRole.UserRole + 4) for item in items])
            self.settings.setValue(prefix + "disabled", [item.data(Qt.ItemDataRole.UserRole + 4) for item in items
                                                       if item.checkState() != Qt.CheckState.Checked])
            self.dictionaries_changed.emit()
            self.resources.refresh()
            self.status.clear()
        except OSError as error:
            self.status.setText(str(error))

    def save_text_triggers(self):
        if self._loading:
            return
        prefix = f"profiles/{self.profile.currentData()}/"
        self.settings.setValue(prefix + "selected_text", self.selected_text.isChecked())
        if self.parent() is not None:
            self.parent().scan_settings_changed.emit()

    def validate_text_binding(self, key, value):
        from wordcel.gui.text_shortcuts import validate_shortcuts
        prefix = f"profiles/{self.profile.currentData()}/"
        validate_shortcuts([value, *(self.settings.value(prefix + other, default_text_shortcut() if other == "hotkey" else "")
                                   for other in ("hotkey", "translation_hotkey", "hover_hotkey") if other != key),
                            self.settings.value("next_profile_hotkey", ""),
                            self.settings.value("previous_profile_hotkey", "")])

    def save_shortcut(self):
        try:
            self.validate_text_binding("hotkey", self.shortcut.text())
            prefix = f"profiles/{self.profile.currentData()}/"
            value, preset = self.shortcut.text(), self.shortcut.recorder.keySequence().toString()
            warning = self._apply_shortcut(value, preset) if self.is_active_edit() else ""
            self.settings.setValue(prefix + "hotkey", value)
            self.settings.setValue(prefix + "hotkey_preset", preset)
            if self.settings.editing_global:
                self.preference_groups.apply("shortcuts")
            self.status.setText(warning if isinstance(warning, str) and warning else "")
        except (ValueError, OSError, RuntimeError) as error:
            with QSignalBlocker(self.shortcut.enabled), QSignalBlocker(self.shortcut.recorder):
                self.shortcut.set_value(self.settings.value(f"profiles/{self.profile.currentData()}/hotkey", default_text_shortcut()),
                                        self.settings.value(f"profiles/{self.profile.currentData()}/hotkey_preset", shortcut_preset()))
            self.status.setText(str(error))

    def save_translation_layout(self, enabled):
        self.settings.setValue(f"profiles/{self.profile.currentData()}/translation_side_by_side", enabled)
        if self.is_active_edit():
            self.parent().translation_panel.set_side_by_side(enabled)

    def save_translation_shortcut(self):
        self._save_auxiliary_shortcut("translation", self.translation_shortcut)

    def save_hover_shortcut(self):
        self._save_auxiliary_shortcut("hover", self.hover_shortcut)

    def _save_auxiliary_shortcut(self, name, editor):
        key = f"profiles/{self.profile.currentData()}/" + name + "_hotkey"
        preset = editor.recorder.keySequence().toString()
        try:
            value = editor.text()
            self.validate_text_binding(name + "_hotkey", value)
            warning = ""
            if self.is_active_edit():
                warning = getattr(self.parent(), "apply_" + name + "_shortcut")(value, preset)
            self.settings.setValue(key, value)
            self.settings.setValue(key + "_preset", preset)
            if self.settings.editing_global:
                self.preference_groups.apply("shortcuts")
            self.status.setText(warning if isinstance(warning, str) else "")
        except (ValueError, OSError, RuntimeError) as error:
            with QSignalBlocker(editor.enabled), QSignalBlocker(editor.recorder):
                editor.set_value(self.settings.value(key, ""), self.settings.value(key + "_preset", preset))
            self.status.setText(str(error))

    def save_screen_shortcut(self):
        bindings = ",".join(value for value in (self.scan_key.currentData(), self.scan_mouse.currentData()) if value)
        self.settings.setValue(f"profiles/{self.profile.currentData()}/scan_bindings", bindings)
        self.settings.setValue(f"profiles/{self.profile.currentData()}/block_scan_keys", self.block_scan_keys.isChecked())
        self.notify_scan_settings()

    def save_popup_shortcuts(self):
        from PyQt6.QtGui import QKeySequence
        from wordcel.gui.popup_shortcuts import shortcut_key, native_chord
        profile = self.profile.currentData()
        bindings = {}
        try:
            for action, control in self.popup_shortcuts.items():
                value = control.recorder.keySequence().toString() if control.enabled.isChecked() else ""
                reserved = ("Esc", "Up", "Down", "PgUp", "PgDown", "Home", "End")
                if control.enabled.isChecked() and (not value or any(QKeySequence(value) == QKeySequence(key)
                                                                    for key in reserved)):
                    raise ValueError("Choose a shortcut other than a navigation key or Escape.")
                if value and value in bindings.values():
                    raise ValueError("Choose a different shortcut for each popup action.")
                if value and sys.platform == "win32":
                    native_chord(value)
                bindings[action] = value
        except ValueError as error:
            self.status.setText(str(error))
            return
        for action, value in bindings.items():
            key = shortcut_key(profile, action)
            self.settings.setValue(key, value)
            self.settings.setValue(key + "_preset", self.popup_shortcuts[action].recorder.keySequence().toString())
        if self.parent() is not None:
            self.parent().reload_popup_shortcuts()
            self.parent().update_anki()
        self.notify_scan_settings()
        self.status.clear()

    def save_pin_shortcut(self):
        prefix = f"profiles/{self.profile.currentData()}/"
        try:
            from wordcel.gui.desktop_input import validate_pin_shortcut
            value = self.pin_shortcut.text()
            validate_pin_shortcut(value)
        except ValueError as error:
            with QSignalBlocker(self.pin_shortcut.enabled), QSignalBlocker(self.pin_shortcut.recorder):
                self.pin_shortcut.set_value(self.settings.value(prefix + "pin_shortcut", "c"),
                                            self.settings.value(prefix + "pin_shortcut_preset", "C"))
            self.status.setText(str(error))
            return
        self.settings.setValue(prefix + "pin_shortcut", value)
        self.settings.setValue(prefix + "pin_shortcut_preset", self.pin_shortcut.recorder.keySequence().toString())
        self.notify_scan_settings()
        self.status.clear()

    def notify_scan_settings(self):
        if self.is_active_edit() or self.settings.editing_global is not None and self.parent() is not None:
            self.parent().scan_settings_changed.emit()

    def save_capture_settings(self):
        prefix = f"profiles/{self.profile.currentData()}/"
        self.settings.setValue(prefix + "pin_gesture", self.pin_gesture.currentData())
        self.settings.setValue(prefix + "freeze_while_held", self.freeze_while_held.isChecked())
        self.notify_scan_settings()
        if self.is_active_edit():
            self.parent()._render()

    def save_scan_settings(self):
        component_directory = self.screenai_directory.text().strip()
        provider = self.current_ocr_control()
        if provider.currentData() == "screenai":
            from wordcel.ocr.providers.screenai.component import find_component_directory
            try:
                find_component_directory(component_directory or None)
            except RuntimeError as error:
                self.update_ocr_controls()
                self.screenai_directory.setText(self.settings.value("screenai_directory", ""))
                self.status.setText(str(error))
                return
        prefix = f"profiles/{self.profile.currentData()}/"
        if provider.currentData() is not None:
            self.settings.setValue(prefix + "ocr_provider", provider.currentData())
        self.settings.setValue("screenai_directory", component_directory)
        window = self.parent()
        if self.is_active_edit():
            window._render()
            window.scan_settings_changed.emit()
        self.status.clear()
        if hasattr(self, "resources"):
            self.resources.refresh()

    def profile_changed(self):
        from wordcel.config.config import config
        previous_loading, self._loading = self._loading, True
        code = self.profile.currentData()
        self.remove_profile_button.setEnabled(self.operation is None and self.profile.count() > 1)
        self.remove_profile_button.setToolTip("" if self.profile.count() > 1 else "Keep at least one profile")
        if code is None:
            self._loading = previous_loading
            return
        self.anki.load(code)
        self.profile_name.setText(profile_name(self.settings, code))
        self.profile_language_label.setText(language_name(self.editing_language))
        self.update_active_label()
        for key, editor in (("hotkey", self.shortcut), ("translation_hotkey", self.translation_shortcut), ("hover_hotkey", self.hover_shortcut)):
            editor.set_value(self.settings.value(f"profiles/{code}/{key}", default_text_shortcut() if key == "hotkey" else ""), self.settings.value(f"profiles/{code}/{key}_preset", editor.recorder.keySequence().toString()))
        self.translation_split.setChecked(self.settings.value(f"profiles/{code}/translation_side_by_side", False, bool))
        self.close_on_cursor_leave.setChecked(self.settings.value(f"profiles/{code}/close_on_cursor_leave", False, bool))
        self.cursor_close_margin.setValue(self.settings.value(f"profiles/{code}/cursor_close_margin", 24, int))
        from wordcel.gui.popup_shortcuts import POPUP_ACTIONS, popup_bindings, shortcut_key
        for action, _, default in POPUP_ACTIONS:
            control = self.popup_shortcuts[action]
            with QSignalBlocker(control.enabled), QSignalBlocker(control.recorder):
                control.set_value(popup_bindings(self.settings, code)[action],
                                  self.settings.value(shortcut_key(code, action) + "_preset", default))
        with QSignalBlocker(self.freeze_while_held):
            self.freeze_while_held.setChecked(self.settings.value(f"profiles/{code}/freeze_while_held", True, bool))
        with QSignalBlocker(self.selection_lookup):
            self.selection_lookup.setChecked(self.settings.value(f"profiles/{code}/selection_lookup", False, bool))
        self.status.clear()
        with QSignalBlocker(self.combine_frequencies):
            self.combine_frequencies.setChecked(self.settings.value(f"profiles/{code}/combine_frequencies", True, bool))
        bindings = self.settings.value(f"profiles/{code}/scan_bindings", "shift,middle").split(",")
        with QSignalBlocker(self.block_scan_keys):
            self.block_scan_keys.setChecked(self.settings.value(f"profiles/{code}/block_scan_keys", False, bool))
        self.pin_shortcut.set_value(self.settings.value(f"profiles/{code}/pin_shortcut", "c"),
                                    self.settings.value(f"profiles/{code}/pin_shortcut_preset", "C"))
        with QSignalBlocker(self.selected_text):
            self.selected_text.setChecked(self.settings.value(f"profiles/{code}/selected_text", False, type=bool))
        self.scan_key.setCurrentIndex(max(0, next((self.scan_key.findData(b) for b in bindings if self.scan_key.findData(b) >= 0), 0)))
        self.scan_mouse.setCurrentIndex(max(0, next((self.scan_mouse.findData(b) for b in bindings if self.scan_mouse.findData(b) >= 0), 0)))
        for index in range(self.packs.count()):
            self.packs.item(index).setHidden(self.packs.item(index).data(Qt.ItemDataRole.UserRole + 1) != self.editing_language)
        self.update_dictionary_display()
        self.scan_layout.setRowVisible(self.ja_ocr_provider, self.editing_language == "ja")
        self.scan_layout.setRowVisible(self.tr_ocr_provider, self.editing_language == "tr")
        self.scan_layout.setRowVisible(self.other_ocr_provider, self.editing_language not in ("ja", "tr"))
        self.update_ocr_controls()
        try:
            translation = load_profile_settings(self.settings, code)
        except ValueError as error:
            translation = TranslationSettings()
            self.status.setText(str(error))
        with QSignalBlocker(self.translation_mode):
            self.translation_mode.setCurrentIndex(self.translation_mode.findData(translation.profile if translation.provider == "server" else "custom"))
        self.update_translation_controls(load=True)
        self.translation_endpoint.setText(translation.endpoint)
        self.translation_model.setText(translation.model)
        self.translation_pair_label.setText(language_name(self.editing_language) + " \u2194")
        self.translation_advanced.setChecked(translation.provider == "custom" or any(
            self.settings.value(f"profiles/{code}/translation_{key}", "auto") != "auto" for key in ("source", "target")))
        self.translation_stream.setChecked(translation.stream)
        self.translation_chunk_size.setValue(translation.chunk_size)
        self.translation_warm.setChecked(translation.keep_warm)
        self.appearance.reload()
        self.show_component_controls()
        self.pin_gesture.setCurrentIndex(max(0, self.pin_gesture.findData(self.settings.value(f"profiles/{code}/pin_gesture", "left"))))
        with QSignalBlocker(self.audio_autoplay):
            self.audio_autoplay.setCurrentIndex(max(0, self.audio_autoplay.findData(audio_autoplay_mode(self.settings, code))))
        self.audio_volume.setValue(self.settings.value(f"profiles/{code}/audio_volume", config.audio_volume, type=int))
        from wordcel.audio.sources import database_path, source_order
        self.audio_database.setText(database_path(self.settings, code))
        self.audio_remove.setVisible(bool(self.audio_database.text()))
        self.audio_sources.load(source_order(self.settings, code), self.audio_database.text())
        self.language.setCurrentIndex(max(0, self.language.findData(self.editing_language)))
        self.reload()
        if hasattr(self, "profile_connection"):
            self.reload_connection_choices()
        if hasattr(self, "preference_groups"):
            self.preference_groups.refresh()
        self._loading = previous_loading
        if hasattr(self, "resources"):
            self.resources.refresh()
        if hasattr(self, "data") and self.data.isVisible():
            self.data.refresh()

    def current_ocr_control(self):
        return {"ja": self.ja_ocr_provider, "tr": self.tr_ocr_provider}.get(self.editing_language, self.other_ocr_provider)

    def update_ocr_controls(self):
        from wordcel.language.support import default_ocr_provider, ocr_supported
        code = self.profile.currentData()
        provider = self.current_ocr_control()
        bundled_mac = sys.platform == "darwin" and getattr(sys, "frozen", False)
        supported = []
        for index in range(provider.count()):
            value = provider.itemData(index)
            enabled = bool(value and ocr_supported(self.editing_language, value)
                           and not (bundled_mac and value in {"meikiocr", "paddle"}))
            item = provider.model().item(index)
            item.setEnabled(enabled)
            item.setToolTip("" if enabled else "Install this language's OCR pack in Windows Settings, then restart Wordcel"
                            if value == "windows" else "This OCR provider does not support this language on this computer")
            if enabled:
                supported.append(value)
        default = default_ocr_provider(self.editing_language)
        default = default if default in supported else next(iter(supported), None)
        selected = self.settings.value(f"profiles/{code}/ocr_provider", default)
        index = provider.findData(selected)
        if index < 0:
            provider.addItem("Unavailable", selected)
            index = provider.count() - 1
            provider.model().item(index).setEnabled(False)
        with QSignalBlocker(provider):
            provider.setCurrentIndex(index)
        provider.setEnabled(bool(supported))
        provider.setToolTip("" if selected in supported
                            else "No OCR provider supports this language on this computer" if not supported
                            else "The saved OCR provider does not support this language")
        for control in (self.scan_key, self.scan_mouse):
            enabled = bool(supported) or self.settings.editing_global == "shortcuts"
            control.setEnabled(enabled)
            control.setToolTip("" if enabled else "No OCR provider supports this language on this computer")
        self.show_component_controls()

    def save_selection_policy(self):
        self.settings.setValue(f"profiles/{self.profile.currentData()}/selection_lookup", self.selection_lookup.isChecked())
        if self.is_active_edit():
            self.parent().browser.selection_lookup = self.selection_lookup.isChecked()

    def save_frequency_display(self, enabled):
        self.settings.setValue(f"profiles/{self.profile.currentData()}/combine_frequencies", enabled)
        if self.is_active_edit():
            self.parent()._render()

    def sync_profile(self, code):
        with QSignalBlocker(self.profile):
            if self.profile.findData(code) < 0:
                self.profile.addItem(profile_name(self.settings, code), code)
            self.profile.setCurrentIndex(self.profile.findData(code))
        self.profile_changed()
        if hasattr(self, "navigation"):
            current = self.navigation.currentItem()
            value = current.data(0, Qt.ItemDataRole.UserRole) if current else None
            if value and (value[0] is None or value[0].startswith("global:")):
                return
            from PyQt6.QtWidgets import QTreeWidgetItemIterator
            iterator = QTreeWidgetItemIterator(self.navigation)
            target = None
            while iterator.value():
                item = iterator.value()
                value = item.data(0, Qt.ItemDataRole.UserRole)
                if value and value[0] == code:
                    if target is None or value[1] == self.tabs.currentIndex():
                        target = item
                iterator += 1
            if target is not None:
                with QSignalBlocker(self.navigation):
                    self.navigation.setCurrentItem(target)
                self.profile_details.show()

    def apply_appearance(self):
        window = self.parent()
        if self.is_active_edit() or self.settings.editing_global is not None and window is not None:
            window.reload_appearance()
        self.status.clear()

    def choose_audio(self):
        path, _ = QFileDialog.getOpenFileName(self, "Pronunciation database", self.audio_database.text(), "SQLite (*.db)")
        if path:
            self.audio_database.setText(path)
            self.autosave(self.save_audio)

    def save_audio(self):
        code = self.profile.currentData()
        self.save_autoplay()
        self.settings.setValue(f"profiles/{code}/audio_volume", self.audio_volume.value())
        self.settings.setValue(f"profiles/{code}/audio_database", self.audio_database.text().strip())
        path = self.audio_database.text().strip()
        if path != self.audio_sources.path:
            self.audio_sources.load(self.audio_sources.order(), path, prefer_local=True)
        self.settings.setValue(f"profiles/{code}/audio_priority", self.audio_sources.order())
        self.audio_remove.setVisible(bool(path))
        self.status.clear()

    def remove_audio_database(self):
        self.audio_database.clear()
        self.autosave(self.save_audio)

    def save_autoplay(self):
        if self._loading:
            return
        self.settings.setValue(f"profiles/{self.profile.currentData()}/audio_autoplay_mode", self.audio_autoplay.currentData())

    def choose_screenai(self):
        directory = QFileDialog.getExistingDirectory(self, "Chrome Screen AI component", self.screenai_directory.text())
        if directory:
            self.screenai_directory.setText(directory)
            self.autosave(self.save_scan_settings)

    def choose_dictionaries(self, *, language=None):
        paths, _ = QFileDialog.getOpenFileNames(self, "Import dictionaries", "", "Yomitan dictionaries (*.zip)")
        if not paths:
            return
        if language is None:
            language = self.language.currentData()
            if self.language.currentIndex() < 0 or self.language.currentText() != self.language.itemText(self.language.currentIndex()):
                language = self.language.currentText().strip().lower() or None
        self.begin_operation(paths, language=language)

    def update_translation_controls(self, *_args, load=False):
        custom = self.translation_mode.currentData() == "custom"
        self.update_translation_languages(load=load)
        self.translation_advanced_form.setRowVisible(self.translation_endpoint, False)
        self.translation_advanced_form.setRowVisible(self.translation_model, False)
        if custom:
            self.translation_advanced.setChecked(True)
        self.translation_advanced_form.setRowVisible(self.translation_warm, not custom)
        if hasattr(self, "resources"):
            self.resources.refresh()

    def update_translation_languages(self, *, load=False):
        from wordcel.dictionary.translation import translation_language
        from wordcel.language.support import translation_languages
        code = self.profile.currentData()
        if not code:
            return
        custom = self.translation_mode.currentData() == "custom"
        normalize = lambda value: value if custom or value == "auto" else translation_language(value)
        partner = normalize(self.settings.value(f"profiles/{code}/target", default_partner(self.editing_language))
                            if load else self.translation_partner.currentData()
                            or self.settings.value(f"profiles/{code}/target", default_partner(self.editing_language)))
        selected = {key: normalize(self.settings.value(f"profiles/{code}/translation_{key}", "auto")
                                   if load else control.currentData())
                    for key, control in (("source", self.translation_source), ("target", self.translation_target))}
        codes = translation_languages("custom" if custom else "server", self._imported_languages,
                                      (*profile_languages(self.settings), self.editing_language, partner, *selected.values()))
        codes = sorted(codes - {"auto", None, ""})
        tooltip = "Language support depends on your server model" if custom else ""
        with QSignalBlocker(self.translation_partner):
            self.translation_partner.clear()
            for language in dict.fromkeys([*codes, partner]):
                self.translation_partner.addItem(language_name(language), language)
                item = self.translation_partner.model().item(self.translation_partner.count() - 1)
                supported = language in codes
                item.setEnabled(supported)
                item.setToolTip(tooltip if supported else "The selected model does not support this language")
            self.translation_partner.setCurrentIndex(self.translation_partner.findData(partner))
        self.translation_partner.setToolTip(tooltip if partner in codes
                                            else "The selected model does not support this language")
        languages = {language: language_name(language) for language in codes}
        for key, control in (("source", self.translation_source), ("target", self.translation_target)):
            with QSignalBlocker(control):
                for language in (normalize(self.editing_language), partner, selected[key]):
                    control.addItem("Automatic" if language == "auto" else language_name(language), language)
                control.set_pair(normalize(self.editing_language), partner)
                control.set_languages(languages, selected=selected[key], tooltip=tooltip)

    def save_translation(self, *, cancel=True):
        mode = self.translation_mode.currentData()
        try:
            code = self.profile.currentData()
            if self.translation_partner.currentData() == self.editing_language:
                raise ValueError("Choose two different languages for the translation pair.")
            if self.translation_source.currentData() == self.translation_target.currentData() != "auto":
                raise ValueError("Choose different source and target languages.")
            save_profile_settings(self.settings, code, TranslationSettings(
                provider="custom" if mode == "custom" else "server",
                profile=mode if mode != "custom" else "quality",
                endpoint=self.translation_endpoint.text(), model=self.translation_model.text(),
                auto_start=True, stream=self.translation_stream.isChecked(),
                keep_warm=self.translation_warm.isChecked(), chunk_size=self.translation_chunk_size.value()))
            self.settings.setValue(f"profiles/{code}/target", self.translation_partner.currentData())
            for key, control in (("source", self.translation_source), ("target", self.translation_target)):
                self.settings.setValue(f"profiles/{code}/translation_{key}", control.currentData())
                with QSignalBlocker(control):
                    control.set_pair(self.editing_language, self.translation_partner.currentData())
            if self.is_active_edit():
                window = self.parent()
                with QSignalBlocker(window.source), QSignalBlocker(window.foreign):
                    window.update_translation_languages(self.translation_partner.currentData())
                if cancel:
                    window._edited()
            self.status.clear()
            if hasattr(self, "resources"):
                from wordcel.gui.resources import managed_translation_available
                managed_translation_available.cache_clear()
                self.resources.refresh()
            if self.is_active_edit():
                self.parent().refresh_translation_availability()
            return True
        except (ValueError, OSError) as error:
            self.status.setText(str(error))
            return False

    def operation_busy(self, resource):
        from wordcel.gui.resource_jobs import jobs
        registered = jobs.snapshot()
        if registered and (resource == "all" or "all" in registered):
            return True
        if resource in registered:
            return True
        resource = setup_resource(resource)
        active = tuple(self.operations) or ((self.operation,) if self.operation is not None else ())
        return any(resource == "all" or job.resource in {resource, "all"} for job in active)

    def set_operation_busy(self, busy):
        if hasattr(self, "data"):
            self.data.set_busy()
        for control in (self.import_button, self.packs, self.up, self.down, self.remove_pack, self.language):
            control.setEnabled(not self.operation_busy("dictionaries"))
        self.remove_profile_button.setEnabled(not busy and self.profile.count() > 1)

    def begin_operation(self, paths, language=None, profile=None, recommended=None, remove=None, morphology=None, ocr=None, fonts=False,
                        asset=None, remove_language=None, update=None, bundle=None, engine=None):
        operation = SetupOperation(paths, self.directory, language, profile, recommended, remove, morphology, ocr, fonts,
                                   asset, remove_language, update, bundle, engine)
        if self.operation_busy(operation.resource):
            operation.deleteLater()
            return
        label = StatusLabel()
        label.setWordWrap(True)
        label.setText({"translation": "Downloading translation…", "ocr": "Downloading OCR…",
                       "morphology": "Downloading word-form support…", "fonts": "Downloading font…",
                       "dictionaries": "Updating dictionaries…"}.get(operation.resource, "Removing data…"))
        if bundle:
            label.setText("Exporting resources…" if bundle[0] == "export" else "Importing resources…")
        self.jobs_layout.addWidget(label)
        self.operations[operation] = label
        self.operation = next(iter(self.operations))
        operation.refresh.connect(self.dictionaries_changed)
        operation.progress.connect(lambda text, job=operation: self._operation_progress(job, text))
        operation.finished.connect(lambda status, changed, job=operation: self._finished(status, changed, job))
        self.cancel_button.setVisible(True)
        self.cancel_button.setText("Cancel all" if len(self.operations) > 1 else "Cancel")
        self.cancel_button.setEnabled(True)
        self.set_operation_busy(True)
        operation.start()
        self.resources.refresh()

    def _operation_progress(self, operation, text):
        label = self.operations.get(operation)
        if label is not None:
            label.setText(text)

    def cancel_operation(self):
        active = tuple(self.operations) or ((self.operation,) if self.operation is not None else ())
        if active:
            for operation in active:
                operation.cancelled.set()
            self.status.setText("Finishing the current step…")
            self.cancel_button.setEnabled(False)

    def _finished(self, status, changed, operation=None):
        operation = operation or self.operation
        removed_language = operation.remove_language if operation is not None else None
        ocr_changed = changed and operation is not None and (
            operation.ocr or operation.bundle or operation.engine or operation.asset and operation.asset.startswith(("ocr:", "engine:")))
        font_installed = changed and operation is not None and (operation.fonts or operation.bundle)
        component = operation.installed_component if operation is not None else ""
        if component:
            self.screenai_directory.setText(component)
            self.settings.setValue("screenai_directory", component)
        label = self.operations.pop(operation, None)
        if label is not None:
            self.jobs_layout.removeWidget(label)
            label.deleteLater()
        self.operation = next(iter(self.operations), None)
        if operation is not None:
            operation.deleteLater()
        if changed and removed_language:
            self._forget_profile(removed_language)
        self.cancel_button.setVisible(bool(self.operations))
        self.cancel_button.setText("Cancel all" if len(self.operations) > 1 else "Cancel")
        self.cancel_button.setEnabled(any(not job.cancelled.is_set() for job in self.operations))
        self.set_operation_busy(bool(self.operations))
        self.update_translation_controls()
        self.update_ocr_controls()
        self.reload(preserve=True)
        self.resources.refresh()
        if self.data.isVisible():
            self.data.refresh()
        self.status.setText(status)
        if changed:
            self.dictionaries_changed.emit()
            if self.parent() is not None:
                if ocr_changed:
                    self.parent().models_changed.emit()
                self.parent().scan_settings_changed.emit()
                if font_installed:
                    self.parent()._render_identity = None
                    self.parent().reload_appearance()
        if self._close_pending:
            self._close_pending = False
            super().reject()

    def reject(self):
        self.audio_sources.shutdown()
        # Closing Settings leaves the background job running. Cancel is explicit.
        super().reject()

    def closeEvent(self, event):
        self.audio_sources.shutdown()
        super().closeEvent(event)
