import unittest

from wordcel.dictionary.kanji import KanjiEntry, kanji_characters
from wordcel.gui.kanji_panel import render_kanji, render_kanji_details, render_kanji_export


class KanjiTests(unittest.TestCase):
    def test_summary_merges_exact_duplicates_for_any_number_of_sources(self):
        records = tuple(KanjiEntry("猫", source, ("ビョウ",), ("ねこ",), ("cat",),
                                  stats=(("strokes", "11"), ("halpern", "123")))
                        for source in ("One", "Two", "Three"))
        for count in (1, 2, 3):
            with self.subTest(count=count):
                html = render_kanji_details(records[:count])
                for value in (">cat</span>", ">ビョウ</span>", ">ねこ</span>"):
                    self.assertEqual(html.count(value), 1)
                self.assertNotIn("Strokes", html)
                for label, reading in (("音", "ビョウ"), ("訓", "ねこ")):
                    start = html.index(f'<small>{label}</small> ')
                    row = html[start:html.index('</p>', start)]
                    self.assertIn(reading, row)
                    self.assertNotIn('<br>', row)
                    self.assertEqual(row.count('<small>'), 1)
                self.assertNotIn("halpern", html)
                for record in records[:count]:
                    self.assertNotIn(f'<small>{record.source}', html)
                    self.assertIn(record.source, html)

    def test_reference_stats_stay_out_of_popup_and_remain_in_export(self):
        records = (KanjiEntry("猫", "Readings", onyomi=("ビョウ",)),
                   KanjiEntry("猫", "Meanings", meanings=("cat",), stats=(("stroke_count", "11"),)),
                   KanjiEntry("猫", "Other", stats=(("strokes", "12"), ("custom", "<value>"))))
        html = render_kanji_details(records)
        self.assertIn("cat", html)
        self.assertIn("ビョウ", html)
        self.assertNotIn("Strokes", html)
        self.assertNotIn("custom", html)
        self.assertIn('title="Readings"', html)
        self.assertIn('title="Meanings"', html)
        exported = render_kanji_export(records, "猫")
        self.assertIn("Strokes 11", exported)
        self.assertIn("Strokes 12", exported)
        self.assertIn("&lt;value&gt;", exported)
        self.assertEqual(render_kanji_details(()), "")

    def test_origin_header_highlights_selected_kanji_and_escapes_text(self):
        html = render_kanji_details((KanjiEntry("猫", meanings=("cat",)),),
                                   origin="猫<&𠮷", available_characters={"猫", "𠮷"})
        self.assertIn("<u>猫</u>", html)
        self.assertNotIn("background-color:", html)
        self.assertIn("&lt;&amp;", html)
        self.assertIn('href="kanjiselect:%F0%A0%AE%B7"', html)
        self.assertNotIn('href="kanjiselect:%E7%8C%AB"', html)

    def test_components_and_examples_are_deduplicated_without_losing_data(self):
        records = tuple(KanjiEntry("猫", source, components=({"c": "田", "m": "field"},),
                                  examples=({"w": "子猫", "r": "こねこ", "m": "kitten"},))
                        for source in ("One", "Two"))
        html = render_kanji_details(records)
        self.assertEqual(html.count("field"), 1)
        self.assertEqual(html.count("kitten"), 1)
        self.assertIn("Parts", html)
        self.assertIn("Examples", html)

    def test_characters_preserve_order_and_include_extensions(self):
        self.assertEqual(kanji_characters("日本語の日本𠮷"), ("日", "本", "語", "𠮷"))
        self.assertEqual(kanji_characters("日本語", 2), ("日", "本"))
        self.assertEqual(kanji_characters("日本語", 0), ())
        self.assertEqual(kanji_characters("ひらがなカタカナabc"), ())


    def test_compact_panel_keeps_details_separate(self):
        entry = KanjiEntry("猫", "Kanji Source", ("ビョウ",), ("ねこ",), ("cat",), stats=(("strokes", "11"),),
                           components=({"c": "田", "m": "field"},), examples=({"w": "子猫", "r": "こねこ", "m": "kitten"},))
        compact = render_kanji((entry,))
        self.assertIn("猫", compact)
        self.assertIn("ビョウ", compact)
        self.assertIn("ねこ", compact)
        for label, reading in (("音", "ビョウ"), ("訓", "ねこ")):
            start = compact.index(f'<small>{label}</small> ')
            row = compact[start:compact.index('</p>', start)]
            self.assertIn(reading, row)
            self.assertNotIn('<br>', row)
            self.assertEqual(row.count('<small>'), 1)
        self.assertIn("cat", compact)
        self.assertIn('href="kanji:toggle"', compact)
        self.assertNotIn("Strokes", compact)
        self.assertNotIn("kitten", compact)
        expanded = render_kanji((entry,), expanded=True)
        self.assertNotIn("Strokes", expanded)
        self.assertIn("kitten", expanded)
        self.assertIn("field", expanded)
        self.assertIn("Kanji Source", expanded)

    def test_untrusted_text_is_escaped_and_empty_panel_hidden(self):
        entry = KanjiEntry("<", 'bad"source', meanings=("<script>bad()</script>",),
                           stats=(("x", '<img src="https://example.test/">'),),
                           examples=({"w": "<b>bad</b>"},))
        html = render_kanji((entry,), expanded=True)
        self.assertNotIn("<script>", html)
        self.assertNotIn('<img src=', html)
        self.assertIn("&lt;script&gt;", html)
        self.assertEqual(render_kanji(()), "")

    def test_dictionary_entries_share_one_character_in_all_modes(self):
        entries = (KanjiEntry("決", "First", meanings=("decide",)),
                   KanjiEntry("定", "First", meanings=("determine",)),
                   KanjiEntry("決", "Second", onyomi=("ケツ",), meanings=("agree",)),
                   KanjiEntry("定", "Second", onyomi=("テイ",), meanings=("establish",)))
        for options in ({}, {"expanded": True}, {"compact_only": True}):
            with self.subTest(options=options):
                html = render_kanji(entries, **options)
                self.assertEqual(html.count(">決</a></td>"), 1)
                self.assertEqual(html.count(">定</a></td>"), 1)
                self.assertEqual(html.count('rowspan="2"'), 2)
                self.assertLess(html.index("agree"), html.index(">定</a></td>"))
                for value in ("First", "Second", "decide", "determine", "agree", "establish", "ケツ", "テイ"):
                    self.assertIn(value, html)

    def test_distinct_characters_use_a_compact_three_column_grid(self):
        entries = tuple(KanjiEntry(character, meanings=(f"meaning {character}",))
                        for character in "日本語")

        html = render_kanji(entries, compact_only=True)

        self.assertEqual(html.count('<td valign="top" width="33%"'), 3)
        self.assertEqual(html.count('style="font-size:30px'), 3)

        two_html = render_kanji(entries[:2], compact_only=True)
        self.assertEqual(two_html.count('<td valign="top" width="50%"'), 2)

    def test_clicking_a_character_shows_all_sources_in_a_full_width_section(self):
        entries = (KanjiEntry("日", "First", ("ニチ",), ("ひ",), ("day", "sun"), ("grade1",),
                            (("strokes", "4"),), ({"c": "一", "m": "one"},),
                            ({"w": "日本", "r": "にほん", "m": "Japan"},)),
                   KanjiEntry("日", "Second", ("ジツ",), ("か",), ("date",), ("jlptN5",),
                            (("grade", "1"),), (), ()))

        compact = render_kanji(entries, compact_only=True)
        self.assertIn('href="kanji:%E6%97%A5" title="Expand"', compact)
        self.assertNotIn("Strokes 4", compact)
        self.assertNotIn("Japan", compact)

        detailed = render_kanji(entries, compact_only=True, expanded_characters={"日"})
        self.assertIn('href="kanji:%E6%97%A5" title="Collapse"', detailed)
        for value in ("First", "Second", "day", "sun", "date", "ニチ", "ジツ", "ひ", "か", "one", "Japan"):
            self.assertIn(value, detailed)
        for value in ("Strokes", "Grade", "grade1", "jlptN5"):
            self.assertNotIn(value, detailed)
        self.assertGreaterEqual(detailed.count('<table width="100%"'), 2)

    def test_character_links_url_encode_unicode(self):
        html = render_kanji((KanjiEntry("𠮷", meanings=("variant",)),), compact_only=True)

        self.assertIn('href="kanji:%F0%A0%AE%B7" title="Expand"', html)

    def test_kanji_only_result_is_not_reported_as_an_empty_lookup(self):
        from wordcel.dictionary.search import SearchResult
        from wordcel.gui.quick_lookup import render_result
        html = render_result(SearchResult("日", "ja", "en", kanji=(KanjiEntry("日", meanings=("day",)),)))
        self.assertIn("day", html)
        self.assertNotIn("No entry found", html)


if __name__ == "__main__":
    unittest.main()
