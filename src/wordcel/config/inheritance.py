"""Shared preference groups with retained, independent profile overrides."""
from functools import lru_cache

GROUPS = {
    "appearance": ("theme_name", "font_family", "font_size_header", "font_size_definitions",
                   "font_size_sentence", "furigana_scale", "scale", "background_opacity",
                   "color_background", "color_foreground", "color_highlight_word", "color_highlight_reading",
                   "custom/", "buttons/", "pitch_colors", "kanji_stroke_order", "headword_furigana",
                   "definition_furigana", "compact_preview", "preview_frequency", "preview_pitch",
                   "preview_grammar", "preview_definitions", "pinned_frequency", "pinned_pitch",
                   "pinned_grammar", "pinned_sentence"),
    "shortcuts": ("hotkey", "hotkey_preset", "translation_hotkey", "translation_hotkey_preset",
                  "hover_hotkey", "hover_hotkey_preset", "scan_bindings", "block_scan_keys",
                  "pin_shortcut", "pin_shortcut_preset", "pin_gesture", "popup/",
                  "anki/shortcut", "anki/shortcut_preset", "side_button_scrolling"),
    "popup": ("close_on_cursor_leave", "cursor_close_margin", "snap_scrolling", "translation_side_by_side"),
    "audio": ("audio_volume", "audio_autoplay_mode"),
}


@lru_cache(maxsize=256)
def group_for(key):
    return next((group for group, keys in GROUPS.items()
                 if any(key.startswith(item) if item.endswith("/") else key == item for item in keys)), None)


def raw_settings(settings):
    return settings.raw if isinstance(settings, PreferenceSettings) else settings


def overridden(settings, profile, group):
    return raw_settings(settings).value(f"profiles/{profile}/overrides/{group}", False, bool)


def set_override(settings, profile, group, enabled):
    settings = raw_settings(settings)
    prefix = f"profiles/{profile}/"
    if enabled and not settings.value(prefix + f"overrides/{group}_saved", False, bool):
        # Snapshot only this group. Later global edits must not leak into an override.
        for key in list(settings.allKeys()):
            if key.startswith(prefix) and group_for(key[len(prefix):]) == group:
                settings.remove(key)
        source = f"defaults/{group}/"
        for key in settings.allKeys():
            if key.startswith(source):
                settings.setValue(prefix + key[len(source):], settings.value(key))
        settings.setValue(prefix + f"overrides/{group}_saved", True)
    settings.setValue(prefix + "overrides/" + group, enabled)


def migrate_defaults(settings):
    settings = raw_settings(settings)
    if settings.value("defaults_version", 0, int) >= 1:
        return
    from wordcel.config.profiles import profile_ids
    identities = profile_ids(settings)
    active = settings.value("profile", "")
    source = active if active in identities else next(iter(identities), "")
    snapshots = {identity: {key[len(f"profiles/{identity}/"):]: settings.value(key)
                           for key in settings.allKeys() if key.startswith(f"profiles/{identity}/")}
                 for identity in identities}
    for group in GROUPS:
        baseline = {key: value for key, value in snapshots.get(source, {}).items() if group_for(key) == group}
        for key, value in baseline.items():
            settings.setValue(f"defaults/{group}/{key}", value)
        for identity, values in snapshots.items():
            own = {key: value for key, value in values.items() if group_for(key) == group}
            settings.setValue(f"profiles/{identity}/overrides/{group}", own != baseline)
            settings.setValue(f"profiles/{identity}/overrides/{group}_saved", own != baseline)
    settings.setValue("defaults_version", 1)
    settings.sync()


class PreferenceSettings:
    """QSettings view; resolve shared reads without materializing inherited copies.

    Reads and writes use the effective scope; inactive custom values remain intact.
    Global editors force only their selected group to the shared scope.
    """

    def __init__(self, settings):
        self.raw = raw_settings(settings)
        self.editing_global = None

    def __getattr__(self, name):
        return getattr(self.raw, name)

    def resolve(self, key):
        parts = key.split("/", 2)
        if len(parts) != 3 or parts[0] != "profiles":
            return key
        _, profile, relative = parts
        group = group_for(relative)
        if group and (self.editing_global == group or
                      self.editing_global == "popup_all" and group in ("appearance", "popup") or
                      not overridden(self.raw, profile, group)):
            return f"defaults/{group}/{relative}"
        return key

    def value(self, key, *args, **kwargs):
        return self.raw.value(self.resolve(key), *args, **kwargs)

    def contains(self, key):
        return self.raw.contains(self.resolve(key))

    def setValue(self, key, value):
        self.raw.setValue(self.resolve(key), value)

    def remove(self, key):
        self.raw.remove(self.resolve(key))
