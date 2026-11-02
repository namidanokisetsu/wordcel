"""Compatibility helpers for the one-time shared-preferences migration.

Profiles used to resolve a group of values from ``defaults/`` unless an
``overrides/<group>`` flag was set. The current settings format stores the
effective value in every profile. ``PreferenceSettings`` remains as a thin
adapter for callers that still accept the old wrapper while migration code can
be removed independently of the GUI cleanup.
"""

from copy import deepcopy
from pathlib import Path


GROUPS = {
    "appearance": ("theme_name", "font_family", "font_size_header", "font_size_definitions", "font_size_sentence",
                   "furigana_scale", "scale", "background_opacity", "color_background", "color_foreground",
                   "color_highlight_word", "color_highlight_reading", "custom/", "buttons/", "pitch_colors",
                   "kanji_stroke_order", "headword_furigana", "definition_furigana", "compact_preview",
                   "preview_frequency", "preview_pitch", "preview_grammar", "preview_definitions",
                   "pinned_frequency", "pinned_pitch", "pinned_grammar", "pinned_sentence"),
    "shortcuts": ("hotkey", "hotkey_preset", "translation_hotkey", "translation_hotkey_preset",
                  "copy_hotkey", "copy_hotkey_preset", "hover_hotkey", "hover_hotkey_preset", "scan_bindings",
                  "block_scan_keys", "pin_shortcut", "pin_shortcut_preset", "pin_gesture", "popup/",
                  "anki/shortcut", "anki/shortcut_preset", "side_button_scrolling"),
    "popup": ("close_on_cursor_leave", "cursor_close_margin", "snap_scrolling", "translation_side_by_side"),
    "audio": ("audio_volume", "audio_autoplay_mode"),
}

MIGRATION_VERSION = 2


def group_for(key):
    """Return the old shared-preference group for a profile-relative key."""
    return next((group for group, keys in GROUPS.items()
                 if any(key.startswith(item) if item.endswith("/") else key == item for item in keys)), None)


def raw_settings(settings):
    """Return the underlying QSettings object for either settings API."""
    return settings.raw if isinstance(settings, PreferenceSettings) else settings


class PreferenceSettings:
    """Transparent QSettings compatibility view.

    The old class redirected profile reads and writes to shared defaults. It
    deliberately no longer does that: every profile is independent after the
    migration. ``editing_global`` is retained as a harmless compatibility
    attribute until the settings UI stops assigning it.
    """

    def __init__(self, settings):
        self.raw = raw_settings(settings)
        self.editing_global = None

    def __getattr__(self, name):
        return getattr(self.raw, name)

    def resolve(self, key):
        return key

    def value(self, key, *args, **kwargs):
        return self.raw.value(key, *args, **kwargs)

    def contains(self, key):
        return self.raw.contains(key)

    def setValue(self, key, value):
        self.raw.setValue(key, value)

    def remove(self, key):
        self.raw.remove(key)


def overridden(settings, profile, group):
    """Read legacy metadata for compatibility with older callers.

    This value has no effect on reads after migration and is removed by
    :func:`migrate_defaults`.
    """
    return raw_settings(settings).value(f"profiles/{profile}/overrides/{group}", False, bool)


def set_override(settings, profile, group, enabled):
    """Write legacy metadata for old callers without changing runtime reads."""
    raw_settings(settings).setValue(f"profiles/{profile}/overrides/{group}", bool(enabled))


def _profile_ids(settings):
    from wordcel.config.profiles import profile_ids
    return profile_ids(settings)


def _backup(settings):
    """Keep a local copy of the pre-migration settings, if possible."""
    from PyQt6.QtCore import QSettings

    filename = settings.fileName()
    if not filename:
        return None
    path = Path(filename)
    backup_path = path.with_name(path.name + ".inheritance-backup.ini")
    if backup_path.exists():
        return backup_path
    try:
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        backup = QSettings(str(backup_path), QSettings.Format.IniFormat)
        for key in settings.allKeys():
            backup.setValue(key, deepcopy(settings.value(key)))
        backup.sync()
        if backup.status() != QSettings.Status.NoError:
            raise OSError("Could not back up settings.")
    except (OSError, RuntimeError):
        # The profile migration has a second backup path. Do not make an
        # otherwise valid in-memory migration unusable for registry-backed or
        # test settings that cannot expose a file.
        return None
    return backup_path


def _sync(settings):
    from PyQt6.QtCore import QSettings

    settings.sync()
    if settings.status() != QSettings.Status.NoError:
        raise OSError("Could not save migrated settings.")


def _profile_relative_keys(settings, identity):
    prefix = f"profiles/{identity}/"
    return {key[len(prefix):] for key in settings.allKeys() if key.startswith(prefix)}


def _legacy_snapshot(settings, identity, group):
    """Build the effective old value map for one profile and one group."""
    prefix = f"profiles/{identity}/"
    own = {key[len(prefix):]: settings.value(key)
           for key in settings.allKeys()
           if key.startswith(prefix) and group_for(key[len(prefix):]) == group}
    defaults_prefix = f"defaults/{group}/"
    defaults = {key[len(defaults_prefix):]: settings.value(key)
                for key in settings.allKeys() if key.startswith(defaults_prefix)}
    marker = f"profiles/{identity}/overrides/{group}"
    # With no shared-defaults data, profile values were already independent.
    # When the marker is absent, retain explicit profile values as well; only
    # an explicit false marker means that stale local values are inactive.
    inheritance_present = settings.value("defaults_version", 0, int) >= 1 or bool(defaults)
    if not inheritance_present:
        return own
    if settings.value(marker, False, bool):
        return own
    return defaults


def _effective_snapshots(settings, identities):
    return {identity: {group: _legacy_snapshot(settings, identity, group)
                       for group in GROUPS}
            for identity in identities}


def migrate_defaults(settings):
    """Materialize legacy effective preferences into independent profiles.

    The operation is versioned and idempotent. Values are planned before any
    writes, explicit false/empty values are copied using ``allKeys`` and
    nested keys are included through :func:`group_for`. The completion marker
    is written only as part of a successful sync; a backup remains in local
    storage for recovery.
    """
    settings = raw_settings(settings)
    if settings.value("defaults_version", 0, int) >= MIGRATION_VERSION:
        return False
    _backup(settings)
    identities = _profile_ids(settings)
    snapshots = _effective_snapshots(settings, identities)
    old_keys = set(settings.allKeys())
    original = {key: deepcopy(settings.value(key)) for key in old_keys}
    previous_version = settings.value("defaults_version") if settings.contains("defaults_version") else None

    # Clear only old shared data and each profile's old group values. Profile
    # identity, connection refs, dictionaries, and feature flags are outside
    # the inheritance groups and are untouched.
    for key in old_keys:
        if key.startswith("defaults/") or key == "defaults_version" or "/overrides/" in key:
            settings.remove(key)
    for identity, groups in snapshots.items():
        prefix = f"profiles/{identity}/"
        for key in list(settings.allKeys()):
            relative = key[len(prefix):] if key.startswith(prefix) else ""
            if relative and group_for(relative):
                settings.remove(key)
        for values in groups.values():
            for relative, value in values.items():
                settings.setValue(prefix + relative, deepcopy(value))
    settings.setValue("defaults_version", MIGRATION_VERSION)
    try:
        _sync(settings)
    except Exception:
        # Restore the live object as well as the on-disk backup so retrying
        # after a transient sync failure recomputes the same effective values.
        for key in list(settings.allKeys()):
            if key not in original:
                settings.remove(key)
        for key, value in original.items():
            settings.setValue(key, deepcopy(value))
        if previous_version is None:
            settings.remove("defaults_version")
        else:
            settings.setValue("defaults_version", previous_version)
        raise
    return True
