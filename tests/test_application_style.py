import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtGui import QFontDatabase, QFontInfo, QFontMetricsF, QPalette, QRawFont
from PyQt6.QtWidgets import QApplication, QCheckBox, QComboBox, QFormLayout, QLineEdit, QPushButton, QWidget

from wordcel.config.config import config
from wordcel.gui.application_style import application_palette, configure_application
from wordcel.gui.profile_appearance import ProfileAppearance, load_appearance
from wordcel.gui.settings_section import SettingsSection
from wordcel.gui.typography import default_family, document_font


class ApplicationStyleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        configure_application(cls.app)

    def test_repeated_setup_does_not_register_fonts_or_change_widget_geometry(self):
        widget = QWidget()
        form = QFormLayout(widget)
        for label, control in (("Text", QLineEdit()), ("Language", QComboBox()),
                               ("Enabled", QCheckBox()), ("Action", QPushButton("Continue"))):
            form.addRow(label, control)
        widget.show()
        self.app.processEvents()
        geometry = [form.itemAt(i).widget().geometry() for i in range(form.count())]
        with patch.object(QFontDatabase, "addApplicationFont") as register:
            configure_application(self.app)
            register.assert_not_called()
        self.assertEqual(geometry, [form.itemAt(i).widget().geometry() for i in range(form.count())])
        self.assertEqual(self.app.style().name().lower(), "fusion")
        self.assertEqual(QFontInfo(self.app.font()).family(), "Noto Sans")
        self.assertEqual(self.app.font().pixelSize(), 13)
        widget.close()

    def test_default_families_and_text_metrics_match_for_both_platforms(self):
        values = []
        for platform in ("darwin", "win32"):
            with patch("wordcel.gui.typography.sys.platform", platform):
                row = []
                for language, text, family in (("ja", "家の読み方", "Noto Sans JP"),
                                                ("tr", "ışık araç çığ", "Noto Sans"),
                                                ("en", "Settings", "Noto Sans")):
                    font = document_font(default_family(language), 14, language)
                    self.assertEqual(QFontInfo(font).family(), family)
                    raw = QRawFont.fromFont(font)
                    self.assertTrue(all(raw.supportsCharacter(char) for char in text))
                    metrics = QFontMetricsF(font)
                    row.append((metrics.horizontalAdvance(text), metrics.height()))
                values.append(row)
        self.assertEqual(values[0], values[1])

    def test_profile_font_survives_unrelated_saves_and_profile_switches(self):
        previous = config.font_family
        self.addCleanup(setattr, config, "font_family", previous)
        with tempfile.TemporaryDirectory() as folder:
            settings = QSettings(str(Path(folder) / "settings.ini"), QSettings.Format.IniFormat)
            chosen = "Wordcel unavailable font fixture"
            settings.setValue("profiles/ja/font_family", chosen)
            profile = ["ja"]
            widget = ProfileAppearance(settings, lambda: profile[0], lambda: None)
            try:
                widget.pinned_grammar.click()
                self.assertEqual(settings.value("profiles/ja/font_family"), chosen)
                self.assertEqual(widget.font.currentText(), chosen)
                load_appearance(settings, "ja")
                self.assertEqual(config.font_family, chosen)
                profile[0] = "tr"
                widget.reload()
                widget.save()
                profile[0] = "ja"
                widget.reload()
                widget.save()
                self.assertEqual(settings.value("profiles/ja/font_family"), chosen)
                widget.font.setCurrentFont(document_font("Noto Sans JP", 14, "ja"))
                self.assertEqual(settings.value("profiles/ja/font_family"), "Noto Sans JP")
            finally:
                widget.deleteLater()

    def test_disclosure_and_palette_changes_keep_button_size(self):
        section = SettingsSection("Preview", QWidget(), collapsible=True)
        before = section.toggle.sizeHint()
        for opened in (True, False, True):
            section.toggle.setChecked(opened)
            self.assertEqual(section.toggle.sizeHint(), before)
            self.assertFalse(section.toggle.icon().isNull())
        for scheme in (Qt.ColorScheme.Light, Qt.ColorScheme.Dark):
            palette = application_palette(self.app.style(), scheme)
            foreground = palette.color(QPalette.ColorRole.Text)
            background = palette.color(QPalette.ColorRole.Base)
            self.assertGreater(abs(foreground.lightness() - background.lightness()), 150)
        section.deleteLater()
