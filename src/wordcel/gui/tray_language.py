"""Language indicator for the system tray."""
from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QIcon, QPainter, QPixmap


class TrayLanguageIcons:
    def __init__(self, base_icon, mask=False):
        self.base_icon = base_icon
        self.mask = mask
        self.icons = {}

    def icon(self, language):
        label = language.split("-", 1)[0].upper() or "?"
        if label in self.icons:
            return self.icons[label]
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        self.base_icon.paint(painter, 0, 0, 64, 37)
        badge = QRectF(1, 37, 62, 26)
        painter.setPen(Qt.PenStyle.NoPen)
        if self.mask:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.setBrush(Qt.GlobalColor.transparent)
            painter.drawRoundedRect(badge.adjusted(-1, -1, 1, 1), 6, 6)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.setBrush(QColor("black" if self.mask else "#283e52"))
        painter.drawRoundedRect(badge, 5, 5)
        font = QFont()
        font.setBold(True)
        font.setPixelSize(27)
        while QFontMetricsF(font).horizontalAdvance(label) > badge.width() - 4 and font.pixelSize() > 8:
            font.setPixelSize(font.pixelSize() - 1)
        painter.setFont(font)
        if self.mask:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        painter.setPen(QColor("white"))
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, label)
        painter.end()
        icon = QIcon(pixmap)
        icon.setIsMask(self.mask)
        self.icons[label] = icon
        return icon


def update_tray_profile(tray, window, icons):
    language = window.preferred_foreign
    tray.setIcon(icons.icon(language))
    tray.setToolTip(f"Wordcel: {window.source.currentText()} ({language})")
