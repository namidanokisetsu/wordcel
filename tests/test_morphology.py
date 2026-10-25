import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile

from wordcel.dictionary.library import import_yomitan
from wordcel.dictionary.search import SearchEngine
from wordcel.language.analyzer import Token, WordAnalysis
from wordcel.language.stanza_analyzer import StanzaAnalyzer, setup_models


class MorphologyTests(unittest.TestCase):
    def test_single_token_fallback_is_dictionary_bound_across_representative_languages(self):
        for language, surface, lemma in (("ru", "книгами", "книга"), ("uk", "книгами", "книга"),
                                         ("ko", "책을", "책"), ("de", "Bücher", "Buch")):
            with self.subTest(language=language):
                self.pack(language, [(lemma, ["book"], "")])
                analyzer = Mock()
                analyzer.analyze.return_value = (Token(0, len(surface), lemma),)
                self.engine._analyzer = (language, analyzer)
                result = self.engine.search(surface, source=language, morphology=True)
                self.assertEqual([(e.term, e.route) for e in result.entries], [(lemma, "lemma")])
                analyzer.analyze.return_value = (Token(0, len(surface), "missing lemma"),)
                self.engine.cache.clear()
                self.assertFalse(self.engine.search(surface, source=language, morphology=True).entries)

    def test_expanded_tokens_keep_all_words_and_one_original_source_span(self):
        analyzer = StanzaAnalyzer.__new__(StanzaAnalyzer)
        words = [SimpleNamespace(text=text, lemma=lemma, upos=pos) for text, lemma, pos in
                 (("و", "و", "CCONJ"), ("الكتاب", "كتاب", "NOUN"))]
        token = SimpleNamespace(start_char=3, end_char=10, text="والكتاب", words=words)
        analyzer.pipeline = Mock(return_value=SimpleNamespace(sentences=[SimpleNamespace(tokens=[token])]))
        result = analyzer.analyze("في والكتاب")
        self.assertEqual([(t.start, t.end) for t in result], [(3, 10)])
        self.assertEqual([(w.text, w.lemma, w.pos) for w in result[0].words],
                         [("و", "و", "CCONJ"), ("الكتاب", "كتاب", "NOUN")])
        self.assertEqual(analyzer.analyze("في والكتاب"), result)
        analyzer.pipeline.assert_called_once()

    def test_multiword_expansions_find_later_lemmas_without_replacing_exact_forms(self):
        for language, surface, words, expected in (
            ("ar", "والكتاب", ("و", "كتاب"), "كتاب"),
            ("fr", "du", ("de", "le"), "le"),
            ("es", "del", ("de", "el"), "el"),
            ("he", "בספר", ("ב", "ספר"), "ספר"),
        ):
            with self.subTest(language=language):
                self.pack(language, [(expected, ["fixture definition"], "")])
                original = "… " + surface + "."
                analyzer = Mock()
                analyzer.analyze.return_value = (Token(2, 2 + len(surface), words[0], words=tuple(
                    WordAnalysis(word, word) for word in words)),)
                self.engine._analyzer = (language, analyzer)
                result = self.engine.search(surface, source=language, morphology=True,
                                            context=(original, 2, 2 + len(surface)))
                self.assertEqual([(e.term, e.route) for e in result.entries], [(expected, "lemma")])
                self.assertEqual((result.text, result.matched_length), (surface, len(surface)))
                # A partial selection must not acquire lemmas from the whole token.
                self.assertFalse(self.engine.search(surface[:-1], source=language, morphology=True,
                    context=(original, 2, 1 + len(surface))).entries)
                self.pack(language, [(surface, ["exact entry"], ""), (expected, ["lemma entry"], "")])
                with patch.object(self.engine, "_lemma_lookup", side_effect=AssertionError("Exact first")):
                    self.assertEqual(self.engine.search(surface, source=language, morphology=True).entries[0].term, surface)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.engine = SearchEngine(self.root / "library")
        self.turkish_available = patch("wordcel.language.turkish_analyzer.available", return_value=False)
        self.turkish_available.start()
        self.addCleanup(self.turkish_available.stop)

    def tearDown(self):
        self.engine.close()
        self.temp.cleanup()

    def pack(self, language, rows):
        archive = self.root / (language + ".zip")
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("index.json", json.dumps(dict(title=language, format=3, sourceLanguage=language)))
            zf.writestr("term_bank_1.json", json.dumps([[term, "", "", rules, 0, definitions, -1, ""]
                                                      for term, definitions, rules in rows]))
        import_yomitan(archive, self.root / "library")
        self.engine.refresh()

    def test_off_exact_and_imported_forms_never_initialize_models(self):
        self.pack("tr", [("kitap", ["book"], ""), ("kitaplar", [["kitap", ["plural"]]], "")])
        with patch("wordcel.language.stanza_analyzer.StanzaAnalyzer") as factory:
            self.engine.search("kitaplarımdan", source="tr")
            self.assertEqual(self.engine.search("kitap", source="tr", morphology=True).entries[0].term, "kitap")
            self.assertEqual(self.engine.search("kitaplar", source="tr", morphology=True).entries[0].route, "form")
            factory.assert_not_called()

    def test_context_span_preserves_original_text_and_bounds_lemma_lookup(self):
        self.pack("de", [("Buch", ["book"], ""), ("lesen", ["read"], "")])
        analyzer = Mock()
        analyzer.analyze.return_value = (Token(0, 3, "das"), Token(4, 10, "Buch"), Token(11, 16, "lesen"))
        self.engine._analyzer = ("de", analyzer)
        text = "Die Bücher lesen."
        result = self.engine.search("Bücher", source="de", morphology=True, context=(text, 4, 10))
        self.assertEqual([e.term for e in result.entries], ["Buch"])
        self.assertEqual(result.entries[0].route, "lemma")
        self.assertEqual(result.text, "Bücher")
        analyzer.analyze.assert_called_once_with(text)
        self.engine.search("Bücher", source="de", morphology=True, context=(text, 4, 10))
        analyzer.analyze.assert_called_once()

    def test_automatic_detection_can_recover_a_profile_language_lemma(self):
        self.pack("de", [("laufen", ["run"], "")])
        analyzer = Mock()
        analyzer.analyze.return_value = (Token(0, 4, "laufen"),)
        self.engine._analyzer = ("de", analyzer)
        result = self.engine.search("lief", foreign="de", pair=("de", "en"), morphology=True)
        self.assertEqual((result.source, result.target), ("de", "en"))
        self.assertEqual(result.entries[0].term, "laufen")

    def test_japanese_keeps_rule_based_deconjugation_with_option_enabled(self):
        self.pack("ja", [("食べる", ["eat"], "v1")])
        with patch("wordcel.language.stanza_analyzer.StanzaAnalyzer") as factory:
            self.assertEqual(self.engine.search("食べました", source="ja", morphology=True).entries[0].term, "食べる")
            factory.assert_not_called()

    def test_turkish_verb_stems_find_infinitives_without_forms_or_nominal_homographs(self):
        from wordcel.language.turkish_analyzer import TrAnalysis
        self.pack("tr", [("okumak", ["read"], ""), ("ok", ["arrow"], ""),
                         ("oku", ["imperative: read"], ""), ("gelmek", ["come"], ""),
                         ("dinlemek", ["listen"], ""), ("kitap", ["book"], "")])
        analyzer = Mock()
        self.engine._turkish_analyzer = analyzer
        for text, expected in (("okuyorlar", "okumak"), ("geldik", "gelmek"), ("dinliyor", "dinlemek")):
            with self.subTest(text=text):
                analyzer.candidates.return_value = (TrAnalysis(expected, "VERB"),)
                result = self.engine.search(text, source="tr", morphology=True)
                self.assertEqual([entry.term for entry in result.entries], [expected])
        analyzer.candidates.return_value = (TrAnalysis("kitap", "NOUN"),)
        self.assertEqual(self.engine.search("kitaplar", source="tr", morphology=True).entries[0].term, "kitap")

    def test_missing_models_are_retryable_after_refresh_without_download(self):
        self.pack("de", [("Buch", ["book"], "")])
        with patch("wordcel.language.stanza_analyzer.default_model_dir", return_value=self.root), \
                patch("wordcel.language.stanza_analyzer.StanzaAnalyzer") as factory:
            with self.assertRaisesRegex(RuntimeError, "Base-form model unavailable"):
                self.engine.search("Bücher", source="de", morphology=True)
            factory.assert_not_called()
            self.assertTrue(self.engine.search("Buch", source="de", morphology=True).entries)
            (self.root / "resources.json").write_text("{}")
            factory.return_value.analyze.return_value = (Token(0, 6, "Buch"),)
            self.engine.refresh()
            self.assertTrue(self.engine.search("Bücher", source="de", morphology=True).entries)

    def test_shared_stanza_setup_keeps_downloads_explicit(self):
        stanza = SimpleNamespace(__version__="1.14.0", download=Mock(), Pipeline=Mock())
        with patch.dict("sys.modules", {"stanza": stanza}):
            setup_models(self.root, language="de")
            StanzaAnalyzer(self.root, language="de")
        self.assertEqual(stanza.download.call_args.args, ("de",))
        self.assertEqual(stanza.Pipeline.call_args.args, ("de",))
        self.assertEqual(stanza.Pipeline.call_args.kwargs["processors"],
                         {"tokenize": "default", "pos": "default", "lemma": "default"})
        self.assertIsNone(stanza.download.call_args.kwargs["package"])
        self.assertIsNone(stanza.Pipeline.call_args.kwargs["package"])
        self.assertIsNone(stanza.Pipeline.call_args.kwargs["download_method"])

    def test_model_status_checks_dependencies_without_loading_stanza(self):
        from wordcel.language.stanza_analyzer import model_status
        resources = {"ru": {"packages": {"default": {"tokenize": "t", "pos": "p", "lemma": "l"}},
            "tokenize": {"t": {}}, "lemma": {"l": {}},
            "pos": {"p": {"dependencies": [{"model": "pretrain", "package": "vectors"}]}}}}
        (self.root / "resources.json").write_text(json.dumps(resources))
        for name, package in (("tokenize", "t"), ("pos", "p"), ("lemma", "l")):
            folder = self.root / "ru" / name
            folder.mkdir(parents=True)
            (folder / f"{package}.pt").write_bytes(b"fixture")
        with patch("wordcel.language.stanza_analyzer.version", return_value="1.14.0"):
            self.assertEqual(model_status("ru", self.root), "Model needed")
            folder = self.root / "ru/pretrain"
            folder.mkdir()
            (folder / "vectors.pt").write_bytes(b"fixture")
            self.assertEqual(model_status("ru", self.root), "Installed")

    def test_explicit_installer_uses_current_environment_and_only_selected_language(self):
        from importlib.metadata import PackageNotFoundError
        from wordcel.scripts.setup_morphology import install
        with patch("wordcel.scripts.setup_morphology.version", side_effect=PackageNotFoundError), \
                patch("wordcel.scripts.setup_morphology._run") as run, \
                patch("wordcel.scripts.setup_morphology.sys.platform", "win32"):
            install("ru")
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(commands[0], ["-m", "ensurepip"])
        self.assertIn("https://download.pytorch.org/whl/cpu", commands[1])
        self.assertIn("stanza==1.14.0", commands[2])
        self.assertEqual(commands[-1], ["-m", "wordcel.scripts.setup_morphology", "ru"])

    def test_installer_cancellation_finishes_current_step_without_launching_next(self):
        import threading
        from importlib.metadata import PackageNotFoundError
        from wordcel.scripts.setup_morphology import install
        cancelled = threading.Event()
        process = Mock(returncode=0)
        def finish():
            cancelled.set()
            return "", None
        process.communicate.side_effect = finish
        with patch("wordcel.scripts.setup_morphology.version", side_effect=PackageNotFoundError), \
                patch("wordcel.scripts.setup_morphology.sys.executable", "C:/env/pythonw.exe"), \
                patch("wordcel.scripts.setup_morphology.subprocess.Popen", return_value=process) as launch:
            with self.assertRaisesRegex(InterruptedError, "cancelled"):
                install("ru", cancelled=cancelled)
            launch.assert_called_once()
            self.assertEqual(Path(launch.call_args.args[0][0]).name, "python.exe")
            process.terminate.assert_not_called()
