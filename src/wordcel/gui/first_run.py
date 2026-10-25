"""One-time resource suggestions for a newly added language profile."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout,
                            QLabel, QPushButton, QProgressBar, QVBoxLayout, QWidget)


def needs_setup(settings):
    from wordcel.language.profiles import configured_profiles
    return not configured_profiles(settings)


def complete_first_setup(settings):
    import sys
    if sys.platform != "win32" or settings.contains("start_with_windows"):
        return
    from wordcel.utils.startup import is_startup_enabled, set_startup_enabled
    try:
        if not is_startup_enabled():
            set_startup_enabled(True)
    except OSError:
        import logging
        logging.getLogger(__name__).exception("Could not enable Windows startup")
        return
    settings.setValue("start_with_windows", True)
    settings.sync()


class FirstLanguage(QDialog):
    def __init__(self, settings, imported=()):
        super().__init__()
        from wordcel.gui.quick_lookup import language_name
        from wordcel.gui.language_chooser import LanguageComboBox
        from wordcel.language.profiles import configured_profiles
        from wordcel.language.support import profile_languages
        self.settings = settings
        self.setWindowTitle("Wordcel Setup")
        self.setMinimumWidth(360)
        layout = QVBoxLayout(self)
        self.language = LanguageComboBox()
        self.language.addItem("Choose a language…", None)
        for code in sorted(profile_languages(imported, (__import__("wordcel.config.profiles", fromlist=["languages"]).languages(settings))),
                           key=lambda code: language_name(code).casefold()):
            self.language.add_language(code, language_name(code))
        form = QFormLayout()
        form.addRow("Lookup language", self.language)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.continue_button = QPushButton("Continue")
        self.continue_button.setEnabled(False)
        self.continue_button.setDefault(True)
        self.continue_button.clicked.connect(self.accept)
        buttons.addWidget(self.continue_button)
        layout.addLayout(buttons)
        self.language.currentTextChanged.connect(lambda: self.continue_button.setEnabled(self.language.selected_code() is not None))

    def accept(self):
        code = self.language.selected_code()
        if code is None:
            return
        from wordcel.config.profiles import create_profile
        identity = create_profile(self.settings, code)
        self.settings.setValue("profile", identity)
        self.settings.setValue("initial_profile", identity)
        self.settings.sync()
        super().accept()


class LanguageSuggestion(QDialog):
    def __init__(self, window, language=None):
        super().__init__(window)
        self.window = window
        from wordcel.config.profiles import profile_language
        self.profile = language or getattr(window, "active_profile", window.preferred_foreign)
        self.language = profile_language(window.settings, self.profile)
        self.operation = None
        self.completed_tasks = []
        from wordcel.dictionary.library import Library
        library = Library(window.directory)
        try:
            self.installed_packs = tuple(meta for _, meta, _ in library.packs if meta["language"] == self.language)
        finally:
            library.close()
        from wordcel.gui.quick_lookup import language_name
        from wordcel.gui.language_setup import language_plan
        self.setWindowTitle(language_name(self.language))
        self.resize(480, 300)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Install recommended essentials"))
        layout.addWidget(QLabel("Dictionary and screen recognition"))
        self.customize = QCheckBox("Customize")
        layout.addWidget(self.customize)
        self.details = QWidget()
        detail_layout = QVBoxLayout(self.details)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.details)
        self.details.hide()
        self.customize.toggled.connect(self.details.setVisible)
        self.choices = []
        resource_rows = {}
        for task in language_plan(self.language):
            check = QCheckBox(task.label)
            check.setChecked(task.kind != "translation")
            if task.kind in {"ocr", "translation"}:
                row = QHBoxLayout()
                row.addWidget(check)
                (layout if task.kind == "translation" else detail_layout).addLayout(row)
                resource_rows[task.kind] = row
            else:
                detail_layout.addWidget(check)
            self.choices.append((task, check))
        self.translation = QComboBox(self)
        self.translation.addItem("Lightweight (1.9 GB)", "lightweight")
        self.translation.addItem("Quality (8 GB)", "quality")
        self.translation.addItem("No translation download", None)
        self.translation.setToolTip("Downloaded models are shared by all languages")
        from wordcel.gui.resources import translation_ready
        from wordcel.dictionary.translation import load_profile_settings
        try:
            preferred = load_profile_settings(window.settings, self.profile).profile
        except ValueError:
            preferred = "lightweight"
        installed = [name for name in ("lightweight", "quality") if translation_ready(name)]
        selected = preferred if preferred in installed else next(iter(installed), "lightweight")
        if window.settings.contains(f"profiles/{self.profile}/translation"):
            selected = preferred
        self.translation.setCurrentIndex(self.translation.findData(selected))
        self.translation.currentIndexChanged.connect(self.refresh_choices)
        if "translation" in resource_rows:
            resource_rows["translation"].addWidget(self.translation, 1)
        else:
            self.translation.hide()
        self.translation.setEnabled(any(task.kind == "translation" and check.isChecked() for task, check in self.choices))
        from wordcel.gui.resources import ocr_ready
        from wordcel.language.support import default_ocr_provider, ocr_supported
        self.ocr = QComboBox(self)
        self.ocr.addItem("No OCR download", None)
        providers = (("windows", "Windows OCR (local)"), ("vision", "Apple Vision (local)"),
                     ("meikiocr", "MeikiOCR (local)"), ("paddle", "PaddleOCR (local)"),
                     ("screenai", "Chrome Screen AI (local)"))
        available = [provider for provider, label in providers if ocr_supported(self.language, provider)]
        for provider, label in providers:
            if provider in available:
                self.ocr.addItem(label, provider)
        saved = window.settings.value(f"profiles/{self.profile}/ocr_provider", "")
        installed = [provider for provider in available if ocr_ready(provider, window.settings.value("screenai_directory", ""))]
        selected = saved if saved in available else next(iter(installed), default_ocr_provider(self.language))
        self.ocr.setCurrentIndex(max(0, self.ocr.findData(selected)))
        if "ocr" in resource_rows:
            resource_rows["ocr"].addWidget(self.ocr, 1)
        else:
            self.ocr.hide()
        self.ocr.currentIndexChanged.connect(self.refresh_choices)
        for task, check in self.choices:
            if task.kind == "translation":
                check.toggled.connect(self.translation.setEnabled)
            elif task.kind == "ocr":
                check.toggled.connect(self.ocr.setEnabled)
        self.bar = QProgressBar()
        self.bar.hide()
        layout.addWidget(self.bar)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.later = QPushButton("Later")
        self.later.clicked.connect(self.reject)
        buttons.addWidget(self.later)
        self.install = QPushButton("Install")
        self.install.setDefault(True)
        self.install.clicked.connect(self.accept)
        buttons.addWidget(self.install)
        layout.addLayout(buttons)
        self.refresh_choices()
        self.adjustSize()

    def selected_tasks(self):
        from dataclasses import replace
        tasks = [replace(task, value=self.translation.currentData() if task.kind == "translation" else self.ocr.currentData())
                 if task.kind in {"translation", "ocr"} else task
                 for task, check in self.choices if check.isChecked()]
        return [task for task in tasks if task.value is not None and not self.task_ready(task)]

    def task_ready(self, task):
        if task in self.completed_tasks:
            return True
        if task.kind == "translation":
            from wordcel.gui.resources import translation_ready
            return task.value is not None and translation_ready(task.value)
        if task.kind == "ocr":
            from wordcel.gui.resources import ocr_ready
            return task.value is not None and ocr_ready(task.value, self.window.settings.value("screenai_directory", ""))
        if task.kind == "fonts":
            from wordcel.utils.stroke_order_font import font_ready
            return font_ready()
        if task.kind == "dictionary":
            return any(task.value.matches(meta) for meta in self.installed_packs)
        if task.kind == "morphology":
            from wordcel.language.stanza_analyzer import model_status
            return model_status(task.value) == "Installed"
        return False

    def refresh_choices(self):
        from dataclasses import replace
        for task, check in self.choices:
            selected = replace(task, value=self.translation.currentData() if task.kind == "translation" else self.ocr.currentData()) \
                if task.kind in {"translation", "ocr"} else task
            installed = self.task_ready(selected)
            check.setText(task.label + (" ✓" if installed else ""))
            check.setEnabled(self.operation is None and not installed)

    def use_translation(self, profile):
        from dataclasses import replace
        from wordcel.dictionary.translation import load_profile_settings, save_profile_settings
        settings = load_profile_settings(self.window.settings, self.profile)
        save_profile_settings(self.window.settings, self.profile, replace(settings, provider="server", profile=profile))

    def accept(self):
        if self.operation is not None:
            return
        from wordcel.dictionary.library import default_library_path
        from wordcel.gui.language_setup import LanguageSetup
        from wordcel.gui.resources import translation_ready
        if any(task.kind == "translation" and check.isChecked() for task, check in self.choices):
            if self.translation.currentData() is not None and translation_ready(self.translation.currentData()):
                self.use_translation(self.translation.currentData())
                self.window.refresh_library()
        if self.ocr.currentData() is not None and any(task.kind == "ocr" and check.isChecked() for task, check in self.choices):
            from wordcel.gui.resources import ocr_ready
            if ocr_ready(self.ocr.currentData(), self.window.settings.value("screenai_directory", "")):
                self.window.settings.setValue(f"profiles/{self.profile}/ocr_provider", self.ocr.currentData())
                self.window.scan_settings_changed.emit()
        tasks = self.selected_tasks()
        if not tasks:
            self.finish_setup()
            return
        self.operation = LanguageSetup(tasks, self.window.directory or default_library_path())
        self.bar.setRange(0, len(tasks))
        self.bar.setValue(0)
        self.bar.show()
        self.install.setEnabled(False)
        self.translation.setEnabled(False)
        self.ocr.setEnabled(False)
        for task, check in self.choices:
            check.setEnabled(False)
        self.later.setText("Stop downloads")
        self.operation.stage.connect(self.download_stage)
        self.operation.progress.connect(self.status.setText)
        self.operation.finished.connect(self.download_finished)
        self.operation.thread.start()

    def download_stage(self, index, label):
        self.bar.setValue(index)
        self.status.setText(label)

    def download_finished(self, completed, errors):
        code = self.profile
        for task, value in completed:
            if task.kind == "ocr":
                self.window.settings.setValue(f"profiles/{code}/ocr_provider", task.value)
                if value:
                    self.window.settings.setValue("screenai_directory", value)
            elif task.kind == "translation":
                self.use_translation(task.value)
        self.window.refresh_library()
        self.window.scan_settings_changed.emit()
        if self.window._setup is not None:
            self.window._setup.reload(preserve=True)
            self.window._setup.resources.refresh()
        cancelled = self.operation.cancelled.is_set()
        self.operation = None
        self.completed_tasks.extend(task for task, _ in completed if task not in self.completed_tasks)
        self.bar.setValue(len(completed))
        self.install.setEnabled(True)
        self.install.setText("Retry" if errors else "Install")
        self.refresh_choices()
        self.translation.setEnabled(any(task.kind == "translation" and check.isChecked()
                                        for task, check in self.choices))
        self.ocr.setEnabled(any(task.kind == "ocr" and check.isChecked() for task, check in self.choices))
        if any(task.kind == "fonts" for task, value in completed) and hasattr(self.window, "reload_appearance"):
            self.window._render_identity = None
            self.window.reload_appearance()
        self.later.setText("Later")
        self.status.setText("\n".join(errors) if errors else "Installed items were kept." if cancelled else "Ready.")
        if not errors and not cancelled:
            self.finish_setup()

    def finish_setup(self):
        self.window.settings.setValue(f"profiles/{self.profile}/setup_completed", True)
        handoff = FirstLookup(self.window, self.profile)
        self.window._first_lookup = handoff
        handoff.show()
        super().accept()

    def reject(self):
        if self.operation is not None:
            self.operation.cancelled.set()
        super().reject()


def offer_resources(window, code, *, force=False):
    key = f"profiles/{code}/resources_suggested"
    if not force and window.settings.value(key, False, bool):
        return None
    suggestions = getattr(window, "_resource_suggestions", None)
    if suggestions is None:
        window._resource_suggestions = suggestions = {}
    if code in suggestions and suggestions[code].isVisible():
        suggestions[code].raise_()
        return suggestions[code]
    suggestion = LanguageSuggestion(window, code)
    suggestions[code] = suggestion
    suggestion.show()
    suggestion.raise_()
    from wordcel.utils.window_focus import activate_application
    activate_application()
    suggestion.activateWindow()
    window.settings.setValue(key, True)
    window.settings.sync()
    return suggestion


class FirstLookup(QDialog):
    def __init__(self, window, identity):
        super().__init__(window)
        from wordcel.config.profiles import profile_language
        from wordcel.gui.resources import ocr_ready
        from wordcel.language.support import default_ocr_provider
        from wordcel.dictionary.library import Library
        self.setWindowTitle("Try a lookup")
        language = profile_language(window.settings, identity)
        layout = QVBoxLayout(self)
        example = {"ja": "?", "tr": "merhaba", "en": "hello", "zh": "??", "ru": "??????",
                   "de": "Hallo", "fr": "bonjour", "es": "hola", "ko": "??"}.get(language, "hello")
        sample = QLabel(example)
        sample.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(sample)
        bindings = window.settings.value(f"profiles/{identity}/scan_bindings", "shift,middle")
        key = next(iter(bindings.split(",")), "")
        text = "Hold " + key.replace("+", " + ").title() + " and point at a word" if key else "Open Search to look up a word"
        layout.addWidget(QLabel(text))
        provider = window.settings.value(f"profiles/{identity}/ocr_provider", default_ocr_provider(language))
        library = Library(window.directory)
        try:
            dictionary_ready = any(meta["language"] == language and int(meta.get("entries", 0)) > 0 for _, meta, _ in library.packs)
        finally:
            library.close()
        screen_ready = ocr_ready(provider, window.settings.value("screenai_directory", ""))
        permission_ready = True
        import sys
        if sys.platform == "darwin":
            from wordcel.utils.macos import require_screen_capture_permission, require_input_monitoring_permission
            try:
                require_screen_capture_permission()
                require_input_monitoring_permission()
            except RuntimeError:
                permission_ready = False
        if not dictionary_ready or not screen_ready:
            repair = QPushButton("Resume setup")
            repair.clicked.connect(lambda: offer_resources(window, identity, force=True))
            layout.addWidget(repair)
        if not permission_ready:
            repair = QPushButton("Screen access?")
            repair.clicked.connect(window.open_settings)
            layout.addWidget(repair)
        # Voices are optional and never gate dictionary or screen lookup.
        from PyQt6.QtCore import QLocale
        from PyQt6.QtTextToSpeech import QTextToSpeech
        self.speech = QTextToSpeech(self)
        voices = [voice for voice in self.speech.availableVoices() if voice.locale().language() == QLocale(language).language()]
        if not voices:
            layout.addWidget(QLabel("Sentence audio voice unavailable"))
        search = QPushButton("Open Search")
        search.clicked.connect(lambda: self.try_lookup(window, identity, example))
        layout.addWidget(search)

    def try_lookup(self, window, identity, example):
        window.set_mode(identity)
        window.open_search(example)
        self.accept()
