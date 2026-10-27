# wordcel/gui/region_selector.py
import logging

from PyQt6.QtCore import Qt, QPoint, QRect, QRectF, QTimer
from PyQt6.QtGui import QColor, QPainter, QPen, QMouseEvent, QKeyEvent, QGuiApplication, QCursor
from PyQt6.QtWidgets import QDialog

logger = logging.getLogger(__name__)

class RegionSelector(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        from pynput.mouse import Controller
        self.mouse_controller = Controller()

        self.setGeometry(self.get_current_screen(QCursor.pos()).geometry())

        # Window setup for a seamless overlay
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)

        # Points for drawing the overlay (in Qt's logical coordinates)
        self.begin_logical = QPoint()
        self.end_logical = QPoint()

        # Points for the final result (in physical coordinates)
        self.begin_physical = None
        self.selection_rect = None
        self.logical_selection_rect = None

        self.has_selection_started = False

        self.update_timer = QTimer(self)
        self.update_timer.setInterval(16)
        self.update_timer.timeout.connect(self.update_selection_rect)
        self.update_timer.start()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 100))

        if self.has_selection_started:
            rect_logical = QRect(self.begin_logical - self.geometry().topLeft(),
                                 self.end_logical - self.geometry().topLeft()).normalized()

            # Clear the selected area
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(rect_logical, Qt.GlobalColor.transparent)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

            # Draw the border, adjusted to be fully visible at the edges
            pen = QPen(QColor(30, 200, 255), 1, Qt.PenStyle.SolidLine)
            painter.setPen(pen)
            border_rect = rect_logical.adjusted(0, 0, -1, -1)
            painter.drawRect(border_rect)

    def mousePressEvent(self, event: QMouseEvent):
        self.begin_logical = QCursor.pos()
        self.end_logical = self.begin_logical

        # Store the physical position for the final result
        px, py = self.mouse_controller.position
        self.begin_physical = QPoint(px, py)

        self.has_selection_started = True
        self.update()

    def update_selection_rect(self):
        mouse_pos = QCursor.pos()
        if not self.has_selection_started:
            current_screen = self.get_current_screen(mouse_pos)
            if current_screen:
                self.setGeometry(current_screen.geometry())
                self.update()
            return

        self.end_logical = mouse_pos
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if not self.has_selection_started:
            return
        self.update_timer.stop()
        self.end_logical = QCursor.pos()
        self.logical_selection_rect = QRect(self.begin_logical, self.end_logical).normalized()

        # Get the final physical position
        px, py = self.mouse_controller.position
        end_physical = QPoint(px, py)

        # Create the final selection rectangle using the stored physical coordinates
        self.selection_rect = QRect(self.begin_physical, end_physical).normalized()
        self.accept()

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Escape:
            if self.update_timer.isActive():
                self.update_timer.stop()
            self.selection_rect = None
            self.reject()

    @staticmethod
    def get_current_screen(point):
        for screen in QGuiApplication.screens():
            if screen.geometry().contains(point):
                return screen
        return None

    @staticmethod
    def get_region(*, logical=False):
        logger.info("Awaiting region selection... you can change the scan region in the tray")
        selector = RegionSelector()
        if selector.exec() == QDialog.DialogCode.Accepted:
            return selector.logical_selection_rect if logical else selector.selection_rect
        return None


class TextRegionSelector(QDialog):
    """One frozen overlay per display, keeping each display's native scale."""
    def __init__(self, screen, snapshot, finish):
        super().__init__()
        self.snapshot, self.finish = snapshot, finish
        self.origin = None
        self.selection = QRect()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setGeometry(screen.geometry())
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self.snapshot)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 100))
        if not self.selection.isEmpty():
            painter.save()
            painter.setClipRect(self.selection)
            painter.drawPixmap(self.rect(), self.snapshot)
            painter.restore()
            painter.setPen(QPen(self.palette().highlight().color(), 1))
            painter.drawRect(self.selection.adjusted(0, 0, -1, -1))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self.finish(None)
        elif event.button() == Qt.MouseButton.LeftButton:
            self.origin = event.position()
            self.selection = QRect()
            self.update()

    def mouseMoveEvent(self, event):
        if self.origin is not None:
            self.selection = QRectF(self.origin, event.position()).normalized().toAlignedRect().intersected(self.rect())
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self.origin is None:
            return
        self.mouseMoveEvent(event)
        self.origin = None
        if self.selection.width() < 2 or self.selection.height() < 2:
            self.selection = QRect()
            self.update()
            return
        image = self.snapshot.toImage()
        sx, sy = image.width() / self.width(), image.height() / self.height()
        rect = self.selection
        left, top = round(rect.x() * sx), round(rect.y() * sy)
        right, bottom = round((rect.x() + rect.width()) * sx), round((rect.y() + rect.height()) * sy)
        self.finish(image.copy(left, top, right - left, bottom - top))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.finish(None)
        else:
            event.ignore()

    def closeEvent(self, event):
        self.finish(None)
        event.accept()

    @staticmethod
    def get_image():
        from PyQt6.QtCore import QEventLoop
        loop = QEventLoop()
        result = None
        def finish(image):
            nonlocal result
            result = image
            loop.quit()
        # Capture every display before showing any overlay.
        captures = [(screen, screen.grabWindow(0)) for screen in QGuiApplication.screens()]
        if not captures or any(pixmap.isNull() for _, pixmap in captures):
            raise RuntimeError("Screen capture is unavailable. Check screen recording permissions.")
        overlays = [TextRegionSelector(screen, pixmap, finish) for screen, pixmap in captures]
        app = QGuiApplication.instance()
        def cancel(*_):
            finish(None)
        app.screenAdded.connect(cancel)
        app.screenRemoved.connect(cancel)
        app.aboutToQuit.connect(loop.quit)
        try:
            for overlay in overlays:
                overlay.show()
            active = next((overlay for overlay in overlays if overlay.geometry().contains(QCursor.pos())), overlays[0])
            active.raise_()
            active.activateWindow()
            loop.exec()
            return result
        finally:
            app.screenAdded.disconnect(cancel)
            app.screenRemoved.disconnect(cancel)
            app.aboutToQuit.disconnect(loop.quit)
            for overlay in overlays:
                overlay.hide()
                overlay.deleteLater()
