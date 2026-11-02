import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PyQt6.QtCore import QSettings

from wordcel.gui.lookup_shortcuts import LookupShortcuts


class LookupShortcutTests(unittest.TestCase):
    def test_profile_restore_reuses_all_listeners_and_shutdown_stops_each_once(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = QSettings(str(Path(directory) / "settings.ini"), QSettings.Format.IniFormat)
            window = SimpleNamespace(settings=settings, active_profile="ja", translation_available=Mock(return_value=True),
                                     **{name + "_requested": Mock() for name in
                                        ("hotkey", "translation", "hover_toggle", "copy", "next_profile", "previous_profile")})
            for profile, modifier in (("ja", "shift"), ("tr", "alt")):
                for name, key in (("hotkey", "d"), ("translation", "t"), ("hover", "h"), ("copy", "x")):
                    setting = "hotkey" if name == "hotkey" else name + "_hotkey"
                    settings.setValue(f"profiles/{profile}/{setting}", f"<ctrl>+<{modifier}>+{key}")
            settings.setValue("next_profile_hotkey", "<ctrl>+<page_down>")
            settings.setValue("previous_profile_hotkey", "<ctrl>+<page_up>")
            listeners = []

            def create(bindings):
                listener = Mock()
                listeners.append(listener)
                return listener

            with patch("wordcel.gui.text_shortcuts.TextHotKeys", side_effect=create) as factory:
                shortcuts = LookupShortcuts(window)
                factory.assert_not_called()
                shortcuts.restore()
                self.assertEqual(factory.call_count, 5)
                window.active_profile = "tr"
                shortcuts.restore()
                self.assertEqual(factory.call_count, 5)
                for listener in listeners:
                    listener.start.assert_called_once_with()
                    listener.update_bindings.assert_called_once()
                    listener.stop.assert_not_called()
                    listener.join.assert_not_called()
                    for callback in listener.update_bindings.call_args.args[0].values():
                        callback()
                for name in ("hotkey", "translation", "hover_toggle", "copy", "next_profile", "previous_profile"):
                    getattr(window, name + "_requested").emit.assert_called_once_with()
                self.assertEqual(tuple(shortcuts._listeners["hotkey"].update_bindings.call_args.args[0]),
                                 ("<ctrl>+<alt>+d",))
                shortcuts.shutdown()
                shortcuts.shutdown()
                for listener in listeners:
                    listener.stop.assert_called_once_with()
                    listener.join.assert_not_called()
                self.assertTrue(all(listener is None for listener in shortcuts._listeners.values()))
