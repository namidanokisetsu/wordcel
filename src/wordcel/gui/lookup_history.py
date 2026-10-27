"""History worker, recording timer and independent browsing window."""
from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict
from datetime import datetime, timedelta
from html import escape
from pathlib import Path

from PyQt6.QtCore import QObject, QPoint, QSignalBlocker, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAbstractTextDocumentLayout, QPalette, QTextDocument
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFormLayout,
                            QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                            QMessageBox, QPushButton, QStyledItemDelegate, QStyle, QVBoxLayout, QWidget)

from wordcel.history import EncounterSession, HistoryStore, primary_entries


class HistoryService(QObject):
    changed = pyqtSignal()
    preferences_changed = pyqtSignal()
    results = pyqtSignal(int, object)
    failed = pyqtSignal(str)

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.settings = window.settings
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="history")
        self.store = None
        self.closed = False
        self.engine = None
        self.session = EncounterSession()
        self.payload = None
        self.mode = "hover"
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.record)
        self.browser = None
        self.preferences_changed.connect(self.preferences_updated)
        self.maintenance = QTimer(self)
        self.maintenance.setInterval(3600000)
        self.maintenance.timeout.connect(self.prune)
        self.maintenance.start()
        self.prune()

    def value(self, key, default, kind=bool):
        return self.settings.value("history/" + key, default, kind)

    def enabled(self):
        return self.value("enabled", False)

    def _run(self, callback):
        if self.closed:
            return
        def run():
            try:
                if self.store is None:
                    from wordcel.utils.paths import paths
                    self.store = HistoryStore(Path(self.window.directory or paths.data_dir) / "history.sqlite3")
                callback()
            except Exception as error:
                self.failed.emit(str(error))
        self.executor.submit(run)

    def prune(self):
        days = self.value("retention", 0, int)
        if not days:
            return
        def work():
            self.store.prune(days)
            self.changed.emit()
        self._run(work)

    def preferences_updated(self):
        self.timer.stop()
        # Changes apply to subsequent visits; never backfill the displayed result.
        self.session.suppressed = True
        self.prune()

    def reset(self):
        self.timer.stop()
        self.session.reset()
        self.payload = None

    def display(self, result, context, start, end, mode, *, restored=False):
        identity = (result.source, result.text, context, start, end)
        changed = self.session.display(identity, enabled=self.enabled(), restored=restored)
        if changed:
            self.timer.stop()
        self.payload = (result, context, start, end)
        self.mode = mode
        if self.session.suppressed or self.session.recorded or not self.enabled():
            return
        if mode != "hover":
            self.timer.stop()
            self.record()
        elif changed and self.value("hover", False):
            self.timer.start(round(self.value("delay", 0.5, float) * 1000))

    def pin(self):
        self.timer.stop()
        self.mode = "pinned"
        self.record()

    def record(self):
        allowed = self.enabled() and self.value(self.mode, self.mode != "hover")
        if self.payload and self.session.claim(allowed):
            payload = self.payload
            import time
            timestamp = time.time()
            days = self.value("retention", 0, int)
            def work():
                self.store.record(*payload, timestamp=timestamp)
                self.store.prune(days)
                self.changed.emit()
            self._run(work)

    def search(self, revision, query, language, limit, preferred, preferences=None, max_lookup_length=25):
        def work():
            def forms():
                if not query or any(char.isspace() for char in query):
                    return ()
                from wordcel.dictionary.search import SearchEngine
                from wordcel.language.morphology import model_available
                if self.engine is None:
                    self.engine = SearchEngine(self.window.directory)
                self.engine.library.set_preferences(preferences)
                result = self.engine.search(query, source=language or preferred, foreign=language or preferred,
                                            morphology=model_available(language or preferred), romaji=True,
                                            max_lookup_length=max_lookup_length)
                if result.matched_length != len(query.strip()):
                    return ()
                return tuple(dict.fromkeys(entry.term for entry in primary_entries(result.entries)))
            rows, total = self.store.search(query, language, forms, limit=limit)
            self.results.emit(revision, (rows, total, self.store.languages()))
        self._run(work)

    def delete(self, identity):
        def work():
            self.store.delete(identity)
            self.changed.emit()
        self._run(work)

    def clear(self, parent):
        if QMessageBox.question(parent, "Clear history", "Delete all encounters?",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.delete(None)

    def open(self):
        if self.browser is None:
            self.browser = HistoryWindow(self)
        self.browser.showNormal()
        self.browser.raise_()
        self.browser.activateWindow()
        self.browser.refresh()

    def open_settings(self):
        self.window.open_settings()
        self.window._setup.tabs.setCurrentWidget(self.window._setup.history_tab)

    def shutdown(self):
        if self.closed:
            return
        self.closed = True
        self.reset()
        self.maintenance.stop()
        if self.browser:
            self.browser.close()
        def close():
            if self.engine:
                self.engine.close()
            if self.store:
                self.store.close()
        self.executor.submit(close)
        self.executor.shutdown(wait=True)


class HistorySettings(QWidget):
    def __init__(self, service):
        super().__init__()
        self.service = service
        layout = QFormLayout(self)
        self.checks = {}
        for key, title, default in (("enabled", "Enable history", False), ("pinned", "Pinned lookups", True),
                                    ("manual", "Manual/text lookups", True), ("hover", "Hover lookups", False),
                                    ("button_manual", "Show button in search", False),
                                    ("button_ocr", "Show button in OCR popups", False)):
            control = QCheckBox(title)
            self.checks[key] = control
            layout.addRow(control)
            control.toggled.connect(lambda value, key=key: self.save(key, value))
        self.delay = QDoubleSpinBox()
        self.delay.setRange(0.1, 60)
        self.delay.setSingleStep(0.1)
        self.delay.setSuffix(" s")
        layout.addRow("Display duration", self.delay)
        self.delay.valueChanged.connect(lambda value: self.save("delay", value))
        self.retention = QComboBox()
        for text, days in (("Forever", 0), ("30 days", 30), ("90 days", 90), ("1 year", 365)):
            self.retention.addItem(text, days)
        layout.addRow("Keep history", self.retention)
        self.retention.currentIndexChanged.connect(lambda _: self.save("retention", self.retention.currentData()))
        clear = QPushButton("Clear history")
        clear.clicked.connect(lambda: service.clear(self))
        layout.addRow(clear)
        service.preferences_changed.connect(self.sync)
        self.sync()

    def sync(self):
        for key, control in self.checks.items():
            with QSignalBlocker(control):
                control.setChecked(self.service.value(key, key in ("pinned", "manual")))
        with QSignalBlocker(self.delay), QSignalBlocker(self.retention):
            self.delay.setValue(self.service.value("delay", 0.5, float))
            self.retention.setCurrentIndex(max(0, self.retention.findData(self.service.value("retention", 0, int))))
        self.layout().setRowVisible(self.delay, self.checks["hover"].isChecked())

    def save(self, key, value):
        self.service.settings.setValue("history/" + key, value)
        self.service.preferences_changed.emit()


class CardDelegate(QStyledItemDelegate):
    def __init__(self, parent):
        super().__init__(parent)
        self.documents = OrderedDict()

    def document(self, option, index):
        key = (index.data(Qt.ItemDataRole.DisplayRole), option.font.toString(), self.parent().viewport().width())
        if key in self.documents:
            self.documents.move_to_end(key)
            return self.documents[key]
        doc = QTextDocument()
        doc.setDefaultFont(option.font)
        doc.setHtml(index.data(Qt.ItemDataRole.DisplayRole))
        doc.setTextWidth(max(1, self.parent().viewport().width()))
        self.documents[key] = doc
        if len(self.documents) > 256:
            self.documents.popitem(last=False)
        return doc

    def sizeHint(self, option, index):
        return self.document(option, index).size().toSize()

    def paint(self, painter, option, index):
        painter.save()
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
        doc = self.document(option, index)
        painter.translate(option.rect.topLeft())
        context = QAbstractTextDocumentLayout.PaintContext()
        context.palette = option.palette
        if option.state & QStyle.StateFlag.State_Selected:
            context.palette.setColor(QPalette.ColorRole.Text, option.palette.highlightedText().color())
        doc.documentLayout().draw(painter, context)
        painter.restore()


class CardList(QListWidget):
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.scheduleDelayedItemsLayout()


class HistoryWindow(QDialog):
    def __init__(self, service):
        super().__init__()
        self.service = service
        self.revision = 0
        self.limit = 100
        self.rows = {}
        self.setWindowTitle("History")
        self.resize(620, 620)
        layout = QVBoxLayout(self)
        banner = QHBoxLayout()
        self.state = QLabel()
        banner.addWidget(self.state, 1)
        self.enable = QPushButton("Enable history")
        self.enable.clicked.connect(self.enable_history)
        banner.addWidget(self.enable)
        settings = QPushButton("Settings")
        settings.setFlat(True)
        settings.clicked.connect(service.open_settings)
        banner.addWidget(settings)
        layout.addLayout(banner)
        row = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("Search history")
        self.query.setClearButtonEnabled(True)
        self.query.setMaxLength(2000)
        row.addWidget(self.query, 1)
        self.language = QComboBox()
        self.language.addItem("All languages", "")
        row.addWidget(self.language)
        layout.addLayout(row)
        self.cards = CardList()
        self.cards.setSpacing(max(0, self.style().pixelMetric(QStyle.PixelMetric.PM_LayoutVerticalSpacing)))
        self.cards.setItemDelegate(CardDelegate(self.cards))
        self.cards.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.cards.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.cards.itemActivated.connect(self.open_card)
        self.cards.itemClicked.connect(self.open_card)
        layout.addWidget(self.cards, 1)
        self.status = QLabel()
        layout.addWidget(self.status)
        footer = QHBoxLayout()
        delete = QPushButton("Delete")
        delete.clicked.connect(self.delete_selected)
        footer.addWidget(delete)
        clear = QPushButton("Clear history")
        clear.clicked.connect(lambda: service.clear(self))
        footer.addWidget(clear)
        footer.addStretch()
        self.more = QPushButton("More")
        self.more.clicked.connect(self.load_more)
        footer.addWidget(self.more)
        layout.addLayout(footer)
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(180)
        self.debounce.timeout.connect(self.refresh)
        self.query.textChanged.connect(self.query_changed)
        self.language.currentIndexChanged.connect(self.query_changed)
        service.results.connect(self.receive)
        service.changed.connect(self.refresh)
        service.preferences_changed.connect(self.sync)
        service.failed.connect(self.status.setText)
        self.sync()

    def sync(self):
        enabled = self.service.enabled()
        self.state.setText("" if enabled else "History is off")
        self.enable.setVisible(not enabled)
        self.enable.setToolTip("Defaults: pinned and manual/text lookups")
        if not enabled and not self.service.settings.contains("history/enabled"):
            self.state.setText("History is off<br><small>Defaults: pinned and manual/text</small>")

    def enable_history(self):
        self.service.settings.setValue("history/enabled", True)
        self.service.preferences_changed.emit()

    def query_changed(self):
        self.revision += 1
        self.limit = 100
        self.debounce.start()

    def refresh(self):
        if not self.isVisible():
            return
        self.revision += 1
        from wordcel.config.config import config
        from wordcel.config.profiles import dictionary_preferences
        window = self.service.window
        self.service.search(self.revision, self.query.text(), self.language.currentData(), self.limit,
                            window.preferred_foreign, dictionary_preferences(window.settings, window.active_profile),
                            config.max_lookup_length)

    def load_more(self):
        self.limit += 100
        self.refresh()

    def receive(self, revision, response):
        if revision != self.revision:
            return
        rows, total, languages = response
        from wordcel.gui.quick_lookup import language_name
        current = self.language.currentData()
        if tuple(self.language.itemData(i) for i in range(1, self.language.count())) != languages:
            with QSignalBlocker(self.language):
                self.language.clear()
                self.language.addItem("All languages", "")
                for language in languages:
                    self.language.addItem(language_name(language), language)
                self.language.setCurrentIndex(max(0, self.language.findData(current)))
        self.rows = {row["id"]: row for row in rows}
        desired = []
        previous_day = None
        today = datetime.now().date()
        searching = bool(self.query.text().strip())
        for row in rows:
            stamp = datetime.fromtimestamp(row["timestamp"])
            day = stamp.date()
            if not searching and day != previous_day:
                title = "Today" if day == today else "Yesterday" if day == today - timedelta(days=1) else day.isoformat()
                desired.append((day.isoformat(), "<b>" + title + "</b>"))
                previous_day = day
            groups = {}
            for _, term, reading in row["words"]:
                readings = groups.setdefault(term, [])
                if reading and reading != term and reading not in readings:
                    readings.append(reading)
            words = [escape(term) + (" (" + "・".join(map(escape, readings)) + ")" if readings else "")
                     for term, readings in groups.items()]
            title = " · ".join(words) or escape(row["form"])
            text, start, end = row["context"], row["start"], row["end"]
            context = escape(text[:start]) + "<b>" + escape(text[start:end]) + "</b>" + escape(text[end:])
            html = "<b>" + title + "</b> &nbsp; " + stamp.strftime("%Y-%m-%d %H:%M" if searching else "%H:%M") + "<br>" + context.replace("\n", "<br>")
            if row["excerpt"]:
                html += "<br><i>" + escape(row["excerpt"]) + "</i>"
            desired.append((row["id"], html))
        selected = self.cards.currentItem()
        selected = selected.data(Qt.ItemDataRole.UserRole) if selected else None
        scroll = self.cards.verticalScrollBar().value()
        anchor = self.cards.itemAt(QPoint(0, 0))
        anchor_id = anchor.data(Qt.ItemDataRole.UserRole) if anchor else None
        anchor_top = self.cards.visualItemRect(anchor).top() if anchor else 0
        changed = False
        self.cards.setUpdatesEnabled(False)
        try:
            for index, (identity, html) in enumerate(desired):
                item = self.cards.item(index)
                if item is None or item.data(Qt.ItemDataRole.UserRole) != identity:
                    changed = True
                    existing = next((i for i in range(index + 1, self.cards.count()) if self.cards.item(i).data(Qt.ItemDataRole.UserRole) == identity), None)
                    item = self.cards.takeItem(existing) if existing is not None else QListWidgetItem()
                    item.setData(Qt.ItemDataRole.UserRole, identity)
                    if isinstance(identity, str):
                        item.setFlags(Qt.ItemFlag.NoItemFlags)
                    self.cards.insertItem(index, item)
                if item.text() != html:
                    changed = True
                    item.setText(html)
                if identity == selected:
                    self.cards.setCurrentItem(item)
            while self.cards.count() > len(desired):
                changed = True
                self.cards.takeItem(self.cards.count() - 1)
            if changed:
                self.cards.doItemsLayout()
                anchor = next((self.cards.item(i) for i in range(self.cards.count())
                               if self.cards.item(i).data(Qt.ItemDataRole.UserRole) == anchor_id), None)
                if anchor:
                    scroll += self.cards.visualItemRect(anchor).top() - anchor_top
            self.cards.verticalScrollBar().setValue(scroll)
        finally:
            self.cards.setUpdatesEnabled(True)
        self.more.setVisible(len(rows) < total)
        self.status.setText("" if rows else "No encounters" if not searching else "No matches")

    def open_card(self, item):
        row = self.rows.get(item.data(Qt.ItemDataRole.UserRole))
        if row:
            self.service.window.restore_encounter(row)

    def delete_selected(self):
        item = self.cards.currentItem()
        if item and item.data(Qt.ItemDataRole.UserRole) in self.rows:
            self.service.delete(item.data(Qt.ItemDataRole.UserRole))
