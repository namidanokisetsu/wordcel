import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from unittest.mock import patch

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QApplication

from wordcel.gui.profile_indicator import ProfileIndicator


class ProfileIndicatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_repeated_switches_update_one_noninteractive_indicator(self):
        indicator = ProfileIndicator()
        self.addCleanup(indicator.close)
        area = QGuiApplication.primaryScreen().availableGeometry()
        with patch("wordcel.gui.profile_indicator.QCursor.pos", return_value=area.bottomRight()):
            indicator.show_profile("Japanese")
            indicator.show_profile("Turkish")
        self.assertEqual(indicator.text(), "Turkish")
        self.assertTrue(indicator.isVisible())
        self.assertTrue(indicator.timer.isActive())
        self.assertTrue(indicator.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating))
        self.assertTrue(indicator.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))
        self.assertTrue(area.contains(indicator.geometry()))
        indicator.timer.timeout.emit()
        self.assertFalse(indicator.isVisible())
