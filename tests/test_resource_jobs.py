import threading
import unittest
from wordcel.gui.resource_jobs import ResourceJobs
from wordcel.gui.setup_operation import SetupRequest
from wordcel.dictionary.updates import DictionaryUpdate


class ResourceJobTests(unittest.TestCase):
    def test_shared_mutations_lock_across_distinct_item_keys(self):
        for first, second in (("dictionary-import", "dictionary:recommended"),
                              ("runtime:cpu", "translation:compact"),
                              ("engine:paddle", "ocr:paddle")):
            with self.subTest(first=first, second=second):
                jobs, owner, stop = ResourceJobs(), object(), threading.Event()
                self.assertTrue(jobs.claim((first,), owner, stop, "first"))
                self.assertFalse(jobs.claim((second,), object(), stop, "second"))
                jobs.finish(owner)
                self.assertTrue(jobs.claim((second,), object(), stop, "second"))

    def test_independent_resources_can_install_together(self):
        jobs, stop = ResourceJobs(), threading.Event()
        self.assertTrue(jobs.claim(("translation:compact",), object(), stop, "translation"))
        self.assertTrue(jobs.claim(("ocr:paddle",), object(), stop, "OCR"))
        self.assertFalse(jobs.claim(("all",), object(), stop, "export"))

    def test_immutable_update_batches_keep_their_identity(self):
        updates = tuple(DictionaryUpdate(str(i), "Words", "en", "a", "b") for i in range(2))
        request = SetupRequest.from_options(update=updates)
        self.assertEqual(request.kind, "update")
        self.assertEqual(request.job_keys, ("dictionary:0", "dictionary:1"))
        replacement = SetupRequest.from_options(update=("words.zip", "identity"))
        self.assertEqual(replacement.kind, "replace")
        self.assertEqual(replacement.job_keys, ("dictionary:identity",))
