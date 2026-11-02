"""Narrow Cocoa event routing for the menu-bar item.

Qt's macOS tray integration can treat a left click as a context-menu click
when a QMenu is attached. The adapter keeps QSystemTrayIcon for artwork and
geometry, while routing only clicks inside that item through a local Cocoa
monitor. Other application and menu events remain Qt-owned.
"""
import sys

from PyQt6.QtCore import QObject, QTimer
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QApplication


class MacTrayAdapter(QObject):
    def __init__(self, tray, menu, on_search, parent=None):
        super().__init__(parent)
        self.tray = tray
        self.menu = menu
        self.on_search = on_search
        self._monitor = None
        self._nsevent = None
        self._button_down = None
        self._left_down = None
        self._right_down = None

    def install(self):
        if sys.platform != "darwin" or QApplication.platformName() != "cocoa":
            return False
        try:
            from AppKit import (NSEvent, NSEventMaskLeftMouseDown,
                                NSEventMaskLeftMouseUp, NSEventMaskRightMouseDown,
                                NSEventMaskRightMouseUp, NSLeftMouseDown,
                                NSLeftMouseUp, NSRightMouseDown, NSRightMouseUp)
        except ImportError:
            return False
        mask = (NSEventMaskLeftMouseDown | NSEventMaskLeftMouseUp
                | NSEventMaskRightMouseDown | NSEventMaskRightMouseUp)
        self._nsevent = NSEvent
        self._left_down = NSLeftMouseDown
        self._left_up = NSLeftMouseUp
        self._right_down = NSRightMouseDown
        self._right_up = NSRightMouseUp
        self._button_down = None
        self._monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(mask, self._event)
        return self._monitor is not None

    def _contains_tray(self):
        geometry = self.tray.geometry()
        return not geometry.isNull() and geometry.contains(QCursor.pos())

    @staticmethod
    def _is_status_window(event):
        window = getattr(event, "window", None)
        native_window = window() if callable(window) else window
        if native_window is None:
            return True
        class_name = getattr(native_window, "className", lambda: "")()
        return not class_name or "StatusBar" in str(class_name)

    def _event(self, event):
        event_type = event.type()
        if not self._is_status_window(event):
            return event
        if event_type == self._left_down and self._contains_tray():
            self._button_down = self._left_down
            QTimer.singleShot(0, self.on_search)
            return None
        if event_type == self._right_down and self._contains_tray():
            self._button_down = self._right_down
            point = QCursor.pos()
            QTimer.singleShot(0, lambda: self.menu.popup(point))
            return None
        button_up = {
            self._left_up: self._left_down,
            self._right_up: self._right_down,
        }
        if event_type in button_up and self._button_down == button_up[event_type]:
            self._button_down = None
            return None
        return event

    def shutdown(self):
        if self._monitor is not None and self._nsevent is not None:
            self._nsevent.removeMonitor_(self._monitor)
            self._monitor = None
