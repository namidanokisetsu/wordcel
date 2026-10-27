"""Settings navigation and shared service connection editors."""
from PyQt6.QtCore import QSignalBlocker, Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QMenu, QSizePolicy, QToolButton, QTreeWidget, QTreeWidgetItem, QWidget

from wordcel.config.profiles import connection, profile_ids, profile_name


class SettingsNavigation:
    def highlight_active_profile(self, active):
        if not hasattr(self, "scope"):
            return
        for index in range(1, self.scope.count()):
            identity = self.scope.itemData(index)
            self.scope.setItemText(index, profile_name(self.settings, identity) + (" ✓" if identity == active else ""))

    def is_active_edit(self):
        return self.settings.editing_global is None and self.parent() is not None and getattr(self.parent(), "active_profile", None) == self.profile.currentData()

    def build_sidebar(self, layout, tabs):
        from PyQt6.QtWidgets import QComboBox, QLineEdit, QListWidget, QVBoxLayout
        self._navigation_state = {}
        self.scope = QComboBox()
        self.scope.setAccessibleName("Editing")
        self.scope.setToolTip("Choose a profile or edit defaults used by profiles")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search settings…")
        self.search.setClearButtonEnabled(True)
        self.search_results = QListWidget()
        self.search_results.setAccessibleName("Settings search results")
        self.search_results.hide()
        self.navigation = QTreeWidget()
        self.navigation.setHeaderHidden(True)
        self.navigation.setRootIsDecorated(False)
        self.navigation.setIndentation(0)
        self.navigation.setAccessibleName("Settings pages")
        sidebar = QWidget()
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.addWidget(self.search)
        row = QHBoxLayout()
        row.addWidget(QLabel("Editing"))
        row.addWidget(self.scope, 1)
        self.profile_menu = QMenu(self)
        self.profile_menu.addAction("New profile", self.choose_profile)
        self.profile_actions = {}
        for title, callback in (("Activate", self.activate_profile), ("Duplicate", self.duplicate_profile),
                                ("Move up", lambda: self.reorder_profile(-1)),
                                ("Move down", lambda: self.reorder_profile(1)), ("Delete", self.remove_profile)):
            self.profile_actions[title] = self.profile_menu.addAction(title, callback)
        self.profile_menu.aboutToShow.connect(self.update_profile_actions)
        manage = QToolButton()
        manage.setText("⋯")
        manage.setToolTip("Manage profiles")
        manage.setAccessibleName("Manage profiles")
        manage.setMenu(self.profile_menu)
        manage.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        manage.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        row.addWidget(manage)
        sidebar_layout.addLayout(row)
        sidebar_layout.addWidget(self.navigation, 1)
        sidebar_layout.addWidget(self.search_results, 1)
        tabs.tabBar().hide()
        layout.removeWidget(tabs)
        layout.removeWidget(self.profile_header)
        layout.removeWidget(self.profile_details)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        self.profile_header.hide()
        content_layout.addWidget(self.profile_details)
        content_layout.addWidget(tabs, 1)
        body = QHBoxLayout()
        body.addWidget(sidebar)
        body.addWidget(content, 1)
        layout.insertLayout(0, body, 1)
        self.navigation.currentItemChanged.connect(self.navigate)
        self.scope.currentIndexChanged.connect(self.change_scope)
        self.search.textChanged.connect(self.search_settings)
        self.search_results.itemActivated.connect(self.open_search_result)
        self.search_results.itemClicked.connect(self.open_search_result)
        tabs.currentChanged.connect(self.sync_navigation)
        self.resize(900, 620)

    def rebuild_profiles(self, selected=None):
        scope = selected or (self.scope.currentData() if self.scope.count() else
                             self.settings.value("settings/scope", self.profile.currentData()))
        selected = selected or (scope if scope in profile_ids(self.settings) else self.profile.currentData())
        with QSignalBlocker(self.profile), QSignalBlocker(self.initial_profile), QSignalBlocker(self.scope):
            self.profile.clear()
            self.initial_profile.clear()
            self.scope.clear()
            self.scope.addItem("Shared defaults", "shared")
            for identity in profile_ids(self.settings):
                name = profile_name(self.settings, identity)
                self.profile.addItem(name, identity)
                self.initial_profile.addItem(name, identity)
                self.scope.addItem(name, identity)
            self.profile.setCurrentIndex(max(0, self.profile.findData(selected)))
            self.scope.setCurrentIndex(0 if scope == "shared" else max(1, self.scope.findData(selected)))
            self.initial_profile.setCurrentIndex(max(0, self.initial_profile.findData(self.settings.value("initial_profile", ""))))
        self.highlight_active_profile(self.settings.value("profile", ""))
        self.profile_changed()
        self.populate_navigation()

    def populate_navigation(self):
        page = self.tabs.currentIndex()
        shared = self.scope.currentData() == "shared"
        with QSignalBlocker(self.navigation):
            self.navigation.clear()
            selected = None
            titles = ("Popup", "Shortcuts", "Audio") if shared else ("Lookup", "Dictionaries", "Popup", "Shortcuts", "Audio", "Translation", "Anki")
            for title in (*titles, "Startup", "Connections", "Storage"):
                global_page = title in ("Startup", "Connections", "Storage")
                if title == "Startup":
                    heading = QTreeWidgetItem(self.navigation, ["App-wide"])
                    heading.setFlags(Qt.ItemFlag.NoItemFlags)
                target = "Audio playback" if shared and title == "Audio" else title
                index = next(i for i in range(self.tabs.count()) if self.tabs.tabText(i) == target)
                identity = self.profile.currentData()
                if global_page:
                    identity = None
                elif shared:
                    identity = "global:" + {"Popup": "popup_all", "Shortcuts": "shortcuts", "Audio": "audio"}[title]
                item = QTreeWidgetItem(self.navigation, [title])
                item.setData(0, Qt.ItemDataRole.UserRole, (identity, index))
                if index == page or title == "Audio" and self.tabs.tabText(page) in ("Audio", "Audio playback"):
                    selected = item
            self.navigation.setCurrentItem(selected or self.navigation.topLevelItem(0))
        self.navigate(self.navigation.currentItem())
        self.search_settings()

    def change_scope(self):
        identity = self.scope.currentData()
        self.appearance._preview_timer.stop()
        old_scope = self._editing_scope
        positions = [self.tabs.widget(i).verticalScrollBar().value() for i in range(self.tabs.count())]
        self._navigation_state[old_scope] = positions
        if identity != "shared" and identity != self.profile.currentData():
            self.settings.editing_global = None
            with QSignalBlocker(self.profile):
                self.profile.setCurrentIndex(self.profile.findData(identity))
            self.profile_changed()
        self.populate_navigation()
        for i, position in enumerate(self._navigation_state.get(identity, positions)):
            self.tabs.widget(i).widget().layout().activate()
            self.tabs.widget(i).verticalScrollBar().setValue(position)

    def update_profile_actions(self):
        order = list(profile_ids(self.settings))
        identity = self.profile.currentData()
        index = order.index(identity) if identity in order else -1
        editing = self.scope.currentData() != "shared"
        self.profile_actions["Activate"].setEnabled(editing and identity != self.settings.value("profile", ""))
        self.profile_actions["Duplicate"].setEnabled(editing)
        self.profile_actions["Delete"].setEnabled(editing and len(order) > 1)
        self.profile_actions["Move up"].setEnabled(editing and index > 0)
        self.profile_actions["Move down"].setEnabled(editing and 0 <= index < len(order) - 1)

    def navigate(self, item, previous=None):
        value = item.data(0, Qt.ItemDataRole.UserRole) if item else None
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
            self.resources.refresh_actions()
        if global_group:
            self.preference_groups.load_global_audio()
        self.preference_groups.refresh()
        self.profile_details.setVisible(identity is not None and not global_group)
        self.tabs.setCurrentIndex(page)
        self._editing_scope = self.scope.currentData()
        self.settings.setValue("settings/scope", self._editing_scope)
        self.settings.setValue("settings/page", self.tabs.tabText(page))

    def sync_navigation(self, page):
        for index in range(self.navigation.topLevelItemCount()):
            item = self.navigation.topLevelItem(index)
            value = item.data(0, Qt.ItemDataRole.UserRole)
            if value and value[1] == page:
                self.navigation.setCurrentItem(item)
                return
        # Links to profile-only features leave shared defaults explicitly.
        if self.scope.currentData() == "shared":
            self.scope.setCurrentIndex(self.scope.findData(self.profile.currentData()))

    def search_settings(self, *_):
        from PyQt6.QtWidgets import QAbstractButton, QLabel, QListWidgetItem
        from wordcel.gui.settings_section import SettingsSection
        query = self.search.text().strip().casefold()
        self.navigation.setVisible(not query)
        self.search_results.setVisible(bool(query))
        self.search_results.clear()
        if not query:
            return
        for index in range(self.navigation.topLevelItemCount()):
            item = self.navigation.topLevelItem(index)
            value = item.data(0, Qt.ItemDataRole.UserRole)
            if not value:
                continue
            page = self.tabs.widget(value[1])
            seen = set()
            for control in page.widget().findChildren(QWidget):
                if not isinstance(control, (QLabel, QAbstractButton)) or control.isHidden():
                    continue
                label = control.text().replace("&", "").strip()
                if not label or "<" in label:
                    continue
                sections = []
                parent = control.parentWidget()
                hidden = False
                while parent is not None and parent is not page.widget():
                    if parent.isHidden():
                        hidden = True
                    if isinstance(parent, SettingsSection):
                        sections.append(parent.toggle.text())
                    parent = parent.parentWidget()
                title = " › ".join((item.text(0), *reversed(sections), label))
                if hidden or title in seen:
                    continue
                seen.add(title)
                if all(word in title.casefold() for word in query.split()):
                    result = QListWidgetItem(title, self.search_results)
                    result.setData(Qt.ItemDataRole.UserRole, (value, control))

    def open_search_result(self, item):
        value, control = item.data(Qt.ItemDataRole.UserRole)
        self.navigate_item(value)
        from wordcel.gui.settings_section import SettingsSection
        parent = control.parentWidget()
        while parent is not None:
            if isinstance(parent, SettingsSection):
                parent.toggle.setChecked(True)
            parent = parent.parentWidget()
        page = self.tabs.widget(value[1])
        page.widget().layout().activate()
        page.ensureWidgetVisible(control)
        self.search.clear()
        control.setFocus(Qt.FocusReason.OtherFocusReason)

    def navigate_item(self, value):
        for index in range(self.navigation.topLevelItemCount()):
            item = self.navigation.topLevelItem(index)
            if item.data(0, Qt.ItemDataRole.UserRole) == value:
                self.navigation.setCurrentItem(item)
                self.navigate(item)
                return

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
                                      for key in ("hotkey", "translation_hotkey", "hover_hotkey", "copy_hotkey"))])
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
