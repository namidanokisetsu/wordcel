"""Static settings groups, with optional disclosure for long inventories."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFormLayout, QLabel, QToolButton, QVBoxLayout, QWidget


def align_form_columns(*forms):
    labels = [item.widget() for form in forms for row in range(form.rowCount())
              if (item := form.itemAt(row, QFormLayout.ItemRole.LabelRole)) is not None and item.widget()]
    width = max((label.sizeHint().width() for label in labels), default=0)
    for label in labels:
        label.setMinimumWidth(width)


class SettingsSection(QWidget):
    def __init__(self, title, content, *, collapsible=False):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.toggle = QToolButton()
        self.toggle.setText(title)
        self.toggle.setCheckable(True)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.ArrowType.RightArrow)
        layout.addWidget(self.toggle)
        layout.addWidget(content)
        content.hide()
        self.toggle.toggled.connect(content.setVisible)
        self.toggle.toggled.connect(lambda opened: self.toggle.setArrowType(
            Qt.ArrowType.DownArrow if opened else Qt.ArrowType.RightArrow))
        if not collapsible:
            self.toggle.setChecked(True)
            self.toggle.hide()
            heading = QLabel(title)
            font = heading.font()
            font.setBold(True)
            heading.setFont(font)
            layout.insertWidget(0, heading)


class StatusLabel(QLabel):
    def __init__(self):
        super().__init__()
        self.hide()

    def setText(self, text):
        super().setText(text)
        self.setVisible(bool(text))

    def clear(self):
        self.setText("")
