"""CPU-only Arabic inference using the existing authenticated worker transport."""
from dataclasses import asdict
from multiprocessing.connection import Client
import os
from pathlib import Path
import re
import sys
import tempfile
import time

from wordcel.ocr.paddle_worker import PaddleWorker, _address


def _command(address, authkey, root, use_onnx, runtime_site):
    executable = Path(sys.executable)
    if executable.name.lower() == "pythonw.exe":
        executable = executable.with_name("python.exe")
    args = ["--arabic-worker", "--arabic-address", address, "--arabic-auth", authkey.hex(),
            "--arabic-runtime", str(runtime_site), "--arabic-model-dir", str(root)]
    if getattr(sys, "frozen", False):
        if sys.platform == "win32" and executable.with_name("wordcel-cli.exe").exists():
            executable = executable.with_name("wordcel-cli.exe")
        return [str(executable), *args]
    return [str(executable), "-m", "wordcel.scripts.quick_lookup", *args]


class ArabicWorker(PaddleWorker):
    def __init__(self, root, runtime_site):
        try:
            super().__init__(root, False, runtime_site, command_factory=_command)
        except RuntimeError as error:
            raise RuntimeError(str(error).replace("Paddle OCR", "Arabic analysis").replace("Paddle worker", "Arabic worker")) from error

    @property
    def closed(self):
        return super().closed or self._process is None or self._process.poll() is not None

    def analyze(self, payload, cancelled=None):
        with self._lock:
            self._connection.send(("predict", payload))
            deadline = time.monotonic() + 30
            while not self._connection.poll(.05):
                if cancelled is not None and cancelled.is_set():
                    self.close()
                    raise InterruptedError("Arabic analysis cancelled")
                if self._process.poll() is not None or time.monotonic() >= deadline:
                    self.close()
                    raise RuntimeError("Arabic analysis worker stopped or timed out")
            kind, result = self._connection.recv()
            if kind != "result":
                raise RuntimeError("Arabic analysis failed: " + str(result))
            return result

    def close(self):
        # Windows venv launchers own a second Python process. Retain its handle
        # so cancellation frees the actual model even if the launcher exits.
        handle, kernel = None, None
        if sys.platform == "win32" and getattr(self, "pid", None):
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = kernel.OpenProcess(0x100001, False, self.pid)
        try:
            super().close()
        finally:
            if handle:
                if kernel.WaitForSingleObject(handle, 0) == 0x102:
                    kernel.TerminateProcess(handle, 1)
                kernel.CloseHandle(handle)


class ExactAnalyzer:
    def __init__(self, database):
        from camel_tools.morphology.analyzer import Analyzer
        from camel_tools.utils.charmap import CharMapper
        self.strict = Analyzer(database, norm_map=CharMapper({"ـ": ""}), backoff="NONE", cache_size=128)
        # CALIMA's stem index folds these letters. Recover its exact spellings
        # from diac before admitting candidates; never expose folded homographs.
        self.index = Analyzer(database, backoff="NONE", cache_size=128)

    def __getattr__(self, name):
        return getattr(self.strict, name)

    def analyze(self, surface):
        from .arabic import compatible_vowels, explicit_long_vowels
        found = {}
        for row in (*self.strict.analyze(surface), *self.index.analyze(surface)):
            vocalized = explicit_long_vowels(row.get("diac", ""))
            if compatible_vowels(surface, vocalized) and row.get("lex") and row.get("pos") != "punc":
                row = dict(row, diac=vocalized)
                found.setdefault(tuple(sorted(row.items())), row)
        return list(found.values())


class Engine:
    def __init__(self, root):
        from camel_tools.morphology.database import MorphologyDB
        self.root = Path(root)
        database = MorphologyDB(str(self.root / "morphology-0.4.0/morphology.db"))
        self.analyzer = ExactAnalyzer(database)

    def analyze(self, request):
        from .arabic import compatible_vowels
        from .arabic_analyzer import ArabicAnalysis
        from .profiles import get_profile
        text, start, end = request["text"], request["start"], request["end"]
        if not isinstance(text, str) or len(text) > 2000 or not 0 <= start < end <= len(text):
            return []
        surface = text[start:end]
        spans = get_profile("ar").word_spans(text)
        if (start, end) not in spans or len(surface) > 64:
            return []
        analyses = self.analyzer.analyze(surface)
        analyses.sort(key=lambda row: (-float(row.get("pos_lex_logprob", -99)),
                                       -float(row.get("lex_logprob", -99)), row.get("diac", "")))
        result, seen = [], set()
        for row in analyses:
            if not compatible_vowels(surface, row.get("diac", "")):
                continue
            lemma = re.sub(r"_\d+$", "", row.get("lex", ""))
            features = tuple((key, str(row[key])) for key in ("asp", "per", "gen", "num", "vox", "cas", "stt", "mod") if key in row)
            prefixes = tuple(row[key] for key in ("prc3", "prc2", "prc1", "prc0") if row.get(key) not in {None, "0", "na"})
            suffixes = tuple(row[key] for key in ("enc0",) if row.get(key) not in {None, "0", "na"})
            identity = lemma, row.get("diac"), row.get("pos"), features, prefixes, suffixes
            if identity in seen or not lemma:
                continue
            seen.add(identity)
            result.append(asdict(ArabicAnalysis(start, end, surface, row.get("diac", surface), lemma, lemma,
                                                row.get("pos", ""), features, prefixes, suffixes,
                                                row.get("root", ""), row.get("stem", ""))))
            if len(result) == 64:
                break
        return result


def serve(address, authkey, runtime_site, root):
    sys.path.insert(0, str(Path(runtime_site).resolve()))
    catalogue = tempfile.TemporaryDirectory(prefix="wordcel-camel-")
    Path(catalogue.name, "catalogue.json").write_text(
        '{"version":"1.6","packages":{},"components":{}}', encoding="utf-8")
    os.environ.update(CAMELTOOLS_DATA=catalogue.name, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                      TOKENIZERS_PARALLELISM="false", OMP_NUM_THREADS="2", MKL_NUM_THREADS="2")
    connection = Client(_address(address), authkey=authkey)
    try:
        engine = Engine(root)
        connection.send(("ready", {"pid": os.getpid()}))
        while connection.poll(120):
            command, payload = connection.recv()
            if command == "close":
                connection.send(("closed", None))
                return
            if command != "predict":
                raise ValueError("Unknown Arabic worker command")
            try:
                connection.send(("result", engine.analyze(payload)))
            except Exception as error:
                connection.send(("error", f"{type(error).__name__}: {error}"))
    except (EOFError, BrokenPipeError):
        pass
    except Exception as error:
        connection.send(("error", f"{type(error).__name__}: {error}"))
    finally:
        connection.close()
        catalogue.cleanup()
