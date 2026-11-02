"""Named settings profiles and explicit, data-preserving reset operations."""

from copy import deepcopy
import json
import sys
from uuid import uuid4


PROFILE_VERSION = 2
PROFILE_KEYS = (
    "hotkey", "hotkey_preset", "translation_hotkey", "translation_hotkey_preset",
    "copy_hotkey", "copy_hotkey_preset", "hover_hotkey", "hover_hotkey_preset",
    "translation_side_by_side", "close_on_cursor_leave", "cursor_close_margin",
)
CONNECTION_KEYS = {"anki": "anki/connection", "translation": "translation_connection"}


def profile_language(settings, identity):
    return settings.value(f"profiles/{identity}/language", identity or "")


def profile_name(settings, identity):
    from wordcel.gui.quick_lookup import language_name
    return settings.value(f"profiles/{identity}/name", "") or language_name(profile_language(settings, identity))


def profile_ids(settings):
    settings.beginGroup("profiles")
    try:
        available = settings.childGroups()
    finally:
        settings.endGroup()
    order = settings.value("profile_order", [], type=list)
    return tuple(dict.fromkeys([*(item for item in order if item in available), *available]))


def languages(settings):
    return tuple(dict.fromkeys(profile_language(settings, identity) for identity in profile_ids(settings)))


def dictionary_preferences(settings, identity):
    prefix = f"profiles/{identity}/dictionaries/"
    if not settings.contains(prefix + "order"):
        return None
    return {key: settings.value(prefix + key, [], type=list) for key in ("order", "disabled")}


def connection(settings, kind, identity):
    prefix = f"connections/{kind}/{identity}/"
    return {key[len(prefix):]: settings.value(key) for key in settings.allKeys() if key.startswith(prefix)}


def save_connection(settings, kind, values):
    """Return a reusable connection record for a matching value set."""
    settings.beginGroup("connections/" + kind)
    try:
        identities = settings.childGroups()
    finally:
        settings.endGroup()
    for identity in identities:
        if connection(settings, kind, identity) == values:
            return identity
    return create_connection(settings, kind, values)


def create_connection(settings, kind, values):
    """Create a fresh mutable connection record without deduplication."""
    identity = uuid4().hex
    for key, value in values.items():
        settings.setValue(f"connections/{kind}/{identity}/{key}", deepcopy(value))
    return identity


def clone_connection(settings, kind, identity):
    """Clone one connection record and return its new identity."""
    values = connection(settings, kind, identity)
    if not values:
        return identity
    return create_connection(settings, kind, values)


def ensure_private_connection(settings, profile, kind):
    """Detach a profile from a connection shared by another profile.

    Editing a connection is mutable state. This helper is intentionally
    explicit so feature-owned editors can call it immediately before saving a
    record while preserving the profile's current assignment.
    """
    key = CONNECTION_KEYS[kind]
    prefix = f"profiles/{profile}/"
    identity = settings.value(prefix + key, "")
    if not identity or not connection(settings, kind, identity):
        return identity
    references = [candidate for candidate in profile_ids(settings)
                  if settings.value(f"profiles/{candidate}/{key}", "") == identity]
    if len(references) <= 1:
        return identity
    identity = clone_connection(settings, kind, identity)
    settings.setValue(prefix + key, identity)
    return identity


def _sync(settings):
    from PyQt6.QtCore import QSettings

    settings.sync()
    if settings.status() != QSettings.Status.NoError:
        raise OSError("Could not save profile settings.")


def _backup(settings):
    from pathlib import Path
    from PyQt6.QtCore import QSettings

    filename = settings.fileName()
    if not filename:
        return None
    path = Path(filename)
    backup_path = path.with_name(path.name + ".profiles-backup.ini")
    if settings.format() == QSettings.Format.NativeFormat and __import__("sys").platform == "win32":
        from wordcel.utils.paths import paths
        backup_path = Path(paths.data_dir) / "settings-profiles-backup.ini"
    if backup_path.exists():
        return backup_path
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    backup = QSettings(str(backup_path), QSettings.Format.IniFormat)
    for key in settings.allKeys():
        backup.setValue(key, deepcopy(settings.value(key)))
    backup.sync()
    if backup.status() != QSettings.Status.NoError:
        raise OSError("Could not back up settings.")
    return backup_path


def migrate(settings, directory=None):
    """Migrate legacy language settings while preserving a local backup."""
    if settings.value("profiles_version", 0, int) >= PROFILE_VERSION:
        return False
    original = {key: deepcopy(settings.value(key)) for key in settings.allKeys()}
    _backup(settings)
    from wordcel.dictionary.library import Library
    from wordcel.dictionary.translation import load_profile_settings, save_profile_settings

    library = Library(directory)
    try:
        defaults = {"order": [meta["resource_id"] for _, meta, _ in library.packs],
                    "disabled": [meta["resource_id"] for _, meta, _ in library.packs if not meta["enabled"]]}
        title_ids = {meta["title"]: meta["resource_id"] for _, meta, _ in library.packs}
        imported = {meta["language"] for _, meta, _ in library.packs}
    finally:
        library.close()
    from wordcel.language.profiles import default_partner

    current = settings.value("profile", "")
    removed = set(settings.value("removed_profiles", [], type=list))
    existing = set(profile_ids(settings))
    for language in (imported | ({current} if current else set())) - removed - existing:
        settings.setValue(f"profiles/{language}/target", default_partner(language))
    for identity in profile_ids(settings):
        prefix = f"profiles/{identity}/"
        settings.setValue(prefix + "language", profile_language(settings, identity))
        settings.setValue(prefix + "name", profile_name(settings, identity))
        for key in PROFILE_KEYS:
            if settings.contains(key) and not settings.contains(prefix + key):
                settings.setValue(prefix + key, deepcopy(settings.value(key)))
        if not settings.contains(prefix + "dictionaries/order"):
            for key, value in defaults.items():
                settings.setValue(prefix + "dictionaries/" + key, deepcopy(value))
        for mode in ("collapsed", "expanded"):
            key = prefix + mode + "_dictionaries"
            if settings.contains(key):
                settings.setValue(key, [title_ids.get(value, value)
                                        for value in settings.value(key, [], type=list)])
        anki = prefix + "anki/"
        if not settings.contains(anki + "connection"):
            record = {"endpoint": settings.value(anki + "endpoint", "http://127.0.0.1:8765"),
                      "api_key": settings.value(anki + "api_key", "")}
            settings.setValue(anki + "connection", create_connection(settings, "anki", record))
        try:
            save_profile_settings(settings, identity, load_profile_settings(settings, identity))
        except ValueError:
            pass  # Keep invalid settings for explicit repair.
    settings.setValue("profile_order", list(profile_ids(settings)))
    if not settings.value("profile", "") and profile_ids(settings):
        settings.setValue("profile", profile_ids(settings)[0])
    settings.setValue("profiles_version", PROFILE_VERSION)
    try:
        _sync(settings)
    except Exception:
        for key in list(settings.allKeys()):
            if key not in original:
                settings.remove(key)
        for key, value in original.items():
            settings.setValue(key, deepcopy(value))
        raise

    # Complete the inheritance migration when this is the first settings
    # entry point. A later call is a cheap idempotent no-op.
    from wordcel.config.inheritance import migrate_defaults
    migrate_defaults(settings)
    return True


def _copy_profile_values(settings, source, destination):
    source_prefix = f"profiles/{source}/"
    destination_prefix = f"profiles/{destination}/"
    values = {key[len(source_prefix):]: deepcopy(settings.value(key))
              for key in settings.allKeys() if key.startswith(source_prefix)}
    for relative, value in values.items():
        if relative == "anki/connection":
            value = clone_connection(settings, "anki", value)
        elif relative == "translation_connection":
            value = clone_connection(settings, "translation", value)
        settings.setValue(destination_prefix + relative, value)


def create_profile(settings, language, name=None, duplicate=None):
    from wordcel.dictionary.library import language_code
    from wordcel.language.profiles import default_partner

    language = language_code(language)
    identity = uuid4().hex
    prefix = f"profiles/{identity}/"
    if duplicate:
        if duplicate not in profile_ids(settings):
            raise ValueError("Unknown profile.")
        _copy_profile_values(settings, duplicate, identity)
    settings.setValue(prefix + "language", language)
    settings.setValue(prefix + "name", name.strip() if name else profile_name(settings, identity))
    if not settings.contains(prefix + "target"):
        settings.setValue(prefix + "target", default_partner(language))
    if not settings.contains(prefix + "anki/connection"):
        settings.setValue(prefix + "anki/connection", create_connection(
            settings, "anki", {"endpoint": "http://127.0.0.1:8765", "api_key": ""}))
    settings.setValue("profile_order", list(profile_ids(settings)))
    if not settings.value("profile", ""):
        settings.setValue("profile", identity)
    _sync(settings)
    return identity


def delete_profile(settings, identity):
    order = list(profile_ids(settings))
    if identity not in order or len(order) < 2:
        raise ValueError("Keep at least one profile.")
    index = order.index(identity)
    order.remove(identity)
    fallback = order[min(index, len(order) - 1)]
    settings.remove(f"profiles/{identity}")
    settings.setValue("profile_order", order)
    for key in ("profile", "initial_profile"):
        if settings.value(key, "") == identity:
            settings.setValue(key, fallback)
    _sync(settings)
    return settings.value("profile", fallback)


# Explicit scopes for the settings UI. Prefix entries end in '/'. Values that
# represent optional feature enablement, credentials, resource assignments,
# and connection refs are intentionally absent from these maps.
PROFILE_PAGE_KEYS = {
    "Lookup": ("freeze_while_held",),
    "Dictionaries": ("dictionaries/", "collapsed_dictionaries", "expanded_dictionaries",
                      "hidden_examples_dictionaries", "hidden_grammar_dictionaries", "combine_frequencies"),
    "Shortcuts": ("hotkey", "hotkey_preset", "translation_hotkey", "translation_hotkey_preset",
                  "copy_hotkey", "copy_hotkey_preset", "hover_hotkey", "hover_hotkey_preset", "popup/",
                  "anki/shortcut", "anki/shortcut_preset", "pin_shortcut", "pin_shortcut_preset", "pin_gesture",
                  "scan_bindings", "block_scan_keys", "side_button_scrolling"),
    "Appearance": ("theme_name", "font_family", "font_size_header", "font_size_definitions", "font_size_sentence",
                   "furigana_scale", "scale", "background_opacity", "color_background", "color_foreground",
                   "color_highlight_word", "color_highlight_reading", "custom/", "buttons/", "pitch_colors",
                   "kanji_stroke_order", "headword_furigana", "definition_furigana", "compact_preview",
                   "preview_frequency", "preview_pitch", "preview_grammar", "preview_definitions",
                   "pinned_frequency", "pinned_pitch", "pinned_grammar", "pinned_sentence", "snap_scrolling",
                   "close_on_cursor_leave", "cursor_close_margin", "translation_side_by_side"),
    "Audio": ("audio_volume", "audio_autoplay_mode", "audio_priority"),
    "Translation": ("target", "translation_source", "translation_target"),
    "Anki": ("anki/deck", "anki/model", "anki/fields", "anki/field_maps", "anki/tags",
             "anki/duplicate_action", "anki/duplicate_scope", "anki/duplicate_decks", "anki/check_all_models",
             "anki/notifications"),
}
APP_PAGE_KEYS = {
    "General": ("initial_profile", "ocr/preload", "history/delay", "history/retention"),
    "Startup": ("initial_profile", "ocr/preload"),
    "History": ("history/delay", "history/retention"),
    "Storage": (),
    "Shortcuts": ("next_profile_hotkey", "next_profile_hotkey_preset", "previous_profile_hotkey",
                  "previous_profile_hotkey_preset"),
}
SHORTCUT_DEFAULTS = {
    "hotkey": ("<cmd>+<shift>+d" if sys.platform == "darwin" else "<ctrl>+<shift>+d"),
    "translation_hotkey": ("<cmd>+<shift>+t" if sys.platform == "darwin" else "<ctrl>+<shift>+t"),
    "copy_hotkey": ("<cmd>+<shift>+x" if sys.platform == "darwin" else "<ctrl>+<shift>+x"),
    "hover_hotkey": ("<cmd>+<shift>+h" if sys.platform == "darwin" else "<ctrl>+<shift>+h"),
    "pin_shortcut": "c", "popup/copy_text_shortcut": "Ctrl+C",
    "popup/replay_shortcut": "R", "popup/anki_shortcut": "Shift+A", "popup/copy_shortcut": "Shift+C",
    "popup/back_shortcut": "Alt+Left", "popup/history_shortcut": "Shift+H", "anki/shortcut": "Shift+A",
}
APP_SHORTCUT_DEFAULTS = {
    "next_profile_hotkey": ("<cmd>+<alt>+<page_down>" if sys.platform == "darwin"
                             else "<ctrl>+<alt>+<page_down>"),
    "previous_profile_hotkey": ("<cmd>+<alt>+<page_up>" if sys.platform == "darwin"
                                 else "<ctrl>+<alt>+<page_up>"),
}
SHORTCUT_PRESETS = {
    "hotkey": "Ctrl+Shift+D", "translation_hotkey": "Ctrl+Shift+T", "copy_hotkey": "Ctrl+Shift+X",
    "hover_hotkey": "Ctrl+Shift+H", "pin_shortcut": "C", "popup/copy_text_shortcut": "Ctrl+C",
    "popup/replay_shortcut": "R", "popup/anki_shortcut": "Shift+A", "popup/copy_shortcut": "Shift+C",
    "popup/back_shortcut": "Alt+Left", "popup/history_shortcut": "Shift+H", "anki/shortcut": "Shift+A",
    "next_profile_hotkey": "Ctrl+Alt+PgDown", "previous_profile_hotkey": "Ctrl+Alt+PgUp",
}


def _matches(relative, specification):
    return relative == specification or specification.endswith("/") and relative.startswith(specification)


def _remove_scoped(settings, prefix, specifications, preserve=()):
    removed = []
    for key in list(settings.allKeys()):
        if not key.startswith(prefix):
            continue
        relative = key[len(prefix):]
        if key in preserve:
            continue
        if any(_matches(relative, specification) for specification in specifications):
            settings.remove(key)
            removed.append(key)
    return removed


def _reset_binding(settings, key, default):
    """Reset a shortcut while retaining its current enabled/disabled state."""
    if not settings.contains(key):
        return []
    value = settings.value(key)
    preset = key + "_preset"
    relative = key.split("/", 2)[2] if key.startswith("profiles/") else key
    display = SHORTCUT_PRESETS.get(relative, default)
    if value == "":
        settings.setValue(key, "")
        settings.setValue(preset, display)
        return [key, preset]
    settings.setValue(key, default)
    settings.setValue(preset, display)
    return [key, preset]


def _reset_scan_bindings(settings, key):
    """Reset the scan key and mouse defaults without enabling either one."""
    if not settings.contains(key):
        return []
    value = settings.value(key)
    if not isinstance(value, str):
        return []
    from wordcel.gui.activation import KEYBOARD_TOKENS, MOUSE_TOKENS, parse_activation_bindings
    if not value:
        return_value = ""
    else:
        try:
            bindings = parse_activation_bindings(value)
        except ValueError:
            return []
        key_enabled = any(binding & KEYBOARD_TOKENS for binding in bindings)
        mouse_enabled = any(binding & MOUSE_TOKENS for binding in bindings)
        return_value = ",".join(filter(None, ("shift" if key_enabled else "",
                                                "middle" if mouse_enabled else "")))
    settings.setValue(key, return_value)
    return [key]


def _reset_translation(settings, prefix):
    """Reset translation behavior while retaining provider and server data."""
    key = prefix + "translation"
    if not settings.contains(key):
        return []
    try:
        values = json.loads(settings.value(key, ""))
    except (TypeError, ValueError):
        return []
    if not isinstance(values, dict):
        return []
    from wordcel.dictionary.translation import TranslationSettings
    try:
        TranslationSettings(**values).validated()
    except (TypeError, ValueError):
        return []
    defaults = TranslationSettings()
    for name in ("auto_start", "stream", "keep_warm", "chunk_size"):
        default = getattr(defaults, name)
        values[name] = default
    settings.setValue(key, json.dumps(values, ensure_ascii=False))
    return [key]


def reset_page(settings, profile_id, page):
    """Restore one profile page while preserving identity, data and enablement."""
    if profile_id not in profile_ids(settings):
        raise ValueError("Unknown profile.")
    if page not in PROFILE_PAGE_KEYS:
        raise ValueError("Unknown profile settings page.")
    prefix = f"profiles/{profile_id}/"
    specifications = PROFILE_PAGE_KEYS[page]
    if page == "Shortcuts":
        binding_keys = set(SHORTCUT_DEFAULTS) | {"scan_bindings"}
        non_binding = tuple(specification for specification in specifications
                            if specification not in binding_keys and not specification.endswith("/"))
        removed = _remove_scoped(settings, prefix, non_binding)
    else:
        removed = _remove_scoped(settings, prefix, specifications)
    if page == "Translation":
        changed = _reset_translation(settings, prefix)
        removed.extend(changed)
    if page == "Shortcuts":
        for relative, default in SHORTCUT_DEFAULTS.items():
            if any(_matches(relative, specification) for specification in specifications):
                # The normal key map includes the profile prefix; popup and
                # Anki bindings remain independently disableable.
                removed.extend(_reset_binding(settings, prefix + relative, default))
        removed.extend(_reset_scan_bindings(settings, prefix + "scan_bindings"))
    _sync(settings)
    return tuple(dict.fromkeys(removed))


def reset_profile(settings, profile_id):
    """Restore all profile preferences without changing its identity or data."""
    if profile_id not in profile_ids(settings):
        raise ValueError("Unknown profile.")
    changed = []
    for page in PROFILE_PAGE_KEYS:
        if page == "Shortcuts":
            # Do this page once without syncing; the final sync below keeps a
            # profile reset atomic from the UI's perspective.
            prefix = f"profiles/{profile_id}/"
            binding_keys = set(SHORTCUT_DEFAULTS) | {"scan_bindings"}
            non_binding = tuple(specification for specification in PROFILE_PAGE_KEYS[page]
                                if specification not in binding_keys and not specification.endswith("/"))
            changed.extend(_remove_scoped(settings, prefix, non_binding))
            for relative, default in SHORTCUT_DEFAULTS.items():
                changed.extend(_reset_binding(settings, prefix + relative, default))
            changed.extend(_reset_scan_bindings(settings, prefix + "scan_bindings"))
        else:
            changed.extend(_remove_scoped(settings, f"profiles/{profile_id}/", PROFILE_PAGE_KEYS[page]))
            if page == "Translation":
                changed.extend(_reset_translation(settings, f"profiles/{profile_id}/"))
    _sync(settings)
    return tuple(dict.fromkeys(changed))


def reset_app_page(settings, page):
    """Restore app-wide settings, including profile-switching keys separately."""
    if page not in APP_PAGE_KEYS:
        raise ValueError("Unknown app settings page.")
    preserved = {"history/enabled", "history/pinned", "history/manual", "history/hover",
                 "history/button_manual", "history/button_ocr", "hover_scan/startup"}
    if page == "Shortcuts":
        removed = []
        for key, default in APP_SHORTCUT_DEFAULTS.items():
            removed.extend(_reset_binding(settings, key, default))
    else:
        removed = _remove_scoped(settings, "", APP_PAGE_KEYS[page], preserve=preserved)
    _sync(settings)
    return tuple(dict.fromkeys(removed))
