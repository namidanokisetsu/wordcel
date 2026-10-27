"""Brief, non-interactive feedback for profile shortcuts."""
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QCursor, QGuiApplication
from PyQt6.QtWidgets import QLabel

from wordcel.gui.popup_style import popup_position


class ProfileIndicator(QLabel):
    def __init__(self):
        super().__init__(None, Qt.WindowType.ToolTip | Qt.WindowType.WindowDoesNotAcceptFocus
                         | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setStyleSheet("QLabel { padding: 6px 10px; }")
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)

    def show_profile(self, name):
        self.setText(name)
        self.adjustSize()
        point = QCursor.pos()
        screen = QGuiApplication.screenAt(point) or QGuiApplication.primaryScreen()
        if screen is not None:
            self.move(*popup_position(point.x(), point.y(), self.size(), screen.availableGeometry(), "flip_both"))
        self.show()
        self.timer.start(1200)
