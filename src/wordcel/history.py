"""Text-only encounter storage and portable SQLite substring search."""
from collections import defaultdict
from pathlib import Path
import sqlite3
import time
import unicodedata


def normalized(text):
    return unicodedata.normalize("NFKC", text).casefold()


def grams(text, size):
    return {text[i:i + size] for i in range(len(text) - size + 1)}


def primary_entries(entries):
    length = max((entry.lookup_length for entry in entries), default=0)
    return tuple(entry for entry in entries if not entry.lookup_length or entry.lookup_length == length)


def primary_words(words, form):
    """Recover obvious full-word candidates from records saved before span metadata."""
    form = normalized(form)
    if any(form in (normalized(term), normalized(reading)) for _, term, reading in words):
        kept = []
        for word in words:
            values = (normalized(word[1]), normalized(word[2]))
            if form in values or not any(value and form.startswith(value) for value in values):
                kept.append(word)
        return kept
    return words


class HistoryStore:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA foreign_keys=ON;
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS encounters(
                id INTEGER PRIMARY KEY, timestamp REAL NOT NULL, language TEXT NOT NULL,
                form TEXT NOT NULL, context TEXT NOT NULL, start INTEGER, end INTEGER);
            CREATE INDEX IF NOT EXISTS recent ON encounters(timestamp DESC, id DESC);
            CREATE TABLE IF NOT EXISTS words(
                id INTEGER PRIMARY KEY, language TEXT, headword TEXT, reading TEXT,
                UNIQUE(language, headword, reading));
            CREATE TABLE IF NOT EXISTS encounter_words(
                encounter INTEGER REFERENCES encounters ON DELETE CASCADE,
                word INTEGER REFERENCES words ON DELETE CASCADE, position INTEGER,
                PRIMARY KEY(encounter, word));
            CREATE INDEX IF NOT EXISTS word_encounters ON encounter_words(word, encounter);
            CREATE TABLE IF NOT EXISTS texts(
                id INTEGER PRIMARY KEY, encounter INTEGER REFERENCES encounters ON DELETE CASCADE,
                word INTEGER REFERENCES words ON DELETE CASCADE,
                kind TEXT, source TEXT DEFAULT '', value TEXT, folded TEXT);
            CREATE INDEX IF NOT EXISTS encounter_texts ON texts(encounter);
            CREATE INDEX IF NOT EXISTS word_texts ON texts(word);
            CREATE TABLE IF NOT EXISTS grams(
                gram TEXT, text INTEGER REFERENCES texts ON DELETE CASCADE,
                PRIMARY KEY(gram, text)) WITHOUT ROWID;
            CREATE INDEX IF NOT EXISTS text_grams ON grams(text);
        """)
        if self.db.execute("PRAGMA user_version").fetchone()[0] == 0:
            with self.db:
                for encounter in self.db.execute("SELECT id,form FROM encounters").fetchall():
                    words = self.db.execute("SELECT w.id,w.language,w.headword,w.reading FROM encounter_words ew JOIN words w ON w.id=ew.word WHERE ew.encounter=?", (encounter[0],)).fetchall()
                    keep = primary_words([tuple(word)[1:] for word in words], encounter[1])
                    for word in words:
                        if tuple(word)[1:] not in keep:
                            self.db.execute("DELETE FROM encounter_words WHERE encounter=? AND word=?", (encounter[0], word[0]))
                self._cleanup()
                self.db.execute("PRAGMA user_version=1")

    def close(self):
        self.db.close()

    def _text(self, value, kind, *, encounter=None, word=None, source=""):
        folded = normalized(value)
        identity = self.db.execute(
            "INSERT INTO texts(encounter,word,kind,source,value,folded) VALUES(?,?,?,?,?,?)",
            (encounter, word, kind, source, value, folded)).lastrowid
        self.db.executemany("INSERT INTO grams VALUES(?,?)",
                            ((gram, identity) for size in (1, 2, 3) for gram in grams(folded, size)))

    def record(self, result, context, start, end, timestamp=None):
        from wordcel.dictionary.plain_content import extract_glosses
        with self.db:
            identity = self.db.execute("INSERT INTO encounters(timestamp,language,form,context,start,end) VALUES(?,?,?,?,?,?)",
                                       (time.time() if timestamp is None else timestamp, result.source,
                                        result.text, context, start, end)).lastrowid
            self._text(result.text, "form", encounter=identity)
            self._text(context, "context", encounter=identity)
            groups = defaultdict(lambda: defaultdict(list))
            for entry in primary_entries(result.entries):
                groups[entry.language, entry.term, entry.reading][entry.source].extend(extract_glosses(entry.definitions))
            for position, (key, sources) in enumerate(groups.items()):
                self.db.execute("INSERT OR IGNORE INTO words(language,headword,reading) VALUES(?,?,?)", key)
                word = self.db.execute("SELECT id FROM words WHERE language=? AND headword=? AND reading=?", key).fetchone()[0]
                self.db.execute("INSERT INTO encounter_words VALUES(?,?,?)", (identity, word, position))
                if not self.db.execute("SELECT 1 FROM texts WHERE word=? AND kind='word'", (word,)).fetchone():
                    self._text(key[1], "word", word=word)
                    self._text(key[2], "word", word=word)
                for source, definitions in sources.items():
                    value = "\n".join(dict.fromkeys(definitions))
                    old = self.db.execute("SELECT value FROM texts WHERE word=? AND kind='definition' AND source=?", (word, source)).fetchone()
                    if old and old[0] == value:
                        continue
                    self.db.execute("DELETE FROM texts WHERE word=? AND kind='definition' AND source=?", (word, source))
                    self._text(value, "definition", word=word, source=source)
            return identity

    def _cleanup(self):
        self.db.execute("DELETE FROM words WHERE NOT EXISTS(SELECT 1 FROM encounter_words WHERE word=words.id)")

    def delete(self, identity=None):
        with self.db:
            if identity is None:
                self.db.execute("DELETE FROM encounters")
            else:
                self.db.execute("DELETE FROM encounters WHERE id=?", (identity,))
            self._cleanup()

    def prune(self, days, now=None):
        if days:
            with self.db:
                self.db.execute("DELETE FROM encounters WHERE timestamp<?", ((time.time() if now is None else now) - days * 86400,))
                self._cleanup()

    def languages(self):
        return tuple(row[0] for row in self.db.execute("SELECT DISTINCT language FROM encounters ORDER BY language"))

    def _matches(self, query):
        # Ordinary B-tree indexes work with the SQLite bundled on both platforms.
        pieces = sorted(grams(query, min(3, len(query))))
        if not pieces:
            return []
        # One indexed gram narrows candidates; instr verifies literal substrings.
        rarest = min(pieces, key=lambda gram: self.db.execute("SELECT count(*) FROM grams WHERE gram=?", (gram,)).fetchone()[0])
        return self.db.execute("SELECT t.* FROM grams g JOIN texts t ON t.id=g.text WHERE g.gram=? AND instr(t.folded,?)>0",
                               (rarest, query)).fetchall()

    def search(self, query="", language="", base_forms=None, limit=100, offset=0):
        query = normalized(query.strip())
        matches = {}
        def collect(rows, analysis=""):
            for row in rows:
                kind = row["kind"]
                if analysis and (kind != "word" or row["folded"] != analysis):
                    continue
                rank = 2 if analysis else (0 if row["folded"] == query else 1) if kind in ("word", "form") else 3 if kind == "definition" else 4
                ids = ((row["encounter"],),) if row["encounter"] else self.db.execute("SELECT encounter FROM encounter_words WHERE word=?", (row["word"],))
                for (identity,) in ids:
                    if identity not in matches or rank < matches[identity][0]:
                        excerpt = ""
                        if rank == 3:
                            index = row["folded"].find(query)
                            excerpt = row["source"] + ": " + row["value"][max(0, index - 40):index + len(query) + 100]
                        matches[identity] = rank, excerpt
        if query:
            collect(self._matches(query))
            if language:
                matching_language = {row[0] for row in self.db.execute("SELECT id FROM encounters WHERE language=?", (language,))}
                matches = {identity: match for identity, match in matches.items() if identity in matching_language}
            if base_forms and not any(rank < 2 for rank, _ in matches.values()):
                for form in base_forms():
                    collect(self._matches(normalized(form)), analysis=normalized(form))
        with self.db:
            self.db.execute("CREATE TEMP TABLE IF NOT EXISTS matches(id INTEGER PRIMARY KEY, rank INTEGER)")
            self.db.execute("DELETE FROM matches")
            self.db.executemany("INSERT INTO matches VALUES(?,?)", ((identity, match[0]) for identity, match in matches.items()))
        source = "encounters e JOIN matches m ON e.id=m.id" if query else "encounters e"
        where = " WHERE e.language=?" if language else ""
        params = (language,) if language else ()
        total = self.db.execute("SELECT count(*) FROM " + source + where, params).fetchone()[0]
        order = "m.rank," if query else ""
        found = [dict(row) for row in self.db.execute("SELECT e.* FROM " + source + where +
                 " ORDER BY " + order + "e.timestamp DESC,e.id DESC LIMIT ? OFFSET ?", (*params, limit, offset))]
        for row in found:
            row["words"] = [tuple(word) for word in self.db.execute(
                "SELECT w.language,w.headword,w.reading FROM encounter_words ew JOIN words w ON w.id=ew.word WHERE ew.encounter=? ORDER BY ew.position", (row["id"],))]
            row["excerpt"] = matches.get(row["id"], (0, ""))[1]
        return found, total


class EncounterSession:
    """One continuous visit, independent of repaint and OCR refresh frequency."""
    def __init__(self):
        self.reset()

    def reset(self):
        self.identity = None
        self.recorded = False
        self.suppressed = False

    def display(self, identity, *, enabled=True, restored=False):
        changed = identity != self.identity
        if changed:
            self.identity = identity
            self.recorded = False
            self.suppressed = restored or not enabled
        return changed

    def claim(self, enabled):
        if self.identity is None or self.recorded or self.suppressed or not enabled:
            return False
        self.recorded = True
        return True
