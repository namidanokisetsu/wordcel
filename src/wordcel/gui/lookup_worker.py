"""Background dictionary lookup worker used by the popup and translation views."""
import threading

from PyQt6.QtCore import QObject, pyqtSignal

from wordcel.config.config import config
from wordcel.dictionary.search import SearchEngine
from wordcel.utils.timing import mark


class LookupWorker(QObject):
    completed = pyqtSignal(int, object)
    failed = pyqtSignal(int, str)
    languages = pyqtSignal(object)
    progress = pyqtSignal(int, object)
    translation_state = pyqtSignal(int, str)
    analysis_updated = pyqtSignal(int, object)

    def __init__(self, directory=None, engine_factory=None):
        super().__init__()
        self._factory = engine_factory or (lambda: SearchEngine(directory))
        self._condition = threading.Condition()
        self._pending = None
        self._active_cancel = None
        self._refresh = True
        self._stopped = False
        self._engine = None
        self._thread = threading.Thread(target=self._run, name="dictionary-search", daemon=True)

    def start(self):
        self._thread.start()

    def request(self, revision, text, source, foreign, translate=False, target=None, pair=None, translation_settings=None,
                morphology=False, context=None, exact_only=False, dictionary_options=None):
        self.cancel()
        mark("dispatch", revision, translation=translate)
        with self._condition:
            self._pending = (revision, text, source, foreign, translate, target, pair, translation_settings, morphology,
                              context, exact_only, dictionary_options, threading.Event())
            self._condition.notify()

    def cancel(self):
        with self._condition:
            if self._pending is not None:
                self._pending[-1].set()
            self._pending = None
            if self._active_cancel is not None:
                self._active_cancel.set()
            translator = getattr(self._engine, "translator", None)
        cancel = getattr(translator, "cancel", None)
        if callable(cancel):
            cancel()

    def refresh(self):
        with self._condition:
            self._refresh = True
            self._condition.notify()

    def shutdown(self):
        self.cancel()
        with self._condition:
            self._stopped = True
            self._pending = None
            self._condition.notify()

    def _emit(self, signal, *args):
        with self._condition:
            if self._stopped:
                return
        try:
            signal.emit(*args)
        except RuntimeError:
            pass  # The application may have closed while a local model was running.

    def _run(self):
        engine = None
        try:
            while True:
                with self._condition:
                    self._condition.wait_for(lambda: self._stopped or self._pending is not None or self._refresh)
                    if self._stopped:
                        return
                    pending, self._pending = self._pending, None
                    self._active_cancel = pending[-1] if pending else None
                    refresh, self._refresh = self._refresh, False
                try:
                    if engine is None:
                        engine = self._factory()
                        with self._condition:
                            self._engine = engine
                            if self._stopped:
                                return
                    elif refresh:
                        engine.refresh()
                    if refresh:
                        codes = sorted({meta["language"] for _, meta, _ in engine.library.packs})
                        self._emit(self.languages, codes)
                    if pending is not None:
                        revision, text, source, foreign, translate, target, pair, translation_settings, morphology, context, exact_only, dictionary_options, cancelled = pending
                        if isinstance(engine, SearchEngine):
                            before = engine.library.revision
                            engine.library.set_preferences(dictionary_options)
                            if before != engine.library.revision:
                                engine.cache.clear()
                        mark("dequeue", revision)
                        options = {"target": target} if target else {}
                        if pair:
                            options.update(pair=pair, translation_settings=translation_settings)
                        if morphology:
                            options["morphology"] = True
                        if context is not None:
                            options["context"] = context
                        if exact_only:
                            options["exact_only"] = True
                        if isinstance(engine, SearchEngine):
                            provisional = []
                            def analysis_progress(result):
                                if not cancelled.is_set():
                                    self._emit(self.analysis_updated if provisional else self.completed, revision, result)
                                    provisional.append(True)
                            options.update(cancelled=cancelled, request_id=revision, romaji=not translate,
                                           translation_progress=lambda result: self._emit(self.progress, revision, result),
                                           translation_state=lambda value: self._emit(self.translation_state, revision, value))
                            options["max_lookup_length"] = config.max_lookup_length
                            options["analysis_progress"] = analysis_progress
                        result = engine.search(text, source=source, foreign=foreign, translate=translate, **options)
                        mark("lookup_done", revision)
                        if not cancelled.is_set():
                            self._emit(self.analysis_updated if isinstance(engine, SearchEngine) and provisional else self.completed,
                                       revision, result)
                except Exception as error:
                    self._emit(self.failed, pending[0] if pending else -1, str(error))
        finally:
            if engine is not None:
                engine.close()
