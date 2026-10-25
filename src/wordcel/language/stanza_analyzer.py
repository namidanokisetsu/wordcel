from collections import OrderedDict
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path

from .analyzer import Token, WordAnalysis

STANZA_VERSION = "1.14.0"
RESOURCES_VERSION = "1.14.0"


def processors_for(language):
    return dict.fromkeys(("tokenize", "pos", "lemma"), "default")


def model_status(language, model_dir=None):
    """Inspect local files without importing Stanza or loading its models."""
    from wordcel.optional_runtimes import ready, activate
    if not ready("stanza"):
        return "Not installed"
    activate()
    try:
        if version("stanza") != STANZA_VERSION:
            return "Setup needed"
        version("torch")
    except PackageNotFoundError:
        return "Not installed"
    root = Path(model_dir or default_model_dir(language))
    try:
        resources = json.loads((root / "resources.json").read_text(encoding="utf-8"))
        while "alias" in resources[language]:
            language = resources[language]["alias"]
        resource = resources[language]
        defaults = resource["packages"]["default"]
        processors = {name: defaults[name] if package == "default" else package
                      for name, package in processors_for(language).items()}
        if "mwt" in defaults and "mwt" not in processors:
            processors["mwt"] = defaults["mwt"]
        required = set(processors.items())
        for name, package in processors.items():
            required.update((item["model"], item["package"])
                            for item in resource[name][package].get("dependencies", ()))
        if all((root / language / name / f"{package}.pt").is_file() and
               (root / language / name / f"{package}.pt").stat().st_size for name, package in required):
            return "Installed"
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return "Model needed"


def default_model_dir(language):
    from wordcel.utils.paths import paths
    return Path(paths.data_dir) / "languages" / language / "stanza" / RESOURCES_VERSION


def model_available(language):
    return language not in {"ja", "tr"} and model_status(language) == "Installed"


def setup_models(model_dir=None, *, language):
    from wordcel.optional_runtimes import require
    require("stanza")
    import stanza
    if stanza.__version__ != STANZA_VERSION:
        raise RuntimeError(f"Install stanza=={STANZA_VERSION} before setting up models")
    stanza.download(language, model_dir=str(model_dir or default_model_dir(language)),
                    package=None, processors=processors_for(language),
                    resources_version=RESOURCES_VERSION)


class StanzaAnalyzer:
    def __init__(self, model_dir=None, *, language):
        from wordcel.optional_runtimes import require
        require("stanza")
        import stanza
        if stanza.__version__ != STANZA_VERSION:
            raise RuntimeError(f"Expected stanza=={STANZA_VERSION}")
        self.language = language
        model_dir = Path(model_dir or default_model_dir(language)).resolve()
        processors = processors_for(language)
        configuration = ",".join(f"{name}={package}" for name, package in processors.items())
        self.identity = f"{language}:stanza:{STANZA_VERSION}:{RESOURCES_VERSION}:{configuration}:{model_dir}"
        self.pipeline = stanza.Pipeline(
            language, dir=str(model_dir), package=None, processors=processors,
            download_method=None, use_gpu=False, verbose=False,
            resources_version=RESOURCES_VERSION,
        )

    def _document(self, text):
        if not hasattr(self, "_documents"):
            self._documents = OrderedDict()
        if text not in self._documents:
            self._documents[text] = self.pipeline(text)
        self._documents.move_to_end(text)
        if len(self._documents) > 32:
            self._documents.popitem(last=False)
        return self._documents[text]


    def analyze(self, text):
        doc = self._document(text)
        tokens = []
        seen = set()
        for sentence in doc.sentences:
            for token in sentence.tokens:
                words = tuple(WordAnalysis(word.text, word.lemma if word.lemma not in {None, "", "_"} else word.text, word.upos)
                              for word in token.words if word.upos != "PUNCT")
                if not words:
                    continue
                start, end = token.start_char, token.end_char
                if (start, end) not in seen:
                    tokens.append(Token(start, end, words[0].lemma, words[0].pos, words))
                    seen.add((start, end))
        return tuple(tokens)
