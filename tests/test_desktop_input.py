"""Shared input suppression and independently configurable shortcuts."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from wordcel.gui.desktop_input import DesktopInput


class DesktopInputTests(unittest.TestCase):
    def test_source_wheel_and_page_keys_notify_without_consuming_input(self):
        with patch("wordcel.gui.desktop_input.KeyboardListener"), patch("pynput.mouse.Listener"):
            inputs = DesktopInput("shift", "", "", 400)
        changed = Mock()
        inputs.source_changed.connect(changed)
        try:
            inputs.visible.set()
            inputs.popup_handle = 123
            with patch("wordcel.utils.window_focus.route_popup_wheel", return_value=True):
                self.assertFalse(inputs.filter_mouse(0x20A, SimpleNamespace()))
                changed.assert_not_called()
            inputs.clicks.suppress_event.reset_mock()
            with patch("wordcel.utils.window_focus.route_popup_wheel", return_value=False):
                self.assertTrue(inputs.filter_mouse(0x20A, SimpleNamespace()))
                changed.assert_called_once()
                inputs.clicks.suppress_event.assert_not_called()
            for key in (0x22, 0x27, 0x20, 0x41):
                inputs.filter_key(0x100, SimpleNamespace(vkCode=key))
            self.assertEqual(changed.call_count, 5)
            inputs.filter_key(0x100, SimpleNamespace(vkCode=0x10))
            inputs.filter_key(0x101, SimpleNamespace(vkCode=0x22))
            inputs.popup_controls_active.set()
            inputs.filter_key(0x100, SimpleNamespace(vkCode=0x22))
            self.assertEqual(changed.call_count, 5)
            inputs.keys.suppress_event.assert_not_called()
        finally:
            inputs.shutdown()

    def test_escape_is_suppressed_only_for_visible_popup_including_key_up(self):
        with patch("wordcel.gui.desktop_input.KeyboardListener"), patch("wordcel.gui.desktop_input.TextHotKeys"), patch("pynput.mouse.Listener"):
            inputs = DesktopInput("shift,middle", "<ctrl>+<alt>+l", "<ctrl>+<alt>+d", 400)
        try:
            inputs.filter_key(0x100, SimpleNamespace(vkCode=27))
            inputs.keys.suppress_event.assert_not_called()
            inputs.visible.set()
            inputs.filter_key(0x100, SimpleNamespace(vkCode=27))
            inputs.visible.clear()
            inputs.filter_key(0x101, SimpleNamespace(vkCode=27))
            self.assertEqual(inputs.keys.suppress_event.call_count, 2)
            inputs.filter_key(0x100, SimpleNamespace(vkCode=27))
            self.assertEqual(inputs.keys.suppress_event.call_count, 2)
        finally:
            inputs.shutdown()

    def test_text_shortcuts_can_be_disabled_individually(self):
        with patch("wordcel.gui.desktop_input.KeyboardListener"), patch("wordcel.gui.desktop_input.TextHotKeys") as shortcuts, patch("pynput.mouse.Listener"):
            inputs = DesktopInput("shift", "", "", 400)
            try:
                shortcuts.assert_not_called()
                inputs.set_shortcuts("", "<ctrl>+k")
                self.assertEqual(list(shortcuts.call_args.args[0]), ["<ctrl>+k"])
                inputs.set_shortcuts("", "")
                self.assertIsNone(inputs.shortcuts)
            finally:
                inputs.shutdown()

    def test_escape_blocked_by_a_qt_popup_is_passed_through(self):
        with patch("wordcel.gui.desktop_input.KeyboardListener"), patch("wordcel.gui.desktop_input.TextHotKeys"), patch("pynput.mouse.Listener"):
            inputs = DesktopInput("shift", "", "", 400)
        try:
            inputs.visible.set()
            inputs.escape_dismiss_blocked.set()
            inputs.filter_key(0x100, SimpleNamespace(vkCode=27))
            inputs.filter_key(0x101, SimpleNamespace(vkCode=27))
            inputs.keys.suppress_event.assert_not_called()
        finally:
            inputs.shutdown()
