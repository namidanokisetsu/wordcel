from contextlib import closing
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from wordcel.dictionary.library import Library, import_yomitan


class DefinitionTagTests(unittest.TestCase):
    def test_outer_bundle_has_actionable_error_and_does_not_publish_a_pack(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "bundle.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("nested/dictionary.zip", b"not extracted")
            with self.assertRaisesRegex(ValueError, "Extract this bundle"):
                import_yomitan(archive, root / "library")
            self.assertEqual(list((root / "library").iterdir()), [])

    def test_plain_names_retain_expanded_tags_once_without_polluting_search(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "names.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("index.json", json.dumps(dict(title="Names", format=3, sourceLanguage="ja")))
                zf.writestr("tag_bank_1.json", json.dumps([["fem", "name", 4, "female given name", 0]]))
                zf.writestr("term_bank_1.json", json.dumps([
                    ["あかねこ", "あかねこ", "fem", "", 0, ["Akaneko", "Another reading"], -1, ""]]))
            import_yomitan(archive, root / "library")
            with closing(Library(root / "library")) as library:
                entry = library.lookup("あかねこ")[0]
                text = json.dumps(entry.definitions)
                self.assertEqual(text.count("female given name"), 1)
                self.assertIn("Akaneko", text)
                self.assertEqual(entry.definitions[1], "Another reading")
                self.assertEqual(library.reverse("Akaneko")[0].term, "あかねこ")
                self.assertFalse(library.reverse("female"))

    def test_structured_sense_tags_are_not_duplicated(self):
        from wordcel.dictionary.metadata import tagged_definitions
        definitions = [{"type": "structured-content", "content": [
            {"tag": "span", "data": {"class": "tag"}, "content": "noun"}, "meaning"]}]
        self.assertIs(tagged_definitions(definitions, "n", {"n": "noun"}), definitions)


    def test_nontext_definitions_are_preserved(self):
        from wordcel.dictionary.metadata import tagged_definitions
        definitions = [{"type": "image", "path": "images/picture.png"}]
        self.assertEqual(tagged_definitions(definitions, "picture", {}), definitions)

    def test_tags_keep_legacy_grammar_section_boundaries(self):
        from wordcel.dictionary.metadata import tagged_definitions
        from wordcel.gui.gloss_content import normalize_definitions
        definitions = [{"type": "structured-content", "content": [
            "【 Meaning 】", {"tag": "div", "content": "at intervals of"},
            "【 Explanation 】", {"tag": "div", "content": "explanation"}]}]
        tagged = tagged_definitions(definitions, "おきに", {})
        normalized = normalize_definitions(tagged, "Bunpro Dictionary")
        self.assertEqual([node["data"]["content"] for node in normalized[0]["content"]
                          if isinstance(node, dict) and node.get("tag") == "div"],
                         ["glosses", "explanation"])
