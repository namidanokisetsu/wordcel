"""Small monochrome action icons drawn locally for the shared popup."""
from functools import lru_cache
from PyQt6.QtCore import QByteArray, QRectF, QSize, Qt
from PyQt6.QtGui import QIcon, QIconEngine, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QToolButton

POPUP_ACTIONS = (("anki", "Add to Anki"), ("audio_sentence", "Sentence audio"),
                 ("audio", "Word audio"), ("translate", "Translate"),
                 ("copy", "Copy"), ("close", "Close"), ("back", "Back"))


_SHAPES = {
    "swap": '<path d="M3 8h17m-4-4 4 4-4 4M21 16H4m4-4-4 4 4 4"/>',
    "anki": '<circle cx="12" cy="12" r="10"/><path d="M7 12h10M12 7v10"/>',
    "anki_saved": '<circle cx="12" cy="12" r="10"/><path d="m7 12 3 3 7-7"/>',
    "audio": '<path d="M2 9h4l6-4v14l-6-4H2ZM16 8c3 2 3 6 0 8M19 3c5 4.5 5 13.5 0 18"/>',
    "back": '<path d="m14 5-7 7 7 7M7 12h13"/>',
    "close": '<path d="m6 6 12 12M18 6 6 18"/>',
    "copy": '<rect x="8" y="8" width="12" height="12" rx="1.5"/><path d="M16 8V4H4v12h4"/>',
    "pin": '<path d="m8 3 8 0-1 7 3 3v2H6v-2l3-3-1-7ZM12 15v7"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="m9 3 1-1h4l1 1v2l2 1 2-1 2 3-1 2-1 1v2l1 1 1 2-2 3-2-1-2 1v2l-1 1h-4l-1-1v-2l-2-1-2 1-2-3 1-2 1-1v-2l-1-1-1-2 2-3 2 1 2-1V3Z"/>',
    "translate": '<path d="M3 4h10M8 2v2M11 4c0 6-3 9-8 11M5 7c1 3 4 6 7 7M13 21l4-11 4 11M14.5 17h5"/>',
}


@lru_cache(maxsize=None)
def _shape(name):
    shape = _SHAPES["audio" if name == "audio_sentence" else name]
    renderer = QSvgRenderer(QByteArray(
        f'<svg xmlns="http://www.w3.org/2000/svg"><g id="shape">{shape}</g></svg>'.encode()))
    bounds = renderer.boundsOnElement("shape")
    center = bounds.center()
    extent = 14 if name == "close" else 20
    scale = extent / max(bounds.width(), bounds.height())
    # Normalize shape size without cancelling the raster's display-scale transform.
    return (f'<g transform="translate(12 12) scale({scale}) '
            f'translate({-center.x()} {-center.y()})" stroke-width="{1.6 / scale}">{shape}</g>')


class ActionIconEngine(QIconEngine):
    def __init__(self, name, color):
        super().__init__()
        self.name, self.color = name, color
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">'
           f'<g fill="none" stroke="{color}" stroke-width="1.6" stroke-linecap="round" '
           f'stroke-linejoin="round">{_shape(name)}</g></svg>')
        self.renderer = QSvgRenderer(QByteArray(svg.encode()))

    def clone(self):
        return ActionIconEngine(self.name, self.color)

    def isNull(self):
        return not self.renderer.isValid()

    def paint(self, painter, rect, mode, state):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if mode == QIcon.Mode.Disabled:
            painter.setOpacity(painter.opacity() * .45)
        self.renderer.render(painter, QRectF(rect))
        painter.restore()

    def pixmap(self, size, mode, state):
        return self.scaledPixmap(size, mode, state, 1)

    def scaledPixmap(self, size, mode, state, scale):
        pixmap = QPixmap(size * scale)
        pixmap.setDevicePixelRatio(scale)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        self.paint(painter, QRectF(0, 0, size.width(), size.height()), mode, state)
        painter.end()
        return pixmap


def action_icon(name, color):
    return QIcon(ActionIconEngine(name, color))


def action_button(name, description, color):
    button = QToolButton()
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setProperty("action_name", name)
    button.setIcon(action_icon(name, color))
    button.setIconSize(QSize(16, 16))
    button.setFixedSize(25, 25)
    button.setAccessibleName(description)
    button.setToolTip(description)
    return button
