"""Global lookup shortcuts and their profile-bound listener lifecycle."""
import sys

from PyQt6.QtCore import Qt

from wordcel.gui.profile_preferences import default_text_shortcut


class LookupShortcuts:
    def __init__(self, window):
        self.window = window
        self.restored = False
        self.failed = set()
        self._listeners = dict.fromkeys(("cycle", "hotkey", "copy", "hover", "translation"))
        self._callbacks = {name: getattr(window, name + "_requested").emit for name in
                           ("hotkey", "translation", "hover_toggle", "copy", "next_profile", "previous_profile")}

    def apply(self, name, value, preset=None):
        from wordcel.gui.text_shortcuts import validate_shortcuts
        window = self.window
        prefix = f"profiles/{window.active_profile}/"
        key = "hotkey" if name == "hotkey" else name + "_hotkey"
        validate_shortcuts([value, *(window.settings.value(
            prefix + other, default_text_shortcut() if name != "hotkey" and other == "hotkey" else "")
            for other in ("hotkey", "translation_hotkey", "hover_hotkey", "copy_hotkey") if other != key)])
        callback = self._callbacks["hover_toggle" if name == "hover" else name]
        available = name != "translation" or window.translation_available()
        bindings = {value: callback} if value and available else {}
        warning = self._update_listener(name, bindings)
        window.settings.setValue(prefix + key, value)
        if preset is not None:
            window.settings.setValue(prefix + key + "_preset", preset)
        return warning

    def restore(self, explicit=None):
        self.restored = True
        settings = self.window.settings
        prefix = f"profiles/{self.window.active_profile}/"
        binding = explicit if explicit is not None else settings.value(prefix + "hotkey", default_text_shortcut())
        self.apply("hotkey", binding)
        for name in ("translation", "hover", "copy"):
            self.apply(name, settings.value(prefix + name + "_hotkey", ""))
        self.restore_cycle()

    def restore_cycle(self):
        from wordcel.gui.text_shortcuts import validate_shortcuts
        settings = self.window.settings
        names = ("next_profile", "previous_profile")
        values = [settings.value(name + "_hotkey", "") for name in names]
        validate_shortcuts([*values, *(settings.value(f"profiles/{self.window.active_profile}/" + key, "")
                                      for key in ("hotkey", "translation_hotkey", "hover_hotkey", "copy_hotkey"))])
        bindings = {value: self._callbacks[name] for value, name in zip(values, names) if value}
        self._update_listener("cycle", bindings)

    def _update_listener(self, name, bindings):
        from wordcel.gui.text_shortcuts import TextHotKeys
        from wordcel.utils.macos import AccessibilityPermissionError, InputMonitoringPermissionError
        previous = self._listeners[name]
        if previous is not None:
            previous.update_bindings(bindings)
            if not bindings:
                previous.stop()
                self._listeners[name] = None
            self.failed.discard(name)
            return ""
        if bindings:
            listener = TextHotKeys(bindings)
            try:
                listener.start()
            except (InputMonitoringPermissionError, AccessibilityPermissionError, OSError) as error:
                self.failed.add(name)
                self.window.show_message(str(error))
                return str(error)
            self._listeners[name] = listener
            self.failed.discard(name)
        return ""

    def application_state_changed(self, state):
        if (state == Qt.ApplicationState.ApplicationActive and self.restored
                and not self.window._shutting_down and self.failed):
            from wordcel.utils.macos import privacy_permission_granted
            if sys.platform == "darwin" and not privacy_permission_granted("input_monitoring"):
                return
            self.restore()
            if self.failed:
                self.window.show_message("Restart Wordcel to enable global shortcuts.")

    def shutdown(self):
        for name, listener in self._listeners.items():
            if listener is not None:
                listener.stop()
                self._listeners[name] = None
