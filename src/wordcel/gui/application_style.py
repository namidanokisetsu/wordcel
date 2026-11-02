"""Shared widget metrics and colors; desktop integration stays native."""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPalette

from wordcel.gui.typography import document_font, register_fonts


def application_palette(style, scheme):
    palette = style.standardPalette()
    if scheme == Qt.ColorScheme.Dark:
        for role, color in {
            "Window": "#242424", "WindowText": "#f0f0f0", "Base": "#1c1c1c",
            "AlternateBase": "#303030", "Text": "#f0f0f0", "Button": "#303030",
            "ButtonText": "#f0f0f0", "Highlight": "#346cac", "HighlightedText": "#ffffff",
            "Light": "#505050", "Midlight": "#404040", "Mid": "#202020", "Dark": "#181818",
            "PlaceholderText": "#a0a0a0", "Link": "#88bbff", "LinkVisited": "#c7a6ff",
        }.items():
            palette.setColor(getattr(QPalette.ColorRole, role), QColor(color))
        for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
            palette.setColor(QPalette.ColorGroup.Disabled, role, QColor("#969696"))
    return palette


def configure_application(app):
    if app.property("wordcel_style"):
        return
    register_fonts()
    app.setStyle("Fusion")
    app.setFont(document_font("Noto Sans", 13, "en"))

    def update_palette(scheme):
        app.setPalette(application_palette(app.style(), scheme))

    update_palette(app.styleHints().colorScheme())
    app.styleHints().colorSchemeChanged.connect(update_palette)
    app.setProperty("wordcel_style", True)
