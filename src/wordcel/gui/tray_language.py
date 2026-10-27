"""Language indicator for the system tray."""
from functools import lru_cache

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QIcon, QPainter, QPixmap


@lru_cache(maxsize=128)
def language_icon(language, mask=False):
    label = language.split("-", 1)[0].upper() or "?"
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    if not mask:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#283e52"))
        painter.drawRoundedRect(QRectF(2, 2, 60, 60), 12, 12)
    painter.setPen(QColor("black" if mask else "white"))
    font = QFont()
    font.setBold(True)
    font.setPixelSize(35)
    while QFontMetricsF(font).horizontalAdvance(label) > 56 and font.pixelSize() > 8:
        font.setPixelSize(font.pixelSize() - 1)
    painter.setFont(font)
    painter.drawText(QRectF(2, 2, 60, 60), Qt.AlignmentFlag.AlignCenter, label)
    painter.end()
    icon = QIcon(pixmap)
    icon.setIsMask(mask)
    return icon


def update_tray_profile(tray, window, mask=False):
    language = window.preferred_foreign
    tray.setIcon(language_icon(language, mask))
    tray.setToolTip(f"Wordcel: {window.source.currentText()} ({language})")
