import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import zipfile

from wordcel.dictionary.library import Library, import_yomitan
from wordcel.dictionary.updates import check_update, replace_dictionary, update_batch, DictionaryUpdate


class DictionaryUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.directory = self.root / "library"
        self.original = import_yomitan(self.archive("Words [old]", "release-a"), self.directory)
        self.library = Library(self.directory)
        self.addCleanup(self.library.close)
        self.metadata = dict(self.library.packs[0][1])
        self.identity = self.metadata["resource_id"]

    def archive(self, title, revision, language="en", invalid=False):
        path = self.root / (revision + ".zip")
        with zipfile.ZipFile(path, "w") as bundle:
            bundle.writestr("index.json", json.dumps(dict(title=title, revision=revision, format=3,
                sourceLanguage=language, indexUrl="https://example.org/index.json", downloadUrl="https://example.org/words.zip")))
            bundle.writestr("term_bank_1.json", json.dumps([["cat", "", "", "", 0, [revision]]] if not invalid else [False]))
        return path

    def test_publisher_revisions_are_opaque_and_unknown_sources_are_manual(self):
        fetch = Mock(return_value=dict(revision="release-b", downloadUrl="https://example.org/words.zip"))
        available = check_update(self.metadata, fetch)
        self.assertEqual(available.status, "Update available")
        self.assertEqual(available.available, "release-b")
        fetch.return_value["revision"] = "release-a"
        self.assertEqual(check_update(self.metadata, fetch).status, "Up to date")
        self.assertEqual(check_update({**self.metadata, "index_url": ""}, fetch).status, "Replace from ZIP")

    def test_dated_titles_keep_identity_and_all_readers_refresh_with_their_preferences(self):
        second = Library(self.directory)
        self.addCleanup(second.close)
        second.set_preferences(dict(order=[self.identity], disabled=[self.identity]))
        archive = self.archive("Words [new]", "release-b")
        replacement = replace_dictionary(archive, self.directory, self.identity)
        self.assertTrue(self.original.exists())
        self.assertNotEqual(replacement, self.original)
        self.assertEqual(self.library.lookup("cat", "en")[0].glosses(), ["release-a"])
        self.library.refresh_if_changed()
        second.refresh_if_changed()
        self.assertEqual(self.library.lookup("cat", "en")[0].glosses(), ["release-b"])
        self.assertFalse(second.lookup("cat", "en"))
        self.assertEqual(self.library.packs[0][1]["resource_id"], self.identity)
        self.assertEqual(len(self.library.packs), 1)
        restarted = Library(self.directory)
        try:
            self.assertEqual(restarted.packs[0][1]["title"], "Words [new]")
        finally:
            restarted.close()

    def test_failed_cancelled_or_incompatible_replacement_keeps_old_version(self):
        for archive, cancel in ((self.archive("Invalid", "bad", invalid=True), None),
                                (self.archive("Wrong language", "wrong", language="tr"), None),
                                (self.archive("Cancelled", "cancel"), lambda: True)):
            with self.assertRaises((ValueError, InterruptedError)):
                replace_dictionary(archive, self.directory, self.identity, cancelled=cancel)
            self.library.refresh_if_changed()
            self.assertEqual(self.library.lookup("cat", "en")[0].glosses(), ["release-a"])
        self.assertEqual(list(self.directory.glob(".import-*")), [])

    def test_update_all_keeps_successes_and_reports_individual_failures(self):
        updates = [DictionaryUpdate(str(i), str(i), "en", "a", "b", "https://example.org/words.zip") for i in range(3)]
        with patch("wordcel.dictionary.updates.install_update", side_effect=[None, ValueError("Invalid ZIP"), None]) as install:
            status, changed = update_batch(updates, self.directory, Mock(), threading.Event())
        self.assertTrue(changed)
        self.assertEqual(install.call_count, 3)
        self.assertIn("1: Invalid ZIP", status)


if __name__ == "__main__":
    unittest.main()
