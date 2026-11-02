"""One-time resource suggestions for a newly added language profile."""
from PyQt6.QtCore import Qt, pyqtSlot
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
        from wordcel.gui.language_names import language_name
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
        from wordcel.gui.language_names import language_name
        from wordcel.gui.language_setup import language_plan
        self.setWindowTitle(language_name(self.language))
        self.resize(480, 300)
        layout = QVBoxLayout(self)
        self.workflow = QComboBox()
        self.workflow.addItem("Dictionary lookup", "dictionary")
        self.workflow.addItem("Dictionary and screen recognition", "ocr")
        self.workflow.setCurrentIndex(1)
        layout.addWidget(self.workflow)
        self.customize = QCheckBox("Customize")
        layout.addWidget(self.customize)
        self.details = QWidget()
        detail_layout = QVBoxLayout(self.details)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.details)
        self.details.hide()
        self.customize.toggled.connect(self.details.setVisible)
        self.installed_summary = QLabel()
        self.installed_summary.setWordWrap(True)
        layout.addWidget(self.installed_summary)
        self.choices = []
        resource_rows = {}
        for task in language_plan(self.language):
            check = QCheckBox(task.label)
            check.setChecked(task.kind in {"dictionary", "ocr"})
            if task.kind in {"ocr", "translation"}:
                row = QHBoxLayout()
                row.addWidget(check)
                detail_layout.addLayout(row)
                resource_rows[task.kind] = row
            else:
                detail_layout.addWidget(check)
            self.choices.append((task, check))
        self.translation_touched = False
        self.translation = QComboBox(self)
        from wordcel.translation_catalog import model_label
        for identity in ("lightweight", "quality", "compact"):
            self.translation.addItem(model_label(identity), identity)
        self.translation.addItem("No translation download", None)
        self.translation.setToolTip("Downloaded models are shared by all languages")
        from wordcel.gui.resources import translation_ready
        from wordcel.dictionary.translation import load_profile_settings
        try:
            options = load_profile_settings(window.settings, self.profile)
            preferred = options.profile
            self.translation_backend = options.backend
        except ValueError:
            preferred = "lightweight"
            self.translation_backend = "automatic"
        installed = [name for name in ("lightweight", "quality", "compact") if translation_ready(name)]
        selected = preferred if preferred in installed else next(iter(installed), "lightweight")
        if window.settings.contains(f"profiles/{self.profile}/translation"):
            selected = preferred
        self.translation.setCurrentIndex(self.translation.findData(selected))
        self.translation.currentIndexChanged.connect(self.refresh_choices)
        self.translation.activated.connect(lambda _: setattr(self, "translation_touched", True))
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
        default = default_ocr_provider(self.language)
        preferred = default if self.language == "tr" else next(iter(installed), default)
        selected = saved if saved in available else preferred
        self.ocr.setCurrentIndex(max(0, self.ocr.findData(selected)))
        if "ocr" in resource_rows:
            resource_rows["ocr"].addWidget(self.ocr, 1)
        else:
            self.ocr.hide()
        self.ocr.currentIndexChanged.connect(self.refresh_choices)
        self.workflow.currentIndexChanged.connect(self.select_workflow)
        for task, check in self.choices:
            if task.kind == "translation":
                check.toggled.connect(self.translation.setEnabled)
            elif task.kind == "ocr":
                check.toggled.connect(self.ocr.setEnabled)
        self.transfer = QLabel()
        self.transfer.setWordWrap(True)
        layout.addWidget(self.transfer)
        self.translation_fit = QLabel()
        self.translation_fit.setWordWrap(True)
        detail_layout.addWidget(self.translation_fit)
        self.capabilities, self.verified = None, set()
        from wordcel.gui.resources import ResourcePreparation
        self.preparation = ResourcePreparation(self)
        self.preparation.finished.connect(self.prepared_resources)
        self.preparation.thread.start()
        for task, check in self.choices:
            check.toggled.connect(self.refresh_choices)
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

    def select_workflow(self):
        for task, check in self.choices:
            if task.kind == "ocr":
                check.setChecked(self.workflow.currentData() == "ocr")
        self.refresh_choices()

    @pyqtSlot(object, object)
    def prepared_resources(self, capabilities, verified):
        from PyQt6 import sip
        if sip.isdeleted(self.translation):
            return
        self.capabilities, self.verified = capabilities, verified
        from wordcel.translation_catalog import recommend_model
        if not self.translation_touched and not self.window.settings.contains(f"profiles/{self.profile}/translation") \
                and not any(task.kind == "translation" and check.isChecked() for task, check in self.choices):
            from wordcel.gui.resources import translation_ready
            if not any(translation_ready(name) for name in ("lightweight", "quality", "compact")):
                identity = recommend_model(capabilities.memory)
                self.translation.setCurrentIndex(self.translation.findData(identity))
        self.refresh_choices()

    def selected_tasks(self):
        from dataclasses import replace
        tasks = [replace(task, value=self.translation.currentData() if task.kind == "translation" else self.ocr.currentData(),
                         backend=self.translation_backend if task.kind == "translation" else "automatic")
                 if task.kind in {"translation", "ocr"} else task
                 for task, check in self.choices if check.isChecked()]
        return [task for task in tasks if task.value is not None and not self.task_ready(task)]

    def task_ready(self, task):
        if task in self.completed_tasks:
            return True
        if task.kind == "translation":
            from wordcel.gui.resources import translation_ready
            return task.value is not None and translation_ready(task.value, task.backend)
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
        installed_labels = [meta["title"] for meta in self.installed_packs]
        for task, check in self.choices:
            selected = replace(task, value=self.translation.currentData() if task.kind == "translation" else self.ocr.currentData(),
                               backend=self.translation_backend if task.kind == "translation" else "automatic") \
                if task.kind in {"translation", "ocr"} else task
            installed = self.task_ready(selected)
            check.setText(task.label + (" ✓ Installed" if installed else ""))
            check.setEnabled(self.operation is None and not installed)
            if installed and (task.kind != "dictionary" or task in self.completed_tasks):
                installed_labels.append(task.label)
        self.installed_summary.setText("Installed: " + ", ".join(installed_labels) if installed_labels else "No resources installed")
        from wordcel.gui.resources import translation_transfer_size, transfer_label
        from wordcel.translation_catalog import fit_message
        known, unknown = 0, False
        for task in self.selected_tasks():
            if task.kind == "translation":
                cost = translation_transfer_size(task.value, self.translation_backend, capabilities=self.capabilities, verified=self.verified)
                if cost is None:
                    unknown = True
                else:
                    known += cost
            elif task.kind == "ocr" and task.value in {"vision", "windows"}:
                pass
            else:
                unknown = True
        self.transfer.setText(transfer_label(known, unknown))
        identity = self.translation.currentData()
        self.translation_fit.setText(fit_message(identity, self.capabilities.memory if self.capabilities else None) if identity else "")

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
        self.workflow.setEnabled(False)
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
        self.workflow.setEnabled(True)
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
