import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PyQt6.QtCore import QPoint, QRect
from PyQt6.QtWidgets import QApplication

from wordcel.gui.macos_tray import MacTrayAdapter


class MacTrayDispatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tray = Mock()
        self.tray.geometry.return_value = QRect(10, 20, 30, 30)
        self.menu = Mock()
        self.search = Mock()
        self.adapter = MacTrayAdapter(self.tray, self.menu, self.search)
        self.adapter._left_down = 1
        self.adapter._left_up = 2
        self.adapter._right_down = 3
        self.adapter._right_up = 4

    def test_left_click_dispatches_search_and_consumes_native_event(self):
        event = SimpleNamespace(type=lambda: 1)
        with patch("wordcel.gui.macos_tray.QCursor.pos", return_value=QPoint(20, 30)), \
                patch("wordcel.gui.macos_tray.QTimer.singleShot", side_effect=lambda delay, callback: callback()):
            self.assertIsNone(self.adapter._event(event))
        self.search.assert_called_once_with()
        self.menu.popup.assert_not_called()
        self.assertIsNone(self.adapter._event(SimpleNamespace(type=lambda: 2)))

    def test_right_click_dispatches_context_menu_and_consumes_native_event(self):
        event = SimpleNamespace(type=lambda: 3)
        with patch("wordcel.gui.macos_tray.QCursor.pos", return_value=QPoint(20, 30)), \
                patch("wordcel.gui.macos_tray.QTimer.singleShot", side_effect=lambda delay, callback: callback()):
            self.assertIsNone(self.adapter._event(event))
        self.search.assert_not_called()
        self.menu.popup.assert_called_once_with(QPoint(20, 30))
        self.assertIsNone(self.adapter._event(SimpleNamespace(type=lambda: 4)))

    def test_clicks_outside_status_item_pass_through(self):
        event = SimpleNamespace(type=lambda: 1)
        with patch("wordcel.gui.macos_tray.QCursor.pos", return_value=QPoint(200, 200)):
            self.assertIs(self.adapter._event(event), event)
        self.search.assert_not_called()

    def test_clicks_from_another_native_window_pass_through(self):
        native_window = SimpleNamespace(className=lambda: "NSWindow")
        event = SimpleNamespace(type=lambda: 1, window=lambda: native_window)
        with patch("wordcel.gui.macos_tray.QCursor.pos", return_value=QPoint(20, 30)):
            self.assertIs(self.adapter._event(event), event)
        self.search.assert_not_called()


if __name__ == "__main__":
    unittest.main()
