"""Global editors and compact profile-level inheritance controls."""
from PyQt6.QtCore import QSignalBlocker
from PyQt6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QSpinBox, QVBoxLayout, QWidget

from wordcel.config.inheritance import overridden, set_override
from wordcel.gui.shortcut_edit import LOOKUP_PRESETS


class PreferenceGroups:
    def __init__(self, owner):
        self.owner = owner
        self.controls = {}
        self.global_audio_page = None

    def wrap(self, group, content):
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        label = {"appearance": "text and content", "audio": "audio playback", "popup": "layout and behavior"}.get(group, group)
        inherit = QCheckBox("Use shared defaults for " + label)
        layout.addWidget(inherit)
        layout.addWidget(content)
        layout.addStretch()
        self.controls[group] = inherit, content
        inherit.toggled.connect(lambda checked: self.toggle(group, checked))
        return wrapper

    def refresh(self):
        owner = self.owner
        for group, (inherit, content) in self.controls.items():
            global_edit = owner.settings.editing_global == group or (
                owner.settings.editing_global == "popup_all" and group in ("appearance", "popup"))
            inherited = not overridden(owner.settings, owner.profile.currentData(), group)
            with QSignalBlocker(inherit):
                inherit.setChecked(inherited)
            inherit.setVisible(not global_edit)
            content.setVisible(True)
            content.setEnabled(global_edit or not inherited)

    def reload(self, group):
        if group == "popup_all":
            self.reload("appearance")
            self.reload("popup")
            return
        owner = self.owner
        previous, owner._loading = owner._loading, True
        prefix = f"profiles/{owner.profile.currentData()}/"
        settings = owner.settings
        try:
            if group == "appearance":
                owner.appearance.reload()
            elif group == "shortcuts":
                from wordcel.gui.quick_lookup import default_text_shortcut
                from wordcel.gui.popup_shortcuts import POPUP_ACTIONS, popup_bindings, shortcut_key
                for key, editor in (("hotkey", owner.shortcut), ("translation_hotkey", owner.translation_shortcut),
                                    ("hover_hotkey", owner.hover_shortcut), ("copy_hotkey", owner.copy_shortcut), ("pin_shortcut", owner.pin_shortcut)):
                    default = default_text_shortcut() if key == "hotkey" else "c" if key == "pin_shortcut" else ""
                    editor.set_value(settings.value(prefix + key, default),
                                     settings.value(prefix + key + "_preset", LOOKUP_PRESETS[key]))
                for action, _, default in POPUP_ACTIONS:
                    owner.popup_shortcuts[action].set_value(popup_bindings(settings, owner.profile.currentData())[action],
                        settings.value(shortcut_key(owner.profile.currentData(), action) + "_preset", default))
                bindings = settings.value(prefix + "scan_bindings", "shift,middle").split(",")
                for control in (owner.scan_key, owner.scan_mouse):
                    control.setCurrentIndex(max(0, next((control.findData(b) for b in bindings if control.findData(b) >= 0), 0)))
                owner.block_scan_keys.setChecked(settings.value(prefix + "block_scan_keys", False, bool))
                owner.pin_gesture.setCurrentIndex(max(0, owner.pin_gesture.findData(settings.value(prefix + "pin_gesture", "left"))))
                with QSignalBlocker(owner.appearance.side_button_scrolling):
                    owner.appearance.side_button_scrolling.setChecked(settings.value(prefix + "side_button_scrolling", True, bool))
            elif group == "popup":
                owner.close_on_cursor_leave.setChecked(settings.value(prefix + "close_on_cursor_leave", False, bool))
                owner.cursor_close_margin.setValue(settings.value(prefix + "cursor_close_margin", 24, int))
                owner.translation_split.setChecked(settings.value(prefix + "translation_side_by_side", False, bool))
                owner.appearance.snap_scrolling.setChecked(settings.value(prefix + "snap_scrolling", True, bool))
            elif group == "audio":
                from wordcel.config.config import config
                owner.audio_volume.setValue(settings.value(prefix + "audio_volume", config.audio_volume, int))
                owner.audio_autoplay.setCurrentIndex(max(0, owner.audio_autoplay.findData(settings.value(prefix + "audio_autoplay_mode", "pin"))))
            self.refresh()
        finally:
            owner._loading = previous

    def toggle(self, group, inherited):
        owner = self.owner
        if owner._loading:
            return
        scroll = owner.tabs.currentWidget().verticalScrollBar()
        position = scroll.value()
        set_override(owner.settings, owner.profile.currentData(), group, not inherited)
        self.reload(group)
        owner.tabs.currentWidget().widget().layout().activate()
        scroll.setValue(position)
        self.apply(group)

    def apply(self, group):
        owner = self.owner
        window = owner.parent()
        if window is None:
            return
        if owner.settings.editing_global:
            if overridden(owner.settings, window.active_profile, group):
                return
        elif not owner.is_active_edit():
            return
        if group == "shortcuts":
            window.restore_shortcut()
            window.reload_popup_shortcuts()
            window.scan_settings_changed.emit()
        elif group in ("appearance", "popup"):
            if group == "popup":
                window.translation_panel.set_side_by_side(window.settings.value(
                    f"profiles/{window.active_profile}/translation_side_by_side", False, bool))
            window.reload_appearance()
            window.scan_settings_changed.emit()

    def add_global_audio(self, add_page):
        page = QWidget()
        form = QFormLayout(page)
        self.volume = QSpinBox()
        self.volume.setRange(0, 100)
        self.autoplay = QComboBox()
        for title, value in (("Off", "off"), ("On lookup", "lookup"), ("When pinned", "pin")):
            self.autoplay.addItem(title, value)
        form.addRow("Autoplay", self.autoplay)
        form.addRow("Volume", self.volume)
        self.global_audio_page = add_page(page, "Audio playback")
        self.volume.valueChanged.connect(lambda value: self.owner.settings.raw.setValue("defaults/audio/audio_volume", value))
        self.autoplay.currentIndexChanged.connect(lambda: self.owner.settings.raw.setValue(
            "defaults/audio/audio_autoplay_mode", self.autoplay.currentData()))

    def load_global_audio(self):
        from wordcel.config.config import config
        with QSignalBlocker(self.volume), QSignalBlocker(self.autoplay):
            self.volume.setValue(self.owner.settings.raw.value("defaults/audio/audio_volume", config.audio_volume, int))
            self.autoplay.setCurrentIndex(max(0, self.autoplay.findData(
                self.owner.settings.raw.value("defaults/audio/audio_autoplay_mode", "pin"))))
