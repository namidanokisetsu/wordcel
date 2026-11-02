import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from unittest.mock import patch

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget

from wordcel.gui.macos_permissions import PermissionNotice


class MacPermissionNoticeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.parent = QWidget()
        self.addCleanup(self.parent.deleteLater)
        self.addCleanup(self.parent.close)
        self.states = {"screen_recording": False, "accessibility": True}
        status = patch("wordcel.gui.macos_permissions.privacy_permission_granted", side_effect=self.states.get)
        status.start()
        self.addCleanup(status.stop)
        self.notice = PermissionNotice((("screen_recording", "Screen Recording is needed for OCR."),
                                         ("accessibility", "Accessibility is needed for scan controls.")), self.parent)
        QVBoxLayout(self.parent).addWidget(self.notice)

    def test_only_missing_permissions_have_recovery_actions(self):
        self.assertFalse(self.notice.rows["screen_recording"].isHidden())
        self.assertTrue(self.notice.rows["accessibility"].isHidden())
        with patch("wordcel.gui.macos_permissions.open_privacy_settings") as open_settings:
            self.notice.rows["screen_recording"].findChild(QPushButton).click()
        open_settings.assert_called_once_with("screen_recording")

    def test_returning_from_settings_rechecks_without_requesting_permission(self):
        self.parent.show()
        self.states["screen_recording"] = True
        self.notice.application_state_changed(Qt.ApplicationState.ApplicationActive)
        self.assertTrue(self.notice.isHidden())
        self.states["accessibility"] = False
        self.notice.application_state_changed(Qt.ApplicationState.ApplicationActive)
        self.assertFalse(self.notice.isHidden())
        self.assertFalse(self.notice.rows["accessibility"].isHidden())

    def test_showing_feature_page_refreshes_previously_hidden_notice(self):
        self.states["screen_recording"] = True
        self.notice.refresh()
        self.assertTrue(self.notice.isHidden())
        self.states["screen_recording"] = False
        self.parent.show()
        self.app.processEvents()
        self.assertFalse(self.notice.isHidden())
