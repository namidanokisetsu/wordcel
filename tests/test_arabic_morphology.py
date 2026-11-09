from dataclasses import replace
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import zipfile

from wordcel.dictionary.library import import_yomitan
from wordcel.dictionary.search import SearchEngine
from wordcel.language.arabic_analyzer import ArabicAnalysis, matches_entry
from wordcel.language.arabic_resources import PACKAGES, transfer_size


class ArabicMorphologyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        archive = root / "words.zip"
        rows = [["كتاب", "كِتَاب", "", "n", 0, ["book"]],
                ["كتب", "كَتَبَ", "", "v", 0, ["write"]],
                ["وبالكتب", "وَبِالْكُتُبِ", "", "n", 0, ["attested phrase"]]]
        with zipfile.ZipFile(archive, "w") as pack:
            pack.writestr("index.json", json.dumps(dict(title="Arabic", format=3, sourceLanguage="ar")))
            pack.writestr("term_bank_1.json", json.dumps(rows))
        import_yomitan(archive, root / "library")
        self.engine = SearchEngine(root / "library")
        self.engine._arabic_analyzer = Mock()
        self.reading = ArabicAnalysis(0, 7, "وبالكتب", "وَبِالْكُتُبِ", "كِتاب", "كِتاب", "noun",
                                      (("num", "p"),), ("wa_conj", "bi_prep", "Al_det"))

    def tearDown(self):
        self.engine._arabic_analyzer = None
        self.engine.close()
        self.temp.cleanup()

    def test_exact_entry_survives_and_analysis_adds_dictionary_lemma(self):
        self.engine._arabic_analyzer.candidates.return_value = (self.reading,)
        with patch("wordcel.language.arabic_resources.available", return_value=True):
            result = self.engine.search("وبالكتب", source="ar", morphology=True)
        self.assertEqual([e.term for e in result.entries], ["وبالكتب", "كتاب"])
        self.assertEqual(result.entries[0].route, "exact")
        self.assertEqual(result.entries[1].morphology, (self.reading,))
        self.assertIn("plural", result.entries[1].inflection[0])
        self.assertEqual(result.entries[1].reading, "كِتَاب")

    def test_analyzer_cannot_invent_dictionary_definitions_or_cross_spelling(self):
        self.engine._arabic_analyzer.candidates.return_value = (replace(self.reading, lemma="missing"),)
        with patch("wordcel.language.arabic_resources.available", return_value=True):
            result = self.engine.search("بالكتب", source="ar", morphology=True)
        self.assertFalse(result.entries)
        noun = self.engine.library.lookup("كتاب", "ar")[0]
        self.assertFalse(matches_entry(replace(self.reading, lemma="كتاب", vocalized_lemma="كُتَاب"), noun))

    def test_context_keeps_alternatives_and_publishes_a_fast_result(self):
        noun = replace(self.reading, surface="كتب", start=3, end=6)
        verb = replace(noun, lemma="كَتَب", vocalized_lemma="كَتَب", pos="verb", vocalized_surface="كَتَبَ",
                       provenance="Context suggestion")
        self.engine._arabic_analyzer.candidates.side_effect = [(noun,), (verb, noun)]
        updates = []
        with patch("wordcel.language.arabic_resources.available", return_value=True):
            result = self.engine.search("كتب", source="ar", morphology=True, context=("هو كتب رسالة", 3, 6),
                                        arabic_context=True, analysis_progress=updates.append)
        self.assertTrue(updates)
        self.assertEqual({e.term for e in result.entries}, {"كتب", "كتاب"})
        self.assertEqual(result.entries[0].term, "كتب")
        self.assertTrue(any(a.provenance == "Context suggestion" for e in result.entries for a in e.morphology))

    def test_worker_failure_preserves_dictionary_result(self):
        self.engine._arabic_analyzer.candidates.side_effect = RuntimeError("worker stopped")
        with patch("wordcel.language.arabic_resources.available", return_value=True):
            result = self.engine.search("كتاب", source="ar", morphology=True)
        self.assertEqual(result.entries[0].term, "كتاب")

    def test_cancelled_analysis_is_not_cached(self):
        cancelled = threading.Event()
        self.engine._arabic_analyzer.candidates.side_effect = InterruptedError("cancelled")
        with patch("wordcel.language.arabic_resources.available", return_value=True):
            with self.assertRaises(InterruptedError):
                self.engine.search("كتاب", source="ar", morphology=True, cancelled=cancelled)
        self.assertFalse(self.engine.cache)

    def test_transfer_cost_includes_only_missing_component_dependencies(self):
        with patch("wordcel.optional_runtimes.manifest", return_value={"features": {
                "arabic": [{"size": 100}], "arabic-context": [{"size": 200}]} }), \
                patch("wordcel.optional_runtimes.ready", return_value=False), \
                patch("wordcel.language.arabic_resources.model_ready", return_value=False):
            self.assertEqual(transfer_size(), 100 + PACKAGES["morphology"]["size"])
            self.assertEqual(transfer_size("context"), 300 + sum(p["size"] for p in PACKAGES.values()))
