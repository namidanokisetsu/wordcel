"""Settings navigation and scoped restore actions."""
from PyQt6.QtCore import QSignalBlocker, Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QMenu, QSizePolicy, QToolButton, QTreeWidget, QTreeWidgetItem, QWidget

from wordcel.config.profiles import profile_ids, profile_name
from wordcel.gui.action_icons import action_button


class SettingsNavigation:
    APP_PAGES = ("Startup", "Profile switching", "History", "Storage")

    def highlight_active_profile(self, active):
        if not hasattr(self, "scope"):
            return
        for index in range(self.scope.count()):
            identity = self.scope.itemData(index)
            self.scope.setItemText(index, profile_name(self.settings, identity) + (" ✓" if identity == active else ""))

    def is_active_edit(self):
        return self.parent() is not None and getattr(self.parent(), "active_profile", None) == self.profile.currentData()

    def build_sidebar(self, layout, tabs):
        from PyQt6.QtWidgets import QComboBox, QLineEdit, QListWidget, QVBoxLayout
        from wordcel.gui.settings_section import SettingsSection
        self._navigation_state = {}
        self._navigation_ready = False
        self.scope = QComboBox()
        self.scope.setAccessibleName("Editing")
        self.scope.setToolTip("Profile to edit")
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
        self.app_navigation = QTreeWidget()
        self.app_navigation.setHeaderHidden(True)
        self.app_navigation.setRootIsDecorated(False)
        self.app_navigation.setIndentation(0)
        self.app_navigation.setAccessibleName("App settings pages")
        sidebar = QWidget()
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        sidebar_layout.addWidget(self.search)
        self.app_group = SettingsSection("App settings", self.app_navigation, collapsible=True)
        sidebar_layout.addWidget(self.app_group)
        profile_content = QWidget()
        profile_layout = QVBoxLayout(profile_content)
        profile_layout.setContentsMargins(0, 0, 0, 0)
        profile_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        row = QHBoxLayout()
        self.scope_label = QLabel("Editing")
        row.addWidget(self.scope_label)
        row.addWidget(self.scope, 1)
        self.profile_menu = QMenu(self)
        self.profile_menu.addAction("New profile", self.choose_profile)
        self.profile_actions = {}
        for title, callback in (("Activate", self.activate_profile), ("Duplicate", self.duplicate_profile),
                                ("Rename…", self.rename_profile), ("Reset profile settings…", self.restore_profile_defaults),
                                ("Move up", lambda: self.reorder_profile(-1)),
                                ("Move down", lambda: self.reorder_profile(1)), ("Delete", self.remove_profile)):
            self.profile_actions[title] = self.profile_menu.addAction(title, callback)
        self.profile_menu.aboutToShow.connect(self.update_profile_actions)
        manage = action_button("settings", "Manage profiles")
        manage.setAutoRaise(True)
        manage.setStyleSheet("""
            QToolButton {background:transparent;border:0;border-radius:4px;padding:0;}
            QToolButton:hover,QToolButton:pressed {background:palette(midlight);}
            QToolButton:focus {border:1px solid palette(highlight);}
            QToolButton::menu-indicator {image:none;width:0;height:0;}
        """)
        manage.setMenu(self.profile_menu)
        manage.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        manage.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        row.addWidget(manage)
        row.addStretch()
        profile_layout.addLayout(row)
        profile_layout.addWidget(self.navigation)
        self.profile_group = SettingsSection("Profile settings", profile_content, collapsible=True)
        sidebar_layout.addWidget(self.profile_group)
        for name, group in (("app", self.app_group), ("profile", self.profile_group)):
            group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
            group.toggle.setAutoRaise(True)
            group.toggle.setStyleSheet("""
                QToolButton {background:transparent;border:0;padding:3px;text-align:left;}
                QToolButton:hover {background:palette(midlight);}
                QToolButton:focus {border:1px solid palette(highlight);}
            """)
            group.toggle.setChecked(self.settings.value(f"settings/{name}_expanded", True, bool))
            group.toggle.toggled.connect(lambda opened, name=name: self.settings.setValue(
                f"settings/{name}_expanded", opened))
        sidebar_layout.addWidget(self.search_results)
        sidebar_layout.addStretch()
        sidebar.setMinimumWidth(max(sidebar.sizeHint().width(), self.navigation.sizeHint().width(),
                                    self.app_navigation.sizeHint().width()))
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
        self.app_navigation.currentItemChanged.connect(self.navigate)
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
            self.initial_profile.addItem("Last used", "")
            self.scope.clear()
            for identity in profile_ids(self.settings):
                name = profile_name(self.settings, identity)
                self.profile.addItem(name, identity)
                self.initial_profile.addItem(name, identity)
                self.scope.addItem(name, identity)
            self.profile.setCurrentIndex(max(0, self.profile.findData(selected)))
            self.scope.setCurrentIndex(max(0, self.scope.findData(selected)))
            self.initial_profile.setCurrentIndex(max(0, self.initial_profile.findData(self.settings.value("initial_profile", ""))))
        self.highlight_active_profile(self.settings.value("profile", ""))
        self.profile_changed()
        self.populate_navigation()

    def populate_navigation(self):
        page = self.tabs.currentIndex()
        with QSignalBlocker(self.navigation), QSignalBlocker(self.app_navigation):
            if not self.navigation.topLevelItemCount():
                for title in (*self.APP_PAGES, "Lookup", "Dictionaries", "Shortcuts", "Popup", "Audio", "Translation", "Anki"):
                    index = next(i for i in range(self.tabs.count()) if self.tabs.tabText(i) == title)
                    tree = self.app_navigation if title in self.APP_PAGES else self.navigation
                    item = QTreeWidgetItem(tree, [title])
                    item.setData(0, Qt.ItemDataRole.UserRole, (None, index))
            selected = None
            for item in self.navigation_items():
                index = item.data(0, Qt.ItemDataRole.UserRole)[1]
                identity = None if item.treeWidget() is self.app_navigation else self.profile.currentData()
                item.setData(0, Qt.ItemDataRole.UserRole, (identity, index))
                if index == page:
                    selected = item
            selected = selected or self.navigation.topLevelItem(0)
            selected.treeWidget().setCurrentItem(selected)
            for tree in (self.app_navigation, self.navigation):
                tree.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                tree.setFixedHeight(sum(tree.sizeHintForRow(i) for i in range(tree.topLevelItemCount()))
                                    + 2 * tree.frameWidth())
        self.navigate(selected, reveal=False)
        self.search_settings()

    def change_scope(self):
        identity = self.scope.currentData()
        self.appearance._preview_timer.stop()
        old_scope = getattr(self, "_editing_scope", self.profile.currentData())
        positions = [self.tabs.widget(i).verticalScrollBar().value() for i in range(self.tabs.count())]
        self._navigation_state[old_scope] = positions
        if identity != self.profile.currentData():
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
        editing = identity in order
        self.profile_actions["Activate"].setEnabled(editing and identity != self.settings.value("profile", ""))
        self.profile_actions["Duplicate"].setEnabled(editing)
        self.profile_actions["Delete"].setEnabled(editing and len(order) > 1)
        self.profile_actions["Move up"].setEnabled(editing and index > 0)
        self.profile_actions["Move down"].setEnabled(editing and 0 <= index < len(order) - 1)

    def navigate(self, item, previous=None, *, reveal=True):
        value = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if not value:
            return
        other = self.app_navigation if item.treeWidget() is self.navigation else self.navigation
        with QSignalBlocker(other):
            other.clearSelection()
            other.setCurrentItem(None)
        identity, page = value
        profile_page = identity is not None
        group = self.profile_group if profile_page else self.app_group
        if self._navigation_ready and reveal:
            group.toggle.setChecked(True)
        self.profile_details.setVisible(profile_page)
        title = self.tabs.tabText(page)
        self.reset_button.setText(f"Reset {title}…")
        self.reset_button.setVisible(title != "Storage")
        self.tabs.setCurrentIndex(page)
        self._editing_scope = self.scope.currentData()
        self.settings.setValue("settings/scope", self._editing_scope)
        self.settings.setValue("settings/page", self.tabs.tabText(page))

    def sync_navigation(self, page):
        for item in self.navigation_items():
            value = item.data(0, Qt.ItemDataRole.UserRole)
            if value and value[1] == page:
                item.treeWidget().setCurrentItem(item)
                return
    def search_settings(self, *_):
        from PyQt6.QtWidgets import QAbstractButton, QLabel, QListWidgetItem
        from wordcel.gui.settings_section import SettingsSection
        query = self.search.text().strip().casefold()
        self.profile_group.setVisible(not query)
        self.app_group.setVisible(not query)
        self.search_results.setVisible(bool(query))
        self.search_results.clear()
        if not query:
            return
        for item in self.navigation_items():
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
                    section = parent.parentWidget()
                    collapsed_content = (isinstance(section, SettingsSection)
                                         and not section.toggle.isChecked())
                    if parent.isHidden() and not collapsed_content:
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
        for item in self.navigation_items():
            if item.data(0, Qt.ItemDataRole.UserRole) == value:
                item.treeWidget().setCurrentItem(item)
                self.navigate(item)
                return

    def navigation_items(self):
        for tree in (self.app_navigation, self.navigation):
            for index in range(tree.topLevelItemCount()):
                yield tree.topLevelItem(index)

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

    def restore_page_defaults(self):
        from wordcel.config.profiles import reset_app_page, reset_page
        page = self.tabs.tabText(self.tabs.currentIndex())
        identity = self.profile.currentData()
        if page == "Storage":
            return
        scope = page if page in self.APP_PAGES else f"{page} for {profile_name(self.settings, identity)}"
        self.confirm_restore(scope, lambda: reset_app_page(self.settings, page)
                             if page in self.APP_PAGES else reset_page(self.settings, identity, page), page)

    def restore_profile_defaults(self):
        from wordcel.config.profiles import reset_profile
        identity = self.profile.currentData()
        self.confirm_restore("profile settings for " + profile_name(self.settings, identity),
                             lambda: reset_profile(self.settings, identity), "Profile")

    def confirm_restore(self, scope, reset, page):
        from PyQt6.QtWidgets import QMessageBox
        message = f"Reset {scope}?\n\nEnabled features, connections and saved data are kept."
        if QMessageBox.question(self, "Reset settings", message,
                               QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                               QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        try:
            reset()
            self.refresh_after_reset(page)
        except (ValueError, OSError) as error:
            self.status.setText(str(error))

    def refresh_after_reset(self, page):
        scrolls = [self.tabs.widget(i).verticalScrollBar().value() for i in range(self.tabs.count())]
        self.appearance._preview_timer.stop()
        if page in self.APP_PAGES:
            self._loading = True
            try:
                if page == "Startup":
                    for control, key, default in ((self.preload_ocr, "ocr/preload", True),
                                                   (self.hover_startup, "hover_scan/startup", False)):
                        with QSignalBlocker(control):
                            control.setChecked(self.settings.value(key, default, bool))
                    with QSignalBlocker(self.initial_profile):
                        self.initial_profile.setCurrentIndex(max(0, self.initial_profile.findData(
                            self.settings.value("initial_profile", ""))))
                elif page == "History":
                    self.history_settings.service.preferences_changed.emit()
                elif page == "Profile switching":
                    for key, editor in self.cycle_shortcuts.items():
                        preset = "Ctrl+Alt+PgDown" if key == "next_profile" else "Ctrl+Alt+PgUp"
                        editor.set_value(self.settings.value(key + "_hotkey", ""),
                                         self.settings.value(key + "_hotkey_preset", preset))
            finally:
                self._loading = False
            if self.parent() is not None:
                if page == "Startup":
                    self.parent().scan_settings_changed.emit()
                elif page == "Profile switching":
                    self.parent().restore_cycle_shortcuts()
        else:
            self._resetting = True
            try:
                self.profile_changed(only_page=None if page == "Profile" else page)
            finally:
                self._resetting = False
            if self.is_active_edit():
                window = self.parent()
                if page in ("Shortcuts", "Profile"):
                    window.restore_shortcut()
                if page in ("Popup", "Profile"):
                    window.translation_panel.set_side_by_side(self.settings.value(
                        f"profiles/{self.profile.currentData()}/translation_side_by_side", False, bool))
                    window.reload_appearance()
                elif page == "Shortcuts":
                    window.reload_popup_shortcuts()
                if page in ("Lookup", "Shortcuts", "Popup", "Profile"):
                    window.scan_settings_changed.emit()
                if page in ("Dictionaries", "Profile"):
                    window.refresh_library()
                elif page == "Translation":
                    window._edited()
                    window.refresh_translation_availability()
                if page in ("Anki", "Profile"):
                    window.update_anki()
        for i, position in enumerate(scrolls):
            self.tabs.widget(i).widget().layout().activate()
            self.tabs.widget(i).verticalScrollBar().setValue(position)
