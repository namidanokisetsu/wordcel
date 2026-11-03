"""Shared dictionary selection without touching the system clipboard."""
from PyQt6.QtCore import pyqtSignal, Qt, QPointF, QUrl
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import QApplication, QTextBrowser


DISCLOSURE_LINKS = ("collapse:", "expand:", "details:", "inflections:")


class DictionaryBrowser(QTextBrowser):
    word_selected = pyqtSignal(str)

    def __init__(self, *args, selection_lookup=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.selection_lookup = selection_lookup
        self.selecting = False
        self._selection_emitted = False
        self._control_press = None
        self.selectionChanged.connect(self._clear_control_selection)

    def _clear_control_selection(self):
        cursor = self.textCursor()
        if not cursor.hasSelection():
            return
        block = self.document().findBlock(cursor.selectionStart())
        if cursor.selectionEnd() > block.position() + block.length() - 1:
            return
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            if (fragment.position() < cursor.selectionEnd()
                    and fragment.position() + fragment.length() > cursor.selectionStart()
                    and not fragment.charFormat().anchorHref().startswith(DISCLOSURE_LINKS)):
                return
            iterator += 1
        # QTextBrowser can also select a focused link when it is shown again.
        cursor.clearSelection()
        self.setTextCursor(cursor)

    def hideEvent(self, event):
        # A native dismissal can consume the mouse release during selection.
        self.selecting = False
        self._selection_emitted = False
        self._control_press = None
        super().hideEvent(event)

    def contextMenuEvent(self, event):
        menu = self.createStandardContextMenu()
        if self.selected_text():
            menu.addSeparator()
            menu.addAction("Look up", self.lookup_selection)
        menu.exec(event.globalPos())
        menu.deleteLater()

    def mousePressEvent(self, event):
        self._selection_emitted = False
        self._control_press = None
        point = event.position().toPoint()
        anchor = self.anchorAt(point)
        if event.button() == Qt.MouseButton.LeftButton and anchor.startswith(DISCLOSURE_LINKS):
            self._control_press = (anchor, point)
            self.selecting = False
            event.accept()
            return
        self.selecting = event.button() == Qt.MouseButton.LeftButton
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._control_press is not None:
            anchor, origin = self._control_press
            if (event.position().toPoint() - origin).manhattanLength() >= QApplication.startDragDistance():
                self._control_press = ("", origin)
            event.accept()
            return
        super().mouseMoveEvent(event)
        point = event.position().toPoint()
        flags = self.textInteractionFlags()
        shape = Qt.CursorShape.ArrowCursor
        if (flags & Qt.TextInteractionFlag.LinksAccessibleByMouse
                and not self.selecting and self.anchorAt(point)):
            shape = Qt.CursorShape.PointingHandCursor
        elif flags & Qt.TextInteractionFlag.TextSelectableByMouse:
            document_point = QPointF(point.x() + self.horizontalScrollBar().value(),
                                     point.y() + self.verticalScrollBar().value())
            if (self.selecting or self.document().documentLayout().hitTest(
                    document_point, Qt.HitTestAccuracy.ExactHit) >= 0):
                shape = Qt.CursorShape.IBeamCursor
        self.viewport().setCursor(shape)

    def selected_text(self):
        return self.textCursor().selectedText().replace("\u2029", "\n").strip()

    def text_at(self, point):
        document_point = QPointF(point.x() + self.horizontalScrollBar().value(),
                                 point.y() + self.verticalScrollBar().value())
        if self.document().documentLayout().hitTest(document_point, Qt.HitTestAccuracy.ExactHit) < 0:
            return ""
        selected = self.selected_text()
        cursor = self.cursorForPosition(point)
        selection = self.textCursor()
        if selected and selection.selectionStart() <= cursor.position() < selection.selectionEnd():
            return selected
        cursor.select(QTextCursor.SelectionType.WordUnderCursor)
        text = cursor.selectedText().strip()
        return text if any(c.isalpha() for c in text) else ""

    def lookup_selection(self):
        text = self.selected_text()
        if text and len(text) <= 2000:
            self.word_selected.emit(text)

    def mouseDoubleClickEvent(self, event):
        if self.anchorAt(event.position().toPoint()).startswith(DISCLOSURE_LINKS):
            self.mousePressEvent(event)
            return
        self.selecting = event.button() == Qt.MouseButton.LeftButton
        super().mouseDoubleClickEvent(event)
        if self.selection_lookup and self.selecting and not self.anchorAt(event.position().toPoint()):
            self._selection_emitted = True
            self.lookup_selection()

    def mouseReleaseEvent(self, event):
        if self._control_press is not None and event.button() == Qt.MouseButton.LeftButton:
            anchor, origin = self._control_press
            self._control_press = None
            point = event.position().toPoint()
            if (anchor and self.anchorAt(point) == anchor
                    and (point - origin).manhattanLength() < QApplication.startDragDistance()):
                self.anchorClicked.emit(QUrl(anchor))
            event.accept()
            return
        # A link handler can scroll or replace the document during Qt's release.
        anchor = self.anchorAt(event.position().toPoint())
        self.selecting = False
        super().mouseReleaseEvent(event)
        if (self.selection_lookup and not self._selection_emitted and event.button() == Qt.MouseButton.LeftButton
                and not anchor):
            self.lookup_selection()
        self._selection_emitted = False
