"""Named settings profiles, independent of language policies and installed files."""
from uuid import uuid4


PROFILE_KEYS = ("hotkey", "hotkey_preset", "translation_hotkey", "translation_hotkey_preset",
                "copy_hotkey", "copy_hotkey_preset", "hover_hotkey", "hover_hotkey_preset", "translation_side_by_side",
                "close_on_cursor_leave", "cursor_close_margin")


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
    settings.beginGroup("connections/" + kind)
    try:
        identities = settings.childGroups()
    finally:
        settings.endGroup()
    for identity in identities:
        if connection(settings, kind, identity) == values:
            return identity
    identity = uuid4().hex
    for key, value in values.items():
        settings.setValue(f"connections/{kind}/{identity}/{key}", value)
    return identity


def migrate(settings, directory=None):
    """Copy current Wordcel settings once; retain a typed, restart-safe backup."""
    if settings.value("profiles_version", 0, int) >= 1:
        return
    from pathlib import Path
    from PyQt6.QtCore import QSettings
    backup_path = Path(settings.fileName()).with_name(Path(settings.fileName()).name + ".profiles-backup.ini")
    # Native Windows settings are registry paths, so keep their backup in app data.
    if settings.format() == QSettings.Format.NativeFormat and __import__("sys").platform == "win32":
        from wordcel.utils.paths import paths
        backup_path = Path(paths.data_dir) / "settings-profiles-backup.ini"
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    if not backup_path.exists():
        backup = QSettings(str(backup_path), QSettings.Format.IniFormat)
        for key in settings.allKeys():
            backup.setValue(key, settings.value(key))
        backup.sync()
        if backup.status() != QSettings.Status.NoError:
            raise OSError("Could not back up settings.")
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
    for language in (imported | ({current} if current else set())) - removed:
        if language not in profile_ids(settings):
            settings.setValue(f"profiles/{language}/target", default_partner(language))
    for identity in profile_ids(settings):
        prefix = f"profiles/{identity}/"
        settings.setValue(prefix + "language", profile_language(settings, identity))
        settings.setValue(prefix + "name", profile_name(settings, identity))
        for key in PROFILE_KEYS:
            if settings.contains(key) and not settings.contains(prefix + key):
                settings.setValue(prefix + key, settings.value(key))
        if not settings.contains(prefix + "dictionaries/order"):
            for key, value in defaults.items():
                settings.setValue(prefix + "dictionaries/" + key, value)
        for mode in ("collapsed", "expanded"):
            key = prefix + mode + "_dictionaries"
            if settings.contains(key):
                settings.setValue(key, [title_ids.get(value, value) for value in settings.value(key, [], type=list)])
        anki = prefix + "anki/"
        if not settings.contains(anki + "connection"):
            record = {"endpoint": settings.value(anki + "endpoint", "http://127.0.0.1:8765"),
                      "api_key": settings.value(anki + "api_key", "")}
            settings.setValue(anki + "connection", save_connection(settings, "anki", record))
        try:
            save_profile_settings(settings, identity, load_profile_settings(settings, identity))
        except ValueError:
            pass  # Keep invalid settings for explicit repair, including their distinct endpoint.
    settings.setValue("profile_order", list(profile_ids(settings)))
    if not settings.value("profile", "") and profile_ids(settings):
        settings.setValue("profile", profile_ids(settings)[0])
    settings.setValue("profiles_version", 1)
    settings.sync()


def create_profile(settings, language, name=None, duplicate=None):
    from wordcel.config.inheritance import raw_settings
    settings = raw_settings(settings)
    from wordcel.dictionary.library import language_code
    from wordcel.language.profiles import default_partner
    language = language_code(language)
    identity = uuid4().hex
    prefix = f"profiles/{identity}/"
    if duplicate:
        source = f"profiles/{duplicate}/"
        for key in settings.allKeys():
            if key.startswith(source):
                settings.setValue(prefix + key[len(source):], settings.value(key))
    settings.setValue(prefix + "language", language)
    if name:
        settings.setValue(prefix + "name", name.strip())
    else:
        settings.setValue(prefix + "name", profile_name(settings, identity))
    if not settings.contains(prefix + "target"):
        settings.setValue(prefix + "target", default_partner(language))
    if not settings.contains(prefix + "anki/connection"):
        settings.setValue(prefix + "anki/connection", save_connection(settings, "anki",
                          {"endpoint": "http://127.0.0.1:8765", "api_key": ""}))
    settings.setValue("profile_order", list(profile_ids(settings)))
    if not settings.value("profile", ""):
        settings.setValue("profile", identity)
    settings.sync()
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
    settings.sync()
    return settings.value("profile", fallback)
