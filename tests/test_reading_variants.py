import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from copy import deepcopy
from dataclasses import replace
from itertools import product
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

from PyQt6.QtCore import QPoint, QRect, QSettings, QUrl
from PyQt6.QtWidgets import QApplication, QMenu

from wordcel.anki import AnkiSettings, note_values
from wordcel.config.config import config
from wordcel.dictionary.kanji import KanjiEntry
from wordcel.dictionary.library import Entry, Library, import_yomitan
from wordcel.dictionary.metadata import Frequency
from wordcel.dictionary.pitch import Pitch
from wordcel.dictionary.search import SearchResult
from wordcel.gui.lookup_render import group_headwords, render_result
from wordcel.gui.quick_lookup import LocalDictionaryBrowser, QuickLookupWindow
from wordcel.gui.ruby import READING, RUBY
from wordcel.gui.typography import document_font
from test_quick_lookup import FakeEngine, disclosure


READINGS = ("だいじょうぶ", "だいじょぶ")
WORD = "大丈夫"


def variants(sources=("JMdict", "Second"), definitions=("safe; all right",)):
    return tuple(Entry(f"{source}:{index}", WORD, reading, source, "ja", tuple(definitions),
                       frequencies=(Frequency("Corpus", 106 + index, str(106 + index)),),
                       pitches=(Pitch("Pitch", reading, 3),) if index == 0 else ())
                 for source in sources for index, reading in enumerate(READINGS))


class ReadingGroupTests(unittest.TestCase):
    def test_complete_dictionary_matches_merge_without_changing_records(self):
        entries = variants()
        before = deepcopy(entries)
        groups = group_headwords(entries)
        self.assertEqual(list(groups), [(WORD, READINGS[0])])
        self.assertEqual(list(groups[(WORD, READINGS[0])]), [(WORD, reading) for reading in READINGS])
        for reading, records in groups[(WORD, READINGS[0])].items():
            expected = tuple(entry for entry in entries if (entry.term, entry.reading) == reading)
            self.assertEqual(records, expected)
            self.assertTrue(all(a is b for a, b in zip(records, expected)))
        self.assertEqual(entries, before)

    def test_one_differing_dictionary_keeps_both_readings_separate(self):
        entries = variants()
        entries = (*entries[:-1], replace(entries[-1], definitions=("a dependable person",)))
        self.assertEqual(len(group_headwords(entries)), 2)

    def test_missing_or_different_dictionary_is_not_an_equivalent_source_set(self):
        entries = variants()
        for changed in (entries[:-1], (entries[0], entries[-1]),
                        (*entries[:-1], replace(entries[-1], source="Third"))):
            with self.subTest(entries=changed):
                self.assertEqual(len(group_headwords(changed)), 2)

    def test_full_payload_matters_including_hidden_examples_and_usage(self):
        first, second = variants(sources=("JMdict",), definitions=(disclosure("example"),))
        for changes in (
                {"definitions": (disclosure("different example"),)},
                {"definitions": (*first.definitions, "another sense")},
                {"definitions": ({"type": "structured-content", "content": "safe",
                                  "data": {"usage": "rare"}},)},
                {"rules": ("adj-na",)}, {"inflection": ("past",)},
                {"morphology": ("different analysis",)}):
            with self.subTest(changes=changes):
                self.assertEqual(len(group_headwords((first, replace(second, **changes)))), 2)

    def test_only_matching_readings_merge_and_first_occurrence_order_is_preserved(self):
        first, second = variants(sources=("JMdict",))
        distinct = replace(first, id="distinct", reading="だいじょーぶ", definitions=("a brave man",))
        other = replace(first, id="other", term="別語")
        groups = group_headwords((first, distinct, other, second))
        self.assertEqual(list(groups), [(WORD, first.reading), (WORD, distinct.reading), (other.term, other.reading)])
        self.assertEqual(len(groups[(WORD, first.reading)]), 2)

    def test_unknown_readings_and_other_languages_keep_existing_groups(self):
        first, second = variants(sources=("JMdict",))
        for entries in ((replace(first, reading=""), second),
                        (first, replace(second, reading="")),
                        (replace(first, language="ru"), replace(second, language="ru"))):
            with self.subTest(entries=entries):
                self.assertEqual(len(group_headwords(entries)), 2)
        self.assertEqual(group_headwords(()), {})

    def test_multiple_records_and_their_order_are_part_of_the_full_entry(self):
        first, second = variants(sources=("JMdict",))
        extra = replace(first, id="extra", definitions=("a second record",))
        alternate_extra = replace(extra, id="alternate-extra", reading=second.reading)
        self.assertEqual(len(group_headwords((first, extra, second, alternate_extra))), 1)
        self.assertEqual(len(group_headwords((first, extra, second))), 2)
        self.assertEqual(len(group_headwords((first, extra, alternate_extra, second))), 2)

    def test_imported_jmdict_usage_tags_are_compared_without_reimport_or_schema_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / "dictionary.zip"
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("index.json", json.dumps(dict(title="JMdict", format=3, sourceLanguage="ja")))
                output.writestr("tag_bank_1.json", json.dumps([
                    ["rare", "frequency", 0, "rare", 0]]))
                output.writestr("term_bank_1.json", json.dumps([
                    [WORD, READINGS[0], "", "adj-na", 0, ["safe"], 10, ""],
                    [WORD, READINGS[1], "", "adj-na", 0, ["safe"], 10, ""],
                    [WORD, "だいじょーぶ", "rare", "adj-na", 0, ["safe"], 10, ""]]))
            import_yomitan(archive, Path(folder) / "packs")
            library = Library(Path(folder) / "packs")
            try:
                entries = library.lookup(WORD)
                self.assertEqual(len(entries), 3)
                groups = group_headwords(entries)
                self.assertEqual(sorted(map(len, groups.values())), [1, 2])
                self.assertTrue(all(entry.rules == ("adj-na",) for entry in entries))
            finally:
                library.close()


class ReadingVariantRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.browser = LocalDictionaryBrowser(selection_lookup=False)
        self.browser.setFont(document_font("Noto Sans JP", 14, "ja"))

    def tearDown(self):
        self.browser.deleteLater()
        self.app.processEvents()

    def render(self, entries, **options):
        self.browser.setHtml(render_result(SearchResult(WORD, "ja", "en", entries), **options))
        return self.browser.toPlainText()

    def headings(self):
        result = []
        block = self.browser.document().begin()
        while block.isValid():
            if block.blockFormat().headingLevel() == 2:
                result.append(block)
            block = block.next()
        return result

    def test_shared_meanings_render_once_across_preview_pitch_furigana_and_label_options(self):
        entries = variants(definitions=("safe; all right", "second sense"))
        before = deepcopy(entries)
        for preview, compact, pitch, furigana, labels, combine in product((False, True), repeat=6):
            with self.subTest(preview=preview, compact=compact, pitch=pitch, furigana=furigana,
                              labels=labels, combine=combine):
                text = self.render(entries, preview=preview, compact=compact, preview_pitch=pitch,
                                   pinned_pitch=pitch, headword_furigana=furigana,
                                   dictionary_labels=labels, combine_frequencies=combine)
                self.assertEqual(len(self.headings()), 1)
                if furigana and not pitch:
                    iterator = self.headings()[0].begin()
                    readings = []
                    while not iterator.atEnd():
                        fmt = iterator.fragment().charFormat()
                        if fmt.objectType() == RUBY:
                            readings.append(fmt.property(READING))
                        iterator += 1
                    self.assertIn(READINGS[0], readings)
                else:
                    self.assertIn(READINGS[0], text)
                self.assertIn(READINGS[1], text)
                self.assertEqual(text.count("safe; all right"), 1 if preview and compact else 2)
                self.assertEqual(text.count("second sense"), 1 if preview and compact else 2)
                self.assertEqual("[3]" in text, pitch)
                if not preview or not compact:
                    self.assertEqual(text.count("JMdict"), int(labels))
                    self.assertEqual(text.count("Second"), int(labels))
        self.assertEqual(entries, before)

    def test_partial_overlap_preserves_attribution_in_every_dictionary(self):
        entries = variants(definitions=("shared meaning",))
        entries = (*entries[:-2], replace(entries[-2], definitions=("first reading only",)),
                   replace(entries[-1], definitions=("second reading only",)))
        text = self.render(entries)
        self.assertEqual(len(self.headings()), 2)
        self.assertEqual(text.count("shared meaning"), 2)
        first, second = text.split(WORD)[1:]
        self.assertIn("first reading only", first)
        self.assertNotIn("second reading only", first)
        self.assertIn("second reading only", second)
        self.assertNotIn("first reading only", second)

    def test_preview_limits_and_hidden_sections_cannot_create_false_matches(self):
        first, second = variants(sources=("JMdict",), definitions=("shared first sense", "first tail"))
        second = replace(second, definitions=("shared first sense", "second tail"))
        text = self.render((first, second), preview=True, compact=False, preview_definitions=1,
                           hidden_sections={"JMdict": ("examples",)})
        self.assertEqual(len(self.headings()), 2)
        self.assertEqual(text.count("shared first sense"), 2)
        self.assertNotIn("first tail", text)
        self.assertNotIn("second tail", text)

    def test_each_pitch_frequency_and_plain_reading_stays_attached_to_its_variant(self):
        text = self.render(variants(sources=("JMdict",)))
        self.assertIn(f"{READINGS[0]} [3] #106", text)
        self.assertIn(f"[{READINGS[1]}] #107", text)
        text = self.render(variants(sources=("JMdict",)), pinned_pitch=False)
        self.assertIn(f"[{READINGS[0]}] #106", text)
        self.assertIn(f"[{READINGS[1]}] #107", text)


class ReadingVariantInteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings = QSettings(str(Path(self.temp.name) / "settings.ini"), QSettings.Format.IniFormat)
        self.settings.setValue("profile", "ja")
        self.settings.setValue("profiles/ja/audio_autoplay_mode", "off")
        self.previous_config = dict(config.__dict__)
        self.window = QuickLookupWindow(self.temp.name, FakeEngine, self.settings)
        self.window.audio = Mock()
        self.window.audio.current_clip = None
        self.entries = variants()
        self.primary, self.alternate = ((WORD, reading) for reading in READINGS)
        self.popup_patch = patch.object(QMenu, "popup")
        self.popup_patch.start()

    def tearDown(self):
        for menu in self.window.findChildren(QMenu):
            menu.close()
        self.window.shutdown()
        self.window.worker._thread.join(timeout=2)
        self.window.hide()
        self.window.deleteLater()
        self.app.processEvents()
        self.popup_patch.stop()
        config.__dict__.update(self.previous_config)
        self.temp.cleanup()

    def show(self, entries=None, **options):
        self.window.show_entries(self.entries if entries is None else entries, WORD, **options)
        self.app.processEvents()

    def test_one_heading_and_action_row_use_cached_presentation_but_retain_raw_readings(self):
        with patch("wordcel.gui.quick_lookup.group_headwords", wraps=group_headwords) as group:
            self.show()
            self.window._render(static=True)
            self.window._position_headword_actions()
            self.window._presentation_groups()
            group.assert_called_once()
        self.assertEqual(len(self.window._headword_blocks), 1)
        self.assertEqual(list(self.window._headword_rows), [self.primary])
        self.assertEqual(list(self.window._headword_groups()), [self.primary, self.alternate])
        self.assertEqual(self.window._result.entries, self.entries)

    def test_audio_left_click_plays_the_first_reading_without_a_menu(self):
        self.show()
        button = self.window._headword_rows[self.primary][2]
        button.click()
        self.window.audio.play.assert_called_once()
        self.assertIs(self.window.audio.play.call_args.args[0], self.entries[0])
        self.assertEqual(button.findChildren(QMenu), [])
        self.assertEqual(self.window._audio_key(self.alternate), ("ja", WORD, READINGS[1]))
        self.assertEqual(self.window._audio_key(), ("ja", WORD, READINGS[0]))

    def test_source_menu_keeps_readings_and_explicit_source_choices_separate(self):
        self.show()
        button = self.window._headword_rows[self.primary][2]
        with patch("wordcel.audio.sources.source_order", return_value=["tts"]):
            menu = self.window.audio_source_menu(QPoint(), headword=self.primary, button=button)
        submenu = menu.actions()[1].menu()
        self.assertEqual(submenu.title(), READINGS[1])
        submenu.actions()[2].trigger()
        self.assertIs(self.window.audio.play.call_args.args[0], self.entries[1])
        self.assertEqual(self.window.audio.play.call_args.kwargs["source"], "tts")

    def test_stale_reading_menu_cannot_play_a_later_lookup(self):
        self.show()
        button = self.window._headword_rows[self.primary][2]
        menu = self.window.audio_source_menu(QPoint(), headword=self.primary, button=button)
        self.window._invalidate()
        menu.actions()[1].menu().actions()[0].trigger()
        self.window.audio.play.assert_not_called()

    def test_source_menu_cannot_play_replaced_records_with_the_same_revision(self):
        self.show()
        button = self.window._headword_rows[self.primary][2]
        menu = self.window.audio_source_menu(QPoint(), headword=self.primary, button=button)
        replacement = tuple(replace(entry, definitions=("replacement",)) for entry in self.entries)
        self.window._display(SearchResult(WORD, "ja", "en", replacement))
        menu.actions()[1].menu().actions()[0].trigger()
        self.window.audio.play.assert_not_called()

    def test_anki_menu_keeps_duplicate_states_and_exports_full_original_records(self):
        self.show()
        options = AnkiSettings(enabled=True, deck="Words", model="Basic", fields={"Reading": "reading"})
        controller = self.window.lookup_anki
        identity = (self.window.revision, options, tuple(self.window._headword_groups()))
        controller._check_identity = controller._existing_identity = identity
        controller._known_notes = {self.primary: (123,)}
        self.window._result_context = "A complete sentence."
        with patch("wordcel.anki.load_settings", return_value=options), \
                patch.object(controller, "_start_save"), patch("wordcel.gui.anki.export_note") as export:
            menu = self.window._headword_action("anki", self.primary)
            self.assertEqual(menu.actions()[0].toolTip(), "Show in Anki")
            self.assertEqual(menu.actions()[1].toolTip(), "Add to Anki")
            menu.actions()[1].trigger()
            operation, context = controller._queue.pop()
            self.assertEqual(context[1], self.alternate)
            operation()
            exported, sentence = export.call_args.args[:2]
            expected = (self.entries[1], self.entries[3])
            self.assertEqual(exported, expected)
            self.assertTrue(all(a is b for a, b in zip(exported, expected)))
            self.assertEqual(sentence, "A complete sentence.")
            self.assertEqual(note_values(exported)["reading"], READINGS[1])

    def test_pending_primary_anki_save_does_not_disable_the_alternate_reading(self):
        self.show()
        options = AnkiSettings(enabled=True, deck="Words", model="Basic", fields={"Reading": "reading"})
        controller = self.window.lookup_anki
        identity = (self.window.revision, options, tuple(self.window._headword_groups()))
        controller._check_identity = controller._existing_identity = identity
        controller._queue.append((Mock(), (self.window.revision, self.primary, options, False)))
        with patch("wordcel.anki.load_settings", return_value=options):
            self.window.update_anki()
            self.assertTrue(self.window._headword_rows[self.primary][1].isEnabled())
            menu = self.window._headword_action("anki", self.primary)
            self.assertFalse(menu.actions()[0].isEnabled())
            self.assertTrue(menu.actions()[1].isEnabled())
        controller._queue.clear()

    def test_shared_dictionary_collapse_survives_reading_reordering_and_back(self):
        self.show()
        self.window._link(QUrl("collapse:0:0"))
        self.assertEqual(self.window.browser.toPlainText().count("safe; all right"), 1)
        self.window._display(SearchResult(WORD, "ja", "en", tuple(reversed(self.entries))))
        self.assertEqual(self.window.browser.toPlainText().count("safe; all right"), 1)
        other = replace(self.entries[0], term="犬", definitions=("dog",))
        self.window._display(SearchResult("犬", "ja", "en", (other,)))
        self.window.go_back()
        self.assertEqual(self.window.browser.toPlainText().count("safe; all right"), 1)
        self.window._link(QUrl("collapse:0:1"))
        self.assertEqual(self.window.browser.toPlainText().count("safe; all right"), 2)

    def test_shared_disclosures_preserve_selection_scroll_and_window_geometry(self):
        entries = variants(definitions=(disclosure("Expanded example"), "a line\n" * 40, "shared meaning"))
        self.show(entries)
        browser = self.window.browser
        first = browser.document().find("shared meaning")
        browser.setTextCursor(browser.document().find("shared meaning", first.selectionEnd()))
        browser.verticalScrollBar().setValue(browser.verticalScrollBar().maximum() // 2)
        self.assertGreater(browser.verticalScrollBar().value(), 0)
        selected, scroll, geometry = browser.selected_text(), browser.verticalScrollBar().value(), self.window.geometry()
        with patch.object(self.window.worker, "request") as request:
            for _ in range(2):
                self.window._link(QUrl("details:0:1:0"))
                self.app.processEvents()
                self.assertEqual(browser.selected_text(), selected)
                self.assertEqual(browser.verticalScrollBar().value(), scroll)
                self.assertEqual(self.window.geometry(), geometry)
            request.assert_not_called()
        self.assertEqual(browser.toPlainText().count("shared meaning"), 2)

    def test_later_kanji_link_and_actions_use_display_group_indices(self):
        other = replace(self.entries[0], term="犬", reading="いぬ", definitions=("dog",), pitches=())
        self.show((*self.entries, other), kanji=(KanjiEntry("犬", meanings=("dog",)),))
        self.assertEqual(len(self.window._headword_blocks), 2)
        self.assertEqual(list(self.window._headword_rows), [self.primary, ("犬", "いぬ")])
        self.window._link(QUrl("headkanji:1:犬"))
        self.assertEqual(self.window._kanji_origin, "犬")
        self.assertIn("dog", self.window.kanji_browser.toPlainText())
        self.window.go_back()
        self.assertEqual(len(self.window._headword_blocks), 2)
        self.assertEqual(self.window._result.entries, (*self.entries, other))

    def test_sticky_heading_and_actions_follow_the_next_display_group(self):
        entries = variants(definitions=("long definition\n" * 40,))
        other = replace(entries[0], term="犬", reading="いぬ", definitions=("dog definition\n" * 40,), pitches=())
        self.show((*entries, other))
        browser = self.window.browser
        scroller = browser.section_scroll
        self.assertEqual(len(scroller._headings), 2)
        browser.verticalScrollBar().setValue(scroller._top(scroller._headings[1]) + 1)
        self.app.processEvents()
        self.assertTrue(scroller.header.isVisible())
        self.assertIn("犬", scroller.header.toPlainText())
        self.assertNotIn(READINGS[0], scroller.header.toPlainText())
        self.assertFalse(self.window._headword_rows[self.primary][0].isVisible())
        self.assertTrue(self.window._headword_rows[("犬", "いぬ")][0].isVisible())

    def test_merged_heading_wraps_with_actions_at_narrow_and_wide_window_sizes(self):
        self.settings.setValue("profiles/ja/buttons/audio_sentence", True)
        self.show(peek=True)
        self.window.set_context("Sentence containing the word.")
        self.window.pin.setChecked(True)
        self.app.processEvents()
        for width, ruby, pitch in product((320, 480, 680), (False, True), (False, True)):
            with self.subTest(width=width, ruby=ruby, pitch=pitch):
                self.settings.setValue("profiles/ja/headword_furigana", ruby)
                self.settings.setValue("profiles/ja/pinned_pitch", pitch)
                self.window.resize(width, 340)
                self.window.reload_appearance()
                self.app.processEvents()
                block = self.window._headword_blocks[0]
                layout = block.layout()
                self.assertTrue(all(layout.lineAt(index).naturalTextWidth() <= layout.lineAt(index).width()
                                    for index in range(layout.lineCount())))
                row = self.window._headword_rows[self.primary][0]
                shared = self.window.audio_actions
                self.assertTrue(row.isVisible())
                self.assertTrue(shared.isVisible())
                row_rect = QRect(row.mapTo(self.window, QPoint()), row.size())
                shared_rect = QRect(shared.mapTo(self.window, QPoint()), shared.size())
                self.assertFalse(row_rect.intersects(shared_rect))

    def test_pinning_compact_preview_keeps_one_group_and_reveals_all_dictionaries(self):
        self.show(peek=True)
        self.assertEqual(len(self.window._headword_blocks), 1)
        self.assertEqual(self.window.browser.toPlainText().count("safe; all right"), 1)
        self.assertIn(READINGS[1], self.window.browser.toPlainText())
        self.window.pin.setChecked(True)
        self.app.processEvents()
        self.assertEqual(len(self.window._headword_blocks), 1)
        self.assertEqual(self.window.browser.toPlainText().count("safe; all right"), 2)
        self.assertEqual(list(self.window._headword_rows), [self.primary])
        self.window.audio.play.assert_not_called()

    def test_pin_autoplay_uses_the_primary_record_once_and_never_on_rerender(self):
        self.settings.setValue("profiles/ja/audio_autoplay_mode", "pin")
        self.show(peek=True)
        self.window.pin.setChecked(True)
        self.app.processEvents()
        self.window._render(static=True)
        self.window._render(static=True)
        self.window.audio.play.assert_called_once()
        self.assertIs(self.window.audio.play.call_args.args[0], self.entries[0])


if __name__ == "__main__":
    unittest.main()
