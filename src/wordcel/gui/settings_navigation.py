"""Settings navigation and shared service connection editors."""
from PyQt6.QtCore import QSignalBlocker, Qt
from PyQt6.QtGui import QBrush, QPalette
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QMenu, QToolButton, QTreeWidget, QTreeWidgetItem, QWidget

from wordcel.config.profiles import connection, profile_ids, profile_name


class SettingsNavigation:
    def highlight_active_profile(self, active):
        if not hasattr(self, "navigation"):
            return
        group = self.navigation.topLevelItem(2)
        if group is None:
            return
        for index in range(group.childCount()):
            entry = group.child(index)
            identity = entry.data(0, Qt.ItemDataRole.UserRole)[0]
            is_active = identity == active
            name = profile_name(self.settings, identity)
            entry.setText(0, name + ("  \u2713" if is_active else ""))
            font = entry.font(0)
            font.setBold(is_active)
            entry.setFont(0, font)
            entry.setForeground(0, self.navigation.palette().brush(QPalette.ColorRole.Highlight) if is_active else QBrush())
            entry.setToolTip(0, "Active profile" if is_active else "")
            entry.setData(0, Qt.ItemDataRole.AccessibleTextRole, name + (", active profile" if is_active else ""))

    def is_active_edit(self):
        return self.settings.editing_global is None and self.parent() is not None and getattr(self.parent(), "active_profile", None) == self.profile.currentData()

    def build_sidebar(self, layout, tabs):
        self._navigation_state = {}
        self._editing_identity = self.profile.currentData()
        self.navigation = QTreeWidget()
        self.navigation.setHeaderHidden(True)
        self.navigation.setAccessibleName("Settings pages")
        self.navigation.setMinimumWidth(self.navigation.fontMetrics().horizontalAdvance("Translation settings") + 40)
        tabs.tabBar().hide()
        layout.removeWidget(tabs)
        layout.removeWidget(self.profile_header)
        layout.removeWidget(self.profile_details)
        content = QWidget()
        from PyQt6.QtWidgets import QVBoxLayout
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        self.profile_header.hide()
        content_layout.addWidget(self.profile_details)
        content_layout.addWidget(tabs, 1)
        body = QHBoxLayout()
        body.addWidget(self.navigation)
        body.addWidget(content, 1)
        layout.insertLayout(0, body, 1)
        self.profile.hide()
        self.profile_header.layout().itemAt(0).widget().hide()
        self.navigation.currentItemChanged.connect(self.navigate)
        self.navigation.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.navigation.customContextMenuRequested.connect(self.show_profile_menu)
        self.profile_menu = QMenu(self.navigation)
        self.profile_actions = {}
        for title, callback in (("Activate", self.activate_profile), ("Duplicate", self.duplicate_profile),
                                ("Move up", lambda: self.reorder_profile(-1)),
                                ("Move down", lambda: self.reorder_profile(1)), ("Delete", self.remove_profile)):
            self.profile_actions[title] = self.profile_menu.addAction(title, callback)
        self.profile_menu.aboutToShow.connect(self.update_profile_actions)
        self.resize(900, 620)

    def rebuild_profiles(self, selected=None):
        selected = selected or self.profile.currentData()
        old_item = self.navigation.currentItem()
        old_value = old_item.data(0, Qt.ItemDataRole.UserRole) if old_item else None
        old_page = old_item.data(0, Qt.ItemDataRole.UserRole)[1] if old_item and old_item.data(0, Qt.ItemDataRole.UserRole) else 0
        old_group = self.navigation.topLevelItem(2)
        expanded = {}
        if old_group:
            for index in range(old_group.childCount()):
                entry = old_group.child(index)
                expanded[entry.data(0, Qt.ItemDataRole.UserRole)[0]] = entry.isExpanded()
        group_expanded = old_group.isExpanded() if old_group else True
        with QSignalBlocker(self.profile), QSignalBlocker(self.initial_profile), QSignalBlocker(self.navigation):
            self.profile.clear()
            self.initial_profile.clear()
            self.navigation.clear()
            app = QTreeWidgetItem(self.navigation, ["App"])
            app.setData(0, Qt.ItemDataRole.UserRole, (None, self.tabs.indexOf(self.app_tab)))
            for group, title in (("appearance", "Appearance"), ("shortcuts", "Shortcuts"), ("popup", "Popup"), ("audio", "Audio playback")):
                page = self.tabs.indexOf(self.preference_groups.global_audio_page) if group == "audio" else next(
                    i for i in range(self.tabs.count()) if self.tabs.tabText(i) == title)
                child = QTreeWidgetItem(app, [title])
                child.setData(0, Qt.ItemDataRole.UserRole, ("global:" + group, page))
            app.setExpanded(True)
            storage = QTreeWidgetItem(self.navigation, ["Storage"])
            storage.setData(0, Qt.ItemDataRole.UserRole, (None, self.tabs.indexOf(self.data_tab)))
            group = QTreeWidgetItem(self.navigation)
            heading = QWidget()
            toolbar = QHBoxLayout(heading)
            toolbar.setContentsMargins(0, 0, 0, 0)
            toolbar.addWidget(QLabel("Profiles"), 1)
            add = QToolButton()
            add.setText("+")
            add.setToolTip("New profile")
            add.setAccessibleName("New profile")
            add.clicked.connect(self.choose_profile)
            toolbar.addWidget(add)
            self.navigation.setItemWidget(group, 0, heading)
            group.setSizeHint(0, heading.sizeHint())
            group.setFlags(group.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            selected_item = None
            for identity in profile_ids(self.settings):
                name = profile_name(self.settings, identity)
                self.profile.addItem(name, identity)
                self.initial_profile.addItem(name, identity)
                entry = QTreeWidgetItem(group, [name])
                entry.setData(0, Qt.ItemDataRole.UserRole, (identity, 0))
                for index in range(self.tabs.count()):
                    if self.tabs.widget(index) in (self.app_tab, self.data_tab, self.preference_groups.global_audio_page):
                        continue
                    item = QTreeWidgetItem(entry, [self.tabs.tabText(index)])
                    item.setData(0, Qt.ItemDataRole.UserRole, (identity, index))
                    if identity == selected and index == old_page:
                        selected_item = item
                entry.setExpanded(expanded.get(identity, identity == selected))
                if identity == selected and selected_item is None:
                    selected_item = entry
            group.setExpanded(group_expanded)
            self.profile.setCurrentIndex(max(0, self.profile.findData(selected)))
            self.initial_profile.setCurrentIndex(max(0, self.initial_profile.findData(self.settings.value("initial_profile", ""))))
            if old_page == self.tabs.indexOf(self.app_tab):
                selected_item = app
            elif old_page == self.tabs.indexOf(self.data_tab):
                selected_item = storage
            if old_value and old_value[0] and old_value[0].startswith("global:"):
                selected_item = next((app.child(i) for i in range(app.childCount())
                                      if app.child(i).data(0, Qt.ItemDataRole.UserRole) == old_value), selected_item)
            self.navigation.setCurrentItem(selected_item)
        self.profile_changed()
        self.navigate(self.navigation.currentItem())

    def show_profile_menu(self, position):
        item = self.navigation.itemAt(position)
        group = self.navigation.topLevelItem(2)
        if item is None or item.parent() != group:
            return
        self.navigation.setCurrentItem(item)
        self.profile_menu.popup(self.navigation.viewport().mapToGlobal(position))

    def update_profile_actions(self):
        order = list(profile_ids(self.settings))
        identity = self.profile.currentData()
        index = order.index(identity) if identity in order else -1
        self.profile_actions["Activate"].setEnabled(identity != self.settings.value("profile", ""))
        self.profile_actions["Delete"].setEnabled(len(order) > 1)
        self.profile_actions["Move up"].setEnabled(index > 0)
        self.profile_actions["Move down"].setEnabled(0 <= index < len(order) - 1)

    def navigate(self, item, previous=None):
        if item is None:
            return
        value = item.data(0, Qt.ItemDataRole.UserRole)
        if not value:
            return
        identity, page = value
        global_group = identity.split(":", 1)[1] if identity and identity.startswith("global:") else None
        previous_group = self.settings.editing_global
        if previous_group != global_group:
            self.appearance._preview_timer.stop()
            self.settings.editing_global = global_group
            for group in dict.fromkeys(group for group in (previous_group, global_group) if group):
                self.preference_groups.reload(group)
            self.update_ocr_controls()
            self.resources.refresh()
        if global_group:
            self.preference_groups.load_global_audio()
            self.preference_groups.refresh()
            self.profile_details.hide()
            self.tabs.setCurrentIndex(page)
            return
        self.profile_details.setVisible(identity is not None)
        if identity and identity != self.profile.currentData():
            from wordcel.gui.settings_section import SettingsSection
            state = [(self.tabs.widget(i).verticalScrollBar().value()) for i in range(self.tabs.count())]
            sections = [section.toggle.isChecked() for section in self.findChildren(SettingsSection)]
            self._navigation_state[self.profile.currentData()] = state, sections
            self.sync_profile(identity)
            saved = self._navigation_state.get(identity)
            if saved:
                for section, checked in zip(self.findChildren(SettingsSection), saved[1]):
                    section.toggle.setChecked(checked)
                for i, position in enumerate(saved[0]):
                    self.tabs.widget(i).widget().layout().activate()
                    self.tabs.widget(i).verticalScrollBar().setValue(position)
        self.tabs.setCurrentIndex(page)

    def reorder_profile(self, offset):
        order = list(profile_ids(self.settings))
        index = order.index(self.profile.currentData())
        target = index + offset
        if 0 <= target < len(order):
            order[index], order[target] = order[target], order[index]
            self.settings.setValue("profile_order", order)
            self.rebuild_profiles()
            if self.parent() is not None:
                self.parent().update_languages()

    def save_cycle_shortcut(self, name, editor):
        if self._loading:
            return
        from wordcel.gui.text_shortcuts import validate_shortcuts
        from wordcel.config.profiles import PROFILE_KEYS
        value = editor.text()
        other = "previous_profile" if name == "next_profile" else "next_profile"
        try:
            for identity in profile_ids(self.settings):
                validate_shortcuts([value, self.settings.value(other + "_hotkey", ""),
                                    *(self.settings.value(f"profiles/{identity}/{key}", "")
                                      for key in ("hotkey", "translation_hotkey", "hover_hotkey"))])
            self.settings.setValue(name + "_hotkey", value)
            self.settings.setValue(name + "_hotkey_preset", editor.recorder.keySequence().toString())
            if self.parent() is not None:
                self.parent().restore_cycle_shortcuts()
            self.status.clear()
        except (ValueError, OSError, RuntimeError) as error:
            self.status.setText(str(error))
            editor.set_value(self.settings.value(name + "_hotkey", ""), self.settings.value(name + "_hotkey_preset", ""))

    def reload_connections(self):
        with QSignalBlocker(self.connection_list):
            self.connection_list.clear()
            for kind, title in (("anki", "Anki"), ("translation", "Translation")):
                self.settings.beginGroup("connections/" + kind)
                identities = self.settings.childGroups()
                self.settings.endGroup()
                for index, identity in enumerate(identities, 1):
                    record = connection(self.settings, kind, identity)
                    self.connection_list.addItem(record.get("name", f"{title} {index}"), (kind, identity))
        self.load_connection()

    def add_connection(self, kind):
        from PyQt6.QtWidgets import QInputDialog
        from uuid import uuid4
        name, accepted = QInputDialog.getText(self, "New connection", "Name")
        if not accepted or not name.strip():
            return
        identity = uuid4().hex
        values = {"name": name.strip(), "endpoint": "http://127.0.0.1:8765" if kind == "anki" else "http://127.0.0.1:8766/v1"}
        values.update({"api_key": ""} if kind == "anki" else {"model": "local-model"})
        for key, value in values.items():
            self.settings.setValue(f"connections/{kind}/{identity}/{key}", value)
        self.reload_connections()
        self.reload_connection_choices()
        self.connection_list.setCurrentIndex(self.connection_list.findData((kind, identity)))

    def load_connection(self):
        selected = self.connection_list.currentData()
        if not selected:
            return
        kind, identity = selected
        record = connection(self.settings, kind, identity)
        self.connection_endpoint.setText(record.get("endpoint", ""))
        self.connection_key.setText(record.get("api_key", ""))
        self.connection_model.setText(record.get("model", ""))
        self.connection_key.setEnabled(kind == "anki")
        self.connection_model.setEnabled(kind == "translation")
        form = self.connection_list.parentWidget().layout()
        form.setRowVisible(self.connection_key, kind == "anki")
        form.setRowVisible(self.connection_model, kind == "translation")

    def save_connection(self):
        selected = self.connection_list.currentData()
        if not selected:
            return
        kind, identity = selected
        endpoint = self.connection_endpoint.text().strip()
        try:
            if kind == "anki":
                from wordcel.anki import endpoint_address
                endpoint_address(endpoint)
            else:
                from wordcel.dictionary.translation import local_endpoint
                endpoint = local_endpoint(endpoint)
                if not self.connection_model.text().strip():
                    raise ValueError("Enter a server model.")
            values = {"endpoint": endpoint}
            values.update({"api_key": self.connection_key.text()} if kind == "anki" else
                          {"model": self.connection_model.text().strip()})
            for key, value in values.items():
                self.settings.setValue(f"connections/{kind}/{identity}/{key}", value)
            self.profile_changed()
            if self.parent() is not None:
                self.parent().update_anki()
                self.parent().refresh_translation_availability()
            self.status.clear()
        except ValueError as error:
            self.status.setText(str(error))

    def reload_connection_choices(self):
        for kind, control, key in (("anki", self.profile_connection, "anki/connection"),
                                   ("translation", self.translation_connection, "translation_connection")):
            with QSignalBlocker(control):
                control.clear()
                for index in range(self.connection_list.count()):
                    record_kind, identity = self.connection_list.itemData(index)
                    if kind == record_kind:
                        control.addItem(self.connection_list.itemText(index), identity)
                control.setCurrentIndex(control.findData(self.settings.value(f"profiles/{self.profile.currentData()}/{key}", "")))
            if kind == "translation":
                self.translation_form.setRowVisible(control, self.translation_mode.currentData() == "custom")

    def save_anki_connection(self):
        if not self._loading and self.profile_connection.currentData():
            self.settings.setValue(f"profiles/{self.profile.currentData()}/anki/connection", self.profile_connection.currentData())
            self.anki.load(self.profile.currentData())
            if self.is_active_edit():
                self.parent().update_anki()

    def select_translation_connection(self):
        if self._loading or not self.translation_connection.currentData():
            return
        identity = self.translation_connection.currentData()
        record = connection(self.settings, "translation", identity)
        self.translation_endpoint.setText(record.get("endpoint", ""))
        self.translation_model.setText(record.get("model", ""))
        self.settings.setValue(f"profiles/{self.profile.currentData()}/translation_connection", identity)
        self.save_translation()
