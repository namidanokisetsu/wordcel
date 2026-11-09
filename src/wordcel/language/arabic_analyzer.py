"""Small immutable Arabic analyses and a shared, lazy process client."""
from dataclasses import dataclass
import threading

from .arabic import spelling, lexical_vowels_agree, has_vowels


@dataclass(frozen=True)
class ArabicAnalysis:
    start: int
    end: int
    surface: str
    vocalized_surface: str
    lemma: str
    vocalized_lemma: str
    pos: str
    features: tuple = ()
    proclitics: tuple = ()
    enclitics: tuple = ()
    root: str = ""
    stem: str = ""
    provenance: str = "CALIMA MSA"
    score: float = 0


_LABELS = {"p": "past", "i": "imperfect", "c": "imperative", "s": "singular", "d": "dual",
           "p-num": "plural", "m": "masculine", "f": "feminine", "a": "active", "p-vox": "passive",
           "n": "nominative", "a-cas": "accusative", "g": "genitive", "d-stt": "definite",
           "i-stt": "indefinite", "c-stt": "construct"}


def grammar_labels(readings):
    labels = []
    for reading in readings:
        features = dict(reading.features)
        parts = [reading.vocalized_surface, reading.pos]
        for key in ("asp", "per", "gen", "num", "vox", "cas", "stt"):
            value = features.get(key)
            if value and value not in {"na", "0", "u"}:
                label = _LABELS.get(value + "-" + key, _LABELS.get(value, value))
                if key == "per":
                    label = {"1": "first person", "2": "second person", "3": "third person"}.get(value, value)
                parts.append(label)
        if reading.proclitics:
            parts.append("prefixes: " + " + ".join(_clitic(value) for value in reading.proclitics))
        if reading.enclitics:
            parts.append("suffix: " + " + ".join(_clitic(value) for value in reading.enclitics))
        if reading.root:
            parts.append("root: " + reading.root.replace(".", " "))
        if reading.provenance == "Context suggestion":
            parts.append("context suggestion")
        label = " · ".join(dict.fromkeys(part for part in parts if part))
        if label not in labels:
            labels.append(label)
    return tuple(labels)


def _clitic(value):
    return {"Al_det": "ال", "wa_conj": "و", "wa_sub": "و", "fa_conj": "ف", "bi_prep": "ب", "li_prep": "ل",
            "ka_prep": "ك", "sa_fut": "س", "1s_poss": "my", "1p_poss": "our", "2ms_poss": "your (m.)",
            "2fs_poss": "your (f.)", "3ms_poss": "his", "3fs_poss": "her", "3mp_poss": "their"}.get(
                value, value.replace("_", " "))


def matches_entry(reading, entry):
    if spelling(entry.term) != spelling(reading.lemma):
        return False
    vocalized = entry.reading if spelling(entry.reading) == spelling(entry.term) else entry.term
    if has_vowels(vocalized) and not lexical_vowels_agree(vocalized, reading.vocalized_lemma):
        return False
    rules = set(entry.rules)
    if rules and reading.pos == "verb" and not rules.intersection({"v", "vs", "vk"}):
        return False
    if reading.pos != "verb" and rules == {"v"}:
        return False
    return True


_guard = threading.RLock()
_worker = None
_identity = None


def close_worker():
    global _worker, _identity
    with _guard:
        if _worker is not None:
            _worker.close()
        _worker = _identity = None


class ArabicAnalyzer:
    def candidates(self, text, start, end, *, contextual=False, cancelled=None):
        if not 0 <= start < end <= len(text):
            return ()
        from .arabic_resources import available, model_root
        from wordcel.optional_runtimes import runtime_site
        from .arabic_worker import ArabicWorker
        if not available():
            return ()
        context_installed = available("context")
        contextual = contextual and context_installed
        root = model_root().parent
        identity = (str(root), tuple((root / name / "complete.json").stat().st_mtime_ns
                                   for name in (model_root().name, model_root("context").name)
                                   if (root / name / "complete.json").exists()), context_installed)
        global _worker, _identity
        with _guard:
            if cancelled is not None and cancelled.is_set():
                raise InterruptedError("Arabic analysis cancelled")
            if _worker is None or _worker.closed or identity != _identity:
                close_worker()
                _worker = ArabicWorker(root, runtime_site("arabic"),
                                       runtime_site("arabic-context") if context_installed else None)
                _identity = identity
            try:
                rows = _worker.analyze(dict(text=text, start=start, end=end, contextual=contextual), cancelled)
                return tuple(ArabicAnalysis(**dict(row, features=tuple(tuple(p) for p in row["features"]),
                                                  proclitics=tuple(row["proclitics"]), enclitics=tuple(row["enclitics"])))
                             for row in rows)
            except (OSError, EOFError, RuntimeError, InterruptedError):
                close_worker()
                raise
