import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import QApplication

from wordcel.gui.tray_language import TrayLanguageIcons, update_tray_profile


class TrayLanguageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_updates_icon_and_tooltip_for_active_language_and_profile(self):
        tray = Mock()
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.red)
        icons = TrayLanguageIcons(QIcon(pixmap))
        window = SimpleNamespace(preferred_foreign="ja", source=Mock())
        window.source.currentText.return_value = "Japanese"
        update_tray_profile(tray, window, icons)
        japanese = tray.setIcon.call_args.args[0]
        self.assertFalse(japanese.isNull())
        self.assertEqual(japanese.pixmap(QSize(64, 64)).toImage().pixelColor(10, 50), Qt.GlobalColor.red)
        tray.setToolTip.assert_called_with("Wordcel: Japanese (ja)")

        window.preferred_foreign = "tr"
        window.source.currentText.return_value = "Reading"
        update_tray_profile(tray, window, icons)
        turkish = tray.setIcon.call_args.args[0]
        self.assertNotEqual(japanese.pixmap(QSize(32, 32)).toImage(), turkish.pixmap(QSize(32, 32)).toImage())
        tray.setToolTip.assert_called_with("Wordcel: Reading (tr)")

        window.source.currentText.return_value = "Study"
        update_tray_profile(tray, window, icons)
        tray.setToolTip.assert_called_with("Wordcel: Study (tr)")

    def test_macos_icon_is_a_mask(self):
        self.assertTrue(TrayLanguageIcons(QIcon(), True).icon("ja").isMask())
