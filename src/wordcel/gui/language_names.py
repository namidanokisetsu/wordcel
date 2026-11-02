"""Display names for languages supported by the lookup surfaces."""
import re

from PyQt6.QtCore import QLocale

from wordcel.language.support import AVAILABLE_LANGUAGES, EXTRA_NAMES


LANGUAGE_NAMES = {
    "ja": "日本語", "tr": "Türkçe", "en": "English", "de": "Deutsch",
    "fr": "Français", "es": "Español", "ru": "Русский", "zh": "中文",
    "ko": "한국어", "ar": "العربية", "it": "Italiano", "pt": "Português",
    "uk": "Українська", "nl": "Nederlands", "pl": "Polski",
}
for _locale in QLocale.matchingLocales(QLocale.Language.AnyLanguage, QLocale.Script.AnyScript, QLocale.Country.AnyCountry):
    _code = _locale.name().split("_")[0]
    if re.fullmatch(r"[a-z]{2,3}", _code):
        LANGUAGE_NAMES.setdefault(_code, QLocale.languageToString(_locale.language()))
LANGUAGE_NAMES.update(EXTRA_NAMES)
LANGUAGE_NAMES = {code: LANGUAGE_NAMES.get(code, code) for code in sorted(AVAILABLE_LANGUAGES)}
LANGUAGE_NAMES.update({"zh-hant": "中文（繁體）", "zh-tw": "中文（台灣）", "zh-hk": "中文（香港）"})


def language_name(code):
    return LANGUAGE_NAMES.get(code, code)
