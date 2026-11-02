"""Validated setup requests and worker dispatch shared by feature pages."""
from dataclasses import dataclass
import threading
from PyQt6.QtCore import QObject, pyqtSignal


def setup_resource(key):
    if key.startswith("engine:"):
        return "ocr" if key == "engine:paddle" else "morphology"
    return {"dictionary": "dictionaries", "recommended": "dictionaries", "runtime": "translation",
            "stanza": "morphology", "font": "fonts", "cache": "all"}.get(key.split(":", 1)[0], key.split(":", 1)[0])


@dataclass(frozen=True)
class SetupRequest:
    kind: str
    value: object = None
    language: str | None = None
    backend: str = "automatic"

    def __post_init__(self):
        kinds = {"import", "recommended", "update", "replace", "bundle", "engine", "asset", "remove_language",
                 "fonts", "ocr", "morphology", "remove", "translation", "custom_model"}
        if self.kind not in kinds:
            raise ValueError("Unknown setup operation")
        if self.kind in {"import", "recommended", "update"} and not isinstance(self.value, tuple):
            raise ValueError("Setup batches must be tuples")
        if self.kind in {"bundle", "replace"} and (not isinstance(self.value, tuple) or len(self.value) != 2):
            raise ValueError("Incomplete setup request")
        if self.kind == "bundle" and self.value[0] not in {"export", "import"}:
            raise ValueError("Choose resource import or export")
        if self.kind not in {"import", "recommended", "update"} and not self.value:
            raise ValueError("Incomplete setup request")
        if self.kind == "recommended":
            from wordcel.dictionary.catalog import RecommendedDictionary
            if any(not isinstance(item, RecommendedDictionary) for item in self.value):
                raise ValueError("Choose dictionary recommendations")
        if self.kind == "update":
            from wordcel.dictionary.updates import DictionaryUpdate
            if any(not isinstance(item, DictionaryUpdate) for item in self.value):
                raise ValueError("Choose dictionary updates")
        if self.kind in {"translation", "engine", "asset", "remove_language", "ocr", "morphology", "remove"} \
                and not isinstance(self.value, str):
            raise ValueError("Invalid setup resource")
        if self.kind == "translation":
            from wordcel.translation_catalog import MODELS
            from wordcel.translation_models import is_custom_profile
            if self.value not in {*MODELS, "runtime"} and not is_custom_profile(self.value):
                raise ValueError("Choose a translation model")
        if self.kind == "custom_model":
            if not isinstance(self.value, dict):
                raise ValueError("Choose a GGUF model")
            if "local_path" in self.value:
                if set(self.value) != {"local_path"} or not isinstance(self.value["local_path"], str):
                    raise ValueError("Choose one GGUF file")
            else:
                from wordcel.translation_models import validate_custom_spec
                validate_custom_spec(None, self.value)
        if self.backend not in {"automatic", "cpu", "vulkan", "cuda"}:
            raise ValueError("Unknown translation backend")

    @classmethod
    def from_options(cls, paths=(), language=None, backend="automatic", **options):
        known = {"profile", "recommended", "remove", "morphology", "ocr", "fonts", "asset", "remove_language", "update", "bundle", "engine", "custom_model"}
        if options.keys() - known:
            raise ValueError("Unknown setup option")
        selected = [(key, value) for key, value in options.items() if value is not None and value is not False]
        if len(selected) + bool(paths) > 1:
            raise ValueError("Choose one setup operation")
        if not selected:
            return cls("import", tuple(paths), language, backend)
        kind, value = selected[0]
        if kind == "profile":
            kind = "translation"
        elif kind == "recommended":
            value = tuple(value) if isinstance(value, (list, tuple)) else (value,)
        elif kind == "update":
            from wordcel.dictionary.updates import DictionaryUpdate
            if isinstance(value, (list, tuple)) and all(isinstance(item, DictionaryUpdate) for item in value):
                value = tuple(value)
            elif isinstance(value, tuple) and len(value) == 2 and isinstance(value[1], str):
                kind = "replace"
            else:
                raise ValueError("Choose dictionary updates or one replacement ZIP")
        return cls(kind, value, language, backend)

    @property
    def resource(self):
        if self.kind in {"bundle", "remove_language"}:
            return "all"
        if self.kind == "custom_model":
            return "translation"
        if self.kind == "asset":
            return setup_resource(self.value)
        if self.kind == "engine":
            return setup_resource("engine:" + self.value)
        return {"import": "dictionaries", "recommended": "dictionaries", "remove": "dictionaries",
                "update": "dictionaries", "replace": "dictionaries"}.get(self.kind, self.kind)

    @property
    def job_keys(self):
        if self.resource == "all":
            return ("all",)
        if self.kind == "custom_model":
            return ("translation:custom-model",)
        if self.kind == "asset":
            return (self.value,)
        if self.kind == "import":
            return ("dictionary-import",)
        if self.kind in {"recommended", "update"}:
            return tuple("dictionary:" + item.identity for item in self.value)
        if self.kind == "replace":
            return ("dictionary:" + self.value[1],)
        from wordcel.gui.language_setup import SetupTask
        from wordcel.gui.resource_jobs import task_key
        kind = {"translation": "translation", "remove": "dictionary"}.get(self.kind, self.kind)
        if kind == "dictionary":
            return ("dictionary:" + self.value,)
        return (task_key(SetupTask(kind, "", "ja" if kind == "fonts" else self.value)),)


class SetupOperation(QObject):
    progress = pyqtSignal(str)
    finished = pyqtSignal(str, bool)
    refresh = pyqtSignal()

    def __init__(self, request, directory):
        super().__init__()
        if not isinstance(request, SetupRequest):
            raise TypeError("Expected a validated setup request")
        self.request, self.directory = request, directory
        self.resource, self.job_keys = request.resource, request.job_keys
        self.installed_component = ""
        self.cancelled = threading.Event()
        self.thread = threading.Thread(target=self._run, name="dictionary-setup", daemon=True)
        from wordcel.gui.resource_jobs import jobs
        self.jobs = jobs

    def start(self):
        if not self.jobs.claim(self.job_keys, self, self.cancelled, "Preparing download…"):
            self.finished.emit("Resource already downloading.", False)
            return
        self.thread.start()

    def _emit(self, signal, *args):
        if signal == self.progress:
            self.jobs.progress(self, args[0])
        elif signal == self.finished:
            self.jobs.finish(self)
        try:
            signal.emit(*args)
        except RuntimeError:
            pass

    def _run(self):
        try:
            self._emit(self.finished, *self._execute())
        except InterruptedError:
            self._emit(self.finished, "Download cancelled.", False)
        except Exception as error:
            self._emit(self.finished, str(error), False)

    def _execute(self):
        request = self.request
        kind, value = request.kind, request.value
        progress = lambda text: self._emit(self.progress, text)
        if kind == "engine":
            from wordcel.optional_runtimes import install, restart_needed
            install(value, progress, self.cancelled)
            return ("Engine installed. Restart Wordcel to use it." if value == "stanza" and restart_needed() else "Engine installed."), True
        if kind == "bundle":
            from wordcel.resource_bundle import export_bundle, import_bundle
            mode, path = value
            operation = export_bundle if mode == "export" else import_bundle
            operation(path, self.directory, progress, self.cancelled)
            return ("Resources exported.", False) if mode == "export" else ("Resources imported. Restart Wordcel to use new engines.", True)
        if kind in {"update", "replace", "import"}:
            from wordcel.dictionary.import_job import background_import
            return background_import(list(value) if kind == "import" else [], self.directory, request.language, None,
                                     progress, self.cancelled, update=list(value) if kind == "update" else value if kind == "replace" else None)
        if kind == "recommended":
            from wordcel.dictionary.import_job import background_import
            changed, errors = False, []
            for dictionary in value:
                if self.cancelled.is_set():
                    break
                try:
                    status, installed = background_import([], self.directory, dictionary.language, dictionary, progress, self.cancelled)
                    changed |= installed
                    if not installed:
                        errors.append(f"{dictionary.title}: {status}")
                except Exception as error:
                    errors.append(f"{dictionary.title}: {error}")
            status = "Download cancelled." if self.cancelled.is_set() else "Dictionaries installed."
            return "\n".join(errors) or status, changed
        if kind in {"asset", "remove_language"}:
            from wordcel.data_assets import remove_asset, remove_language_data
            remove = remove_language_data if kind == "remove_language" else remove_asset
            remove(value, self.directory, lambda: self._emit(self.refresh), self.cancelled)
            return "Data removed.", True
        if kind == "fonts":
            from wordcel.scripts.setup_stroke_order_font import install
            install(progress, self.cancelled)
            return "Stroke-order font installed.", True
        if kind == "ocr":
            from wordcel.scripts.setup_ocr import install
            self.installed_component = install(value, progress, self.cancelled)
            return "OCR ready. Scan with your selected shortcut.", True
        if kind == "morphology":
            from wordcel.scripts.setup_morphology import install
            from wordcel.optional_runtimes import restart_needed
            install(value, progress, self.cancelled)
            return ("Word-form support installed. Restart Wordcel to use it." if restart_needed() else "Base-form model installed."), True
        if kind == "remove":
            from wordcel.dictionary.library import remove_dictionary
            remove_dictionary(self.directory, value, lambda: self._emit(self.refresh), self.cancelled)
            return "Dictionary removed.", True
        if kind == "custom_model":
            from wordcel.translation_models import local_model, model_identity
            from wordcel.scripts.translation_server import install_model
            path = value.get("local_path")
            spec = local_model(path, self.cancelled) if path else value
            install_model(profile=model_identity(spec), model_spec=spec, local_model=path,
                          backend=request.backend, progress=progress, cancelled=self.cancelled)
            return "Model installed.", True
        if kind == "translation":
            from wordcel.scripts.translation_server import install_model
            options = dict(runtime_only=True) if value == "runtime" else dict(profile=value)
            install_model(backend=request.backend, progress=progress, cancelled=self.cancelled, **options)
            return "Model installed. Translate when ready.", True
        raise ValueError("Unknown setup operation")
