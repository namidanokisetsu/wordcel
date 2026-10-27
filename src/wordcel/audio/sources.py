"""Yomitan source descriptors and retained local source order."""
import json
from urllib.parse import urlsplit


SOURCE_LABELS = {
    "jpod101": "JapanesePod101", "language-pod-101": "LanguagePod101", "jisho": "Jisho",
    "lingua-libre": "Lingua Libre", "wiktionary": "Wiktionary",
    "text-to-speech": "System voice (word)", "text-to-speech-reading": "System voice (reading)",
    "custom": "Custom URL", "custom-json": "Custom URL (JSON)",
    "tts": "System voice", "online": "Online pronunciations",
}
ONLINE_TYPES = frozenset(SOURCE_LABELS) - {"tts", "text-to-speech", "text-to-speech-reading"}


def source_type(source):
    return source.get("type", "") if isinstance(source, dict) else source


def source_key(source):
    return json.dumps(source, sort_keys=True) if isinstance(source, dict) else source


def is_local(source):
    return source_type(source).startswith("db:")


def database_path(settings, language):
    return settings.value(f"profiles/{language}/audio_database", "")


def source_order(settings, language):
    saved = settings.value(f"profiles/{language}/audio_priority")
    if saved is not None:
        return saved if isinstance(saved, list) else [saved] if saved else []
    return ["tts", "online"]


def source_label(source):
    kind = source_type(source)
    label = SOURCE_LABELS.get(kind, kind.removeprefix("db:"))
    if isinstance(source, dict) and kind in ("custom", "custom-json"):
        try:
            host = urlsplit(source.get("url", "")).hostname
        except ValueError:
            host = None
        if host:
            label += f" · {host}"
    return label
