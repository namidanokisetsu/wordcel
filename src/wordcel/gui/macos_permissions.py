"""Feature-specific permission recovery without prompting during navigation."""
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from wordcel.utils.macos import open_privacy_settings, privacy_permission_granted


class PermissionNotice(QWidget):
    def __init__(self, features, parent):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.rows = {}
        for feature, explanation in features:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            label = QLabel(explanation)
            label.setWordWrap(True)
            row_layout.addWidget(label, 1)
            button = QPushButton("Open Settings")
            button.clicked.connect(lambda _, feature=feature: open_privacy_settings(feature))
            row_layout.addWidget(button)
            layout.addWidget(row)
            self.rows[feature] = row
        parent.installEventFilter(self)
        QApplication.instance().applicationStateChanged.connect(self.application_state_changed)
        self.refresh()

    def refresh(self):
        missing = False
        for feature, row in self.rows.items():
            denied = not privacy_permission_granted(feature)
            row.setVisible(denied)
            missing |= denied
        self.setVisible(missing)

    def application_state_changed(self, state):
        if state == Qt.ApplicationState.ApplicationActive and self.parentWidget().isVisible():
            self.refresh()

    def eventFilter(self, watched, event):
        if watched is self.parentWidget() and event.type() == QEvent.Type.Show:
            self.refresh()
        return super().eventFilter(watched, event)
