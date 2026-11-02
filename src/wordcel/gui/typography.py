"""Bundled fonts and explicit language fallbacks for shared text metrics."""
from functools import lru_cache
import logging
from pathlib import Path
import sys
from PyQt6.QtGui import QFont, QFontDatabase


@lru_cache(maxsize=1)
def register_fonts():
    root = Path(__file__).resolve().parents[1] / "resources" / "fonts"
    for name in ("NotoSans.ttf", "NotoSans-Italic.ttf", "NotoSansJP.ttf"):
        if QFontDatabase.addApplicationFont(str(root / name)) < 0:
            logging.getLogger(__name__).warning("Could not load bundled font %s", name)


def document_families(language):
    register_fonts()
    if language == "ja":
        candidates = (("Yu Gothic UI", "Meiryo", "Noto Sans CJK JP", "Noto Sans JP") if sys.platform == "win32"
                      else ("Hiragino Sans", "Hiragino Kaku Gothic ProN", "Noto Sans CJK JP", "Noto Sans JP")
                      if sys.platform == "darwin" else ("Noto Sans CJK JP", "Noto Sans JP", "IPAexGothic"))
    else:
        candidates = ("Segoe UI",) if sys.platform == "win32" else ("Helvetica Neue",) if sys.platform == "darwin" else ("Noto Sans", "DejaVu Sans")
    candidates = ("Noto Sans JP", *candidates) if language == "ja" else ("Noto Sans", "Noto Sans JP", *candidates)
    available = set(QFontDatabase.families())
    return tuple(dict.fromkeys(family for family in candidates if family in available))


def default_family(language):
    families = document_families(language)
    return families[0] if families else QFont().family()


def document_font(family, size, language):
    font = QFont()
    if family:
        font.setFamilies(list(dict.fromkeys((family, *document_families(language)))))
    font.setPixelSize(size)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias | QFont.StyleStrategy.PreferOutline)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return font
