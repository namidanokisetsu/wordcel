"""Shared rendering defaults; persisted preferences live in Qt profiles."""
from dataclasses import dataclass
import os
import sys

APP_NAME = "Meikipop"

# Xwayland permits pointer-anchored popup placement.
if sys.platform.startswith("linux") and os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
    os.environ["QT_QPA_PLATFORM"] = "xcb"


@dataclass
class Config:
    activation_bindings: str = "shift,middle"
    max_lookup_length: int = 25
    audio_volume: int = 80
    theme_name: str = "Dark"
    font_family: str = ""
    font_size_definitions: int = 14
    font_size_sentence: int = 14
    font_size_header: int = 18
    pitch_colors: bool = True
    kanji_stroke_order: bool = True
    color_background: str = "#000000"
    color_foreground: str = "#FFFFFF"
    color_highlight_word: str = "#FFFFFF"
    color_highlight_reading: str = "#B8B8B8"
    background_opacity: int = 250
    popup_position_mode: str = "visual_novel_mode"


config = Config()
