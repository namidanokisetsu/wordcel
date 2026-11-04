"""Compact, shared dictionary surface with a latest-request background worker."""
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import replace
from html import escape
import re
import math
import sys

from PyQt6.QtCore import QEvent, QPoint, QSettings, QSignalBlocker, QSize, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QCursor, QFontMetricsF, QImage, QKeyEvent, QKeySequence, QShortcut, QTextCursor, QTextDocument, QTextFormat
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel,
    QKeySequenceEdit, QLineEdit, QMenu, QSizePolicy, QSplitter, QStackedWidget, QTextEdit, QToolButton, QToolTip, QVBoxLayout, QWidget,
)

from wordcel.config.config import config
from wordcel.dictionary.search import SearchResult
from wordcel.gui.popup_style import DIVIDER_WIDTH, FRAME_PADDING, PANE_PADDING, expanded_geometry, frame_stylesheet, popup_entry_path_contains, popup_position, surface_colors
from wordcel.gui.action_icons import action_button, action_icon
from wordcel.gui.ruby import RubyBrowser
from wordcel.gui.language_names import LANGUAGE_NAMES, language_name
from wordcel.gui.lookup_render import (_compact_context, _dictionary_section_key, group_headwords, render_result)
from wordcel.gui.lookup_worker import LookupWorker
from wordcel.gui.profile_preferences import audio_autoplay_mode
from wordcel.language.profiles import default_partner
from wordcel.config.profiles import (profile_ids, profile_language, profile_name, languages as profile_languages,
                                     dictionary_preferences)
from wordcel.utils.timing import mark


def is_sentence(text):
    words = re.findall(r"[^\W\d_]+", text, re.UNICODE)
    return len(words) > 2 or bool(re.search(r"[。！？!?\n]|\.(?:\s|$)", text.strip())) or "、" in text


class LocalDictionaryBrowser(RubyBrowser):
    scrolled = pyqtSignal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.document().setDocumentMargin(0)
        from wordcel.gui.section_scroll import SectionScroller
        self.section_scroll = SectionScroller(self)

    def setHtml(self, html):
        self._resize_anchor = None
        document = self.document()
        updates = self.updatesEnabled()
        # An ancestor may already suppress painting; do not disable this child explicitly.
        if updates:
            self.setUpdatesEnabled(False)
        try:
            with QSignalBlocker(document), QSignalBlocker(self.verticalScrollBar()):
                document.setLayoutEnabled(False)
                try:
                    self._set_html(html)
                finally:
                    document.setLayoutEnabled(True)
                self.fit_glyphs()
            self.section_scroll._document_changed()
        finally:
            if updates:
                self.setUpdatesEnabled(True)

    def _set_html(self, html):
        super().setHtml(html)
        def heading_format(fmt):
            fmt.clearProperty(QTextFormat.Property.FontSizeAdjustment)
            size = fmt.property(QTextFormat.Property.FontPixelSize)
            if size:
                font = fmt.font()
                font.setPixelSize(int(size))
                fmt.setFont(font)
            return fmt

        indent = 0
        block = self.document().begin()
        while block.isValid():
            text_list = block.textList()
            if text_list is not None:
                metrics = QFontMetricsF(block.charFormat().font().resolve(self.document().defaultFont()))
                marker = text_list.itemText(block) or "•"
                indent = max(indent, math.ceil(metrics.horizontalAdvance(marker + " ")))
            if block.blockFormat().headingLevel():
                # Qt retains h2's relative enlargement alongside our explicit size.
                cursor = QTextCursor(block)
                cursor.setBlockCharFormat(heading_format(block.charFormat()))
                runs = []
                iterator = block.begin()
                while not iterator.atEnd():
                    fragment = iterator.fragment()
                    runs.append((fragment.position(), fragment.length(), fragment.charFormat()))
                    iterator += 1
                for start, length, fmt in runs:
                    cursor.setPosition(start)
                    cursor.setPosition(start + length, QTextCursor.MoveMode.KeepAnchor)
                    cursor.setCharFormat(heading_format(fmt))
            block = block.next()

        if indent:
            self.document().setIndentWidth(indent)
        # Qt can leave trailing blocks unlaid after inline replacements and heading edits.
        self.document().markContentsDirty(0, self.document().characterCount())

    def wheelEvent(self, event):
        super().wheelEvent(event)
        event.accept()

    def reading_anchor(self):
        scroller = getattr(self, "section_scroll", None)
        if scroller is None or scroller.preview or not self.verticalScrollBar().value():
            return None
        # Reuse the character across reflows so line wrapping cannot accumulate drift.
        if getattr(self, "_resize_anchor", None) is not None:
            return self._resize_anchor
        top = scroller.header.geometry().bottom() + 1 if scroller.header.isVisible() else 0
        cursor = self.cursorForPosition(QPoint(0, top))
        return cursor, self.cursorRect(cursor).top()

    @contextmanager
    def preserve_reading_position(self):
        anchor = self.reading_anchor()
        previous = getattr(self, "_reflowing", False)
        self._reflowing = True
        try:
            yield
        finally:
            try:
                self.section_scroll._refresh_header()
                if anchor is not None:
                    cursor, top = anchor
                    bar = self.verticalScrollBar()
                    bar.setValue(bar.value() + self.cursorRect(cursor).top() - top)
                self._resize_anchor = anchor
            finally:
                self._reflowing = previous

    def resizeEvent(self, event):
        if getattr(self, "section_scroll", None) is None:
            super().resizeEvent(event)
            return
        with self.preserve_reading_position():
            super().resizeEvent(event)
            self.section_scroll._lines = None

    def keyPressEvent(self, event):
        if not self.section_scroll.enabled and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            bar = self.verticalScrollBar()
            targets = {Qt.Key.Key_Up: bar.value() - bar.singleStep(),
                       Qt.Key.Key_Down: bar.value() + bar.singleStep(),
                       Qt.Key.Key_PageUp: bar.value() - bar.pageStep(),
                       Qt.Key.Key_PageDown: bar.value() + bar.pageStep(),
                       Qt.Key.Key_Home: 0, Qt.Key.Key_End: bar.maximum()}
            if event.key() in targets:
                bar.setValue(targets[event.key()])
                event.accept()
                return
        super().keyPressEvent(event)

    def scrollContentsBy(self, dx, dy):
        if not getattr(self, "_reflowing", False):
            self._resize_anchor = None
        scroller = getattr(self, "section_scroll", None)
        viewport = self.viewport()
        redraw = bool(scroller and scroller.enabled and not scroller.preview and viewport.updatesEnabled())
        # Qt's pixel scrolling moves viewport children before we restore their
        # anchors. Paint sticky headings and their actions at the final geometry.
        if redraw:
            viewport.setUpdatesEnabled(False)
        try:
            super().scrollContentsBy(dx, dy)
            if scroller is not None:
                scroller._update_header()
            self.scrolled.emit()
        finally:
            if redraw:
                viewport.setUpdatesEnabled(True)

    def loadResource(self, resource_type, name):
        if resource_type == QTextDocument.ResourceType.ImageResource.value and getattr(self, "library_root", None):
            from wordcel.dictionary.media import resolve_image
            path = resolve_image(self.library_root, name.toString())
            if path:
                image = QImage(str(path))
                return image if not image.isNull() else None
        return None


class LookupInput(QLineEdit):
    position_clicked = pyqtSignal(int)

    def mousePressEvent(self, event):
        self._lookup_press = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if (event.button() == Qt.MouseButton.LeftButton and not self.hasSelectedText()
                and not event.modifiers()
                and (event.position().toPoint() - self._lookup_press).manhattanLength() < QApplication.startDragDistance()):
            self.position_clicked.emit(self.cursorPositionAt(event.position().toPoint()))


class QuickLookupWindow(QDialog):
    dictionaries_changed = pyqtSignal()
    mode_changed = pyqtSignal(str)
    ocr_enabled_changed = pyqtSignal(bool)
    scan_settings_changed = pyqtSignal()
    models_changed = pyqtSignal()
    hotkey_requested = pyqtSignal()
    translation_requested = pyqtSignal()
    hover_toggle_requested = pyqtSignal()
    copy_requested = pyqtSignal()
    next_profile_requested = pyqtSignal()
    previous_profile_requested = pyqtSignal()
    profile_activated = pyqtSignal(str)
    anki_notification = pyqtSignal(str)
    selection_requested = pyqtSignal()
    clipboard_requested = pyqtSignal()

    def __init__(self, directory=None, engine_factory=None, settings=None):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        if sys.platform == "darwin":
            self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)
        if QApplication.platformName() == "xcb":
            self.setWindowFlag(Qt.WindowType.X11BypassWindowManagerHint)
        self.directory = directory
        self.settings = settings or QSettings("wordcel", "wordcel")
        from wordcel.config.profiles import migrate
        migrate(self.settings, directory)
        from wordcel.gui.profile_appearance import load_appearance
        load_appearance(self.settings, self.settings.value("profile", ""))
        self.revision = 0
        self._result = None
        self._display_revision = None
        self._pending_revision = None
        self._paint_revision = None
        self._document_revision = None
        self._render_identity = None
        self._fit_identity = None
        self._static_disclosure = False
        self._preserve_scroll = False
        self._needs_place = False
        self._context = ""
        self._encounter_restore = None
        self._encounter_context = None
        from wordcel.gui.lookup_history import HistoryService
        self.lookup_history = HistoryService(self)
        self._peek = False
        self._source_overlay = False
        self._history = []
        self._new_chain = True
        self._expanded = set()
        self._collapsed = set()
        self._details_expanded = set()
        self._kanji_details = set()
        self._kanji_origin = ""
        self._kanji_return_position = None
        self._kanji_heading = None
        self._kanji_heading_anchor = None
        self._pin_anchor_click = False
        self._shutting_down = False
        self._drag_position = None
        self._drag_start = None
        self._dragging = False
        self._resize_start = None
        self._resize_close_guard = False
        self._engage_press = None
        self._setup = None
        self._engine_factory = engine_factory
        self.translation_worker = None
        self._pending_context = None
        self._translation_busy = False
        self._last_request_translate = False
        self._translation_base = None
        self._translation_previous = None
        self._partial_translation = False
        self._translation_chunk = None
        self._translation_model_state = ""
        self._remember_request = False
        self.audio = None
        from wordcel.gui.lookup_anki import LookupAnki
        self.lookup_anki = LookupAnki(self)
        self.lookup_anki.changed.connect(self.update_anki)
        self._headword_rows = {}
        self._headword_blocks = []
        self._action_heading = None
        self._translation_view = False
        self._automatic_translation = False
        self._auto_translation_pending = None
        self._translation_return = None
        self._translation_text = ""
        self._translation_direction = ("auto", "auto")
        self._autoplayed = None
        self._scan_hold_active = False
        self._selection_lookup = False
        self.tray_geometry = None
        self._manual_at_cursor = False
        self._opening_search = False
        self._previous_foreground = None
        self._previous_focus = None
        self._passive_text = False
        self._selection_passive = False
        self._selection_for_search = False
        self._capture_visibility = False
        self.setWindowTitle("Wordcel")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(340, 190)
        self.resize(480, 340)
        self._normal_size = QSize(480, 340)
        self._corner_size = self.settings.value("corner_size", QSize(480, 340), type=QSize)
        self._reading_size_custom = False
        self._auto_fit_size = None
        self._preview_viewport_height = 0
        self._lookup_anchor = None
        self._lookup_vertical = False
        self._lookup_entry_pending = False
        self._result_screenshot = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.frame = QFrame()
        outer.addWidget(self.frame)
        layout = QVBoxLayout(self.frame)
        layout.setContentsMargins(FRAME_PADDING, PANE_PADDING, FRAME_PADDING, PANE_PADDING)
        layout.setSpacing(3)
        self.actions_row = QWidget()
        toolbar = QHBoxLayout(self.actions_row)
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(2)
        self.history_button = self._action("history", "History")
        self.history_button.clicked.connect(self.lookup_history.open)
        toolbar.addWidget(self.history_button)
        self.back = self._action("back", "Back")
        self.back.setEnabled(False)
        self.back.clicked.connect(self.go_back)
        toolbar.addWidget(self.back)
        self.title = QLabel("")
        self.title.setTextFormat(Qt.TextFormat.RichText)
        self.title.linkActivated.connect(self._history_jump)
        self.title.setMinimumWidth(0)
        self.title.installEventFilter(self)
        toolbar.addWidget(self.title, 1)
        self.scan_toggle = QCheckBox(self)
        self.scan_toggle.setToolTip("Screen lookup with your configured scan key")
        self.scan_toggle.toggled.connect(self.ocr_enabled_changed)
        self.scan_toggle.hide()
        self.pin = self._action("pin", "Pin")
        self.pin.setCheckable(True)
        self.pin.setParent(self)
        self.pin.hide()
        self.pin.setToolTip("Keep this result open and resize it")
        self.pin.toggled.connect(self._pin_changed)
        self.copy_button = self._action("copy", "Copy sentence")
        self.copy_button.setEnabled(False)
        self.copy_button.clicked.connect(self.copy_sentence)
        self.settings_button = self._action("settings", "Settings")
        self.settings_menu = QMenu(self.settings_button)
        self.settings_menu.addAction("Settings", self.open_settings)
        self.settings_button.setMenu(self.settings_menu)
        self.settings_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.settings_button.setParent(self)
        self.settings_button.hide()
        close = self._action("close", "Close")
        close.clicked.connect(self.hide)
        self.dismiss_button = close
        self.mode_row = QWidget()
        controls = QHBoxLayout(self.mode_row)
        controls.setContentsMargins(0, 0, 0, 0)
        self.source = QComboBox()
        self.source.setAccessibleName("Profile")
        self.source.setToolTip("Active profile")
        self.foreign = QComboBox()
        self.foreign.setAccessibleName("Translation pair")
        self.foreign.setToolTip("Translate in either direction within this pair")
        self.source.setMinimumContentsLength(8)
        self.foreign.setMinimumContentsLength(7)
        self.target_label = QLabel()
        self.target_label.setAccessibleName("Translation pair")
        self.update_languages(())
        initial_profile = self.settings.value("profile", "")
        self.source.setCurrentIndex(max(0, self.source.findData(initial_profile)))
        self.update_translation_languages(self.settings.value(f"profiles/{initial_profile}/target", default_partner(profile_language(self.settings, initial_profile))))
        self.translate = self._action("translate", "Translate")
        self.translate.setEnabled(False)
        self.translate.clicked.connect(self._translate_clicked)
        self.translate_sentence = self.translate
        self.search = LookupInput()
        self.search.position_clicked.connect(self._lookup_input_position)
        self.search.selectionChanged.connect(lambda: setattr(self, "_input_lookup", None))
        self.search.setPlaceholderText("Search")
        self.search.setAccessibleName("Search text")
        self.search.textEdited.connect(lambda _: setattr(self, "_selection_lookup", False))
        self.search.setMaxLength(2000)
        self.search.textChanged.connect(self._edited)
        self.search.returnPressed.connect(lambda: self.submit(selection=True))
        self.search.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.search.customContextMenuRequested.connect(self._input_menu)
        self.header = QWidget()
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setAlignment(Qt.AlignmentFlag.AlignRight)
        header_layout.addWidget(self.search, 1)
        self.audio_actions = QWidget()
        action_layout = QHBoxLayout(self.audio_actions)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(2)
        self.anki_button = self._action("anki", "Add to Anki")
        self.anki_button.clicked.connect(self.add_to_anki)
        action_layout.addWidget(self.anki_button)
        self.sentence_audio_button = self._action("audio_sentence", "Read sentence")
        self.sentence_audio_button.clicked.connect(lambda: self.play_audio(sentence=True))
        self.sentence_audio_button.setEnabled(False)
        action_layout.addWidget(self.sentence_audio_button)
        self.audio_button = self._action("audio", "Play pronunciation")
        self.audio_button.setEnabled(False)
        self.audio_button.clicked.connect(self.play_audio)
        self.audio_button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.audio_button.customContextMenuRequested.connect(self.audio_source_menu)
        action_layout.addWidget(self.audio_button)
        header_layout.addWidget(self.audio_actions, 0, Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.header)
        controls.addWidget(self.source)
        controls.addWidget(self.target_label)
        controls.addWidget(self.foreign)
        controls.addStretch()
        layout.addWidget(self.mode_row)
        self.context_label = QLabel()
        self.context_label.setWordWrap(True)
        self.context_label.setVisible(False)
        self.context_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.context_label.setParent(self)
        self.browser = LocalDictionaryBrowser(selection_lookup=self.settings.value(
            f"profiles/{initial_profile}/selection_lookup", False, bool))
        from wordcel.dictionary.library import default_library_path
        self.browser.library_root = directory or default_library_path()
        self.browser.section_scroll.set_enabled(self.settings.value(f"profiles/{initial_profile}/snap_scrolling", True, bool))
        self.browser.setOpenLinks(False)
        self.browser.setOpenExternalLinks(False)
        self.browser.setAccessibleName("Dictionary results")
        self.link_timer = QTimer(self)
        self.link_timer.setSingleShot(True)
        self.link_timer.timeout.connect(self._activate_link)
        self._pending_link = None
        self.browser.anchorClicked.connect(self._queue_link)
        self.browser.word_selected.connect(self.lookup_word)
        from wordcel.gui.translation_view import TranslationPanel
        self.translation_panel = TranslationPanel(self.settings)
        self.translation_browser = self.translation_panel.output
        self.translation_panel.language_requested.connect(self._translation_language_menu)
        self.translation_panel.language_selected.connect(self._set_translation_language)
        self.translation_panel.translate_requested.connect(self._submit_translation_source)
        self.translation_panel.source_changed.connect(self._translation_source_edited)
        self.translation_debounce = QTimer(self)
        self.translation_debounce.setSingleShot(True)
        self.translation_debounce.setInterval(500)
        self.translation_debounce.timeout.connect(self._submit_translation_source)
        self.translation_panel.source.composition_changed.connect(self._translation_composition_changed)
        self.translation_panel.swap_requested.connect(self._swap_translation_languages)
        self.content_stack = QStackedWidget()
        self.content_stack.addWidget(self.translation_panel)
        self.content_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        self.content_stack.setMinimumHeight(self.browser.fontMetrics().height())
        self.kanji_panel = QWidget()
        kanji_layout = QVBoxLayout(self.kanji_panel)
        kanji_layout.setContentsMargins(0, 0, 0, 0)
        self.kanji_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        self.kanji_browser = RubyBrowser()
        self.kanji_browser.adaptive_glyphs = True
        self.kanji_browser.setAccessibleName("Kanji details")
        self.kanji_browser.setOpenLinks(False)
        self.kanji_browser.setOpenExternalLinks(False)
        self.kanji_browser.anchorClicked.connect(self._queue_link)
        kanji_layout.addWidget(self.kanji_browser, 1)
        self.content_stack.addWidget(self.kanji_panel)
        from wordcel.gui.translation_view import TranslationView
        self.automatic_output = TranslationView()
        self.automatic_output.setAccessibleName("Automatic translation")
        self.lookup_splitter = QSplitter(Qt.Orientation.Vertical)
        self.lookup_splitter.setChildrenCollapsible(False)
        self.lookup_splitter.setHandleWidth(DIVIDER_WIDTH)
        self.lookup_splitter.addWidget(self.browser)
        self.lookup_splitter.addWidget(self.automatic_output)
        self.lookup_splitter.setStretchFactor(0, 1)
        self.lookup_splitter.setStretchFactor(1, 1)
        self.automatic_output.hide()
        self.content_stack.addWidget(self.lookup_splitter)
        self.content_stack.setCurrentWidget(self.lookup_splitter)
        layout.addWidget(self.content_stack, 1)
        self._kanji_html = ""
        self._kanji_heading_identity = None
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.status.linkActivated.connect(self._open_permission_settings)
        self.status.hide()
        layout.addWidget(self.status)
        toolbar.addWidget(self.translate)
        toolbar.addWidget(self.copy_button)
        toolbar.addWidget(close)
        layout.addWidget(self.actions_row)
        self.actions_row.hide()
        self.lookup_history.preferences_changed.connect(self._place_actions)
        self._popup_actions = dict(anki=self.anki_button, audio_sentence=self.sentence_audio_button,
                                   audio=self.audio_button, translate=self.translate, copy=self.copy_button,
                                   close=self.dismiss_button, back=self.back)
        self.browser.verticalScrollBar().valueChanged.connect(self._position_actions)
        self.browser.document().documentLayout().documentSizeChanged.connect(self._position_actions)
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(180)
        self.debounce.timeout.connect(lambda: self.submit(auto_translate=False))
        self.busy_delay = QTimer(self)
        self.busy_delay.setSingleShot(True)
        self.busy_delay.setInterval(175)
        self.busy_delay.timeout.connect(self._show_busy)
        self.fit_timer = QTimer(self)
        self.fit_timer.setSingleShot(True)
        self.fit_timer.timeout.connect(lambda: self._fit_preview())
        self.render_timer = QTimer(self)
        self.render_timer.setSingleShot(True)
        self.render_timer.timeout.connect(self._render)
        self.stream_timer = QTimer(self)
        self.stream_timer.setSingleShot(True)
        self.stream_timer.setInterval(80)
        self.stream_timer.timeout.connect(self._flush_translation)
        self.cursor_leave_timer = QTimer(self)
        self.cursor_leave_timer.setInterval(50)
        self.cursor_leave_timer.timeout.connect(self._check_cursor_leave)
        self.source.currentIndexChanged.connect(self._mode_changed)
        self.foreign.currentIndexChanged.connect(self._mode_changed)
        self.worker = LookupWorker(directory, engine_factory)
        self.worker.completed.connect(self.deliver)
        self.worker.failed.connect(self._failed)
        self.worker.languages.connect(self.update_languages)
        self.worker.start()
        self.hotkey_requested.connect(self.toggle_lookup)
        self.translation_requested.connect(self.open_translation)
        from wordcel.gui.lookup_shortcuts import LookupShortcuts
        self.lookup_shortcuts = LookupShortcuts(self)
        QApplication.instance().applicationStateChanged.connect(self._application_state_changed)
        self.next_profile_requested.connect(lambda: self.cycle_profile(1))
        self.previous_profile_requested.connect(lambda: self.cycle_profile(-1))
        from wordcel.gui.selection import SelectionCapture
        self.selection = SelectionCapture(self)
        self.selection.completed.connect(self._selected_text_ready)
        self.selection.unavailable.connect(self._selection_unavailable)
        self.selection_requested.connect(self.request_selection)
        self.clipboard_requested.connect(lambda: self.lookup_selected(QApplication.clipboard().text()))
        from wordcel.gui.popup_shortcuts import POPUP_ACTIONS
        self._popup_shortcuts = {}
        for action, _, _ in POPUP_ACTIONS:
            shortcut = QShortcut(self)
            shortcut.setAutoRepeat(False)
            shortcut.activated.connect(lambda action=action: self.popup_action(action))
            self._popup_shortcuts[action] = shortcut
        self.copy_shortcut = self._popup_shortcuts["copy"]
        self.selection_copy_shortcut = self._popup_shortcuts["copy_text"]
        self.back_shortcut = self._popup_shortcuts["back"]
        self.anki_shortcut = self._popup_shortcuts["anki"]
        self.reload_popup_shortcuts()
        self.apply_style()
        self._update_target_visibility()
        self.browser.clear()
        for widget in self.findChildren(QWidget):
            widget.installEventFilter(self)
            widget.setMouseTracking(True)
        self.setMouseTracking(True)
        self.installEventFilter(self)

    def _action(self, name, description):
        return action_button(name, description, config.color_foreground)

    @property
    def is_pinned(self):
        return self.pin.isChecked()

    @property
    def interaction_state(self):
        from wordcel.gui.lookup_session import popup_mode
        return popup_mode(visible=self.isVisible(), preview=self._peek,
                          pinned=self.is_pinned, passive=self._passive_text)

    @property
    def active_profile(self):
        return self.source.currentData() or self.settings.value("profile", "")

    @property
    def preferred_foreign(self):
        return profile_language(self.settings, self.active_profile)

    def apply_style(self):
        colors = surface_colors(config.color_background, config.color_foreground)
        self.frame.setStyleSheet(frame_stylesheet(config.color_background, config.color_foreground,
                                                  config.background_opacity, config.font_family) + f'''
            QLineEdit,QComboBox,QTextBrowser,QTextEdit {{background:transparent;color:{config.color_foreground};
                border:0;padding:3px;selection-background-color:{config.color_highlight_word};
                selection-color:{config.color_background};}}
            QLineEdit {{border-bottom:1px solid {colors['border']};}}
            QTextBrowser,QTextEdit {{border-radius:0;padding:0;}}
            QStackedWidget {{background:transparent;border:0;border-radius:0;}}
            QSplitter {{background:transparent;border:0;border-radius:0;}}
            QSplitter::handle {{background:{colors['border']};}}
            QSplitter::handle:hover {{background:{colors['muted']};}}
            QComboBox QAbstractItemView {{background:{config.color_background};color:{config.color_foreground};}}
            QPushButton,QToolButton {{background:transparent;color:{config.color_foreground};
                border:0;border-radius:4px;padding:3px 5px;}}
            QToolButton[action_name] {{padding:3px;}}
            QPushButton:hover,QToolButton:hover,QToolButton:checked {{background:{colors['hover']};}}
            QPushButton:disabled,QToolButton:disabled {{color:{colors['muted']};}}
            QMenu {{background:{config.color_background};color:{config.color_foreground};
                border:1px solid {colors['border']};padding:4px;}}
            QMenu::item:selected {{background:{colors['hover']};}}
            QCheckBox {{color:{config.color_foreground};spacing:4px;}}
            QScrollBar:vertical {{background:transparent;width:9px;margin:0;}}
            QScrollBar::handle:vertical {{background:{colors['scroll']};min-height:20px;border-radius:1px;margin:0 3px;}}
            QScrollBar::handle:vertical:hover {{background:{colors['muted']};}}
            QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {{height:0;}}
            QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical {{background:transparent;}}
            QScrollBar:horizontal {{background:transparent;height:3px;margin:0;}}
            QScrollBar::handle:horizontal {{background:{colors['scroll']};min-width:20px;border-radius:1px;}}
            QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal {{width:0;}}
            QScrollBar::add-page:horizontal,QScrollBar::sub-page:horizontal {{background:transparent;}}
        ''')
        from wordcel.gui.typography import document_font
        font = document_font(config.font_family, config.font_size_definitions, self.preferred_foreign)
        self.browser.setFont(font)
        self.kanji_browser.setFont(font)
        self.translation_browser.setFont(document_font(config.font_family, config.font_size_sentence, self.preferred_foreign))
        self.automatic_output.setFont(self.translation_browser.font())
        self.translation_panel.source.setFont(self.translation_browser.font())
        self.title.ensurePolished()
        # QLabel puts Japanese font leading below the text; balance its visible ink with the icons.
        self.title.setContentsMargins(0, max(0, self.title.fontMetrics().leading()), 0, 0)
        self.translation_panel.set_side_by_side(self.settings.value(f"profiles/{self.active_profile}/translation_side_by_side", False, bool))
        self.search.setFont(font)
        self.target_label.setPixmap(action_icon("swap", config.color_foreground).pixmap(
            self.translate.iconSize(), self.devicePixelRatioF()))
        for button in self.findChildren(QToolButton):
            name = button.property("action_name")
            if name:
                button.setIcon(action_icon(name, config.color_foreground))

    def reload_appearance(self, render=True):
        from wordcel.gui.profile_appearance import load_appearance
        font_keys = ("font_family", "font_size_header", "font_size_reading", "font_size_definitions", "font_size_sentence", "furigana_scale")
        previous_font = tuple(getattr(config, key) for key in font_keys)
        load_appearance(self.settings, self.active_profile)
        position = None
        if render and self._result is not None and previous_font != tuple(getattr(config, key) for key in font_keys):
            from wordcel.gui.section_scroll import ReadingPosition
            position = ReadingPosition(self.browser)
        self.browser.section_scroll.set_enabled(self.settings.value(f"profiles/{self.active_profile}/snap_scrolling", True, bool))
        self.apply_style()
        if hasattr(self, "_popup_shortcuts"):
            self.reload_popup_shortcuts()
        if render:
            before = tuple(button.isHidden() for button in self._popup_actions.values())
            self._place_actions()
            changed = before != tuple(button.isHidden() for button in self._popup_actions.values())
            self._render(static=changed, preserve_scroll=changed, position=position)

    def compact_preview(self):
        return self.settings.value(f"profiles/{self.active_profile}/compact_preview", True, type=bool)

    def update_languages(self, languages=None):
        if languages is not None:
            self._imported_languages = tuple(languages)
        languages = getattr(self, "_imported_languages", ())
        codes = profile_ids(self.settings)
        from wordcel.dictionary.library import Library
        library = Library(self.directory)
        try:
            self._dictionary_titles = {meta["resource_id"]: meta["title"] for _, meta, _ in library.packs}
        finally:
            library.close()
        current_source = self.source.currentData() or self.settings.value("profile", "")
        with QSignalBlocker(self.source):
            self.source.clear()
            for code in codes:
                self.source.addItem(profile_name(self.settings, code), code)
            self.source.setCurrentIndex(max(0, self.source.findData(current_source)))
        self.update_translation_languages()

    def update_translation_languages(self, target=None):
        from wordcel.dictionary.translation import load_profile_settings, translation_language
        from wordcel.language.support import translation_languages
        profile = self.source.currentData() or self.settings.value("profile", "")
        try:
            options = load_profile_settings(self.settings, profile)
            from wordcel.translation_models import is_custom_profile
            provider = "custom" if is_custom_profile(options.profile) else options.provider
        except ValueError:
            provider = "server"
        target = target or self.foreign.currentData() or self.settings.value(f"profiles/{profile}/target", default_partner(profile))
        if provider == "server":
            target = translation_language(target)
        codes = sorted(translation_languages(provider, getattr(self, "_imported_languages", ()),
                                             (*profile_languages(self.settings), profile_language(self.settings, profile), target)) - {"", None})
        tooltip = "Language support depends on your server model" if provider == "custom" else ""
        with QSignalBlocker(self.foreign):
            self.foreign.clear()
            for code in dict.fromkeys([*codes, target]):
                self.foreign.addItem(language_name(code), code)
                item = self.foreign.model().item(self.foreign.count() - 1)
                item.setEnabled(code in codes)
                item.setToolTip(tooltip if code in codes else "The selected model does not support this language")
            self.foreign.setCurrentIndex(self.foreign.findData(target))
        self.foreign.setToolTip(tooltip or ("Translate in either direction within this pair" if target in codes
                                           else "The selected model does not support this language"))

    def translation_available(self):
        from wordcel.gui.resources import profile_translation_available
        return profile_translation_available(self.settings, self.active_profile)

    def set_mode(self, identity):
        index = self.source.findData(identity)
        if index < 0:
            index = next((i for i in range(self.source.count())
                          if profile_language(self.settings, self.source.itemData(i)) == identity), -1)
        if index < 0:
            from wordcel.language.support import profile_languages as supported_languages
            if identity in supported_languages(getattr(self, "_imported_languages", ()), profile_languages(self.settings)):
                from wordcel.config.profiles import create_profile
                identity = create_profile(self.settings, identity)
                self.update_languages()
                index = self.source.findData(identity)
        if index >= 0:
            self.source.setCurrentIndex(index)

    def cycle_profile(self, offset):
        count = self.source.count()
        if count:
            self.source.setCurrentIndex((self.source.currentIndex() + offset) % count)
            self.profile_activated.emit(self.source.currentText())

    def _update_target_visibility(self):
        self.foreign.setVisible(True)
        self.target_label.setVisible(True)

    def _mode_changed(self):
        mode = self.active_profile
        if not mode:
            return
        if self.settings.value("profile", "") != mode or self.sender() is self.source:
            self.update_translation_languages(self.settings.value(f"profiles/{mode}/target", default_partner(self.preferred_foreign)))
            self.settings.setValue("profile", mode)
        self._update_target_visibility()
        if self.foreign.currentData() == self.preferred_foreign:
            with QSignalBlocker(self.foreign):
                self.foreign.setCurrentIndex(self.foreign.findData(default_partner(self.preferred_foreign)))
        self.settings.setValue(f"profiles/{self.active_profile}/target", self.foreign.currentData())
        self.browser.selection_lookup = self.settings.value(f"profiles/{self.active_profile}/selection_lookup", False, bool)
        self._invalidate()
        if self.audio:
            self.audio.cancel()
        self.mode_changed.emit(self.preferred_foreign)
        self.reload_appearance()
        if self.lookup_shortcuts.restored:
            try:
                self.restore_shortcut()
            except (ValueError, OSError, RuntimeError) as error:
                self.show_message(str(error))
        if self._setup is not None:
            self._setup.update_active_label()
        self.scan_settings_changed.emit()
        self._edited()

    def _invalidate(self):
        self._auto_translation_pending = None
        self._automatic_translation = False
        self.automatic_output.set_busy(False)
        self.automatic_output.hide()
        self.translation_debounce.stop()
        self.revision += 1
        self._pending_context = None
        self.stream_timer.stop()
        self._translation_chunk = None
        if self._partial_translation:
            self._partial_translation = False
            self._result = self._translation_previous
            if self._result is not None:
                self._render()
            else:
                self._clear_browser()
                self._render_identity = None
                self._document_revision = None
        self._pending_revision = None
        self.busy_delay.stop()
        self._remember_request = False
        self.debounce.stop()
        self.worker.cancel()
        if self.translation_worker is not None:
            self.translation_worker.cancel()
        if self.audio:
            self.audio.cancel()
        self._set_translation_busy(False)

    def _show_busy(self):
        if self._pending_revision == self.revision:
            self.translate.setIcon(action_icon("close", config.color_foreground))
            self.translate.setToolTip("Cancel translation" if self._translation_busy else "Cancel lookup")
            self.translate.setAccessibleName(self.translate.toolTip())
            if self._translation_busy and self._translation_model_state:
                self.translate.setToolTip(self.translate.toolTip() + "\n" + self._translation_model_state)
            self.translate.setEnabled(True)

    def _clear_actions(self):
        self.update_anki()
        self.audio_button.setEnabled(False)
        for _, _, audio in self._headword_rows.values():
            audio.setEnabled(False)
        self.sentence_audio_button.setEnabled(False)
        self._clear_context()

    def _clear_browser(self):
        self._action_heading = None
        self._headword_blocks = []
        self.browser.clear()

    def _translate_clicked(self):
        if self._translation_busy or self._pending_revision is not None and not self.busy_delay.isActive():
            self._invalidate()
            self._restore_actions()
        elif self._translation_view:
            self._submit_translation_source()
        else:
            self.submit(translate=True, context=bool(self._context))

    def _show_translation(self, text, source, target):
        self.lookup_history.timer.stop()
        if self._translation_view and self._translation_content.translation:
            self.translation_panel.stale_output = self._translation_content.translation
        if not self._translation_view:
            self.translation_panel.stale_output = ""
            self._translation_return = {}
            for name in (
                "_result", "_result_context", "_result_screenshot", "_result_input",
                "_result_profile", "_result_target", "_expanded", "_details_expanded",
                "_collapsed", "_kanji_details", "_kanji_origin"):
                if hasattr(self, name):
                    value = getattr(self, name)
                    self._translation_return[name] = value.copy() if isinstance(value, set) else value
        self._translation_view = True
        self._translation_text = text
        self._translation_content = SearchResult(text, source, target)
        self.fit_timer.stop()
        self._set_kanji_visible(False)
        self.content_stack.setCurrentWidget(self.translation_panel)
        self.back.setEnabled(True)
        self._update_trail()
        self._place_actions()
        self._render_translation()

    def _render_translation(self):
        result = self._translation_content
        self.translation_panel.set_content(result.text, result.translation,
                                             "Automatic" if result.source == "auto" else language_name(result.source),
                                             language_name(result.target), result.message)

    def _leave_translation(self):
        if not self._translation_view:
            return
        self.translation_panel.close_language_picker()
        self.translation_debounce.stop()
        self.translation_panel.stale_output = ""
        self._translation_view = False
        self._partial_translation = False
        for name, value in (self._translation_return or {}).items():
            setattr(self, name, value)
        self._translation_return = None
        self.content_stack.setCurrentWidget(self.lookup_splitter)
        self._render_kanji_panel()
        self.back.setEnabled(bool(self._history) or self._kanji_view)
        self._update_trail()
        self._place_actions()

    def _translation_language_menu(self, role):
        current = getattr(self._translation_content, role)
        other = self._translation_content.target if role == "source" else self._translation_content.source
        languages = {"auto": "Automatic"} if role == "source" else {}
        for index in range(self.foreign.count()):
            code = self.foreign.itemData(index)
            if self.foreign.model().item(index).isEnabled() and code != other:
                languages[code] = language_name(code)
        self.translation_panel.show_language_picker(role, languages, current)

    def _set_translation_language(self, role, code):
        if not self._translation_view or role not in ("source", "target"):
            return
        self.settings.setValue(f"profiles/{self.active_profile}/translation_{role}", code)
        direction = list(self._translation_direction)
        direction[0 if role == "source" else 1] = code
        self._translation_direction = tuple(direction)
        self._translation_content = replace(self._translation_content, **{role: code})
        self._render_translation()
        if self.translation_panel.source.toPlainText().strip():
            self._submit_translation_source()

    def open_translation(self):
        if isinstance(QApplication.focusWidget(), QKeySequenceEdit):
            return
        if self.isVisible() and self._translation_view:
            self.translation_panel.source.setFocus()
            return
        text = (self._context or (self._result.text if self._result else "")) if self.isVisible() else ""
        if self.isVisible():
            self._invalidate()
            if self._peek:
                self.pin.setChecked(True)
        else:
            self.open_search()
        prefix = f"profiles/{self.active_profile}/translation_"
        source = self.settings.value(prefix + "source", "auto")
        target = self.settings.value(prefix + "target", "auto")
        if text and self._result is not None:
            source = self._result.source
            if target == source:
                target = "auto"
        self._translation_direction = (source, target)
        display_target = target if target != "auto" else (
            self.preferred_foreign if source == self.foreign.currentData() else self.foreign.currentData())
        self._show_translation(text, source, display_target)
        self._source_overlay = False
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        from wordcel.utils.window_focus import focus_pinned_popup
        focus_pinned_popup(self, self.translation_panel.source)
        if text.strip():
            self.translation_debounce.start()

    def _translation_source_edited(self, text):
        if not self._translation_view:
            return
        self.translation_panel.stale_output = self._translation_content.translation or self.translation_panel.stale_output
        if not text.strip():
            self.translation_panel.stale_output = ""
        self._translation_text = text
        self._translation_content = replace(self._translation_content, text=text, translation="", message="")
        self._invalidate()
        self._render_translation()
        self._place_actions()
        if text.strip() and not self.translation_panel.source.composing:
            self.translation_debounce.start()

    def _translation_composition_changed(self, composing):
        self.translation_debounce.stop()
        if not composing and self._translation_view:
            self.translation_debounce.start()

    def _submit_translation_source(self):
        self.translation_debounce.stop()
        if self._translation_view and not self.translation_panel.source.composing:
            self.submit(translate=True, translation_text=self.translation_panel.source.toPlainText())

    def _swap_translation_languages(self):
        if not self._translation_view:
            return
        content = self._translation_content
        if content.source == "auto":
            return
        prefix = f"profiles/{self.active_profile}/translation_"
        self.settings.setValue(prefix + "source", content.target)
        self.settings.setValue(prefix + "target", content.source)
        self._translation_direction = (content.target, content.source)
        text = content.translation or self.translation_panel.source.toPlainText()
        self._translation_content = replace(content, source=content.target, target=content.source)
        self._translation_source_edited(text)

    def _restore_actions(self):
        current = (self._result is not None and getattr(self, "_result_profile", None) == self.active_profile
                   and (self._peek or self._result_input == self.search.text().strip()))
        self._display_revision = self.revision if current else None
        self.audio_button.setEnabled(bool(current and self._result.entries))
        self.sentence_audio_button.setEnabled(bool(current and self._result.text))
        if current:
            self.set_context(getattr(self, "_result_context", ""))

    def _set_translation_busy(self, busy):
        self._translation_busy = busy
        self.translation_panel.set_busy(busy)
        self.automatic_output.set_busy(busy and self._automatic_translation)
        available = self.translation_available()
        self.translate.setEnabled(bool(busy or available and (self.search.text().strip() or self._context)))
        self.translate.setIcon(action_icon("translate", config.color_foreground))
        name = "Cancel translation" if busy else "Translate sentence" if self._peek and self._context else "Translate"
        model = self._result.translation_model if not busy and self._result is not None and self._display_revision == self.revision else ""
        self.translate.setToolTip(name + ("\n" + model if model else "") if busy or available
                                  else "The selected model does not support this language pair")
        self.translate.setAccessibleName(name)

    def _edited(self):
        self.lookup_history.reset()
        self._invalidate()
        self._leave_translation()
        self._display_revision = None
        self._clear_actions()
        text = self.search.text().strip()
        self.translate.setEnabled(bool(text) and self.translation_available())
        self.status.setText("Searching…" if text else "")
        self.status.hide()
        if text:
            self.debounce.start()
        else:
            self._result = None
            self._result_context = ""
            self._render_identity = None
            self._document_revision = None
            self._clear_browser()
            self._close_kanji()

    def _lookup_input_position(self, position):
        from wordcel.language.profiles import get_profile
        raw = self.search.text()
        start = len(raw.encode("utf-16-le")[:position * 2].decode("utf-16-le"))
        profile = get_profile(self._result.source if self._result else self.preferred_foreign)
        for left, right in profile.word_spans(raw):
            if left <= start < right:
                end = len(raw) if profile.word_mode == "unspaced" else right
                self.submit(lookup_span=(left, end))
                return

    def submit(self, translate=None, *, context=False, remember=False, selection=False, translation_text=None,
               lookup_span=None, saved_encounter=None, auto_translate=True, automatic=False):
        if not translate:
            self._leave_translation()
        input_text = self.search.text().strip()
        selected = self.search.selectedText().strip() if selection else ""
        selected = selected if selected != input_text else ""
        eligible = (auto_translate and not translate and not context and not selected
                    and lookup_span is None and not saved_encounter and not self._peek)
        sentence = self._context if context else input_text if selected else None
        text = self._context if context else selected or input_text
        if translate and translation_text is not None:
            text = translation_text.strip()
            sentence = text
        if (self._selection_lookup and not translate and not selected and not context
                and lookup_span is None and not saved_encounter):
            from wordcel.language.profiles import get_profile
            profile = get_profile(self.preferred_foreign)
            spans = profile.word_spans(self.search.text())
            if profile.word_mode == "unspaced" and spans:
                lookup_span = (spans[0][0], len(self.search.text()))
        lookup_context = None
        if lookup_span is not None:
            start, end = lookup_span
            raw = self.search.text()
            text = raw[start:end].strip()
            sentence = input_text
            lookup_context = (raw, start, end)
        if selected:
            raw = self.search.text()
            # QLineEdit uses UTF-16 positions; analysis uses Python character offsets.
            before = raw.encode("utf-16-le")[:self.search.selectionStart() * 2].decode("utf-16-le")
            start = len(before) - (len(raw) - len(raw.lstrip()))
            selection_text = self.search.selectedText()
            start += len(selection_text) - len(selection_text.lstrip())
            lookup_context = (input_text, start, start + len(selected))
        self.debounce.stop()
        if not text:
            return
        exact_only = translate is None and not selected and lookup_span is None and is_sentence(text)
        if translate is None:
            translate = False
        self._invalidate()
        self._automatic_translation = automatic
        self._auto_translation_pending = (self.revision, input_text) if eligible else None
        if translate:
            self.lookup_history.timer.stop()
        self._encounter_restore = (self.revision, saved_encounter) if saved_encounter else None
        self._encounter_context = (self.revision, lookup_context) if lookup_context else None
        self._input_lookup = (self.revision, self.search.text(), lookup_span[0]) if lookup_span is not None else None
        self._last_request_translate = bool(translate)
        self._translation_model_state = ""
        self._translation_previous = self._result
        self._translation_base = self._result if translate and self._result is not None and (
            self._result.text == text or context) else None
        self._remember_request = remember or context or bool(selected)
        self._restore_actions()
        self._pending_revision = self.revision
        self.busy_delay.start()
        self._pending_context = (self.revision, sentence) if sentence else None
        self._set_translation_busy(bool(translate))
        self.status.setText("Translating…" if translate else "Searching…")
        self.status.hide()
        worker = self.worker
        if translate:
            if self.translation_worker is None:
                # SQLite connections stay on each worker's own thread. A cold
                # model must not hold up ordinary dictionary lookup requests.
                self.translation_worker = LookupWorker(self.directory, self._engine_factory)
                self.translation_worker.completed.connect(self.deliver)
                self.translation_worker.failed.connect(self._failed)
                self.translation_worker.progress.connect(self._translation_progress)
                self.translation_worker.translation_state.connect(self._translation_state_changed)
                self.translation_worker.start()
            worker = self.translation_worker
        source = self._result.source if context and self._result else "auto"
        if saved_encounter:
            source = saved_encounter["language"]
            lookup_context = (saved_encounter["context"], saved_encounter["start"], saved_encounter["end"])
        target = None
        if translate:
            prefix = f"profiles/{self.active_profile}/translation_"
            selected_source = self.settings.value(prefix + "source", "auto")
            selected_target = self.settings.value(prefix + "target", "auto")
            if translation_text is not None and self._translation_view:
                selected_source, selected_target = self._translation_direction
            elif context:
                # A new captured sentence owns its source language, regardless of
                # the direction last used in the manual translation editor.
                selected_source = "auto"
            if selected_source != "auto":
                source = selected_source
            if selected_target != "auto":
                target = selected_target
            if selected_source == "auto" and source != "auto" and target == source:
                target = None
            display_source = (source if source != "auto" else self._result.source
                              if self._result and (context or self._result.text == text) else "auto")
            display_target = target or (self.preferred_foreign if display_source == self.foreign.currentData()
                                        else self.foreign.currentData())
            if selected_source == "auto" and display_target == display_source:
                display_target = (self.preferred_foreign if display_source == self.foreign.currentData()
                                  else self.foreign.currentData())
            self._translation_direction = ((source, target or "auto") if context else
                                           (selected_source, selected_target))
            if automatic:
                self.automatic_output.set_content("")
                self.automatic_output.show()
            else:
                self._show_translation(text, display_source, display_target)
        from wordcel.dictionary.translation import load_profile_settings
        try:
            translation_settings = load_profile_settings(self.settings, self.active_profile) if translate else None
        except (ValueError, TypeError) as error:
            self._failed(self.revision, str(error))
            return
        from wordcel.language.morphology import model_available
        worker.request(self.revision, text, source,
                       self.preferred_foreign, translate=bool(translate),
                       target=target,
                       pair=None if saved_encounter else (self.preferred_foreign, self.foreign.currentData()),
                       translation_settings=translation_settings,
                       context=lookup_context if not translate else None,
                       morphology=not translate and not exact_only and model_available(source if saved_encounter else self.preferred_foreign),
                       dictionary_options=dictionary_preferences(self.settings, self.active_profile),
                       exact_only=exact_only)

    def deliver(self, revision, result):
        if (revision != self.revision or self._shutting_down
                or self._automatic_translation and result.text != self._context
                or self._last_request_translate and self._translation_view and result.text != self._translation_text):
            mark("discard", revision, reason="obsolete_lookup")
            return
        mark("accepted", revision)
        self._pending_revision = None
        self.stream_timer.stop()
        self._translation_chunk = None
        if self._partial_translation:
            self._result = self._translation_previous
        self._partial_translation = False
        self.busy_delay.stop()
        self._set_translation_busy(False)
        if self._automatic_translation:
            self.automatic_output.set_content(result.translation, result.message)
            self._result = replace(self._translation_base, translation=result.translation,
                                   translation_model=result.translation_model)
            self._display_revision = revision
            return
        if self._last_request_translate and self._translation_view:
            self._translation_content = result
        if self._last_request_translate and self._translation_base is not None:
            base = self._translation_base
            screenshot = self._result_screenshot
            if result.translation:
                result = replace(result, entries=base.entries, suggestions=base.suggestions,
                                 kanji=base.kanji, matched_length=base.matched_length)
            else:
                result = replace(base, message=result.message)
        self._display(result, remember=self._remember_request)
        input_lookup = getattr(self, "_input_lookup", None)
        if not self._peek and input_lookup and input_lookup[:2] == (revision, self.search.text()):
            raw, start = input_lookup[1:]
            offset = len(raw[:start].encode("utf-16-le")) // 2
            length = len(raw[start:start + result.matched_length].encode("utf-16-le")) // 2
            if self._selection_lookup:
                # Keep the beginning of a long match visible in the input.
                self.search.setSelection(offset + length, -length)
            elif length:
                self.search.setSelection(offset, length)
        restored = self._encounter_restore and self._encounter_restore[0] == revision
        if not self._last_request_translate and not restored:
            self._autoplay_lookup()
        if self._last_request_translate and self._translation_base is not None:
            self._result_screenshot = screenshot
        if self._pending_context and self._pending_context[0] == revision:
            self.set_context(self._pending_context[1])
            self._pending_context = None
        elif not self._peek:
            self.set_context(result.text)
        if not self._last_request_translate:
            if restored:
                row = self._encounter_restore[1]
                self.set_context(row["context"], row["start"], row["end"])
            elif self._encounter_context and self._encounter_context[0] == revision:
                sentence, start, end = self._encounter_context[1]
                if result.matched_length:
                    end = min(end, start + result.matched_length)
                self.set_context(sentence, start, end)
            self.record_encounter(restored=bool(restored))
        if getattr(self, "_history_anki_revision", None) == revision:
            self._history_anki_revision = None
            if not result.entries:
                self.show_message("No dictionary entry found")
            elif not self.settings.value(f"profiles/{self.active_profile}/anki/enabled", False, bool):
                self.show_message("Enable Anki in Settings")
            else:
                self.add_to_anki()
        self.status.setText(f"{language_name(result.source)} → {language_name(result.target)}")
        self.status.hide()

        pending, self._auto_translation_pending = self._auto_translation_pending, None
        if pending and pending[0] == revision and not self._last_request_translate and self.translation_available():
            text = pending[1]
            prefix = f"profiles/{self.active_profile}/auto_translate_"
            missing = not any(entry.definitions for entry in result.entries)
            if (missing and self.settings.value(prefix + "miss", False, bool)
                    or is_sentence(text) and self.settings.value(prefix + "sentences", False, bool)):
                self.submit(translate=True, context=True, automatic=True)

    def _translation_state_changed(self, revision, state):
        if revision == self.revision and self._translation_busy:
            self._translation_model_state = state
            output = self.automatic_output if self._automatic_translation else self.translation_browser
            output.set_loading_state(state)
            self.translate.setToolTip("Cancel translation\n" + state)

    def _translation_progress(self, revision, result):
        if (revision != self.revision or self._shutting_down or not self._translation_busy
                or self._automatic_translation and result.text != self._context
                or self._translation_view and result.text != self._translation_text):
            mark("discard", revision, reason="obsolete_chunk")
            return
        self._translation_chunk = result
        if not self.stream_timer.isActive():
            self.stream_timer.start()

    def _flush_translation(self):
        result, self._translation_chunk = self._translation_chunk, None
        if result is None or not self._translation_busy:
            return
        if self._automatic_translation:
            if self.automatic_output.selecting:
                self._translation_chunk = result
                self.stream_timer.start()
            else:
                self.automatic_output.set_content(result.translation, result.message)
            return
        if self._translation_view:
            self._translation_content = result
        browser = self.translation_browser if self._translation_view else self.browser
        if browser.selecting:
            self._translation_chunk = result
            self.stream_timer.start()
            return
        bar = browser.verticalScrollBar()
        at_end = (bar.maximum() > 0 and bar.value() >= bar.maximum() - 2
                  and not browser.textCursor().hasSelection())
        base = self._translation_base
        if base is not None:
            result = replace(result, entries=base.entries, suggestions=base.suggestions, kanji=base.kanji)
        self._result = result
        self._partial_translation = True
        self._render(static=True)
        if at_end:
            bar.setValue(bar.maximum())

    def dictionary_display_titles(self, mode):
        selected = set(self.settings.value(f"profiles/{self.active_profile}/{mode}_dictionaries", [], type=list))
        mapping = getattr(self, "_dictionary_titles", {})
        return {mapping.get(identity, identity) for identity in selected}

    def collapsed_dictionaries(self):
        return self.dictionary_display_titles("collapsed")

    def set_dictionary_display(self, source, mode):
        if self._result is not None:
            sources = list(dict.fromkeys(entry.source for entry in self._result.entries))
            if source in sources:
                keys = self._section_keys(sources.index(source))
                self._collapsed.difference_update(keys)
                self._expanded.difference_update(keys)
        self._collapsed.discard(source)
        self._expanded.discard(source)
        if mode == "collapsed":
            self._collapsed.add(source)
        elif mode == "expanded":
            self._expanded.add(source)
        self._render()

    def _section_keys(self, source_index):
        sources = list(dict.fromkeys(entry.source for entry in self._result.entries))
        source = sources[source_index]
        return {_dictionary_section_key(*min(variants), source)
                for variants in self._presentation_groups().values()
                if any(entry.source == source for entry in next(iter(variants.values())))}

    def _display(self, result, remember=True, expanded=None, details_expanded=None, collapsed=None,
                 kanji_details=None, kanji_origin=None):
        remember = remember and not self._translation_view
        same = self._result is not None and getattr(self, "_result_profile", None) == self.active_profile and (self._result.text, self._result.source, self._result.target) == (
            result.text, result.source, result.target)
        previous_context = getattr(self, "_result_context", "")
        if remember and not self._new_chain and self._result is not None and not same:
            self._history.append((self._result, getattr(self, "_result_context", ""),
                                  self._result_profile, self._result_target, tuple(self._expanded),
                                  self.browser.verticalScrollBar().value(), tuple(self._details_expanded),
                                  self._result_input, self._result_screenshot, tuple(self._collapsed),
                                  tuple(self._kanji_details), self._kanji_origin))
            self._history = self._history[-30:]
        if details_expanded is not None:
            self._details_expanded = set(details_expanded)
        elif self._new_chain or self._result is None or result.entries != self._result.entries:
            self._details_expanded.clear()
        if collapsed is not None:
            self._collapsed = set(collapsed)
        elif self._new_chain or not same:
            self._collapsed = self.collapsed_dictionaries()
        if kanji_details is not None:
            self._kanji_details = set(tuple(kanji_details)[:1])
            self._kanji_origin = kanji_origin or ""
        elif self._new_chain or not same:
            self._kanji_details.clear()
            self._kanji_origin = ""
        if self._new_chain or not same:
            self._kanji_heading = None
            self._kanji_heading_anchor = None
        if expanded is not None:
            self._expanded = set(expanded)
        elif self._new_chain or not same:
            self._expanded = self.dictionary_display_titles("expanded")
        self._new_chain = False
        self._result = result
        self._display_revision = self.revision
        self._result_profile = self.active_profile
        self._result_target = self.foreign.currentData()
        self._result_context = previous_context if same else ""
        if not same:
            self._result_screenshot = None
        self._result_input = self.search.text().strip()
        self._render(static=same)
        self.back.setEnabled(bool(self._history) or self._translation_view or self._kanji_view)
        self._update_trail()
        self.audio_button.setEnabled(bool(result.entries))
        self.update_anki()
        self._place_actions()
        self.sentence_audio_button.setEnabled(bool(result.text))

    def _render(self, static=False, *, preserve_scroll=False, position=None):
        self._sync_headword_actions()
        self._render_kanji_panel()
        if self._translation_view:
            self._render_translation()
            return
        if self._result is not None:
            self._static_disclosure = self._static_disclosure or static
            self._preserve_scroll = self._preserve_scroll or preserve_scroll
            if self.browser.selecting:
                self.render_timer.start(50)
                return
            static, self._static_disclosure = self._static_disclosure, False
            preserve_scroll, self._preserve_scroll = self._preserve_scroll, False
            compact = self.compact_preview()
            prefix = f"profiles/{self.active_profile}/"
            from wordcel.dictionary.wiktionary_sections import SECTIONS
            hidden_sections = {}
            for kind in SECTIONS:
                for source in self.dictionary_display_titles("hidden_" + kind):
                    hidden_sections.setdefault(source, set()).add(kind)
            preview_options = dict(
                hidden_sections=hidden_sections,
                preview_frequency=self.settings.value(prefix + "preview_frequency", True, bool),
                preview_pitch=self.settings.value(prefix + "preview_pitch", True, bool),
                preview_definitions=self.settings.value(prefix + "preview_definitions", 1, int),
                pinned_frequency=self.settings.value(prefix + "pinned_frequency", True, bool),
                pinned_pitch=self.settings.value(prefix + "pinned_pitch", True, bool),
                dictionary_labels=self.settings.value(prefix + "dictionary_labels", True, bool),
                grammar=self.settings.value(prefix + "preview_grammar", False, bool)
                if self._peek and not self.is_pinned else self.settings.value(prefix + "pinned_grammar", True, bool))
            separate_headwords = (not self.browser.section_scroll.enabled and
                                  len(self._presentation_groups()) > 1)
            self.browser.section_scroll.set_preview(self._peek and not self.is_pinned)
            expanded = self._expanded
            if self._peek and not self.is_pinned and not compact:
                expanded = {entry.source for entry in self._result.entries}
            self._place_actions()
            show_source, source_text = self._peek, None
            source_identity = None
            if self._peek and self.is_pinned:
                show_source = self.settings.value(f"profiles/{self.active_profile}/pinned_sentence", False, bool)
                source_text = self._result_context or (self._result.text if self._result.translation else "")
                source_identity = source_text
                if show_source and source_text:
                    width = (self.browser.viewport().width() - 2 * self.browser.document().documentMargin()
                             - self._action_clearance())
                    from wordcel.gui.typography import document_font
                    sentence_font = document_font(config.font_family, config.font_size_sentence, self.preferred_foreign)
                    source_text = _compact_context(source_text, sentence_font, width)
            from wordcel.gui.profile_appearance import DEFAULTS
            identity = (repr(self._result), self.preferred_foreign, tuple(sorted(expanded)),
                        tuple(sorted(self._details_expanded)),
                        self._peek, self.is_pinned, compact, tuple(preview_options.values()),
                        tuple(getattr(config, key) for key in DEFAULTS), self.devicePixelRatioF(),
                        self.audio_actions.sizeHint().width(), show_source, source_identity if show_source else None,
                        self.settings.value(f"profiles/{self.active_profile}/headword_furigana", False, bool),
                        self.settings.value(f"profiles/{self.active_profile}/definition_furigana", True, bool),
                        self.settings.value(f"profiles/{self.active_profile}/combine_frequencies", True, bool),
                        tuple(sorted(self._collapsed)), separate_headwords, self._headword_clearance())
            if identity == self._render_identity:
                if show_source and source_text:
                    self._resize_source(source_text)
                mark("render_reused", self.revision)
                return
            from wordcel.gui.section_scroll import ReadingPosition
            result_key = (self._result.text, self._result.source, self._result.target)
            if position is None and getattr(self, "_rendered_result_key", None) == result_key:
                position = ReadingPosition(self.browser)
            mark("html_begin", self.revision)
            dictionary_result = (replace(self._result, translation="")
                                 if self._result.entries or self._automatic_translation else self._result)
            self._action_heading = None
            self._headword_blocks = []
            self.browser.setHtml(render_result(dictionary_result, expanded, **preview_options,
                                               overlay_actions=self._action_clearance(),
                                               headword_actions=self._headword_clearance(),
                                               preview=self._peek and not self.is_pinned, compact=compact,
                                               show_source=show_source, source_text=source_text,
                                               details_expanded=self._details_expanded,
                                               headword_furigana=self.settings.value(f"profiles/{self.active_profile}/headword_furigana", False, bool),
                                               definition_furigana=self.settings.value(f"profiles/{self.active_profile}/definition_furigana", True, bool),
                                               collapsed=self._collapsed,
                                               groups=self._presentation_groups(),
                                               separate_headwords=separate_headwords,
                                               combine_frequencies=self.settings.value(f"profiles/{self.active_profile}/combine_frequencies", True, bool)))
            action_heading = None
            headword_blocks = []
            reservations = {}
            block = self.browser.document().begin()
            while block.isValid():
                if block.blockFormat().headingLevel() == 2:
                    headword_blocks.append(block)
                    if self._headword_rows:
                        reservations[block.position()] = (block, max(
                            row.sizeHint().height() for row, _, _ in self._headword_rows.values()))
                if action_heading is None and (show_source and source_text or block.blockFormat().headingLevel() == 2):
                    action_heading = block
                    if self._action_clearance():
                        reservations[block.position()] = (block, self.audio_actions.sizeHint().height())
                block = block.next()
            if action_heading is None and self._action_clearance():
                block = self.browser.document().begin()
                while block.isValid() and not block.text().strip():
                    block = block.next()
                if block.isValid():
                    action_heading = block
                    reservations[block.position()] = (block, self.audio_actions.sizeHint().height())
            document = self.browser.document()
            formats = []
            for block, height in reservations.values():
                document.documentLayout().blockBoundingRect(block)
                line = block.layout().lineAt(0) if block.layout().lineCount() else None
                fmt = block.blockFormat()
                if block == action_heading:
                    fmt.setRightMargin(max(fmt.rightMargin(), self._action_clearance()))
                if line is not None:
                    # Taller actions need room below the text, not extra leading
                    # that changes the heading baseline when pinning.
                    fmt.setBottomMargin(max(fmt.bottomMargin(), math.ceil(height - line.height())))
                formats.append((block, fmt))
            if formats:
                document.setLayoutEnabled(False)
                try:
                    for block, fmt in formats:
                        QTextCursor(block).setBlockFormat(fmt)
                finally:
                    document.setLayoutEnabled(True)
            self._action_heading = action_heading
            self._headword_blocks = headword_blocks
            self._render_identity = identity
            self._rendered_source_text = source_text
            self._rendered_result_key = result_key
            self._document_revision = self.revision
            mark("document_ready", self.revision)
            # Restore snap-page padding before restoring a position near the end.
            self.browser.section_scroll._refresh_header()
            if position is not None:
                position.restore(self.browser, preserve_scroll=preserve_scroll)
            self._position_actions()
            self.browser.setToolTip("")
            if static:
                self.fit_timer.stop()
                self._fit_identity = (self._render_identity, self.browser.viewport().width())
            else:
                self.fit_timer.start(0)

    def _resize_source(self, text):
        if text == self._rendered_source_text:
            return
        browser = self.browser
        document = browser.document()
        cursor = QTextCursor(document.begin())
        cursor.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor)
        fmt = cursor.charFormat()
        cursor.setPosition(0)
        cursor.setPosition(document.begin().length() - 1, QTextCursor.MoveMode.KeepAnchor)
        with browser.preserve_reading_position():
            with QSignalBlocker(document), QSignalBlocker(browser.verticalScrollBar()):
                document.setLayoutEnabled(False)
                try:
                    # A line separator keeps both source lines in their existing block.
                    cursor.insertText(text.replace("\n", "\u2028"), fmt)
                finally:
                    document.setLayoutEnabled(True)
            self._rendered_source_text = text
            browser.section_scroll._document_changed()
        self._position_actions()

    def _fit_preview(self):
        if not self._peek and not self._manual_at_cursor:
            return
        if self._translation_view or self._kanji_view:
            return
        preview = self._peek and not self.is_pinned and self.compact_preview()
        reading = (not self._peek or self.is_pinned) and not self._reading_size_custom and self._normal_size == QSize(480, 340)
        if self._shutting_down or not (preview or reading):
            return
        identity = (self._render_identity, self.browser.viewport().width())
        if identity == self._fit_identity and not self._needs_place:
            return
        self._fit_identity = identity
        mark("fit", self.revision)
        minimum_height = 72 if preview else 190
        if reading and self._inline_actions() and not self._result.entries:
            minimum_height = 0
        self.setMinimumHeight(minimum_height)
        self.layout().activate()
        document = self.browser.document()
        document.setTextWidth(self.browser.viewport().width())
        chrome = self.height() - self.browser.viewport().height()
        natural_height = (document.size().height() - document.rootFrame().frameFormat().bottomMargin()
                          + document.documentMargin())
        scroller = self.browser.section_scroll
        if reading and scroller.enabled and len(scroller.boundaries()) > 1:
            natural_height = min(natural_height, scroller.boundaries()[1][0])
        desired = math.ceil(natural_height) + chrome + 2
        maximum = max(190, self.settings.value("preview_max_height", 340, type=int)) if preview else self._normal_size.height()
        if reading and self._peek:
            maximum = max(maximum, self._preview_viewport_height + chrome + 2)
        if desired > maximum:
            limit = maximum - chrome - 2
            bottoms = []
            block = document.begin()
            while block.isValid():
                top = document.documentLayout().blockBoundingRect(block).top()
                text_layout = block.layout()
                for index in range(text_layout.lineCount()):
                    line = text_layout.lineAt(index)
                    bottom = math.ceil(top + line.y() + line.height())
                    if bottom <= limit:
                        bottoms.append(bottom)
                block = block.next()
            if bottoms:
                desired = max(bottoms) + chrome
        minimum = self._preview_viewport_height + chrome if reading and self._peek else 0
        height = min(maximum, max(self.minimumSizeHint().height(), desired, minimum))
        if self.height() != height:
            mark("geometry", self.revision)
            if self.isVisible() and not self._needs_place:
                self._resize_expanded(QSize(self.width(), height))
            else:
                self.resize(self.width(), height)
        if self.isVisible() and self._needs_place:
            self._place()
            self._needs_place = False
        self._auto_fit_size = self.size()

    def set_compact_preview(self, enabled):
        self.settings.setValue(f"profiles/{self.active_profile}/compact_preview", bool(enabled))
        self._render()

    def _failed(self, revision, message):
        if revision in (-1, self.revision):
            if self._partial_translation:
                self._invalidate()
            self._pending_revision = None
            self.busy_delay.stop()
            self._set_translation_busy(False)
            self._restore_actions()
            if self._automatic_translation:
                self.automatic_output.set_content(self.automatic_output.toPlainText(), str(message))
            elif self._translation_view:
                self._translation_content = replace(self._translation_content, message=str(message))
                self._render_translation()
            else:
                self.show_message(message)

    def show_message(self, text):
        text = str(text)
        if "Allow Wordcel in System Settings" in text:
            feature = ("accessibility" if "Accessibility" in text else
                       "input_monitoring" if "Input Monitoring" in text else
                       "screen_recording" if "Screen Recording" in text else None)
            if feature:
                text += f' <a href="macos-permission:{feature}">Open Settings</a>'
        self.status.setText(text)
        self.status.setVisible(bool(text))

    def _open_permission_settings(self, link):
        prefix = "macos-permission:"
        if link.startswith(prefix):
            from wordcel.utils.macos import open_privacy_settings
            open_privacy_settings(link[len(prefix):])

    def _queue_link(self, url):
        if self._pin_anchor_click:
            self._pin_anchor_click = False
            return
        self._pending_link = (QUrl(url), self.revision, self._render_identity)
        # QTextBrowser must finish mouse release before its document is replaced.
        self.link_timer.start(0)

    def _activate_link(self):
        pending, self._pending_link = self._pending_link, None
        if pending is not None and not self._shutting_down:
            url, revision, identity = pending
            if revision == self.revision and identity == self._render_identity:
                self._link(url)

    def _close_kanji(self):
        self._kanji_details.clear()
        self._kanji_origin = ""
        self._render_kanji_panel()
        self._kanji_heading = None
        self._kanji_heading_anchor = None

    @property
    def _kanji_view(self):
        return self.content_stack.currentWidget() is self.kanji_panel

    def _set_kanji_visible(self, visible):
        if visible == self._kanji_view:
            return
        from wordcel.gui.section_scroll import ReadingPosition
        self.fit_timer.stop()
        focused = QApplication.focusWidget()
        return_focus = not visible and focused is not None and self.kanji_panel.isAncestorOf(focused)
        if visible:
            self._kanji_return_position = ReadingPosition(self.browser)
            self.render_timer.stop()
            self.content_stack.setCurrentWidget(self.kanji_panel)
        else:
            self.content_stack.setCurrentWidget(self.translation_panel if self._translation_view else self.lookup_splitter)
        self.back.setEnabled(bool(self._history) or self._translation_view or visible)
        self._update_trail()
        self._place_actions()
        self.layout().activate()
        self.frame.layout().activate()
        if visible:
            self._align_kanji_heading()
        if not visible:
            if self._kanji_return_position is not None:
                self._kanji_return_position.restore(self.browser, preserve_scroll=True)
                self._kanji_return_position = None
            if return_focus and not self._translation_view:
                self.browser.setFocus(Qt.FocusReason.OtherFocusReason)

    def _kanji_word(self, character):
        return next((entry.term for entry in self._result.entries if character in entry.term),
                    self._result.text or character)

    def _capture_kanji_heading(self):
        if self._result is None or getattr(self, "_rendered_result_key", None) != (
                self._result.text, self._result.source, self._result.target):
            return
        groups = list(self._presentation_groups())
        index = next((index for index, (term, _) in enumerate(groups) if term == self._kanji_origin), None)
        if index is None or index >= len(self._headword_blocks):
            return
        block = self._headword_blocks[index]
        source = self.browser
        sticky = source.section_scroll.header
        if not sticky.isHidden() and source.section_scroll._heading == block.position():
            source = sticky
            block = source.document().begin()
        cursor = QTextCursor(block)
        self._kanji_heading_anchor = self._headword_anchor(source, block)
        from wordcel.gui.ruby import RUBY
        fragment = block.begin().fragment()
        length = 1 if fragment.charFormat().objectType() == RUBY else len(self._kanji_origin.encode("utf-16-le")) // 2
        cursor.setPosition(block.position() + length, QTextCursor.MoveMode.KeepAnchor)
        self._kanji_heading = cursor.selection()

    def _headword_anchor(self, browser, block):
        rect = browser.document().documentLayout().blockBoundingRect(block)
        caret = browser.cursorRect(QTextCursor(block))
        if not block.layout().lineCount():
            return browser.viewport().mapTo(self, caret.topLeft())
        line = block.layout().lineAt(0)
        x = caret.x()
        y = rect.top() + line.y() + line.ascent() - browser.verticalScrollBar().value()
        return browser.viewport().mapTo(self, QPoint(x, round(y)))

    def _align_kanji_heading(self):
        if not self._kanji_view or self._kanji_heading_anchor is None:
            return
        current = self._headword_anchor(self.kanji_browser, self.kanji_browser.document().begin())
        margins = self.kanji_panel.layout().contentsMargins()
        left = max(0, margins.left() + self._kanji_heading_anchor.x() - current.x())
        top = max(0, margins.top() + self._kanji_heading_anchor.y() - current.y())
        self.kanji_panel.layout().setContentsMargins(left, top, 0, 0)
        self.kanji_panel.layout().activate()
        self.kanji_browser.fit_glyphs()

    def _select_kanji(self, character, *, origin=None, toggle=True):
        previous_origin = self._kanji_origin
        self._kanji_origin = origin or (self._kanji_origin if self._kanji_details else self._kanji_word(character))
        if not self._kanji_view or self._kanji_origin != previous_origin:
            self._capture_kanji_heading()
        self._kanji_details = set() if toggle and character in self._kanji_details else {character}
        self.fit_timer.stop()
        self._render_kanji_panel()

    def _render_kanji_panel(self):
        from wordcel.gui.kanji_panel import render_kanji_details
        entries = tuple(entry for entry in self._result.kanji if entry.character in self._kanji_details) if self._result else ()
        visible = bool(entries) and not self._translation_view and not (self._peek and not self.is_pinned)
        if visible and not self._kanji_origin:
            self._kanji_origin = self._kanji_word(entries[0].character)
        if visible and self._kanji_heading is None:
            self._capture_kanji_heading()
        html = render_kanji_details(entries, origin="" if self._kanji_heading is not None else self._kanji_origin,
                                   available_characters={entry.character for entry in self._result.kanji}) if visible else ""
        heading_identity = id(self._kanji_heading) if visible else None
        if html != self._kanji_html or heading_identity != self._kanji_heading_identity:
            self.kanji_browser.setHtml(html, heading=self._kanji_heading if visible else None,
                                       selected=entries[0].character if visible else "")
            self._kanji_html = html
            self._kanji_heading_identity = heading_identity
        self._set_kanji_visible(visible)
        self._align_kanji_heading()
        self._update_trail()

    def _link(self, url):
        if self._result is None:
            return
        if self._pin_anchor_click:
            self._pin_anchor_click = False
            return  # The first click already expanded the complete peek.
        if url.scheme() == "sentence" and url.path() == "translate":
            if not self._peek or self.is_pinned:
                self.submit(translate=True, context=bool(self._context))
            return
        if url.scheme() == "headkanji":
            group, separator, character = url.path().partition(":")
            if not separator:
                group, character = "0", group
            groups = list(self._presentation_groups())
            if (not group.isdigit() or int(group) >= len(groups) or character not in groups[int(group)][0]
                    or character not in {entry.character for entry in self._result.kanji}):
                return
            self._select_kanji(character, origin=groups[int(group)][0], toggle=not self._kanji_view)
            return
        if url.scheme() == "kanjiselect":
            character = url.path()
            if (self._kanji_view and character in self._kanji_origin
                    and character in {entry.character for entry in self._result.kanji}):
                self._select_kanji(character, origin=self._kanji_origin, toggle=False)
            return
        if url.scheme() == "kanji" and url.path() in {entry.character for entry in self._result.kanji}:
            self._select_kanji(url.path())
            return
        if url.scheme() == "details" and re.fullmatch(r"\d+:\d+:\d+", url.path()):
            key = url.path()
            self._details_expanded.symmetric_difference_update((key,))
            self._render(static=True, preserve_scroll=True)
            return
        if url.scheme() == "inflections" and url.path().isdigit():
            groups = tuple(self._presentation_groups())
            if int(url.path()) < len(groups):
                self._details_expanded.symmetric_difference_update((f"inflections:{int(url.path())}",))
                self._render(static=True, preserve_scroll=True)
            return
        if url.scheme() in ("expand", "collapse") and re.fullmatch(r"\d+:\d+", url.path()):
            group_index, source_index = map(int, url.path().split(":"))
            sources = list(dict.fromkeys(entry.source for entry in self._result.entries))
            if not 0 <= source_index < len(sources):
                return
            groups = list(self._presentation_groups())
            if not 0 <= group_index < len(groups):
                return
            variants = self._presentation_groups()[groups[group_index]]
            key = _dictionary_section_key(*min(variants), sources[source_index])
            keys = self._section_keys(source_index)
            if key not in keys:
                return
            source = sources[source_index]
            for state in (self._expanded, self._collapsed):
                if source in state:
                    state.remove(source)
                    state.update(keys)
            if url.scheme() == "collapse":
                self._collapsed.symmetric_difference_update((key,))
            elif key in self._collapsed:
                self._collapsed.remove(key)
                self._expanded.add(key)
            elif key in self._expanded:
                self._expanded.remove(key)
                if source in self.collapsed_dictionaries():
                    self._collapsed.add(key)
            else:
                self._expanded.add(key)
            self._render(static=True, preserve_scroll=True)
            return
        try:
            index = int(url.path())
        except ValueError:
            return
        if url.scheme() in ("expand", "collapse"):
            sources = list(dict.fromkeys(entry.source for entry in self._result.entries))
            if not 0 <= index < len(sources):
                return
            source = sources[index]
            if url.scheme() == "collapse":
                self._collapsed.symmetric_difference_update((source,))
            elif source in self._collapsed:
                self._collapsed.remove(source)
                self._expanded.add(source)
            elif source in self._expanded:
                self._expanded.remove(source)
                if source in self.collapsed_dictionaries():
                    self._collapsed.add(source)
            else:
                self._expanded.add(source)
            self._render(static=True, preserve_scroll=True)
        elif url.scheme() == "suggest" and 0 <= index < len(self._result.suggestions):
            self.lookup_word(str(self._result.suggestions[index]))

    def lookup_word(self, text):
        self.lookup_history.reset()
        self._display_revision = None
        self._clear_actions()
        self._manual_at_cursor = self._manual_at_cursor or self._peek
        self._set_peek(False)
        with QSignalBlocker(self.search):
            self.search.setText(text)
        self.submit(remember=True)

    def _input_menu(self, point):
        menu = self.search.createStandardContextMenu()
        if self.search.hasSelectedText():
            menu.addSeparator()
            menu.addAction("Look up", lambda: self.submit(translate=False, selection=True))
        menu.exec(self.search.mapToGlobal(point))
        menu.deleteLater()

    def go_back(self):
        self.lookup_history.reset()
        if self._translation_view:
            self._invalidate()
            self._leave_translation()
            self.record_encounter(restored=True)
            self._restore_actions()
            self.update_anki()
            return
        if self._kanji_view:
            self._close_kanji()
            return
        if not self._history:
            return
        self._invalidate()
        previous = self._history.pop()
        result, context, profile, target, expanded, scroll = previous[:6]
        with QSignalBlocker(self.search), QSignalBlocker(self.source), QSignalBlocker(self.foreign):
            self.search.setText(previous[7] if len(previous) > 7 else result.text)
            if self.source.findData(profile) < 0:
                self.source.addItem(language_name(profile), profile)
            self.source.setCurrentIndex(self.source.findData(profile))
            self.foreign.setCurrentIndex(self.foreign.findData(target))
        self._update_target_visibility()
        self._invalidate()
        if self.audio:
            self.audio.cancel()
        self.mode_changed.emit(self.preferred_foreign)
        self.settings.setValue("profile", profile)
        self.settings.setValue("source", self.source.currentData())
        self.settings.setValue(f"profiles/{profile}/target", target)
        self.reload_appearance(render=False)
        if self._setup is not None:
            self._setup.update_active_label()
        self.scan_settings_changed.emit()
        self._display(result, remember=False, expanded=expanded,
                      details_expanded=previous[6] if len(previous) > 6 else (),
                      collapsed=previous[9] if len(previous) > 9 else None,
                      kanji_details=previous[10] if len(previous) > 10 else (),
                      kanji_origin=previous[11] if len(previous) > 11 else None)
        self.set_context(context)
        self.record_encounter(restored=True)
        self._result_screenshot = previous[8] if len(previous) > 8 else None
        self.browser.verticalScrollBar().setValue(scroll)
        if self._kanji_view:
            from wordcel.gui.section_scroll import ReadingPosition
            self._kanji_return_position = ReadingPosition(self.browser)
        self.translate.setEnabled(bool(result.text) and self.translation_available())
        self.status.setText(f"{language_name(result.source)} → {language_name(result.target)}")

    def _update_trail(self):
        if self._translation_view or not (self._history or self._kanji_view):
            self.title.clear()
            return
        labels = []
        start = max(0, len(self._history) - 2)
        if start:
            labels.append("…")
        for index in range(start, len(self._history)):
            text = self._history[index][0].text
            short = text[:12] + ("…" if len(text) > 12 else "")
            labels.append(f'<a href="{index}" style="color:{config.color_highlight_word}">{escape(short)}</a>')
        text = self._result.text or (self._result.entries[0].term if self._result.entries else "")
        word = escape(text[:12] + ("…" if len(text) > 12 else ""))
        if self._kanji_view:
            labels.append(f'<a href="word" style="color:{config.color_highlight_word}">{word}</a>')
            labels.append(escape(next(iter(self._kanji_details))))
        else:
            labels.append(word)
        self.title.setText(" › ".join(labels))

    def _history_jump(self, index):
        if index == "word":
            self._close_kanji()
            return
        index = int(index)
        if 0 <= index < len(self._history):
            if self._kanji_view:
                self._close_kanji()
            self._history = self._history[:index + 1]
            self.go_back()

    def _place(self):
        mark("place", self.revision)
        point = (self._lookup_anchor if self._peek and self._lookup_vertical and self._lookup_anchor is not None
                 else QCursor.pos())
        if self._peek:
            self._lookup_anchor = point
        self._lookup_entry_pending = self._peek and self._lookup_vertical
        tray = self.tray_geometry() if not self._peek and not self._manual_at_cursor and self.tray_geometry else None
        if tray and not tray.isNull():
            point = tray.center()
        screen = QApplication.screenAt(point) or QApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            self.resize(min(self.width(), area.width()), min(self.height(), area.height()))
            if not self._peek and not self._manual_at_cursor:
                x = tray.center().x() if tray and not tray.isNull() else area.right()
                y = area.bottom() + 1 - self.height()
                if sys.platform == "darwin":
                    y = area.top()
                    if tray and not tray.isNull():
                        y = max(y, tray.bottom() + 1)
                    y = min(y, area.bottom() + 1 - self.height())
                self.move(max(area.left(), min(x - self.width() // 2, area.right() + 1 - self.width())),
                          max(area.top(), min(y, area.bottom() + 1 - self.height())))
            else:
                self.move(*popup_position(point.x(), point.y(), self.size(), area, config.popup_position_mode,
                                          self._peek and self._lookup_vertical))

    def _set_peek(self, peek):
        from_corner = peek and not self._peek and not self._manual_at_cursor
        if peek:
            self._remember_corner_size()
        self._source_overlay = bool(peek) and sys.platform == "win32"
        if from_corner:
            self.resize(self._normal_size)
        elif peek and not self._peek and (self._reading_size_custom or self.size() != self._auto_fit_size):
            self._normal_size = self.size()
        elif not peek and self._peek and not self.is_pinned:
            self.setMinimumHeight(190)
            self._resize_expanded()
        self._peek = bool(peek)
        self.setSizeGripEnabled(self.is_pinned or not self._peek)
        for grip in self.findChildren(QWidget):
            if grip.inherits("QSizeGrip"):
                grip.installEventFilter(self)
        self._place_actions()
        self.search.setVisible(not self._peek)

    def _resize_expanded(self, requested=None):
        requested = requested or self._normal_size
        previous = self.geometry()
        screen = QApplication.screenAt(previous.center()) or QApplication.primaryScreen()
        if screen is None:
            self.resize(requested)
            return
        self.setGeometry(expanded_geometry(previous, requested, screen.availableGeometry(),
                                           self._lookup_anchor if self._peek else None,
                                           self._peek and self._lookup_vertical))
        if not self._peek and not self._manual_at_cursor:
            rect = self.geometry()
            if sys.platform == "darwin":
                rect.moveTop(previous.top())
            else:
                rect.moveBottom(previous.bottom())
            self.setGeometry(rect)

    def _place_actions(self):
        if self._shutting_down:
            return
        self.frame.layout().setContentsMargins(FRAME_PADDING, 0 if self._translation_view else PANE_PADDING,
                                              FRAME_PADDING, PANE_PADDING)
        kanji_view = self._kanji_view
        self._sync_headword_actions()
        self.mode_row.hide()
        for name, button in self._popup_actions.items():
            visible = self.settings.value(f"profiles/{self.active_profile}/buttons/{name}", name != "audio_sentence", bool)
            if self._peek and not self.is_pinned and name in ("back", "translate", "copy", "close"):
                visible = False
            if name == "anki":
                visible = visible and self.settings.value(f"profiles/{self.active_profile}/anki/enabled", False, bool)
            if name == "translate":
                visible = visible and self.translation_available()
            if name == "back":
                visible = visible and (bool(self._history) or self._translation_view or kanji_view)
            if kanji_view and name in ("translate", "copy", "anki", "audio", "audio_sentence"):
                visible = False
            if name in ("translate", "copy") and self._translation_view:
                visible = False
            if name in ("anki", "audio") and self._headword_rows:
                visible = False
            button.setVisible(visible)
        inline = self._inline_actions()
        container = self.browser.viewport() if inline else self.header
        if self.audio_actions.parentWidget() is not container:
            self.audio_actions.setParent(container)
            if not inline:
                self.header.layout().addWidget(self.audio_actions, 0, Qt.AlignmentFlag.AlignRight)
        self.search.setVisible(not self._peek and not self._translation_view)
        show_history = (not self._translation_view and self.lookup_history.value(
            "button_ocr" if self._peek else "button_manual", False))
        self.history_button.setVisible(show_history)
        self.title.setVisible(not self._peek or self.is_pinned)
        self.header.setVisible(not self._translation_view and not kanji_view and (not self._peek or self.is_pinned and not inline))
        self.audio_actions.setVisible(not self._translation_view and not kanji_view and (not self._peek or self.is_pinned) and
                                      any(not button.isHidden() for button in
                                          (self.anki_button, self.sentence_audio_button, self.audio_button)))
        self.actions_row.setVisible(show_history or ((not self._peek or self.is_pinned) and
                                    (bool(self.title.text()) or any(not button.isHidden() for button in
                                     (self.back, self.translate, self.copy_button, self.dismiss_button)))))
        self._position_actions()

    def _inline_actions(self):
        return bool(not self._translation_view and not self._kanji_view and self._peek and self.is_pinned and self._result
                    and (self._result.entries or not self._result.translation
                         and (self._result.analyses or self._result.suggestions)))

    def _action_clearance(self):
        if not self._inline_actions():
            return 0
        buttons = [button for button in (self.anki_button, self.sentence_audio_button, self.audio_button)
                   if not button.isHidden()]
        return sum(button.width() for button in buttons) + len(buttons) * self.audio_actions.layout().spacing()

    def _position_actions(self, *_):
        toolbar = self.actions_row.layout()
        margin = 0
        if self._inline_actions():
            viewport = self.browser.viewport()
            margin = (self.browser.width() - viewport.geometry().right() - 1
                      + round(self.browser.document().documentMargin()))
        if toolbar.contentsMargins().right() != margin:
            toolbar.setContentsMargins(0, 0, margin, 0)
        self._position_headword_actions()
        if not self._inline_actions() or self.audio_actions.parentWidget() is not self.browser.viewport():
            return
        block = self._action_heading
        if block is None or not block.isValid() or not self._action_clearance():
            self.audio_actions.hide()
            return
        viewport = self.browser.viewport()
        document = self.browser.document()
        offset = -self.browser.verticalScrollBar().value()
        sticky = self.browser.section_scroll.header
        if not sticky.isHidden():
            document = sticky.document()
            block = document.begin()
            offset = sticky.y()
        rect = document.documentLayout().blockBoundingRect(block)
        line = block.layout().lineAt(0) if block.layout().lineCount() else None
        height = line.height() if line is not None else rect.height()
        top = rect.top() + offset + (line.y() if line is not None else 0)
        size = self.audio_actions.sizeHint()
        margin = self.browser.document().documentMargin()
        self.audio_actions.setGeometry(round(viewport.width() - margin - size.width()),
                                       round(top + max(0, (height - size.height()) / 2)), size.width(), size.height())
        self.audio_actions.setVisible(top + height > 0 and top < viewport.height())
        self.audio_actions.raise_()

    def _headword_groups(self):
        groups = OrderedDict()
        for entry in self._result.entries if self._result else ():
            groups.setdefault((entry.term, entry.reading), []).append(entry)
        return groups

    def _presentation_groups(self):
        entries = self._result.entries if self._result else ()
        if getattr(self, "_grouped_entries", None) is not entries:
            self._grouped_headwords = group_headwords(entries)
            self._grouped_entries = entries
        return self._grouped_headwords

    def _sync_headword_actions(self):
        groups = self._presentation_groups()
        if self._translation_view or self._peek and not self.is_pinned:
            groups = {}
        for key in list(self._headword_rows):
            if key not in groups:
                row, _, _ = self._headword_rows.pop(key)
                row.hide()
                row.deleteLater()
        for key in groups:
            if key not in self._headword_rows:
                row = QWidget(self.browser.viewport())
                layout = QHBoxLayout(row)
                layout.setContentsMargins(0, 0, 0, 0)
                layout.setSpacing(self.audio_actions.layout().spacing())
                anki = self._action("anki", "Add to Anki")
                audio = self._action("audio", "Play pronunciation")
                anki.clicked.connect(lambda checked=False, key=key: self._headword_action("anki", key))
                audio.clicked.connect(lambda checked=False, key=key: self._headword_action("audio", key))
                audio.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                audio.customContextMenuRequested.connect(
                    lambda point, key=key, button=audio: self.audio_source_menu(point, headword=key, button=button))
                layout.addWidget(anki)
                layout.addWidget(audio)
                self._headword_rows[key] = row, anki, audio
            row, anki, audio = self._headword_rows[key]
            prefix = f"profiles/{self.active_profile}/"
            anki.setVisible(self.settings.value(prefix + "anki/enabled", False, bool)
                            and self.settings.value(prefix + "buttons/anki", True, bool))
            audio.setVisible(self.settings.value(prefix + "buttons/audio", True, bool))
            audio.setEnabled(self._display_revision == self.revision)
            audio.setIcon(action_icon("audio", config.color_foreground))
        self._headword_rows = {key: self._headword_rows[key] for key in groups}
        if self._headword_rows:
            self.anki_button.hide()
            self.audio_button.hide()

    def _headword_action(self, name, headword):
        variants = self._presentation_groups().get(headword, {})
        operation = self.add_to_anki if name == "anki" else self.play_audio
        if name == "audio" or len(variants) < 2:
            operation(headword=headword)
            return
        button = self._headword_rows[headword][1 if name == "anki" else 2]
        menu = QMenu(button)
        revision = self.revision
        entries = self._result.entries
        states = self.lookup_anki.refresh(variants)[1] if name == "anki" else {}
        for key in variants:
            def invoke(checked=False, key=key):
                if self.revision == revision and self._result is not None and self._result.entries is entries:
                    operation(headword=key)
            action = menu.addAction(key[1], invoke)
            if name == "anki":
                icon, description, ready = states[key]
                action.setIcon(action_icon(icon, config.color_foreground))
                action.setToolTip(description)
                action.setEnabled(ready)
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        menu.setToolTipsVisible(name == "anki")
        menu.popup(button.mapToGlobal(button.rect().bottomLeft()))
        return menu

    def _headword_clearance(self):
        width = max((row.sizeHint().width() for row, anki, audio in self._headword_rows.values()
                     if not anki.isHidden() or not audio.isHidden()), default=0)
        return width + self._action_clearance() if width else 0

    def _position_headword_actions(self):
        if not self._headword_rows:
            return
        document = self.browser.document()
        headings = self._headword_blocks
        viewport = self.browser.viewport()
        scroller = self.browser.section_scroll
        for index, (row, anki, audio) in enumerate(self._headword_rows.values()):
            if (index >= len(headings) or not headings[index].isValid()
                    or anki.isHidden() and audio.isHidden()):
                row.hide()
                continue
            block = headings[index]
            rect = document.documentLayout().blockBoundingRect(block)
            top = rect.top() - self.browser.verticalScrollBar().value()
            if not scroller.header.isHidden() and scroller._heading == block.position():
                top = scroller.header.y()
            size = row.sizeHint()
            shared_width = self._action_clearance() if block == self._action_heading else 0
            line = block.layout().lineAt(0) if block.layout().lineCount() else None
            top += line.y() if line else 0
            height = line.height() if line else rect.height()
            row.setGeometry(round(viewport.width() - document.documentMargin() - size.width() - shared_width),
                            round(top + max(0, (height - size.height()) / 2)), size.width(), size.height())
            row.setVisible(top + height > 0 and top < viewport.height() and not self._translation_view)
            row.raise_()

    def open_search(self, text="", *, at_cursor=False, passive=False, selection=False):
        self.lookup_history.reset()
        self._remember_corner_size()
        self._leave_translation()
        self.remember_foreground()
        self._history.clear()
        self._new_chain = True
        self.title.clear()
        self.back.hide()
        self._passive_text = passive
        self._selection_lookup = selection
        self._opening_search = True
        self._manual_at_cursor = at_cursor
        self.pin.setChecked(False)
        self._set_peek(False)
        if not at_cursor:
            self.resize(self._corner_size)
        self._clear_context()
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, self._passive_text)
        if not self.is_pinned or not self.isVisible():
            self._place()
        self.show()
        self.raise_()
        if not self._passive_text:
            self.activateWindow()
        with QSignalBlocker(self.search):
            self.search.setText(text)
        self._edited()
        self.search.setFocus()
        self.search.selectAll()
        def finish_opening():
            self._opening_search = False
        def focus():
            from wordcel.utils.window_focus import focus_pinned_popup, focus_search
            if self.isVisible() and not self._passive_text:
                if self._translation_view:
                    focus_pinned_popup(self, self.translation_panel.source)
                else:
                    focus_search(self)
            if (sys.platform == "darwin" and QApplication.platformName() != "offscreen"
                    and self.isVisible() and not self.isActiveWindow()):
                # AppKit activation is asynchronous; an earlier focus-loss
                # event must not dismiss Search before activation arrives.
                QTimer.singleShot(300, finish_opening)
            else:
                finish_opening()
        QTimer.singleShot(0, focus)
        if text:
            self.submit()

    def lookup_selected(self, text, *, passive=False):
        if text.strip():
            self.open_search(text.strip()[:2000], at_cursor=True, passive=passive, selection=True)

    def toggle_lookup(self):
        from PyQt6.QtWidgets import QKeySequenceEdit
        if isinstance(QApplication.focusWidget(), QKeySequenceEdit):
            return
        active = QApplication.activeWindow()
        if active is not None and active is not self:
            self.request_lookup()
            return
        if (self.isVisible() and self.search.hasFocus() and self.search.hasSelectedText()
                and self.search.selectedText().strip() != self.search.text().strip()):
            self.submit(translate=False, selection=True)
        elif self.isVisible() and self._selected_reading_browser() is not None:
            browser = self._selected_reading_browser()
            if browser is self.browser:
                browser.lookup_selection()
            else:
                self.lookup_word(browser.selected_text())
        elif self.isVisible():
            self.selection.cancel()
            self.hide()
        elif self.selection.pending:
            self.selection.cancel()
            self._selection_for_search = False
        else:
            self.request_lookup()

    def request_selection(self):
        self._selection_for_search = False
        self._selection_passive = False
        self.selection.start(wait_for_modifiers=True)

    def request_lookup(self):
        if QApplication.activeWindow() is not None:
            focused = QApplication.focusWidget()
            text = focused.selectedText() if isinstance(focused, (QLineEdit, QLabel)) else (
                self._selected_reading_browser().selected_text() if self._selected_reading_browser() else "")
            self.open_search(text)
            return
        if self.selection.pending:
            return
        self._selection_for_search = True
        self.selection.start(wait_for_modifiers=True)

    def _selected_text_ready(self, text):
        if self._selection_for_search:
            self._selection_for_search = False
            self.open_search(text, selection=True)
        else:
            self.lookup_selected(text, passive=self._selection_passive)

    def _selection_unavailable(self, same_application):
        requested, self._selection_for_search = self._selection_for_search, False
        if requested and same_application:
            self.open_search()

    def scan_hold_changed(self, active):
        self._scan_hold_active = active
        self._autoplayed = set() if active else None

    def _audio_key(self, headword=None):
        result = self._result
        if result.entries:
            entries = self._headword_groups().get(headword, ()) if headword is not None else result.entries
            if not entries:
                return None
            entry = entries[0]
            return entry.language, entry.term, entry.reading or ""
        return result.source, result.text, ""

    def _autoplay_lookup(self):
        if (self._result is not None and self._result.entries
                and (self._peek or self._selection_lookup)
                and audio_autoplay_mode(self.settings, self.active_profile) == "lookup"):
            self._autoplay()

    def _autoplay(self):
        if self._result is None:
            return
        key = self._audio_key()
        if self._autoplayed is not None:
            if key in self._autoplayed:
                return
            self._autoplayed.add(key)
        self.play_audio()

    def audio_source_menu(self, point, *, headword=None, button=None):
        if self._result is None or not self._result.entries:
            return
        from wordcel.audio.sources import database_path, is_local, source_label, source_order
        profile = self.preferred_foreign
        button = button or self.audio_button
        menu = QMenu(button)
        revision, entries = self.revision, self._result.entries
        def play(key, source=None):
            if self.revision == revision and self._result is not None and self._result.entries is entries:
                self.play_audio(headword=key, **({"source": source} if source else {}))
        variants = self._presentation_groups().get(headword, {headword: ()})
        for key in variants:
            target = menu.addMenu(key[1]) if len(variants) > 1 else menu
            target.addAction("Use source priority", lambda checked=False, key=key: play(key))
            target.addSeparator()
            for source in source_order(self.settings, profile):
                action = target.addAction(source_label(source), lambda checked=False, source=source, key=key:
                                          play(key, source))
                action.setEnabled(not is_local(source) or bool(database_path(self.settings, profile)))
        clip = getattr(self.audio, "current_clip", None)
        if clip and clip.page_url.startswith("https://commons.wikimedia.org/"):
            from PyQt6.QtCore import QUrl
            from PyQt6.QtGui import QDesktopServices
            menu.addSeparator()
            credit = menu.addAction("Recording source…", lambda: QDesktopServices.openUrl(QUrl(clip.page_url)))
            credit.setToolTip(clip.attribution)
            menu.setToolTipsVisible(True)
        menu.addSeparator()
        menu.addAction("Audio settings…", self.open_audio_settings)
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        menu.popup(button.mapToGlobal(point))
        return menu

    def open_audio_settings(self):
        self.open_settings()
        self._setup.show_audio()

    def update_anki(self):
        options, states = self.lookup_anki.refresh(self._headword_groups())
        buttons = [(None, self.anki_button)]
        buttons.extend((key, button) for key, (_, button, _) in self._headword_rows.items())
        for key, button in buttons:
            icon, description, ready = states[key]
            variants = self._presentation_groups().get(key, {})
            if len(variants) > 1:
                statuses = [states[variant] for variant in variants]
                if any(status[:2] != statuses[0][:2] for status in statuses[1:]):
                    icon, description = "anki", "Add to Anki"
                ready = any(status[2] for status in statuses)
            button.setProperty("action_name", icon)
            button.setIcon(action_icon(icon, config.color_foreground))
            button.setToolTip(description)
            button.setAccessibleName(description)
            button.setEnabled(ready)
        self.anki_button.setVisible(options.enabled and self.settings.value(
            f"profiles/{self.active_profile}/buttons/anki", True, bool) and not self._headword_rows)
        if hasattr(self, "anki_shortcut"):
            binding = self.settings.value(f"profiles/{self.active_profile}/anki/shortcut", "")
            self.anki_shortcut.setKey(QKeySequence(binding))
            self.anki_shortcut.setEnabled(states[None][2] and bool(binding))

    def add_to_anki(self, *, headword=None):
        self.lookup_anki.add(headword=headword)

    def play_audio(self, *, sentence=False, translation=False, source=None, headword=None):
        if self._result is None or self._display_revision != self.revision:
            return
        if not sentence and not translation and self._autoplayed is not None:
            self._autoplayed.add(self._audio_key(headword))
        if self.audio is None:
            from wordcel.gui.lookup_audio import LookupAudio
            self.audio = LookupAudio(self)
            self.audio.failed.connect(self.show_message)
        result = self._result
        if translation:
            text, language = result.translation, result.target
        elif sentence or not result.entries:
            text, language = (self._context or result.text) if sentence else result.text, result.source
        else:
            entries = self._headword_groups().get(headword, ()) if headword is not None else result.entries
            if not entries:
                return
            options = {"source": source} if source else {}
            self.audio.play(entries[0], self.revision, self.settings, profile=self.active_profile, **options)
            return
        self.audio.play_text(text, language, self.revision, self.settings, profile=self.active_profile)

    def show_entries(self, entries, text="", source="ja", peek=False, kanji=(), analyses=(), suggestions=(), message="",
                     vertical=False):
        if peek and self.is_pinned:
            return False
        previous_vertical = self._lookup_vertical
        self._lookup_vertical = bool(vertical and peek and self.settings.value(
            f"profiles/{self.active_profile}/vertical_popup_sides", True, bool))
        entries = tuple(entries or ())
        if (peek and self._peek and not self._translation_view and self._result is not None and self._result.text == text
                and self._result.source == source and self._result.entries == entries
                and self._result.analyses == tuple(analyses) and self._result.suggestions == tuple(suggestions)
                and self._result.message == message
                and self._result.kanji == tuple(kanji) and self.isVisible()):
            if self._lookup_vertical != previous_vertical:
                self._lookup_anchor = QCursor.pos()
                self._place()
            if self._autoplayed is not None and audio_autoplay_mode(self.settings, self.active_profile) == "lookup":
                self._autoplay()
            return True
        self._lookup_anchor = QCursor.pos() if peek else None
        self.lookup_history.timer.stop()
        self._invalidate()
        self._result_screenshot = None
        self._leave_translation()
        self._last_request_translate = False
        self._history.clear()
        self._new_chain = True
        entries = tuple(entries or ())
        partner = self.foreign.currentData()
        target = self.preferred_foreign if source == partner else partner
        result = SearchResult(text, source, target, entries, kanji=tuple(kanji), analyses=tuple(analyses),
                              suggestions=tuple(suggestions), message=message)
        with QSignalBlocker(self.search):
            self.search.setText(text)
        self.translate.setEnabled(bool(text) and self.translation_available())
        self._set_peek(peek)
        self._display(result)
        self._autoplay_lookup()
        self.set_context("")
        self.status.setText("")
        self.status.hide()
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, bool(peek))
        if peek and self.compact_preview():
            self._needs_place = True
            self.fit_timer.start(0)
        elif not self.is_pinned:
            self._place()
        self.show()
        if not peek:
            self.raise_()
        return True

    def set_context(self, text, start=0, end=None):
        previous = getattr(self, "_result_context", "")
        raw = str(text or "")
        leading = len(raw) - len(raw.lstrip())
        self._context_span = (max(0, start - leading), max(0, (len(raw) if end is None else end) - leading))
        self._context = str(text or "").strip()
        self._result_context = self._context
        self.copy_button.setEnabled(bool(self._context))
        self.copy_button.setToolTip("Copy sentence\n\n" + self._context if self._context else "Copy sentence")
        self.context_label.setToolTip(self._context)
        preview = self._context[:180] + ("…" if len(self._context) > 180 else "")
        self.context_label.setTextFormat(Qt.TextFormat.PlainText)
        self.context_label.setText(preview)
        self.context_label.hide()
        self.copy_button.setVisible(bool(self._context) and not self._translation_view)
        self._set_translation_busy(self._translation_busy)
        if self._peek and self.is_pinned and previous != self._context:
            self._render()

    def _clear_context(self):
        previous = getattr(self, "_result_context", "")
        self.set_context("")
        self._result_context = previous

    def copy_sentence(self):
        text = self.translation_panel.source.toPlainText() if self._translation_view else self._context
        if text:
            QApplication.clipboard().setText(text)

    def _pin_changed(self, checked):
        if checked and not self._translation_view:
            self.record_encounter()
            self.lookup_history.pin()
        updates = self.updatesEnabled()
        self.setUpdatesEnabled(False)
        self._pin_transition = True
        try:
            self._apply_pin(checked)
            self.fit_timer.stop()
            self._fit_preview()
        finally:
            self._pin_transition = False
            self.setUpdatesEnabled(updates)

        if checked and self._peek and audio_autoplay_mode(self.settings, self.active_profile) == "pin":
            self._autoplay()

    def _apply_pin(self, checked):
        if checked:
            self.remember_foreground()
            if self._peek:
                self._preview_viewport_height = min(self.browser.viewport().height(),
                                                    math.ceil(self.browser.document().size().height()))
        self.pin.setToolTip("Unpin" if checked else "Pin")
        self.setSizeGripEnabled(checked or not self._peek)
        for grip in self.findChildren(QWidget):
            if grip.inherits("QSizeGrip"):
                grip.installEventFilter(self)
        if self._peek:
            if checked:
                if self._reading_size_custom or self._normal_size != QSize(480, 340):
                    self.setMinimumHeight(190)
                    self._resize_expanded()
            elif self._reading_size_custom or self.size() != self._auto_fit_size:
                self._normal_size = self.size()
        if checked and not self._source_overlay:
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
            from wordcel.utils.window_focus import focus_pinned_popup
            self._opening_search = sys.platform == "darwin"
            focus_pinned_popup(self, self.browser)
            QTimer.singleShot(300, lambda: setattr(self, "_opening_search", False))
        elif checked:
            self.browser.setFocus(Qt.FocusReason.OtherFocusReason)
        self.context_label.hide()
        self._place_actions()
        self.layout().activate()
        self.render_timer.stop()
        self._render(preserve_scroll=True)

    def reload_popup_shortcuts(self):
        from wordcel.gui.popup_shortcuts import popup_bindings
        for action, binding in popup_bindings(self.settings, self.active_profile).items():
            shortcut = self._popup_shortcuts[action]
            shortcut.setKey(QKeySequence(binding))
            shortcut.setEnabled(bool(binding))
        self.update_anki()

    def popup_action(self, action):
        if (not self.isVisible() or self._peek and not self.is_pinned and action not in ("copy_text", "history")
                or QApplication.activeModalWidget() is not None):
            return
        callback = {"replay": self.play_audio, "copy": self.copy_sentence,
                    "copy_text": self.copy_text, "anki": self.add_to_anki, "back": self.go_back,
                    "history": self.lookup_history.open}.get(action)
        if callback is not None:
            callback()

    def navigate_overlay(self, virtual_key):
        keys = {0x21: Qt.Key.Key_PageUp, 0x22: Qt.Key.Key_PageDown, 0x23: Qt.Key.Key_End,
                0x24: Qt.Key.Key_Home, 0x26: Qt.Key.Key_Up, 0x28: Qt.Key.Key_Down}
        if (virtual_key in keys and self._source_overlay and self.is_pinned and self.isVisible()
                and QApplication.activeModalWidget() is None and QApplication.activePopupWidget() is None):
            event = QKeyEvent(QEvent.Type.KeyPress, keys[virtual_key], Qt.KeyboardModifier.NoModifier)
            QApplication.sendEvent(self.kanji_browser if self._kanji_view else self.browser, event)

    def nativeEvent(self, event_type, message):
        if getattr(self, "_source_overlay", False) and event_type == b"windows_generic_MSG":
            import ctypes
            from ctypes import wintypes
            native = wintypes.MSG.from_address(int(message))
            if native.message == 0x0021:  # WM_MOUSEACTIVATE
                return True, 3  # MA_NOACTIVATE preserves source-app hotkey conditions.
        # Let Qt dispatch unhandled messages; calling PyQt's base virtual can
        # crash while Windows is creating the native window handle.
        return False, 0

    def eventFilter(self, watched, event):
        if (event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape
                and watched in (self.search, self.browser, self.translation_browser,
                                self.translation_panel.source)):
            # Child editors receive Escape before QDialog.keyPressEvent. Leave
            # menus and setup dialogs to handle their own dismissal first.
            modal = QApplication.activeModalWidget()
            if QApplication.activePopupWidget() is None and modal in (None, self):
                self.hide()
                event.accept()
                return True
        if (event.type() == QEvent.Type.ShortcutOverride
                and (isinstance(watched, (QLineEdit, QKeySequenceEdit))
                     or isinstance(watched, QTextEdit) and not watched.isReadOnly())):
            event.accept()
            return True
        if (event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease)
                and event.button() in (Qt.MouseButton.BackButton, Qt.MouseButton.ForwardButton)
                and self.settings.value(f"profiles/{self.active_profile}/side_button_scrolling", True, bool)
                and (not self._peek or self.is_pinned)):
            if event.type() == QEvent.Type.MouseButtonPress:
                direction = 1 if event.button() == Qt.MouseButton.BackButton else -1
                if self._kanji_view:
                    bar = self.kanji_browser.verticalScrollBar()
                    bar.setValue(bar.value() + direction * bar.pageStep())
                elif self.browser.section_scroll.enabled:
                    self.browser.section_scroll.advance(direction)
                else:
                    bar = self.browser.verticalScrollBar()
                    bar.setValue(bar.value() + direction * bar.pageStep())
            return True
        if self._grip_event(watched, event):
            return True
        if (event.type() == QEvent.Type.KeyPress and watched is getattr(self, "search", None)
                and self.browser.section_scroll.enabled
                and event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_PageUp, Qt.Key.Key_PageDown)
                and self.browser.section_scroll.eventFilter(self.browser, event)):
            return True
        if (event.type() == QEvent.Type.Paint and hasattr(self, "browser")
                and watched is self.browser.viewport() and self._document_revision is not None
                and self._paint_revision != self._document_revision):
            self._paint_revision = self._document_revision
            mark("paint", self._document_revision)
        if event.type() == QEvent.Type.Resize and hasattr(self, "browser") and watched is self.browser.viewport():
            self._position_actions()
            if (self._peek and self.is_pinned and not self._kanji_view and hasattr(self, "render_timer")
                    and self.settings.value(f"profiles/{self.active_profile}/pinned_sentence", False, bool)
                    and not getattr(self, "_pin_transition", False)):
                self.render_timer.start(0)
        if (event.type() == QEvent.Type.ToolTip
                and watched not in (self.browser.viewport(), self.kanji_browser.viewport())
                and not isinstance(watched, QToolButton)):
            QToolTip.hideText()
            return True
        if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            if (self._translation_view and self._source_overlay
                    and watched in (self.translation_panel.source, self.translation_panel.source.viewport())):
                self._source_overlay = False
                self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
                from wordcel.utils.window_focus import focus_pinned_popup
                focus_pinned_popup(self, self.translation_panel.source)
            if self._passive_text:
                self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
                self.activateWindow()
            self._passive_text = False
        if (event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton
                and self._peek and not self.is_pinned
                and watched not in (self.dismiss_button, self.pin)):
            if watched is self.browser.viewport():
                self._engage_press = event.globalPosition().toPoint()
            else:
                self.pin.setChecked(True)
        elif event.type() == QEvent.Type.MouseButtonRelease and self._engage_press is not None:
            distance = (event.globalPosition().toPoint() - self._engage_press).manhattanLength()
            self._engage_press = None
            if distance < QApplication.startDragDistance() and not self.browser.selected_text():
                self.browser.selecting = False
                self._pin_anchor_click = True
                self.pin.setChecked(True)
                QTimer.singleShot(0, lambda: setattr(self, "_pin_anchor_click", False))
                # Pinning changes the document under the pointer; this release
                # must not activate a link that appeared after the press.
                return True
        elif event.type() == QEvent.Type.MouseButtonRelease and self._pin_anchor_click:
            QTimer.singleShot(0, lambda: setattr(self, "_pin_anchor_click", False))
        if watched is self.title:
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._drag_position = event.globalPosition().toPoint() - self.pos()
                self._drag_start = event.globalPosition().toPoint()
                self._dragging = False
            elif event.type() == QEvent.Type.MouseMove and self._drag_position is not None:
                point = event.globalPosition().toPoint()
                if not self._dragging and (point - self._drag_start).manhattanLength() >= QApplication.startDragDistance():
                    self._dragging = True
                    if self.windowHandle() and self.windowHandle().startSystemMove():
                        return True
                if self._dragging:
                    screen = QApplication.screenAt(point) or QApplication.primaryScreen()
                    area = screen.availableGeometry()
                    position = point - self._drag_position
                    self.move(max(area.left(), min(position.x(), area.right()-self.width()+1)),
                              max(area.top(), min(position.y(), area.bottom()-self.height()+1)))
                    return True
            elif event.type() == QEvent.Type.MouseButtonRelease:
                self._drag_position = None
                if self._dragging:
                    self._dragging = False
                    return True
        if self._edge_event(event):
            return True
        return super().eventFilter(watched, event)

    def _grip_event(self, watched, event):
        if (event.type() != QEvent.Type.MouseButtonPress or event.button() != Qt.MouseButton.LeftButton
                or not isinstance(watched, QWidget) or not watched.inherits("QSizeGrip")):
            return False
        self._resize_close_guard = True
        self.cursor_leave_timer.start()
        if self._peek or self._manual_at_cursor:
            self._reading_size_custom = True
        if sys.platform != "win32":
            return False
        center = watched.mapTo(self, watched.rect().center())
        edges = (Qt.Edge.LeftEdge if center.x() < self.rect().center().x() else Qt.Edge.RightEdge)
        edges |= Qt.Edge.TopEdge if center.y() < self.rect().center().y() else Qt.Edge.BottomEdge
        return self._edge_event(event, edges=edges)

    def _edge_event(self, event, *, edges=None):
        if self._peek and not self.is_pinned or event.type() not in (
                QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
            return False
        point = event.globalPosition().toPoint()
        local = self.mapFromGlobal(point)
        if edges is None:
            edges = Qt.Edge(0)
            if local.x() < 5:
                edges |= Qt.Edge.LeftEdge
            elif local.x() >= self.width() - 5:
                edges |= Qt.Edge.RightEdge
            if local.y() < 5:
                edges |= Qt.Edge.TopEdge
            elif local.y() >= self.height() - 5:
                edges |= Qt.Edge.BottomEdge
        horizontal = bool(edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge))
        vertical = bool(edges & (Qt.Edge.TopEdge | Qt.Edge.BottomEdge))
        diagonal = edges in (Qt.Edge.LeftEdge | Qt.Edge.TopEdge, Qt.Edge.RightEdge | Qt.Edge.BottomEdge)
        self.setCursor(Qt.CursorShape.SizeFDiagCursor if horizontal and vertical and diagonal else
                       Qt.CursorShape.SizeBDiagCursor if horizontal and vertical else
                       Qt.CursorShape.SizeHorCursor if horizontal else Qt.CursorShape.SizeVerCursor if vertical else
                       Qt.CursorShape.ArrowCursor)
        if event.type() == QEvent.Type.MouseButtonPress and edges and event.button() == Qt.MouseButton.LeftButton:
            self._resize_close_guard = True
            self.cursor_leave_timer.start()
            if self._peek or self._manual_at_cursor:
                self._reading_size_custom = True
            # Windows' native sizing loop also receives the OCR hook's routed
            # mouse messages. Keep those drags in the ordinary Qt event loop.
            if sys.platform == "win32" or not self.windowHandle() or not self.windowHandle().startSystemResize(edges):
                self._resize_start = (point, self.geometry(), edges)
            return True
        if self._resize_start:
            if event.type() == QEvent.Type.MouseButtonRelease:
                self._resize_start = None
            elif event.type() == QEvent.Type.MouseMove:
                origin, rect, edges = self._resize_start
                rect = type(rect)(rect)
                delta = point - origin
                area = (QApplication.screenAt(point) or QApplication.primaryScreen()).availableGeometry()
                if edges & Qt.Edge.LeftEdge:
                    rect.setLeft(max(area.left(), min(rect.right()-self.minimumWidth()+1, rect.left()+delta.x())))
                if edges & Qt.Edge.RightEdge:
                    rect.setRight(min(area.right(), max(rect.left()+self.minimumWidth()-1, rect.right()+delta.x())))
                if edges & Qt.Edge.TopEdge:
                    rect.setTop(max(area.top(), min(rect.bottom()-self.minimumHeight()+1, rect.top()+delta.y())))
                if edges & Qt.Edge.BottomEdge:
                    rect.setBottom(min(area.bottom(), max(rect.top()+self.minimumHeight()-1, rect.bottom()+delta.y())))
                self.setGeometry(rect)
            return True
        return False

    def copy_text(self):
        browser = self._selected_reading_browser()
        text = browser.selected_text() if browser else ""
        if not text and self._translation_view:
            text = self.translation_panel.translation or self.translation_panel.source.toPlainText()
        if not text and self._kanji_view:
            text = next(iter(self._kanji_details), "")
        if not text and self._result and self._result.entries:
            text = self._result.entries[0].term
        if text:
            QApplication.clipboard().setText(text)

    def _reading_browsers(self):
        if self._translation_view:
            return (self.translation_panel.source, self.translation_browser)
        if self._kanji_view:
            return (self.kanji_browser,)
        browsers = (self.browser,)
        return browsers if self.automatic_output.isHidden() else (*browsers, self.automatic_output)

    def _selected_reading_browser(self):
        browsers = self._reading_browsers()
        return next((browser for browser in sorted(browsers, key=lambda item: not item.hasFocus())
                     if browser.selected_text()), None)

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self._check_cursor_leave()

    def enterEvent(self, event):
        self._lookup_entry_pending = False
        if self._resize_close_guard:
            self._check_cursor_leave()
        else:
            self.cursor_leave_timer.stop()
        super().enterEvent(event)

    def cursor_close_bounds(self):
        margin = max(0, self.settings.value(f"profiles/{self.active_profile}/cursor_close_margin", 24, int))
        return self.frameGeometry().adjusted(-margin, -margin, margin, margin)

    def lookup_entry_path_contains(self, point):
        return (self.isVisible() and self._peek and self._lookup_vertical and self._lookup_entry_pending
                and popup_entry_path_contains(self.frameGeometry(), self._lookup_anchor, point))

    def _check_cursor_leave(self):
        point = QCursor.pos()
        if not self.isVisible() or self._capture_visibility or self._shutting_down:
            self.cursor_leave_timer.stop()
            return
        inside = self.frameGeometry().contains(point)
        if inside:
            self._lookup_entry_pending = False
        close_on_leave = ((self._peek or self._manual_at_cursor)
                          and self.settings.value(f"profiles/{self.active_profile}/close_on_cursor_leave", True, bool))
        if not self._resize_close_guard and (inside or not close_on_leave):
            self.cursor_leave_timer.stop()
            return
        if not self.cursor_leave_timer.isActive():
            self.cursor_leave_timer.start()
        from wordcel.utils.window_focus import mouse_buttons_down
        dragging = mouse_buttons_down()
        if dragging is None:
            dragging = (QApplication.mouseButtons() != Qt.MouseButton.NoButton
                        or any(browser.selecting for browser in self._reading_browsers()))
        if self._resize_close_guard:
            # A clamped resize can end outside the window. Resume dismissal only
            # after the pointer returns, including when native release precedes Qt.
            if inside and not dragging and self._resize_start is None:
                self._resize_close_guard = False
                self.cursor_leave_timer.stop()
            return
        if (not self.cursor_close_bounds().contains(point)
                and not self.lookup_entry_path_contains(point)
                and not dragging
                and QApplication.activeModalWidget() is None and QApplication.activePopupWidget() is None
                and not (self._setup is not None and self._setup.isVisible())):
            self.hide()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.ActivationChange and not self.isActiveWindow():
            QTimer.singleShot(0, self._dismiss_if_inactive)

    def _dismiss_if_inactive(self):
        if self._opening_search or self._passive_text or self._source_overlay or self._resize_close_guard:
            return
        bounds = self.cursor_close_bounds() if self.settings.value(f"profiles/{self.active_profile}/close_on_cursor_leave", True, bool) else self.geometry()
        if bounds.contains(QCursor.pos()):
            return
        setup_open = self._setup is not None and self._setup.isVisible()
        # A macOS source pin click also reaches the source application, which
        # can retain focus. Explicit outside clicks still dismiss pinned OCR.
        if (not self._peek or (self.is_pinned and sys.platform != "darwin")) and not self.isActiveWindow() and not setup_open \
                and QApplication.activeModalWidget() is None and QApplication.activePopupWidget() is None:
            self.hide()

    def showEvent(self, event):
        from wordcel.utils.window_focus import configure_macos_popup
        if not self._capture_visibility:
            self.remember_foreground()
        configure_macos_popup(self)
        super().showEvent(event)

    def hideEvent(self, event):
        self.cursor_leave_timer.stop()
        if self._capture_visibility:
            super().hideEvent(event)
            return
        self._resize_start = None
        self._resize_close_guard = False
        self.lookup_history.reset()
        if hasattr(self, "worker"):
            self._invalidate()
        self._leave_translation()
        self._remember_corner_size(force=True)
        self.pin.setChecked(False)
        super().hideEvent(event)

    def _remember_corner_size(self, *, force=False):
        if (force or self.isVisible()) and not self._peek and not self._manual_at_cursor:
            self._corner_size = self.size()
            self.settings.setValue("corner_size", self._corner_size)

    def remember_foreground(self):
        if QApplication.platformName() != "offscreen":
            from wordcel.utils.window_focus import foreground_window, focused_child
            handle = foreground_window()
            own_windows = {int(self.winId()), *(int(widget.winId()) for widget in QApplication.topLevelWidgets()
                                              if widget.isVisible())}
            if handle and handle not in own_windows:
                self._previous_foreground = handle
                self._previous_focus = focused_child(handle)

    def hide(self):
        if not self._capture_visibility and QApplication.platformName() != "offscreen":
            from wordcel.utils.window_focus import foreground_window, restore_foreground
            if foreground_window() == int(self.winId()):
                if self._previous_focus:
                    restore_foreground(self._previous_foreground, self._previous_focus)
                else:
                    restore_foreground(self._previous_foreground)
        super().hide()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            event.accept()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        self.hide()
        event.ignore()

    def open_settings(self):
        from wordcel.gui.dictionary_manager import SetupDialog
        if self._setup is None:
            self._setup = SetupDialog(self.directory, self.settings, self.apply_shortcut, self)
            self._setup.dictionaries_changed.connect(self.refresh_library)
        if not self._setup.isVisible():
            self._setup.sync_profile(self.active_profile)
        self._setup.showNormal()
        self._setup.raise_()
        from wordcel.utils.window_focus import activate_application
        activate_application()
        self._setup.activateWindow()

    def record_encounter(self, *, restored=False):
        if self._result is None:
            return
        context = self._context or self._result.text
        start, end = getattr(self, "_context_span", (0, len(context)))
        start, end = min(start, len(context)), min(end, len(context))
        result = self._result
        if end > start and (self._peek or self._encounter_context and self._encounter_context[0] == self.revision):
            result = replace(result, text=context[start:end])
        mode = "pinned" if self.is_pinned else "hover" if self._peek else "manual"
        self.lookup_history.display(result, context, start, end, mode, restored=restored)

    def restore_encounter(self, row, *, add_to_anki=False):
        self.open_search()
        history = self.lookup_history.browser
        if history is not None and history.isVisible():
            self._previous_foreground = int(history.winId())
            self._previous_focus = None
        with QSignalBlocker(self.search):
            self.search.setText(row["form"])
        self.submit(saved_encounter=row)
        self._history_anki_revision = self.revision if add_to_anki else None

    def refresh_library(self):
        self._render_identity = None
        self.refresh_translation_availability()
        self.worker.refresh()
        if self.translation_worker is not None:
            self.translation_worker.refresh()
        self._edited()
        self.dictionaries_changed.emit()

    def apply_shortcut(self, value, preset=None):
        return self.lookup_shortcuts.apply("hotkey", value, preset)

    def restore_shortcut(self, explicit=None):
        self.lookup_shortcuts.restore(explicit)

    def restore_cycle_shortcuts(self):
        self.lookup_shortcuts.restore_cycle()

    def refresh_translation_availability(self):
        from wordcel.gui.resources import managed_translation_available
        managed_translation_available.cache_clear()
        self._place_actions()
        self.reload_popup_shortcuts()
        if self.lookup_shortcuts.restored:
            self.apply_translation_shortcut(self.settings.value(f"profiles/{self.active_profile}/translation_hotkey", ""))
        self.scan_settings_changed.emit()

    def apply_translation_shortcut(self, value, preset=None):
        return self.lookup_shortcuts.apply("translation", value, preset)

    def apply_copy_shortcut(self, value, preset=None):
        return self.lookup_shortcuts.apply("copy", value, preset)

    def apply_hover_shortcut(self, value, preset=None):
        return self.lookup_shortcuts.apply("hover", value, preset)

    def _application_state_changed(self, state):
        self.lookup_shortcuts.application_state_changed(state)

    def shutdown(self):
        if self._shutting_down:
            return
        onboarding = getattr(self, "_language_setup", None)
        if onboarding is not None:
            onboarding.cancelled.set()
        self._shutting_down = True
        self.lookup_history.shutdown()
        self.selection.cancel()
        if self.audio:
            self.audio.shutdown()
        self.debounce.stop()
        for timer in (self.busy_delay, self.fit_timer, self.render_timer, self.stream_timer, self.link_timer,
                      self.cursor_leave_timer, self.translation_debounce):
            timer.stop()
        self._translation_chunk = None
        self.worker.shutdown()
        if self.translation_worker is not None:
            self.translation_worker.shutdown()
        if self._setup is not None:
            self._setup.cancel_operation()
            self._setup.audio_sources.shutdown()
        self.lookup_shortcuts.shutdown()
