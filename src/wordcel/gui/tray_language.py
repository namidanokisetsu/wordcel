"""Language indicator for the system tray."""
from pathlib import Path

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QIcon, QPainter, QPixmap


def _macos_tray_icon():
    """Load the transparent monochrome mark used by the menu bar."""
    from wordcel.utils.paths import paths
    icon = QIcon(str(Path(paths.get_resource_path("tray.svg"))))
    if icon.isNull():
        return QIcon()
    icon.setIsMask(True)
    return icon


class TrayLanguageIcons:
    def __init__(self, base_icon, mask=False):
        self.base_icon = base_icon
        self.mask = mask
        self.icons = {}

    def icon(self, language):
        label = language.split("-", 1)[0].upper() or "?"
        if self.mask:
            # The menu bar supplies the foreground color. A language badge
            # makes this small mark harder to recognize at native size.
            key = "__macos__"
            if key not in self.icons:
                self.icons[key] = _macos_tray_icon()
            return self.icons[key]
        if label in self.icons:
            return self.icons[label]
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        self.base_icon.paint(painter, 0, 0, 64, 64)
        badge = QRectF(26, 39, 38, 25)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("black" if self.mask else "#283e52"))
        painter.drawRoundedRect(badge, 5, 5)
        font = QFont()
        font.setBold(True)
        font.setPixelSize(24)
        while QFontMetricsF(font).horizontalAdvance(label) > badge.width() - 4 and font.pixelSize() > 8:
            font.setPixelSize(font.pixelSize() - 1)
        painter.setFont(font)
        painter.setPen(QColor("white"))
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, label)
        painter.end()
        icon = QIcon(pixmap)
        self.icons[label] = icon
        return icon


def update_tray_profile(tray, window, icons):
    language = window.preferred_foreign
    tray.setIcon(icons.icon(language))
    tray.setToolTip(f"Wordcel: {window.source.currentText()} ({language})")
