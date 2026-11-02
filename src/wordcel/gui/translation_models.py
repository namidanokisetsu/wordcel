"""Explicit GGUF selection; repository metadata is fetched on a worker."""
import logging
import threading

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout,
                            QLabel, QLineEdit, QPushButton, QVBoxLayout)


class ModelFiles(QObject):
    finished = pyqtSignal(int, object, str)

    def find(self, revision, repository):
        def run():
            try:
                from wordcel.translation_models import list_hub_models
                files, error = list_hub_models(repository), ""
            except Exception:
                logging.getLogger(__name__).exception("Could not read GGUF repository")
                files, error = [], "Could not read that repository. Check its name and connection."
            try:
                self.finished.emit(revision, files, error)
            except RuntimeError:
                pass
        threading.Thread(target=run, daemon=True, name="gguf-files").start()


class ModelDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Add translation model")
        self.setMinimumWidth(440)
        self.selection = None
        self.revision = 0
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.repository = QLineEdit()
        self.repository.setPlaceholderText("owner/model")
        self.repository.setToolTip("Public Hugging Face repository")
        self.repository.setAccessibleName("Hugging Face repository")
        form.addRow("Hugging Face", self.repository)
        self.find = QPushButton("Find GGUF files")
        self.find.clicked.connect(self.find_files)
        form.addRow(self.find)
        self.files = QComboBox()
        self.files.setAccessibleName("GGUF file")
        self.files.setMinimumContentsLength(24)
        self.files.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.files.setEnabled(False)
        form.addRow("File", self.files)
        layout.addLayout(form)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        local = QPushButton("Import GGUF…")
        local.clicked.connect(self.import_file)
        buttons.addWidget(local)
        buttons.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self.download = QPushButton("Download")
        self.download.setEnabled(False)
        self.download.clicked.connect(self.accept)
        buttons.addWidget(self.download)
        layout.addLayout(buttons)
        self.worker = ModelFiles(self)
        self.worker.finished.connect(self.show_files)
        self.repository.textEdited.connect(self.invalidate)
        self.repository.returnPressed.connect(self.find_files)
        self.files.currentIndexChanged.connect(self.update_selection)

    def invalidate(self):
        self.revision += 1
        self.files.clear()
        self.files.setEnabled(False)
        self.download.setEnabled(False)
        self.find.setEnabled(True)
        self.status.clear()

    def find_files(self):
        repository = self.repository.text().strip()
        if not repository:
            return
        self.invalidate()
        self.find.setEnabled(False)
        self.status.setText("Finding files…")
        self.worker.find(self.revision, repository)

    @pyqtSlot(int, object, str)
    def show_files(self, revision, files, error):
        if revision != self.revision:
            return
        self.find.setEnabled(True)
        for spec in files:
            name = spec.get("source_file", spec["file"])
            self.files.addItem(f'{name} ({spec["size"] / 1e9:.2g} GB)', spec)
        self.files.setEnabled(bool(files))
        self.status.setText(error or ("" if files else "No supported single-file GGUF models found."))
        self.update_selection()

    def update_selection(self):
        self.selection = self.files.currentData()
        self.download.setEnabled(self.selection is not None)
        if self.selection:
            self.files.setToolTip(self.files.currentText())

    def import_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import model", "", "GGUF models (*.gguf)")
        if path:
            self.selection = {"local_path": path}
            super().accept()

    def accept(self):
        if self.selection:
            super().accept()
