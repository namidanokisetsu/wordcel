"""Keep macOS input listeners out of Carbon's main-thread-only layout API."""
import sys

from pynput import keyboard


class MacListenerMixin:
    def _run(self):
        if sys.platform == "darwin":
            from pynput._util.darwin import ListenerMixin
            # pynput 1.8.2 reads characters from Quartz events. Its unused
            # keycode_context still calls TISGetInputSourceProperty off-thread.
            return ListenerMixin._run(self)
        return super()._run()

    def start(self):
        from wordcel.utils.macos import require_input_monitoring_permission
        require_input_monitoring_permission()
        if sys.platform == "darwin":
            if self.suppress or self._intercept is not None:
                from wordcel.utils.macos import require_accessibility_permission
                require_accessibility_permission()
            from pynput._util.darwin import HIServices
            # PyObjC's lazy symbol cache is not thread-safe. Keyboard and mouse
            # listeners both use this function as soon as their threads start.
            HIServices.AXIsProcessTrusted()
        result = super().start()
        if sys.platform == "darwin":
            self._condition.acquire()
            try:
                if self.is_alive():
                    self._condition.wait_for(
                        lambda: (self._ready and getattr(self, "_loop", None) is not None)
                        or not self.is_alive(), timeout=1)
                ready = (self._ready and getattr(self, "_loop", None) is not None
                         and self.is_alive())
            finally:
                self._condition.release()
            if not ready:
                self.stop()
                self.join(timeout=1)
                raise OSError("Global input listener stopped before it became ready.")
        return result

    def canonical(self, key):
        if sys.platform == "darwin":
            from pynput._util.darwin_vks import SYMBOLS
            typed = getattr(key, "char", "") or ""
            if len(typed) == 1 and typed.isascii() and typed.isalpha():
                return super().canonical(key)
            char = SYMBOLS.get(getattr(key, "vk", None), "")
            if len(char) == 1 and char.isascii() and char.isalpha():
                return keyboard.KeyCode.from_char(char.lower())
        return super().canonical(key)


class KeyboardListener(MacListenerMixin, keyboard.Listener):
    pass
