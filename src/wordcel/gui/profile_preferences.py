"""Small profile preferences shared by settings and lookup surfaces."""
import sys


def default_text_shortcut():
    control = "<cmd>" if sys.platform == "darwin" else "<ctrl>"
    return control + "+<shift>+d"


def shortcut_preset():
    return "Ctrl+Shift+D"


def audio_autoplay_mode(settings, profile):
    return settings.value(f"profiles/{profile}/audio_autoplay_mode", "pin")
