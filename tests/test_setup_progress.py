import io
import json
import pickle
from pathlib import Path
from queue import Queue
import re
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

from wordcel.dictionary.catalog import install_recommended, recommendations
from wordcel.dictionary.import_job import _worker
from wordcel.dictionary.library import import_yomitan
from wordcel.utils.progress import content_length, download_progress, TransferRate


TERM = ["word", "", "", "", 0, ["meaning"], 0, ""]
FREQUENCY = ["word", "freq", 10]
PITCH = ["word", "pitch", {"reading": "word", "pitches": [{"position": 0}]}]
KANJI = ["字", "ジ", "あざ", "", ["character"], {}]


class SetupProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.directory = self.root / "library"

    def archive(self, banks):
        path = self.root / "dictionary.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("index.json", json.dumps(dict(title="Fixture", format=3, sourceLanguage="ja")))
            for name, rows in banks.items():
                archive.writestr(name + ".json", json.dumps(rows))
        return path

    def test_import_percentages_cover_definitions_and_metadata_only_packs(self):
        variants = [{"term_bank_1": [TERM]}, {"term_meta_bank_1": [FREQUENCY]},
                    {"term_meta_bank_1": [PITCH]}, {"kanji_bank_1": [KANJI]},
                    {"term_bank_1": [TERM], "term_bank_2": [],
                     "term_meta_bank_1": [FREQUENCY, PITCH], "kanji_bank_1": [KANJI]}]
        for index, banks in enumerate(variants):
            with self.subTest(banks=banks):
                messages = []
                directory = self.directory / str(index)

                def progress(text):
                    messages.append(text)
                    if text.endswith("100%"):
                        self.assertTrue(list(directory.glob("*.sqlite3")))

                import_yomitan(self.archive(banks), directory, progress=progress)
                percentages = [int(re.search(r"(\d+)%$", text)[1]) for text in messages]
                self.assertEqual(percentages, sorted(percentages))
                self.assertEqual((percentages[0], percentages[-1]), (0, 100))
                self.assertEqual(percentages.count(100), 1)
                self.assertTrue(any(text.startswith("Indexing ") for text in messages))

    def test_single_large_bank_reports_progress_before_bank_completion(self):
        for name, row in (("term_bank_1", TERM), ("term_meta_bank_1", FREQUENCY)):
            with self.subTest(bank=name):
                messages = []
                import_yomitan(self.archive({name: [row] * 2501}), self.directory / name, progress=messages.append)
                percentages = {int(re.search(r"(\d+)%$", text)[1]) for text in messages}
                self.assertTrue(any(0 < percent < 30 for percent in percentages))
                self.assertIn(100, percentages)

    def test_cancellation_never_reports_complete_or_publishes_a_pack(self):
        cancelled = threading.Event()
        messages = []

        def progress(text):
            messages.append(text)
            if not text.endswith("0%"):
                cancelled.set()

        path = self.archive({"term_bank_1": [TERM], "term_bank_2": [TERM]})
        with self.assertRaises(InterruptedError):
            import_yomitan(path, self.directory, progress=progress, cancelled=cancelled.is_set)
        self.assertFalse(any(text.endswith("100%") for text in messages))
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_worker_delivers_completion_even_when_updates_are_throttled(self):
        path = self.archive({"term_bank_1": [TERM]})
        messages = Queue()
        with patch("wordcel.dictionary.import_job.monotonic", return_value=1):
            _worker([path], self.directory, "ja", None, messages, threading.Event())
        updates = []
        while not messages.empty():
            updates.append(messages.get_nowait())
        self.assertIn(("progress", "Importing Fixture · 100%"), updates)
        self.assertTrue(updates[-1][1][1])

    def test_download_uses_percentage_when_length_is_known_and_bytes_otherwise(self):
        payload = self.archive({"term_bank_1": [TERM]}).read_bytes()
        for length in (str(len(payload)), None, "unknown", "-1"):
            with self.subTest(length=length):
                response = io.BytesIO(payload)
                response.headers = {"Content-Length": length} if length is not None else {}
                messages = []
                with patch("wordcel.dictionary.catalog.urlopen", return_value=response):
                    install_recommended(recommendations("ja")[0], self.directory, messages.append, threading.Event())
                downloads = [text for text in messages if text.startswith("Downloading ") and " · " in text]
                self.assertTrue(downloads)
                if length == str(len(payload)):
                    self.assertTrue(downloads[0].endswith("0%"))
                    self.assertTrue(downloads[-1].endswith("100%"))
                else:
                    self.assertTrue(all(text.endswith(" MB") for text in downloads))

    def test_unknown_and_overstated_download_sizes_have_readable_progress(self):
        self.assertEqual(content_length(io.BytesIO()), 0)
        self.assertEqual(download_progress("Dictionary", 2 * 1024**2, 0), "Downloading Dictionary · 2 MB")
        self.assertEqual(download_progress("Dictionary", 20, 10), "Downloading Dictionary · 100%")

    def test_download_bytes_survive_dictionary_process_queue_serialization(self):
        value = pickle.loads(pickle.dumps(download_progress("Words", 500, 1000)))
        self.assertEqual(value, "Downloading Words · 50%")
        self.assertEqual((value.label, value.received, value.size), ("Words", 500, 1000))

    def test_transfer_rate_excludes_resumed_bytes_and_resets_for_new_files(self):
        rate = TransferRate()
        rate.add(download_progress("Model", 8000, 10000), 0)
        self.assertIsNone(rate.speed(0))
        rate.add(download_progress("Model", 9000, 10000), 2)
        self.assertEqual(rate.speed(2), 500)
        self.assertIsNone(rate.speed(7))
        rate.add(download_progress("Model", 100, 10000), 8)
        self.assertIsNone(rate.speed(8))
        rate.add(download_progress("Other", 300, 10000), 9)
        self.assertIsNone(rate.speed(9))


class SetupProgressUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_worker_burst_coalesces_and_delivers_latest_bytes_on_gui_thread(self):
        from wordcel.gui.setup_progress import ProgressRelay
        from PyQt6.QtCore import QObject
        parent = QObject()
        relay = ProgressRelay(parent)
        self.addCleanup(parent.deleteLater)
        received = []
        relay.updated.connect(lambda value: received.append((threading.get_ident(), value)))
        def emit():
            for index in range(10000):
                relay.post(download_progress("Model", index, 10000))
        worker = threading.Thread(target=emit)
        worker.start()
        worker.join()
        self.assertFalse(received)
        relay.stop()
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0][0], threading.get_ident())
        self.assertEqual(received[0][1].received, 9999)

    def test_download_eta_is_specific_to_transfer_and_clears_for_verification(self):
        from wordcel.gui.setup_progress import SetupProgress
        view = SetupProgress()
        self.addCleanup(view.deleteLater)
        with patch("wordcel.gui.setup_progress.monotonic", return_value=0):
            view.setText(download_progress("Model", 8000, 10000))
        with patch("wordcel.gui.setup_progress.monotonic", return_value=2):
            view.setText(download_progress("Model", 9000, 10000))
            self.assertIn("500 B/s", view.detail.text())
            self.assertIn("left to download", view.detail.text())
            self.assertEqual(view.bar.value(), 90)
            self.assertIn("downloaded", view.bar.format())
            view.setText("Verifying model…")
            self.assertEqual(view.bar.maximum(), 0)
            self.assertNotIn("left", view.detail.text())
            view.setText("Ready.")
            self.assertFalse(view.timer.isActive())
            self.assertTrue(view.bar.isHidden())

    def test_unknown_size_and_stalled_transfer_never_invent_percent_or_eta(self):
        from wordcel.gui.setup_progress import SetupProgress
        view = SetupProgress()
        self.addCleanup(view.deleteLater)
        with patch("wordcel.gui.setup_progress.monotonic", return_value=0):
            view.setText(download_progress("OCR", 1024, 0))
            self.assertEqual(view.bar.maximum(), 0)
            self.assertIn("1.0 KB", view.detail.text())
            self.assertNotIn("left", view.detail.text())
        with patch("wordcel.gui.setup_progress.monotonic", return_value=6):
            view.refresh_detail()
            self.assertIn("Waiting for data", view.detail.text())
            self.assertNotIn("/s", view.detail.text())
