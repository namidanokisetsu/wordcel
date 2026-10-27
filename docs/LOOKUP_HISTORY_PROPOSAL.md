# Lookup history proposal

Proposed, not implemented. Recover previously encountered words and sentences;
Anki remains the destination for deliberate study. Build literal search before
considering semantic search.

## Recording

History is opt-in, with one shared enable setting in the History window and a
History tab in Settings. Independent choices cover pinned, hover and manual/text
lookups. Initially select pinned and manual/text only. Preserve choices when
recording is disabled and re-enabled; never backfill disabled periods. Existing
history remains browsable when recording is off.

Record one encounter per continuous lookup of the same word and context, using
lookup-session transitions rather than a time cutoff. Revisiting after moving on
creates another encounter, even with identical context. Rendering and restoration
never record again.

- Pinned and manual/text recording occurs as soon as the result is available.
- Hover recording requires a configurable display duration, initially 0.5 seconds.
  Show this setting only when hover recording is enabled. Measure from result
  display; identical OCR refreshes do not restart it.
- At the threshold, record once and stop the timer. Changing word/context,
  dismissing or disabling recording cancels it. Separate visits do not accumulate.
- Pinning ends the hover timer. If pinned recording is enabled, record immediately
  or reuse the hover encounter. Otherwise cancel unfinished hover recording;
  retain any encounter already recorded.

Support individual deletion, Clear history and retention options including forever.

## Storage and search

Use SQLite in managed app data, with writes/search off the UI thread. Store text,
not screenshots, URLs, audio or rendered dictionary results.

| Record | Contents |
| --- | --- |
| Word | Language, headword and reading, preserving distinct readings. |
| Encounter | Timestamp, encountered form, full context, matched span and associated words. |
| Searchable definition | Plain text and dictionary source, shared across encounters. |

Retain multiple candidate headword groups without creating a card per dictionary
record or conflating candidates. Unresolved lookups may retain query and context.
Reopening performs fresh dictionary lookup with saved context; stored meanings
support search and may differ from current definitions. Deletion removes orphaned
search records.

Empty queries show newest encounters first. Search ranks these matches in order,
using recency within each group:

1. Exact headword, reading or encountered form.
2. Partial matches in those fields.
3. Deconjugation or language-analysis matches.
4. Stored definition matches.
5. Sentence-context matches.

Index words, contexts and definition text. Japanese substring search must work
without spaces. Reuse prepared analyzers and existing Japanese lookup rules;
check literal matches before dictionary-backed base forms. Store encountered
forms to avoid repeated analysis on common queries. Sentence queries initially
match literal fragments only; whole-sentence lemmatization is outside scope.
Meaning search matches stored wording, without translation or inferred synonyms.

## Interface

Open a dedicated History window from the tray or a compact manual Search button.
Keep it separate from Settings and OCR preview. When off, show "History is off",
"Enable history" and a link to its Settings tab. First use identifies pinned and
manual/text as the default scope. Settings also contains recording choices, hover
delay, retention and Clear history.

Use one search field, an optional language filter and compact encounter cards.
Default browsing groups by Today, Yesterday and date. Each card shows headword,
reading when useful, time and context with the encountered span highlighted.
Separate encounters remain separate cards. Search uses the same cards ordered
by match priority/recency, with dates visible instead of day sections. Meaning
matches add a short matching excerpt, not a permanent definition dump.

Opening a card reuses the lookup window, pronunciation and Anki actions without
autoplay. Preserve History's query, selection and scroll. Derive geometry from
content/layouts and avoid rebuilding unchanged results.

## Open decisions and delivery

Before implementation, choose the initial retention default, ambiguous-result
identity/display rules, definition invalidation policy and Japanese substring
index. Verify SQLite features in packaged builds before choosing the index.

Prototype chronological browsing and filtered cards with realistic repeated
encounters, then implement recording, persistence, retention, indexed search and
analyzer integration. Fixture checks cover duplicate suppression, hover
cancellation, pin promotion, restoration, deletion and ranking. Measure cold and
repeated searches before claiming performance improvements.

Consider semantic search only against actual failed baseline searches, before
adding a model, setup requirements or similarity thresholds. Runtime stays
offline and Japanese behavior is preserved.
