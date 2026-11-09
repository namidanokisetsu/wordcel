"""Popup Anki actions, save queue and revision-bound duplicate checks."""
from PyQt6.QtCore import QObject, pyqtSignal


class LookupAnki(QObject):
    changed = pyqtSignal()

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self._task = None
        self._queue = []
        self._saved_revision = None
        self._saved_notes = {}
        self._recent_saves = {}
        self._check_task = None
        self._check_identity = None
        self._check_error = ""
        self._existing_identity = None
        self._known_notes = {}
        self._browse_task = None

    def refresh(self, headwords=()):
        """Refresh checks and return button states keyed by headword, or None for the primary button."""
        window = self.window
        from wordcel.anki import load_settings
        options = load_settings(window.settings, window.active_profile)
        enabled = options.enabled
        groups = window._headword_groups()
        first = next(iter(groups), None)
        identity = (window.revision, options, tuple(groups))
        if (enabled and options.deck and options.model and options.fields and groups
                and window._display_revision == window.revision and not window._shutting_down
                and self._check_task is None and self._check_identity != identity):
            from wordcel.anki import AnkiClient
            from wordcel.gui.anki import AnkiTask
            self._check_identity = identity
            self._check_error = ""
            from wordcel.language.arabic import display_headword
            words = tuple(dict.fromkeys(display_headword(entries[0]) for entries in groups.values()))
            self._check_task = AnkiTask(lambda: AnkiClient(options).existing_notes(words),
                                        (identity, {key: self._recent_saves[key] for key in groups
                                                    if key in self._recent_saves}), self)
            self._check_task.finished.connect(self._existing_finished)
            self._check_task.thread.start()
        existing = self._existing_notes(identity)
        saved_words = ({key: value for key, value in self._saved_notes.items() if value[1] == options}
                       if self._saved_revision == window.revision else {})
        pending_check = self._check_task is not None and self._existing_identity != identity
        ready = (enabled and window._result is not None and bool(window._result.entries)
                 and window._display_revision == window.revision
                 and self._browse_task is None)
        states = {}
        for key in (None, *headwords):
            headword = first if key is None else key
            saved = headword in saved_words or headword in existing
            if self._pending(headword, options):
                state = "anki_checking", "Adding to Anki…", False
            elif saved and options.duplicate_action == "prevent":
                state = "anki_saved", "Show in Anki", ready
            elif saved:
                state = "anki_duplicate", "Add another note", ready
            elif pending_check:
                state = "anki_checking", "Checking Anki…", ready
            elif self._existing_identity == identity and self._check_error:
                state = "anki", "Add to Anki (status unavailable)", ready
            else:
                state = "anki", "Add to Anki", ready
            states[key] = state
        return options, states

    def _pending(self, headword, options):
        contexts = ([self._task.context] if self._task is not None else [])
        contexts += [context for _, context in self._queue]
        return any(context[1] == headword and context[2] == options for context in contexts)

    def _existing_notes(self, identity):
        existing = dict(self._known_notes) if self._existing_identity == identity else {}
        for key in identity[2]:
            saved = self._recent_saves.get(key)
            if saved is not None and saved[1] == identity[1]:
                existing[key] = tuple(dict.fromkeys((*existing.get(key, ()), saved[0])))
        return existing

    def _existing_finished(self, response):
        window = self.window
        task, self._check_task = self._check_task, None
        task.deleteLater()
        if window._shutting_down:
            return
        (identity, saved_snapshot), found, error = response
        from wordcel.anki import load_settings
        current = (window.revision, load_settings(window.settings, window.active_profile), tuple(window._headword_groups()))
        if identity == current:
            from wordcel.language.arabic import display_headword
            expressions = {key: display_headword(entries[0]) for key, entries in window._headword_groups().items()}
            self._existing_identity = identity
            self._check_error = error
            self._known_notes = {key: found[expressions[key]] for key in identity[2]
                                 if not error and expressions[key] in found}
            if not error:
                for key in identity[2]:
                    saved = saved_snapshot.get(key)
                    if (saved is not None and saved[1] == identity[1]
                            and self._recent_saves.get(key) == saved
                            and saved[0] not in found.get(expressions[key], ())):
                        del self._recent_saves[key]
                        if (self._saved_revision == identity[0]
                                and self._saved_notes.get(key) == saved):
                            del self._saved_notes[key]
        self.changed.emit()

    def add(self, *, headword=None):
        window = self.window
        from wordcel.anki import AnkiClient, load_settings
        from wordcel.gui.anki import AnkiTask, export_note
        options = load_settings(window.settings, window.active_profile)
        if (not options.enabled or window._display_revision != window.revision
                or not window._result or not window._result.entries):
            return
        if self._browse_task is not None:
            return
        groups = window._headword_groups()
        headword = headword if headword is not None else next(iter(groups))
        if headword not in groups:
            return
        if self._pending(headword, options):
            return
        query = ""
        existing = self._existing_notes((window.revision, options, tuple(groups)))
        if (options.duplicate_action == "prevent" and self._saved_revision == window.revision
                and headword in self._saved_notes and self._saved_notes[headword][1] == options):
            note_id, saved_options = self._saved_notes[headword]
            query = f"nid:{note_id}"
        elif headword in existing and options.duplicate_action == "prevent":
            saved_options = options
            query = "nid:" + ",".join(map(str, existing[headword]))
        if query:
            self._browse_task = AnkiTask(
                lambda: AnkiClient(saved_options).call("guiBrowse", query=query),
                window.revision, self)
            self._browse_task.finished.connect(self._browse_finished)
            self.changed.emit()
            self._browse_task.thread.start()
            return
        if not options.deck or not options.model or not options.fields:
            window.open_settings()
            window._setup.show_anki()
            return
        entries, sentence = tuple(groups[headword]), window._result_context
        kanji = tuple(item for item in window._result.kanji if item.character in headword[0])
        selection, translation = window.browser.selected_text(), window._result.translation
        screenshot, directory = window._result_screenshot, window.directory
        encountered = window._result.text
        audio_clip = getattr(window.audio, "current_clip", None)
        operation = lambda: export_note(entries, sentence, selection, options, translation=translation,
                                        screenshot=screenshot, directory=directory, audio_clip=audio_clip, kanji=kanji,
                                        encountered=encountered)
        notify = window.settings.value(f"profiles/{window.active_profile}/anki/notifications", False, bool)
        self._queue.append((operation, (window.revision, headword, options, notify)))
        window.show_message("")
        self._start_save()
        self.changed.emit()

    def _start_save(self):
        window = self.window
        if self._task is not None or not self._queue or window._shutting_down:
            return
        from wordcel.gui.anki import AnkiTask
        operation, context = self._queue.pop(0)
        self._task = AnkiTask(operation, context, self)
        self._task.finished.connect(self._finished)
        self._task.thread.start()

    def _finished(self, response):
        window = self.window
        task, self._task = self._task, None
        task.deleteLater()
        (revision, headword, options, notify), note_id, error = response
        self._check_identity = None
        if not error:
            self._recent_saves[headword] = (note_id, options)
        if not error and revision == window.revision:
            if self._saved_revision != revision:
                self._saved_notes.clear()
            self._saved_revision = revision
            self._saved_notes[headword] = (note_id, options)
        if error:
            window.show_message(error if window._display_revision == revision else f"{headword[0]}: {error}")
        if notify:
            window.anki_notification.emit(f"{headword[0]}: {error}" if error else f"Added {headword[0]} to Anki")
        self._start_save()
        self.changed.emit()

    def _browse_finished(self, response):
        window = self.window
        self._browse_task.deleteLater()
        self._browse_task = None
        revision, _, error = response
        if window._display_revision == revision:
            window.show_message(error)
        self.changed.emit()
