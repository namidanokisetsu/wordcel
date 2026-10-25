"""Shared and per-language downloads, inspected on a worker."""
import threading

from PyQt6.QtCore import QObject, QSignalBlocker, QUrl, Qt, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QCheckBox, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

from wordcel.data_assets import inventory, resource_usage
from wordcel.config.profiles import profile_name, languages as profile_languages
from wordcel.gui.settings_section import SettingsSection


def size_label(size):
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{size} B"
        size /= 1024


class InventoryTask(QObject):
    finished = pyqtSignal(object, str)

    def __init__(self, directory, profiles, screenai, parent):
        super().__init__(parent)
        self.arguments = directory, profiles, screenai
        self.thread = threading.Thread(target=self.run, name="data-inventory", daemon=True)

    def run(self):
        try:
            directory, profiles, screenai = self.arguments
            assets, error = inventory(directory, profiles, screenai=screenai), ""
        except Exception as exception:
            assets, error = (), str(exception)
        try:
            self.finished.emit(assets, error)
        except RuntimeError:
            pass


class UpdateCheck(QObject):
    finished = pyqtSignal(object)

    def __init__(self, directory, parent):
        super().__init__(parent)
        self.directory = directory
        self.thread = threading.Thread(target=self.run, name="dictionary-update-check", daemon=True)

    def run(self):
        from wordcel.dictionary.library import Library
        from wordcel.dictionary.updates import check_update
        library = Library(self.directory)
        try:
            results = [check_update(meta) for _, meta, _ in library.packs]
        finally:
            library.close()
        try:
            self.finished.emit(results)
        except RuntimeError:
            pass


class DataPanel(QWidget):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self._task, self._pending = None, False
        self.rows, self.sections = {}, {}
        self.updates = {}
        self._update_task = None
        self.assets = ()
        self.import_buttons = {}
        self.body = QVBoxLayout(self)
        header = QHBoxLayout()
        self.total = QLabel()
        header.addWidget(self.total, 1)
        self.reload = QPushButton("Refresh")
        self.reload.clicked.connect(self.refresh)
        header.addWidget(self.reload)
        self.check_updates = QPushButton("Check for updates")
        self.check_updates.clicked.connect(self.check_dictionary_updates)
        header.addWidget(self.check_updates)
        self.update_all = QPushButton("Update all")
        self.update_all.setEnabled(False)
        self.update_all.clicked.connect(self.install_updates)
        header.addWidget(self.update_all)
        self.body.addLayout(header)
        self.update_notice = QWidget()
        notice_layout = QHBoxLayout(self.update_notice)
        notice_layout.setContentsMargins(0, 0, 0, 0)
        self.update_summary = QLabel()
        self.update_summary.setTextFormat(Qt.TextFormat.PlainText)
        self.update_summary.setWordWrap(True)
        notice_layout.addWidget(self.update_summary, 1)
        dismiss = QPushButton("Dismiss")
        dismiss.clicked.connect(self.update_notice.hide)
        notice_layout.addWidget(dismiss)
        self.body.addWidget(self.update_notice)
        self.update_notice.hide()
        transfers = QHBoxLayout()
        self.export_resources = QPushButton("Export resources…")
        self.import_resources = QPushButton("Import resources…")
        self.export_resources.setToolTip("Save installed resources for another computer with the same operating system and processor")
        self.import_resources.setToolTip("Import an offline resource archive")
        self.export_resources.clicked.connect(lambda: self.transfer_resources("export"))
        self.import_resources.clicked.connect(lambda: self.transfer_resources("import"))
        transfers.addWidget(self.export_resources)
        transfers.addWidget(self.import_resources)
        transfers.addStretch()
        self.body.addLayout(transfers)
        filters = QHBoxLayout()
        self.unused = QCheckBox("Unused only")
        self.add_resources = QCheckBox("Add resources")
        for control in (self.unused, self.add_resources):
            filters.addWidget(control)
            control.toggled.connect(self.filter_rows)
        filters.addStretch()
        self.body.addLayout(filters)
        self.job_rows = {}
        self.job_layout = QVBoxLayout()
        self.body.addLayout(self.job_layout)
        from wordcel.gui.resource_jobs import jobs
        jobs.changed.connect(self.refresh_jobs)
        self.refresh_jobs()
        self.body.addWidget(QLabel("Shared models"))
        self.shared = QVBoxLayout()
        self.body.addLayout(self.shared)
        self.body.addStretch()

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()

    def refresh_jobs(self):
        from wordcel.gui.resource_jobs import jobs
        active = jobs.snapshot()
        for key in set(self.job_rows) - active.keys():
            row = self.job_rows.pop(key)
            self.job_layout.removeWidget(row)
            row.deleteLater()
        for key, (_, cancelled, title) in active.items():
            if key not in self.job_rows:
                row = QWidget()
                layout = QHBoxLayout(row)
                layout.setContentsMargins(0, 0, 0, 0)
                row.label = QLabel()
                row.label.setWordWrap(True)
                layout.addWidget(row.label, 1)
                cancel = QPushButton("Cancel")
                cancel.clicked.connect(cancelled.set)
                layout.addWidget(cancel)
                self.job_rows[key] = row
                self.job_layout.addWidget(row)
            self.job_rows[key].label.setText(title)

    def refresh(self):
        if self._task is not None:
            self._pending = True
            return
        self.reload.setEnabled(False)
        self._task = InventoryTask(self.owner.directory, profile_languages(self.owner.settings),
                                   self.owner.screenai_directory.text(), self)
        self._task.finished.connect(self._finished)
        self._task.thread.start()

    def set_busy(self):
        self.export_resources.setEnabled(not self.owner.operation_busy("all"))
        self.import_resources.setEnabled(not self.owner.operation_busy("all"))
        for button in self.import_buttons.values():
            button.setEnabled(not self.owner.operation_busy("dictionaries"))
        for row in self.rows.values():
            busy = self.owner.operation_busy(row.asset.key)
            row.enabled.setEnabled(not self.owner.operation_busy("dictionaries"))
            row.remove.setEnabled(not busy)
            row.download.setEnabled(not busy)

    def _finished(self, assets, error):
        task, self._task = self._task, None
        task.deleteLater()
        self.reload.setEnabled(True)
        if self._pending:
            self._pending = False
            self.refresh()
            return
        if error:
            self.owner.status.setText(error)
        else:
            self._update(assets)

    def _update(self, assets):
        from wordcel.gui.quick_lookup import language_name
        scroll = self.owner.data_tab.verticalScrollBar()
        position = scroll.value()
        self.assets = assets
        keys = {asset.key for asset in assets}
        for key in set(self.rows) - keys:
            row = self.rows.pop(key)
            row.container.removeWidget(row)
            row.hide()
            row.deleteLater()
        languages = sorted({asset.language for asset in assets if asset.language} | set(profile_languages(self.owner.settings)))
        for code in set(self.sections) - set(languages):
            section = self.sections.pop(code)[0]
            self.body.removeWidget(section)
            section.hide()
            section.deleteLater()
            self.import_buttons.pop(code, None)
        for code in languages:
            if code not in self.sections:
                content = QWidget()
                layout = QVBoxLayout(content)
                layout.setContentsMargins(0, 0, 0, 0)
                section = SettingsSection(language_name(code), content)
                self.sections[code] = section, layout
                button = QPushButton("Import dictionaries…")
                button.setFlat(True)
                button.clicked.connect(lambda checked=False, code=code: self.owner.choose_dictionaries(language=code))
                layout.addWidget(button, alignment=Qt.AlignmentFlag.AlignLeft)
                self.import_buttons[code] = button
                section.toggle.setChecked(code == self.owner.editing_language)
                self.body.insertWidget(self.body.count() - 1, section)
        for asset in assets:
            if asset.key not in self.rows:
                row = QWidget()
                layout = QHBoxLayout(row)
                layout.setContentsMargins(0, 0, 0, 0)
                row.title, row.status = QLabel(), QLabel()
                row.title.setTextFormat(Qt.TextFormat.PlainText)
                row.enabled = QCheckBox()
                row.enabled.setToolTip("Enable dictionary")
                row.enabled.hide()
                row.title.setWordWrap(True)
                layout.addWidget(row.enabled)
                layout.addWidget(row.title, 1)
                layout.addWidget(row.status)
                row.open, row.download, row.remove = QPushButton("Open"), QPushButton("Download"), QPushButton("Remove")
                row.update = QPushButton("Update")
                row.replace = QPushButton("Replace from ZIP")
                row.replace.setToolTip("Install a dictionary ZIP you downloaded, keeping profile settings")
                for button in (row.open, row.download, row.update, row.replace, row.remove):
                    layout.addWidget(button)
                self.rows[asset.key] = row
                target = self.sections[asset.language][1] if asset.language else self.shared
                target.addWidget(row)
                row.container = target
                row.enabled.toggled.connect(lambda enabled, row=row: self._enable(row.asset, enabled))
                row.open.clicked.connect(lambda checked=False, row=row: self._open(row.asset))
                row.download.clicked.connect(lambda checked=False, row=row: self._download(row.asset))
                row.remove.clicked.connect(lambda checked=False, row=row: self._remove(row.asset))
                row.update.clicked.connect(lambda checked=False, row=row: self.owner.begin_operation([], update=[self.updates[row.asset.identity]]))
                row.replace.clicked.connect(lambda checked=False, row=row: self.replace_zip(row.asset))
            row = self.rows[asset.key]
            row.asset = asset
            using = resource_usage(self.owner.settings, asset)
            row.using = using
            source = asset.source or {"ocr": "Local OCR", "runtime": "llama.cpp", "translation": "Tencent Hy-MT2",
                                      "morphology": "Stanza", "fonts": "KanjiStrokeOrders"}.get(asset.kind, "")
            details = " ? ".join(value for value in (asset.revision, source) if value)
            users = ", ".join(profile_name(self.owner.settings, identity) for identity in using)
            row.title.setText("\n".join(value for value in (asset.title, details, "Used by: " + users if users else "Unused") if value))
            update = self.updates.get(asset.identity)
            failed = update and update.status not in {"Update available", "Up to date", "Replace from ZIP"}
            if failed:
                row.title.setText(row.title.text() + "\nUpdate check failed")
            row.update.setVisible(bool(update and update.status == "Update available"))
            row.update.setToolTip("Available: " + update.available if update else "")
            row.replace.setVisible(asset.kind == "dictionary")
            row.title.setToolTip(update.status if failed else "\n".join(map(str, asset.paths)))
            row.enabled.hide()
            with QSignalBlocker(row.enabled):
                row.enabled.setChecked(asset.status == "Enabled")
            row.status.setText(size_label(asset.size) if asset.kind == "dictionary" else
                               asset.status + (" · " + size_label(asset.size) if asset.size else ""))
            present = asset.size > 0 or asset.status in {"Enabled", "Disabled", "Linked"}
            row.open.setVisible(present and bool(asset.paths))
            row.remove.setVisible(present and asset.removable)
            row.download.setText("Repair" if present else "Download")
            row.download.setVisible((not present or asset.status == "Incomplete")
                                    and asset.kind in {"translation", "runtime", "ocr", "morphology", "fonts", "recommended", "engine"})
        self.filter_rows()
        self.total.setText(size_label(sum(asset.size for asset in assets)) + " used")
        self.set_busy()
        self.layout().activate()
        scroll.setValue(position)

    def _open(self, asset):
        path = next((path for path in asset.paths if path.exists()), None)
        if path is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path if path.is_dir() else path.parent)))

    def _download(self, asset):
        if asset.kind == "engine":
            self.owner.begin_operation([], engine=asset.value)
            return
        if asset.kind == "recommended":
            self.owner.begin_operation([], recommended=asset.value)
            return
        parameter = {"translation": "profile", "runtime": "profile", "morphology": "morphology", "ocr": "ocr", "fonts": "fonts"}[asset.kind]
        self.owner.begin_operation([], **{parameter: True if asset.kind == "fonts" else asset.value})

    def _remove(self, asset):
        using = resource_usage(self.owner.settings, asset)
        names = ", ".join(profile_name(self.owner.settings, identity) for identity in using)
        message = f"Remove {asset.title}?" + ("\nUsed by: " + names if names else "")
        if QMessageBox.question(self, "Remove data", message,
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.owner.begin_operation([], asset=asset.key)

    def _enable(self, asset, enabled):
        if asset.kind == "dictionary":
            for index in range(self.owner.packs.count()):
                item = self.owner.packs.item(index)
                if item.data(Qt.ItemDataRole.UserRole) == asset.value:
                    item.setCheckState(Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked)
                    break

    def filter_rows(self, *_):
        for row in self.rows.values():
            asset = row.asset
            present = asset.size > 0 or asset.status in {"Enabled", "Disabled", "Linked", "Built in"}
            visible = (present or self.add_resources.isChecked() or self.owner.operation_busy(asset.key))
            row.setVisible(visible and (not self.unused.isChecked() or not row.using))
        for section, content in self.sections.values():
            section.setVisible(any(not self.rows[asset.key].isHidden() for asset in self.assets if asset.language and
                                  self.rows[asset.key].container is content))

    def check_dictionary_updates(self):
        if self._update_task:
            return
        self.check_updates.setEnabled(False)
        self.update_notice.hide()
        self._update_task = UpdateCheck(self.owner.directory, self)
        self._update_task.finished.connect(self.updates_checked)
        self._update_task.thread.start()

    def updates_checked(self, updates):
        self._update_task.deleteLater()
        self._update_task = None
        self.check_updates.setEnabled(True)
        self.updates = {update.identity: update for update in updates}
        self.update_all.setEnabled(any(update.status == "Update available" for update in updates))
        available = sum(update.status == "Update available" for update in updates)
        manual = sum(update.status == "Replace from ZIP" for update in updates)
        failed = sum(update.status not in {"Update available", "Up to date", "Replace from ZIP"} for update in updates)
        summary = f"{available} update{'s' if available != 1 else ''} available." if available else "No updates found."
        if not updates:
            summary = "No dictionaries installed."
        if manual:
            summary += f" Update checks unavailable for {manual} dictionar{'ies' if manual != 1 else 'y'}; use Replace from ZIP."
        if failed:
            summary += f" {failed} update check{'s' if failed != 1 else ''} failed."
        self.update_summary.setText(summary)
        self.update_notice.show()
        self._update(self.assets)

    def install_updates(self):
        updates = [update for update in self.updates.values() if update.status == "Update available"]
        if updates:
            self.owner.begin_operation([], update=updates)

    def replace_zip(self, asset):
        archive, _ = QFileDialog.getOpenFileName(self, "Replace dictionary", "", "Yomitan ZIP (*.zip)")
        if archive:
            self.owner.begin_operation([], update=(archive, asset.identity))

    def transfer_resources(self, mode):
        if self.owner.operation_busy("all"):
            return
        if mode == "export":
            path, _ = QFileDialog.getSaveFileName(self, "Export resources", "wordcel-resources.zip", "Wordcel resources (*.zip)")
        else:
            path, _ = QFileDialog.getOpenFileName(self, "Import resources", "", "Wordcel resources (*.zip)")
        if path:
            self.owner.begin_operation([], bundle=(mode, path))
