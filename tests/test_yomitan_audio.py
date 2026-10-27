import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from time import monotonic
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication

from wordcel.audio.sources import source_order
from wordcel.audio.worker import AudioRequest, AudioWorker
from wordcel.audio.yomitan import YomitanAudio, audio_list, custom_url
from wordcel.dictionary.library import Entry
from wordcel.gui.audio_sources import AudioSources, _SourceDialog
from wordcel.gui.lookup_audio import LookupAudio


def descriptor(kind="custom-json", url="http://localhost:5050/?term={term}&reading={reading}&language={language}"):
    return {"type": kind, "url": url, "voice": ""}


class YomitanProviderTests(unittest.TestCase):
    def test_exact_custom_json_schema(self):
        sources = [{"url": "https://example.org/audio.mp3", "name": "Speaker"}, {"url": "http://localhost/audio"}]
        self.assertEqual(audio_list({"type": "audioSourceList", "audioSources": sources}), sources)
        self.assertEqual(audio_list({"type": "audioSourceList", "audioSources": []}), [])
        for value in (sources, {}, {"audioSources": sources}, {"type": "wrong", "audioSources": []},
                      {"type": "audioSourceList", "audioSources": [], "extra": True},
                      *({"type": "audioSourceList", "audioSources": [source]} for source in (
                          {}, {"url": 42}, {"url": "url", "name": None}, {"url": "url", "extra": True}))):
            with self.subTest(value=value), self.assertRaises(ValueError):
                audio_list(value)

    def test_url_placeholders_preserve_query_boundaries_and_unknown_markers(self):
        url = custom_url("http://localhost/?term={term}&reading={reading}&language={language}&key=literal%26key&x={unknown}",
                         "猫 & 犬", "ねこ", "ja")
        self.assertEqual(parse_qs(urlsplit(url).query), {
            "term": ["猫 & 犬"], "reading": ["ねこ"], "language": ["ja"],
            "key": ["literal&key"], "x": ["{unknown}"],
        })

    def test_custom_json_candidate_fallback_names_and_source_cache_identity(self):
        client = YomitanAudio()
        listing = {"type": "audioSourceList", "audioSources": [
            {"url": "https://example.org/broken.mp3", "name": "First"},
            {"url": "https://example.org/good", "name": "Second"}]}
        with patch.object(client, "_fetch", side_effect=[listing, ValueError("invalid audio"), b"OggSfixture"]) as fetch:
            result = client.lookup("猫", "ja", "jpn", reading="ねこ", source=descriptor())
            self.assertEqual(result[:3], ("audio.ogg", "Second", b"OggSfixture"))
            self.assertEqual(client.lookup("猫", "ja", "jpn", reading="ねこ", source=descriptor()), result)
            self.assertEqual(fetch.call_count, 3)
        with patch.object(client, "_fetch", return_value={"type": "audioSourceList", "audioSources": []}) as fetch:
            self.assertIsNone(client.lookup("猫", "ja", "jpn", reading="ねこ", source=descriptor(url="https://other.org/")))
            fetch.assert_called_once()

    def test_direct_url_and_mp4_audio(self):
        client = YomitanAudio()
        with patch.object(client, "_fetch", return_value=b"\x00\x00\x00\x18ftypM4A fixture") as fetch:
            result = client.lookup("ev", "tr", "tur", source=descriptor("custom"))
            self.assertEqual(result[0], "audio.m4a")
            self.assertEqual(fetch.call_count, 1)
            self.assertTrue(fetch.call_args.kwargs["audio"])

    def test_jpod_kana_query_and_invalid_audio_hash(self):
        client = YomitanAudio()
        candidates = client._candidates(descriptor("jpod101"), "かな", "かな", "ja", lambda: False, monotonic() + 10)
        self.assertEqual(parse_qs(urlsplit(candidates[0]["url"]).query), {"kana": ["かな"]})
        with patch.object(client, "_fetch", return_value=b"ID3invalid"), patch("wordcel.audio.yomitan.sha256") as digest:
            digest.return_value.hexdigest.return_value = "ae6398b5a27bc8c0a771df6c907ade794be15518174773c58c7c7ddd17098906"
            self.assertIsNone(client.lookup("missing", "ja", "jpn", source=descriptor("jpod101")))
        with patch.object(client, "_fetch") as fetch:
            self.assertIsNone(client.lookup("house", "en", "eng", source=descriptor("jpod101")))
            self.assertIsNone(client.lookup("house", "en", "eng", source=descriptor("jisho")))
            fetch.assert_not_called()

    def test_jisho_exact_headword_reading_and_relative_url(self):
        html = '<audio id="audio_生:なま"><source src="//cdn.example.org/wrong.mp3"></audio>' \
               '<audio id="audio_生:せい"><source src="/right.mp3?a=1&amp;b=2"></audio>'
        client = YomitanAudio()
        with patch.object(client, "_fetch", side_effect=[html, b"ID3fixture"]) as fetch:
            self.assertIsNotNone(client.lookup("生", "ja", "jpn", reading="せい", source=descriptor("jisho")))
            self.assertEqual(fetch.call_args.args[0], "https://jisho.org/right.mp3?a=1&b=2")

    def test_languagepod_exact_turkish_word_post_and_japanese_reading(self):
        html = '<div class="dc-result-row"><span class="dc-vocab">evler</span><audio><source src="wrong.mp3"></audio></div>' \
               '<div class="dc-result-row"><span class="dc-vocab">ev</span><audio><source src="/ev.mp3"></audio></div>'
        client = YomitanAudio()
        with patch.object(client, "_fetch", side_effect=[html, b"ID3fixture"]) as fetch:
            self.assertIsNotNone(client.lookup("ev", "tr", "tur", source=descriptor("language-pod-101")))
            self.assertEqual(fetch.call_args_list[0].args[0], "https://www.turkishclass101.com/learningcenter/reference/dictionary_post")
            self.assertEqual(fetch.call_args_list[0].kwargs["data"]["search_query"], "ev")
            self.assertEqual(fetch.call_args.args[0], "https://www.turkishclass101.com/ev.mp3")
        html = '<div class="dc-result-row"><span class="dc-vocab_kana">なま</span><audio><source src="/wrong.mp3"></audio></div>' \
               '<div class="dc-result-row"><span class="dc-vocab_kana">せい</span><audio><source src="/right.mp3"></audio></div>'
        with patch.object(client, "_fetch", side_effect=[html, b"ID3fixture"]) as fetch:
            self.assertIsNotNone(client.lookup("生", "ja", "jpn", reading="せい", source=descriptor("language-pod-101")))
            self.assertTrue(fetch.call_args.args[0].endswith("/right.mp3"))

    def test_wikimedia_providers_are_independent_and_retain_attribution(self):
        client = YomitanAudio()
        info = {"query": {"pages": {"1": {"title": "File:LL-Q256 (tur)-Speaker-ev.wav", "imageinfo": [{
            "url": "https://upload.wikimedia.org/audio.wav", "user": "Speaker",
            "extmetadata": {"LicenseShortName": {"value": "CC0"}}}]}}}}
        with patch.object(client, "_fetch", return_value=info):
            self.assertIsNone(client.lookup("ev", "tr", "tur", source=descriptor("wiktionary")))
        with patch.object(client, "_fetch", side_effect=[info, b"RIFFfixture"]):
            result = client.lookup("ev", "tr", "tur", source=descriptor("lingua-libre"))
            self.assertEqual((result[1], result[3]), ("Lingua Libre", "Speaker · CC0"))

    def test_cancelled_download_does_not_publish_or_cache(self):
        client = YomitanAudio()
        cancelled = [False]
        def fetch(*args, **kwargs):
            cancelled[0] = True
            return b"ID3fixture"
        with patch.object(client, "_fetch", side_effect=fetch):
            self.assertIsNone(client.lookup("ev", "tr", "tur", source=descriptor("custom"), cancelled=lambda: cancelled[0]))
        self.assertFalse(client.cache)

    def test_worker_delivers_named_exportable_clip_and_drops_stale_result(self):
        callback = Mock()
        worker = AudioWorker(Mock(), Mock(), result_callback=callback)
        request = AudioRequest(4, ("ev", ""), "", (), online=True, source=descriptor())
        worker._latest_request = request
        worker._online = Mock()
        worker._online.lookup.return_value = ("audio.mp3", "Speaker", b"ID3fixture", "", "")
        worker._online_result(request)
        self.assertEqual(callback.call_args.args[1].source, "Speaker")
        self.assertEqual(callback.call_args.args[1].data, b"ID3fixture")
        self.assertEqual(worker._online.lookup.call_args.kwargs["source"], descriptor())
        callback.reset_mock()
        worker.cancel()
        worker._online_result(request)
        callback.assert_not_called()


class LocalAudioHTTPTests(unittest.TestCase):
    def test_real_yomitan_endpoint_redirect_audio_and_invalid_response(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                path = urlsplit(self.path).path
                if path == "/redirect":
                    self.send_response(302)
                    self.send_header("Location", "/audio")
                    self.end_headers()
                    return
                if path == "/list":
                    body = json.dumps({"type": "audioSourceList", "audioSources": [
                        {"name": "Local speaker", "url": base + "/redirect"}]}).encode()
                else:
                    body = b"RIFFfixture" if path == "/audio" else b"<html>not audio</html>"
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        base = f"http://127.0.0.1:{server.server_port}"
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            client = YomitanAudio()
            result = client.lookup("猫", "ja", "jpn", source=descriptor(url=base + "/list?term={term}"))
            self.assertEqual(result[:3], ("audio.wav", "Local speaker", b"RIFFfixture"))
            self.assertIsNone(client.lookup("ev", "tr", "tur", source=descriptor("custom", base + "/invalid")))
            with self.assertRaises(InterruptedError):
                client._fetch(base, external=True, cancelled=lambda: True, deadline=monotonic() + 10)
            with self.assertRaises(ValueError):
                client._fetch("file:///audio.mp3", external=True, cancelled=lambda: False, deadline=monotonic() + 10)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)


class YomitanSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_named_profile_defaults_and_saved_choices(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = QSettings(str(Path(folder) / "settings.ini"), QSettings.Format.IniFormat)
            for language, expected in (
                    ("ja", ["jpod101", "language-pod-101", "jisho", "wiktionary", "lingua-libre", "tts"]),
                    ("tr", ["language-pod-101", "lingua-libre", "wiktionary", "tts"]),
                    ("fr", ["language-pod-101", "lingua-libre", "wiktionary", "tts"]),
                    ("zh-hant", ["language-pod-101", "lingua-libre", "wiktionary", "tts"]),
                    ("fil", ["language-pod-101", "lingua-libre", "wiktionary", "tts"]),
                    ("uk", ["lingua-libre", "wiktionary", "tts"])):
                settings.setValue("profiles/named/language", language)
                self.assertEqual(source_order(settings, "named"), expected)
            for saved in (["tts", "online"], []):
                settings.setValue("profiles/named/audio_priority", saved)
                self.assertEqual(source_order(settings, "named"), saved)

    def test_builtin_sources_visible_without_enabling_saved_disabled_choices(self):
        from wordcel.audio.sources import source_type
        from PyQt6.QtCore import Qt
        sources = AudioSources()
        try:
            saved = [descriptor("jisho"), "tts"]
            sources.load(saved, "", language="ja")
            kinds = [source_type(sources.items.item(i).data(Qt.ItemDataRole.UserRole))
                     for i in range(sources.items.count())]
            self.assertEqual(kinds.count("jisho"), 1)
            self.assertIn("jpod101", kinds)
            self.assertIn("language-pod-101", kinds)
            self.assertEqual(sources.order(), saved)
            sources.load([], "", language="tr")
            kinds = [source_type(sources.items.item(i).data(Qt.ItemDataRole.UserRole))
                     for i in range(sources.items.count())]
            self.assertNotIn("jisho", kinds)
            self.assertIn("language-pod-101", kinds)
            self.assertEqual(sources.order(), [])
        finally:
            sources.shutdown()
            sources.deleteLater()

    def test_descriptors_round_trip_and_keep_active_profile_and_entry_language(self):
        with tempfile.TemporaryDirectory() as folder, patch("wordcel.gui.lookup_audio.AudioWorker"):
            path = str(Path(folder) / "settings.ini")
            settings = QSettings(path, QSettings.Format.IniFormat)
            settings.setValue("profiles/tr/audio_priority", [descriptor(), "tts"])
            settings.sync()
            settings = QSettings(path, QSettings.Format.IniFormat)
            self.assertEqual(source_order(settings, "tr"), [descriptor(), "tts"])
            audio = LookupAudio()
            try:
                with patch.object(audio, "_speak", return_value=True) as speak:
                    audio.play(Entry("house", "house", "", "EN-TR", "en", ("ev",)), 1, settings, profile="tr")
                    request = audio.worker.submit.call_args.args[0]
                    self.assertEqual(request.source, descriptor())
                    self.assertEqual(request.language, "en")
                    audio._audio_result(request, None)
                    speak.assert_called_once_with("house", "en", 80)
            finally:
                audio.shutdown()
                audio.deleteLater()

    def test_import_reorder_disable_and_database_refresh_keep_custom_descriptors(self):
        with patch("wordcel.gui.audio_sources.AudioWorker"):
            sources = AudioSources()
            try:
                sources.load([descriptor(), "tts"], "android.db", prefer_local=True)
                sources.received("android.db", ["jpod"])
                self.assertEqual(sources.order(), ["db:jpod", descriptor(), "tts"])
                sources.append_sources([descriptor("jisho"), descriptor()])
                self.assertEqual(sources.order(), [descriptor("jisho"), descriptor(), "db:jpod", "tts"])
                sources.items.setCurrentRow(3)
                sources.move(-1)
                self.assertIn(descriptor(), sources.order())
                sources.load([], "")
                self.assertEqual(sources.order(), [])
                sources.append_sources([descriptor(), descriptor("jisho")])
                self.assertEqual(sources.order(), [descriptor(), descriptor("jisho")])
            finally:
                sources.shutdown()
                sources.deleteLater()

    def test_custom_dialog_accepts_unchanged_yomitan_url_and_validates_scheme(self):
        dialog = _SourceDialog(descriptor(), None)
        try:
            self.assertEqual(dialog.source(), descriptor())
            self.assertTrue(dialog.ok.isEnabled())
            dialog.url.setText("file:///tmp/audio")
            self.assertFalse(dialog.ok.isEnabled())
        finally:
            dialog.deleteLater()

    def test_full_yomitan_settings_import_selects_profile_and_retains_source_order(self):
        value = {"profiles": [{"name": "Japanese", "options": {"audio": {"sources": [descriptor("jisho"), descriptor()]}}}]}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "yomitan-settings.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            sources = AudioSources()
            try:
                with patch("wordcel.gui.audio_sources.QFileDialog.getOpenFileName", return_value=(str(path), "")), \
                        patch("wordcel.gui.audio_sources.QInputDialog.getItem", return_value=("1. Japanese", True)):
                    sources.import_sources()
                self.assertEqual(sources.order(), [descriptor("jisho"), descriptor()])
            finally:
                sources.shutdown()
                sources.deleteLater()

    def test_tts_word_and_reading_types_use_named_voice(self):
        with tempfile.TemporaryDirectory() as folder, patch("wordcel.gui.lookup_audio.AudioWorker"):
            settings = QSettings(str(Path(folder) / "settings.ini"), QSettings.Format.IniFormat)
            audio = LookupAudio()
            try:
                for kind, expected in (("text-to-speech", "猫"), ("text-to-speech-reading", "ねこ")):
                    source = {"type": kind, "url": "", "voice": "Installed voice"}
                    with patch.object(audio, "_speak", return_value=True) as speak:
                        audio.play(Entry("cat", "猫", "ねこ", "Fixture", "ja", ("cat",)), 1, settings, source=source)
                        speak.assert_called_once_with(expected, "ja", 80, voice="Installed voice")
                audio.worker.submit.assert_not_called()
            finally:
                audio.shutdown()
                audio.deleteLater()

    def test_custom_source_menu_enabled_without_database(self):
        from wordcel.gui.quick_lookup import QuickLookupWindow
        with tempfile.TemporaryDirectory() as folder, patch("wordcel.gui.quick_lookup.QMenu") as menu:
            settings = QSettings(str(Path(folder) / "settings.ini"), QSettings.Format.IniFormat)
            settings.setValue("profiles/tr/audio_priority", [descriptor()])
            window = SimpleNamespace(_result=SimpleNamespace(entries=[SimpleNamespace(language="tr")]),
                                     preferred_foreign="tr", settings=settings, audio_button=Mock(),
                                     audio=None, play_audio=Mock(), open_audio_settings=Mock())
            QuickLookupWindow.audio_source_menu(window, None)
            menu.return_value.addAction.return_value.setEnabled.assert_called_once_with(True)
