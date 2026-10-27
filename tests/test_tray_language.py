import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from PyQt6.QtCore import QSize
from PyQt6.QtWidgets import QApplication

from wordcel.gui.tray_language import language_icon, update_tray_profile


class TrayLanguageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_updates_icon_and_tooltip_for_active_language_and_profile(self):
        tray = Mock()
        window = SimpleNamespace(preferred_foreign="ja", source=Mock())
        window.source.currentText.return_value = "Japanese"
        update_tray_profile(tray, window)
        japanese = tray.setIcon.call_args.args[0]
        self.assertFalse(japanese.isNull())
        tray.setToolTip.assert_called_with("Wordcel: Japanese (ja)")

        window.preferred_foreign = "tr"
        window.source.currentText.return_value = "Reading"
        update_tray_profile(tray, window)
        turkish = tray.setIcon.call_args.args[0]
        self.assertNotEqual(japanese.pixmap(QSize(32, 32)).toImage(), turkish.pixmap(QSize(32, 32)).toImage())
        tray.setToolTip.assert_called_with("Wordcel: Reading (tr)")

        window.source.currentText.return_value = "Study"
        update_tray_profile(tray, window)
        tray.setToolTip.assert_called_with("Wordcel: Study (tr)")

    def test_macos_icon_is_a_mask(self):
        self.assertTrue(language_icon("ja", True).isMask())
