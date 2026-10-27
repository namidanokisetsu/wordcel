from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from wordcel.dictionary.library import Entry
from wordcel.dictionary.search import SearchResult
from wordcel.history import HistoryStore


def result(form="猫", headword="猫", reading="ねこ", meaning="cat", language="ja"):
    return SearchResult(form, language, "en", (Entry("1", headword, reading, "Words", language, (meaning,)),))


class HistoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = HistoryStore(Path(self.temp.name) / "history.sqlite3")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def add(self, value=None, context="猫がいる。", stamp=1):
        return self.store.record(value or result(), context, 0, 1, timestamp=stamp)

    def test_repeated_visits_share_words_and_definitions_but_keep_encounters(self):
        first = self.add(stamp=1)
        second = self.add(stamp=2)
        rows, total = self.store.search()
        self.assertEqual([row["id"] for row in rows], [second, first])
        self.assertEqual(total, 2)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM words").fetchone()[0], 1)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM texts WHERE kind='definition'").fetchone()[0], 1)
        self.store.delete(second)
        self.assertEqual(self.store.search("cat")[1], 1)
        self.store.delete(first)
        for table in ("words", "texts", "grams", "encounter_words"):
            self.assertEqual(self.store.db.execute("SELECT count(*) FROM " + table).fetchone()[0], 0)

    def test_distinct_readings_and_candidate_groups_keep_one_card(self):
        value = SearchResult("生", "ja", "en", (
            Entry("1", "生", "なま", "A", "ja", ("raw",)),
            Entry("2", "生", "せい", "A", "ja", ("life",)),
            Entry("3", "生", "なま", "B", "ja", ("fresh",))))
        self.add(value)
        rows, total = self.store.search()
        self.assertEqual(total, 1)
        self.assertEqual(len(rows[0]["words"]), 2)
        self.assertEqual(self.store.search("せい")[1], 1)

    def test_shorter_fallback_prefixes_are_not_associated_or_searchable(self):
        entries = (replace(result("温泉", "温泉", "おんせん", "hot spring").entries[0], lookup_length=2),
                   replace(result("温", "温", "ぬく", "warm").entries[0], lookup_length=1))
        self.add(SearchResult("温泉", "ja", "en", entries), "温泉へ")
        self.assertEqual(self.store.search()[0][0]["words"], [("ja", "温泉", "おんせん")])
        self.assertEqual(self.store.search("warm")[1], 0)

    def test_existing_full_word_encounters_drop_only_obvious_prefixes(self):
        entries = (result("温泉", "温泉", "おんせん", "hot spring").entries[0],
                   result("温", "温", "ぬく", "warm").entries[0])
        self.add(SearchResult("温泉", "ja", "en", entries), "温泉へ")
        self.store.db.execute("PRAGMA user_version=0")
        self.store.close()
        self.store = HistoryStore(Path(self.temp.name) / "history.sqlite3")
        self.assertEqual(self.store.search()[0][0]["words"], [("ja", "温泉", "おんせん")])
        self.assertEqual(self.store.search("warm")[1], 0)

    def test_literal_priority_recency_definition_and_context(self):
        context = self.add(result("犬", "犬", "いぬ", "dog"), "猫がいる", stamp=5)
        meaning = self.add(result("虎", "虎", "とら", "large 猫"), "forest", stamp=4)
        partial = self.add(result("山猫", "山猫", "やまねこ"), "forest", stamp=3)
        first = self.add(stamp=1)
        second = self.add(stamp=2)
        analyzer = Mock(return_value=("虎",))
        rows, _ = self.store.search("猫", base_forms=analyzer)
        self.assertEqual([row["id"] for row in rows], [second, first, partial, meaning, context])
        analyzer.assert_not_called()
        self.assertIn("large 猫", rows[3]["excerpt"])
        self.assertEqual(rows[4]["excerpt"], "")

    def test_analysis_precedes_stored_meanings_and_context(self):
        base = self.add(result("食べる", "食べる", "たべる", "eat"), "食べる", stamp=1)
        meaning = self.add(result("語", "語", "ご", "食べました"), "語", stamp=2)
        context = self.add(result("犬", "犬", "いぬ", "dog"), "食べました", stamp=3)
        rows, _ = self.store.search("食べました", base_forms=lambda: ("食べる",))
        self.assertEqual([row["id"] for row in rows], [base, meaning, context])

    def test_japanese_substrings_literal_punctuation_language_and_paging(self):
        self.add(result("食べました", "食べる", "たべる", "eat"), "昨日食べました。")
        self.add(result("cat", "cat", "", "feline", "en"), "100% cat", stamp=2)
        for query in ("べ", "べま", "べました", "昨日食"):
            self.assertEqual(self.store.search(query)[1], 1, query)
        self.assertEqual(self.store.search("%")[1], 1)
        self.assertEqual(self.store.search("_" )[1], 0)
        self.assertEqual(self.store.search("cat", "ja")[1], 0)
        self.assertEqual(len(self.store.search(limit=1)[0]), 1)
        self.assertEqual(self.store.search(limit=1, offset=1)[0][0]["form"], "食べました")

    def test_definition_refresh_retention_and_unresolved_records(self):
        self.add(result(meaning="old wording"), stamp=1)
        self.add(result(meaning="new wording"), stamp=1000000)
        self.assertEqual(self.store.search("old wording")[1], 0)
        self.assertEqual(self.store.search("new wording")[1], 2)
        self.store.prune(0, now=2000000)
        self.assertEqual(self.store.search()[1], 2)
        self.store.prune(1, now=1000000)
        self.assertEqual(self.store.search()[1], 1)
        self.add(SearchResult("unknown", "en", "ja"), "unknown text", stamp=1000001)
        self.assertEqual(self.store.search("unknown")[0][0]["words"], [])
        self.store.delete()
        self.assertEqual(self.store.search()[1], 0)


