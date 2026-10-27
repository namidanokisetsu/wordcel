"""Enable and reorder pronunciation sources without syntax entry."""
from PyQt6.QtCore import Qt, QTimer, QSignalBlocker, pyqtSignal
from PyQt6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                             QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QMenu, QToolButton, QVBoxLayout, QWidget)
import json
from pathlib import Path
from urllib.parse import urlsplit

from wordcel.audio.sources import SOURCE_LABELS, is_local, source_key, source_label, source_type
from wordcel.audio.worker import AudioRequest, AudioWorker


class AudioSources(QWidget):
    changed = pyqtSignal()
    sources_ready = pyqtSignal(str, object)
    failed = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.worker = None
        self.path = ""
        self._prefer_local = False
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.items = QListWidget()
        self.items.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.items.setMaximumHeight(130)
        self.items.setToolTip("Sources are tried from top to bottom")
        layout.addWidget(self.items)
        arrows = QVBoxLayout()
        for label, delta in (("↑", -1), ("↓", 1)):
            button = QToolButton()
            button.setText(label)
            button.setToolTip("Move source up" if delta < 0 else "Move source down")
            button.clicked.connect(lambda _, step=delta: self.move(step))
            arrows.addWidget(button)
        arrows.addStretch()
        self.add_button = QToolButton()
        self.add_button.setText("+")
        self.add_button.setToolTip("Add source")
        self.add_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.add_button)
        for kind, label in SOURCE_LABELS.items():
            if kind not in ("tts", "online"):
                menu.addAction(label, lambda checked=False, kind=kind: self.configure(kind=kind))
        menu.addSeparator()
        menu.addAction("Import Yomitan…", self.import_sources)
        self.add_button.setMenu(menu)
        arrows.addWidget(self.add_button)
        for label, tip, callback in (("…", "Edit source", self.configure), ("−", "Remove source", self.remove)):
            button = QToolButton()
            button.setText(label)
            button.setToolTip(tip)
            button.clicked.connect(callback)
            arrows.addWidget(button)
        layout.addLayout(arrows)
        self.items.model().rowsMoved.connect(lambda *_: QTimer.singleShot(0, self.changed.emit))
        self.items.itemChanged.connect(lambda _: self.changed.emit())
        self.items.itemDoubleClicked.connect(lambda _: self.configure())
        self.sources_ready.connect(self.received)

    def order(self):
        return [self.items.item(index).data(Qt.ItemDataRole.UserRole) for index in range(self.items.count())
                if self.items.item(index).checkState() == Qt.CheckState.Checked]

    def load(self, sources, path, *, prefer_local=False):
        self.path = path
        self._prefer_local = prefer_local
        with QSignalBlocker(self.items):
            self.items.clear()
            seen = set()
            for source in [*sources, "online", "tts"]:
                key = source_key(source)
                if key in seen:
                    continue
                seen.add(key)
                if path or not is_local(source):
                    self.add(source, enabled=source in sources)
            self.items.setCurrentRow(0)
        if path:
            if self.worker is None:
                self.worker = AudioWorker(lambda _: None, self.report_status, sources_callback=self.sources_ready.emit)
                self.worker.start()
            self.worker.submit(AudioRequest(0, None, path, ()))

    def report_status(self, text):
        if not text.startswith("Audio database ready"):
            self.failed.emit(text)

    def add(self, source, index=None, *, enabled=True):
        item = QListWidgetItem(source_label(source))
        item.setData(Qt.ItemDataRole.UserRole, source)
        item.setToolTip("Recordings from your selected database" if is_local(source)
                        else "Requires an installed voice for this language" if source_type(source) in (
                            "tts", "text-to-speech", "text-to-speech-reading")
                        else "Pronunciations vary by word and language")
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked)
        self.items.insertItem(self.items.count() if index is None else index, item)

    def received(self, path, sources):
        if path != self.path:
            return
        before = self.order()
        available = list(dict.fromkeys("db:" + source for source in sources))
        order = [self.items.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.items.count())]
        order = [source for source in order if not is_local(source) or source in available]
        local = list(dict.fromkeys([*(source for source in order if is_local(source)), *available]))
        enabled = {source_key(source) for source in before}
        if self._prefer_local:
            order = local + [source for source in order if not is_local(source)]
            enabled.update(local)
        else:
            order += [source for source in local if source not in order]
        changed = self._prefer_local or before != [source for source in order if source_key(source) in enabled]
        self._prefer_local = False
        with QSignalBlocker(self.items):
            self.items.clear()
            for source in order:
                self.add(source, enabled=source_key(source) in enabled)
            self.items.setCurrentRow(0)
        if changed:
            self.changed.emit()

    def move(self, delta):
        row = self.items.currentRow()
        target = row + delta
        if row >= 0 and 0 <= target < self.items.count():
            self.items.insertItem(target, self.items.takeItem(row))
            self.items.setCurrentRow(target)
            self.changed.emit()

    def configure(self, checked=False, *, kind=None):
        item = self.items.currentItem() if kind is None else None
        source = item.data(Qt.ItemDataRole.UserRole) if item else None
        if kind is None and (source is None or source_type(source) in ("tts", "online") or is_local(source)):
            return
        if kind and kind not in ("custom", "custom-json", "text-to-speech", "text-to-speech-reading"):
            self.add({"type": kind, "url": "", "voice": ""})
            self.items.setCurrentRow(self.items.count() - 1)
            self.changed.emit()
            return
        dialog = _SourceDialog(source or {"type": kind, "url": "", "voice": ""}, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            with QSignalBlocker(self.items):
                row = self.items.row(item) if item else self.items.count()
                enabled = item is None or item.checkState() == Qt.CheckState.Checked
                if item:
                    self.items.takeItem(row)
                self.add(dialog.source(), row, enabled=enabled)
                self.items.setCurrentRow(row)
            self.changed.emit()

    def remove(self):
        row = self.items.currentRow()
        if row >= 0:
            self.items.takeItem(row)
            self.changed.emit()

    def import_sources(self):
        path, _ = QFileDialog.getOpenFileName(self, "Yomitan settings", "", "JSON (*.json)")
        if not path:
            return
        try:
            value = json.loads(Path(path).read_text(encoding="utf-8"))
            if isinstance(value, dict) and "profiles" in value:
                profiles = value["profiles"]
                names = [f"{i + 1}. {profile['name']}" for i, profile in enumerate(profiles)]
                name, accepted = QInputDialog.getItem(self, "Yomitan profile", "Profile", names, editable=False)
                if not accepted:
                    return
                value = profiles[names.index(name)]["options"]["audio"]["sources"]
            self.append_sources(value)
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            self.failed.emit("Could not import Yomitan audio sources.")

    def append_sources(self, sources):
        if not isinstance(sources, list) or any(
                not isinstance(source, dict) or source.get("type") not in SOURCE_LABELS
                or source["type"] in ("tts", "online")
                or any(not isinstance(source.get(key, ""), str) for key in ("url", "voice")) for source in sources):
            raise ValueError("Invalid Yomitan audio sources")
        incoming, known = [], set()
        for source in sources:
            source = {"type": source["type"], "url": source.get("url", ""), "voice": source.get("voice", "")}
            if source_key(source) not in known:
                incoming.append((source, True))
                known.add(source_key(source))
        current = [(self.items.item(i).data(Qt.ItemDataRole.UserRole),
                    self.items.item(i).checkState() == Qt.CheckState.Checked) for i in range(self.items.count())]
        merged = incoming + [(source, enabled) for source, enabled in current if source_key(source) not in known]
        if merged == current:
            return
        with QSignalBlocker(self.items):
            self.items.clear()
            for source, enabled in merged:
                self.add(source, enabled=enabled)
            self.items.setCurrentRow(0)
        self.changed.emit()

    def shutdown(self):
        if self.worker:
            self.worker.stop()
            self.worker.join(timeout=1)
            self.worker = None
        self.path = ""


class _SourceDialog(QDialog):
    def __init__(self, source, parent):
        super().__init__(parent)
        self.setWindowTitle("Audio source")
        self.speech = None
        form = QFormLayout(self)
        self.kind = QComboBox()
        for kind, label in SOURCE_LABELS.items():
            if kind not in ("tts", "online"):
                self.kind.addItem(label, kind)
        self.kind.setCurrentIndex(self.kind.findData(source_type(source)))
        form.addRow("Source", self.kind)
        self.url = QLineEdit(source.get("url", "") if isinstance(source, dict) else "")
        self.url.setPlaceholderText("http://localhost:5050/?term={term}&reading={reading}")
        form.addRow("URL", self.url)
        self.voice = QComboBox()
        self.voice.addItem("System default", "")
        self.saved_voice = source.get("voice", "") if isinstance(source, dict) else ""
        form.addRow("Voice", self.voice)
        self.note = QLabel("{term} · {reading} · {language}")
        form.addRow(self.note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        form.addRow(buttons)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.kind.currentIndexChanged.connect(self.update_fields)
        self.ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.url.textChanged.connect(self.validate_url)
        self.update_fields()

    def update_fields(self):
        kind = self.kind.currentData()
        custom = kind in ("custom", "custom-json")
        speech = kind in ("text-to-speech", "text-to-speech-reading")
        self.layout().setRowVisible(self.url, custom)
        self.layout().setRowVisible(self.voice, speech)
        self.note.setVisible(custom)
        self.validate_url()
        if speech and self.speech is None:
            from PyQt6.QtTextToSpeech import QTextToSpeech
            self.speech = QTextToSpeech(self)
            for locale in self.speech.availableLocales():
                self.speech.setLocale(locale)
                for voice in self.speech.availableVoices():
                    if self.voice.findData(voice.name()) < 0:
                        self.voice.addItem(f"{voice.name()} ({voice.locale().name()})", voice.name())
            if self.saved_voice and self.voice.findData(self.saved_voice) < 0:
                self.voice.addItem(self.saved_voice, self.saved_voice)
            self.voice.setCurrentIndex(max(0, self.voice.findData(self.saved_voice)))

    def validate_url(self):
        valid = True
        if self.kind.currentData() in ("custom", "custom-json"):
            try:
                parsed = urlsplit(self.url.text().strip())
                valid = parsed.scheme in ("http", "https") and bool(parsed.hostname) and not parsed.username and not parsed.password
            except ValueError:
                valid = False
        self.ok.setEnabled(valid)

    def source(self):
        kind = self.kind.currentData()
        return {"type": kind, "url": self.url.text().strip() if kind in ("custom", "custom-json") else "",
                "voice": self.voice.currentData() if kind in ("text-to-speech", "text-to-speech-reading") else ""}
