"""Command dispatch stays independent of desktop/model initialization."""
from contextlib import redirect_stderr
import io
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from wordcel.main import main


class CommandTests(unittest.TestCase):
    def test_default_and_search_forward_only_desktop_arguments(self):
        search = Mock(return_value=7)
        with patch.dict(sys.modules, {"wordcel.scripts.quick_lookup": SimpleNamespace(main=search)}):
            self.assertEqual(main([]), 7)
            search.assert_called_once_with([])
            search.reset_mock()
            self.assertEqual(main(["search", "--no-ocr", "cat"]), 7)
            search.assert_called_once_with(["--no-ocr", "cat"])

    def test_import_preserves_explicit_library_and_language(self):
        importer = Mock(return_value="fixture.sqlite3")
        with patch.dict(sys.modules, {"wordcel.dictionary.library": SimpleNamespace(import_yomitan=importer)}), patch("builtins.print"):
            self.assertEqual(main(["import-dictionaries", "a.zip", "b.zip", "--language", "ja", "--directory", "library"]), 0)
        self.assertEqual([call.args for call in importer.call_args_list],
                         [("a.zip", "library", "ja"), ("b.zip", "library", "ja")])

    def test_unknown_command_exits_without_starting_the_desktop(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            main(["unknown-command"])
        self.assertEqual(error.exception.code, 2)
