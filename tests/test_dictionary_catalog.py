import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

from wordcel.dictionary.catalog import install_recommended, recommendations
from wordcel.dictionary.library import Library
from wordcel.language.support import AVAILABLE_LANGUAGES, DICTIONARY_LANGUAGES, TRANSLATION_LANGUAGES


class DictionaryCatalogTests(unittest.TestCase):
    def test_japanese_pitch_recommendation_uses_wadoku_update_index(self):
        japanese = recommendations("ja")
        self.assertEqual([item.title for item in japanese],
                         ["JMdict", "Wiktionary · English definitions", "Kanji · KANJIDIC", "Frequency · Jiten Global", "Pitch · WaDoku"])
        pitch = japanese[-1]
        self.assertEqual(pitch.pack_title, "Wadoku Pitch Accent")
        self.assertEqual(pitch.index_url,
                         "https://github.com/classicsc/wadoku-pitch-dictionary-for-yomitan/releases/latest/download/index.json")
        self.assertTrue(pitch.matches({"language": "ja", "title": "Wadoku Pitch Accent"}))
        wiktionary = japanese[1]
        self.assertIn("/dict/ja/en/wty-ja-en.zip", wiktionary.url)
        self.assertTrue(wiktionary.matches({"language": "ja", "title": "wty-ja-en"}))

    def test_jiten_global_has_publisher_updates_and_does_not_match_media_lists(self):
        frequency = next(item for item in recommendations("ja") if item.pack_title == "Jiten")
        self.assertEqual(frequency.url, "https://api.jiten.moe/api/frequency-list/download")
        self.assertEqual(frequency.index_url, "https://api.jiten.moe/api/frequency-list/index")
        self.assertTrue(frequency.matches({"language": "ja", "title": "Jiten"}))
        self.assertFalse(frequency.matches({"language": "ja", "title": "Jiten (Anime)"}))
        self.assertFalse(frequency.matches({"language": "ja", "title": "BCCWJ"}))

    def test_every_offered_language_has_a_dictionary_or_managed_translation(self):
        self.assertEqual(AVAILABLE_LANGUAGES, DICTIONARY_LANGUAGES | TRANSLATION_LANGUAGES)
        self.assertNotIn("zz", AVAILABLE_LANGUAGES)
        self.assertEqual(recommendations("zz"), ())
        for language in DICTIONARY_LANGUAGES:
            self.assertTrue(recommendations(language))

    def test_download_installs_the_selected_language_and_cleans_temporary_archive(self):
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, "w") as archive:
            archive.writestr("index.json", json.dumps({"title": "English", "format": 3, "sourceLanguage": "en"}))
            archive.writestr("term_bank_1.json", json.dumps([["cat", "", "", "", 1, ["feline"], 0, ""]]))
        with tempfile.TemporaryDirectory() as folder, patch("wordcel.dictionary.catalog.urlopen", return_value=io.BytesIO(payload.getvalue())):
            path = install_recommended(recommendations("en")[0], folder, lambda _: None, threading.Event())
            self.assertEqual(list(Path(folder).iterdir()), [path])
            library = Library(folder)
            try:
                self.assertEqual(library.lookup("cat", "en")[0].term, "cat")
            finally:
                library.close()

    def test_mandarin_uses_broad_chinese_archive_in_its_own_profile(self):
        from wordcel.dictionary.search import SearchEngine
        resource = recommendations("cmn")[0]
        self.assertIn("/dict/zh/en/wty-zh-en.zip", resource.url)
        self.assertEqual(resource.language, "cmn")
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, "w") as archive:
            archive.writestr("index.json", json.dumps({"title": "wty-zh-en", "format": 3, "sourceLanguage": "zh"}))
            archive.writestr("term_bank_1.json", json.dumps([["你好", "nǐ hǎo", "", "", 1, ["hello"], 0, ""]]))
        with tempfile.TemporaryDirectory() as folder, patch("wordcel.dictionary.catalog.urlopen", return_value=io.BytesIO(payload.getvalue())):
            install_recommended(resource, folder, lambda _: None, threading.Event())
            engine = SearchEngine(folder)
            try:
                self.assertTrue(resource.matches(engine.library.packs[0][1]))
                result = engine.search("你好", source="cmn", foreign="cmn")
                self.assertEqual(result.source, "cmn")
                self.assertEqual(result.entries[0].language, "cmn")
                self.assertEqual(result.entries[0].term, "你好")
                self.assertEqual(result.text[:result.matched_length], "你好")
                self.assertEqual(engine.library.lookup("你好", "zh"), ())
            finally:
                engine.close()
