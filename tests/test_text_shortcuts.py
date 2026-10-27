import sys
import unittest
from unittest.mock import Mock, patch

from pynput.keyboard import GlobalHotKeys
from wordcel.gui.text_shortcuts import TextHotKeys


class ShortcutUpdateTests(unittest.TestCase):
    def test_switch_discards_held_chord_and_uses_new_binding(self):
        from pynput.keyboard import Key, KeyCode
        old, new = Mock(), Mock()
        listener = TextHotKeys({"<ctrl>+a": old})
        listener._on_press(Key.ctrl)
        listener.update_bindings({"<ctrl>+b": new})
        listener._on_press(KeyCode.from_char("a"))
        listener._on_press(KeyCode.from_char("b"))
        old.assert_not_called()
        new.assert_not_called()
        listener._on_release(KeyCode.from_char("b"))
        listener._on_press(Key.ctrl)
        listener._on_press(KeyCode.from_char("b"))
        new.assert_called_once_with()
        listener.update_bindings({})
        self.assertEqual(listener._hotkeys, [])

    def test_unchanged_bindings_preserve_held_modifiers(self):
        from pynput.keyboard import Key, KeyCode
        callback = Mock()
        bindings = {"<ctrl>+a": callback}
        listener = TextHotKeys(bindings)
        listener._on_press(Key.ctrl)
        listener.update_bindings(bindings)
        listener._on_press(KeyCode.from_char("a"))
        callback.assert_called_once_with()


@unittest.skipUnless(sys.platform == "win32", "Windows key propagation")
class ShortcutPropagationTests(unittest.TestCase):
    def test_switch_keeps_consuming_release_of_old_shortcut(self):
        listener = TextHotKeys({"<ctrl>+a": Mock()})
        listener._message_loop = Mock()
        listener.suppress_event = Mock()
        listener._key_state = Mock(return_value=0x8000)
        with patch.object(GlobalHotKeys, "_convert", return_value=(0x100, 0x41)):
            listener._convert(0, 0x100, None)
        listener.update_bindings({"<ctrl>+b": Mock()})
        with patch.object(GlobalHotKeys, "_convert", return_value=(0x101, 0x41)):
            listener._convert(0, 0x101, None)
        self.assertEqual(listener.suppress_event.call_count, 2)
    def test_selection_shortcut_is_dispatched_without_replacing_source_selection(self):
        listener = TextHotKeys({"<ctrl>+<alt>+s": Mock()})
        listener._message_loop = Mock()
        listener.suppress_event = Mock()
        listener._key_state = Mock(return_value=0x8000)
        with patch.object(GlobalHotKeys, "_convert", return_value=(0x100, 0x53)):
            listener._convert(0, 0x100, None)
        listener._message_loop.post.assert_called_once_with(listener._WM_PROCESS, 0x100, 0x53)
        listener.suppress_event.assert_called_once()
        listener._key_state.return_value = 0
        with patch.object(GlobalHotKeys, "_convert", return_value=(0x101, 0x53)):
            listener._convert(0, 0x101, None)
        self.assertEqual(listener.suppress_event.call_count, 2)
        listener.suppress_event.reset_mock()
        with patch.object(GlobalHotKeys, "_convert", return_value=(0x100, 0x53)):
            listener._convert(0, 0x100, None)
        listener.suppress_event.assert_not_called()

    def test_other_keys_pass_through_while_modifiers_are_held(self):
        listener = TextHotKeys({"<ctrl>+<shift>+d": Mock()})
        listener._message_loop = Mock()
        listener.suppress_event = Mock()
        listener._key_state = Mock(return_value=0x8000)
        with patch.object(GlobalHotKeys, "_convert", return_value=(0x100, 0x43)):
            self.assertEqual(listener._convert(0, 0x100, None), (0x100, 0x43))
        listener.suppress_event.assert_not_called()
        listener._message_loop.post.assert_not_called()
