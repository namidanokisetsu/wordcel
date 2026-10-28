# Development

See the [user guide](USER_GUIDE.md) for everyday use and
[AGENTS.md](../AGENTS.md) for repository conventions. The shared desktop app is
the only desktop entrypoint. Japanese lookup uses the shared app.

## Run from source

Use Python 3.12 for the desktop dependencies. On Windows:

```powershell
py -3.12 -m venv .venv-desktop
.\.venv-desktop\Scripts\python -m pip install -e .
.\start-wordcel.cmd
```

On macOS, create `.venv`, install with `python -m pip install -e .`, and use
[start-wordcel.command](../start-wordcel.command). Grant screen/input
permissions to the launching app or terminal. `wordcel`, `wordcel search`
and `wordcel-search` open the shared popup;
`python -m wordcel.scripts.quick_lookup --no-ocr` starts dictionary search alone.
Use Settings for explicit dictionary, OCR and model downloads.
Source and installed Wordcel use the same settings and data. Quit
the running tray app first; single-instance forwarding otherwise opens that copy.

## Architecture

Paths are relative to `src/wordcel/`. All languages use the shared desktop app,
input handling and dictionary renderer. Language-specific analysis stays separate.

| Area | Main modules | Responsibility |
| --- | --- | --- |
| Dictionaries | `dictionary/library.py`, `dictionary/search.py` | Atomic Yomitan imports, indexed lookup, ordering and revision-based cache invalidation. |
| Languages | `language/profiles.py`, `language/support.py`, `language/*_analyzer.py` | Language availability, source spans, deconjugation and spelling recovery. |
| Popup | `gui/quick_lookup.py`, `gui/dictionary_browser.py`, `gui/lookup_session.py` | Result state, shared rendering, navigation and disclosure. |
| History | `history.py`, `gui/lookup_history.py` | Encounter transitions, worker-owned SQLite storage, indexed text search and browsing. |
| Input and OCR | `gui/desktop_input.py`, `gui/unified_ocr.py`, `ocr/` | Capture, worker-bound recognition, selection and global shortcuts. |
| Settings and data | `gui/dictionary_manager.py`, `gui/data_manager.py`, `data_assets.py` | Profile preferences, resource inventory and explicit setup/removal jobs. |
| Translation | `dictionary/translation.py` | Lazy local inference, cancellation and loopback-only custom servers. |
| Audio | `audio/yomitan.py`, `audio/online.py`, `gui/lookup_audio.py` | Ordered sources, worker downloads, cancellation and bounded caches. |
| Anki | `anki.py`, `gui/anki.py` | Duplicate queries, note snapshots, media preparation and queued saves. |

### Lookup and language analysis

Exact entries and imported forms precede fallback analysis. Preserve original
text offsets, source records and dictionary order. Full matches precede prefix
scanning; `max_lookup_length` also belongs in cache identity. Unspaced lookup
starts at the pointed character; combining marks stay attached and scans stop
at source gaps. Missing definitions may retain analyses without dictionary entries.

Japanese uses bundled deconjugation rules. Headword/reading groups rank by
frequency, kana preference and deconjugation cost; limits apply to groups.
Exact compounds may append shorter direct prefixes without changing the longest
match span. Entries retain their source match length so history can omit those
shorter fallback groups. Manual search adds whole-query romkan2 candidates while preserving
English precedence; OCR and exact phrase checks keep their existing behavior.
Captured unspaced text uses prefix lookup from its first lexical character,
without sentence classification. The search field retains the full context;
clicking a character reuses positional lookup and highlights the matched word.

Turkish uses Zeyrek 0.1.3, accent recovery and precomputed lexicon rankings,
retaining full morpheme paths. Profile activation prepares a shared analyzer in
the background; worker parsing is serialized. Turkish never starts Stanza.
Other languages may use optional Stanza fallback, preserving expanded tokens'
original spans and testing joined lemmas before individual alternatives.
Russian and Persian retain spelling recovery. Arabic removes tatweel and ordinary
vowel marks only after exact lookup fails; distinct letters remain separate.
NLP imports are lazy, setup is explicit and runtime analysis stays offline.
Language availability belongs in `language/support.py` and the translation registry.

Dictionary lookup must not use LLM explanation, rewriting, aggregation or
reranking. Translation stays separate from dictionary analysis. Submitted text
can translate automatically on missing definitions or sentence
input, both off by default, using per-profile Translation settings. Sentence detection
uses punctuation, line breaks or at least three word groups, never a partial match.

### UI and asynchronous state

Capture, recognition, lookup, downloads and note preparation run off the UI
thread. Reject stale work by request revision and relevant profile/settings
identity. Reuse prepared analyzers, OCR providers and stable cache identities.
OCR preloading runs on the scan worker after event-loop startup, checks installed
resources only and yields to scans. Shortcut listeners update bindings in place;
disabling a binding must not wait on the UI thread.

Pinning freezes the result. Disclosure and translation round trips preserve the
dictionary document, selection, scroll and window geometry. Batch document/layout
updates; derive action placement, pane sizes and scrolling from rendered bounds.
Kanji uses a shared detail pane without rebuilding the dictionary document.
Preview defaults to one definition; pinned results have no definition cutoff.
Collapsed dictionaries and Wiktionary section visibility affect display only;
Anki retains full source records. Structured/plain definition conversion lives
in `dictionary/structured_content.py` and `dictionary/plain_content.py`.

Translation has a separate reading surface. Source edits invalidate work
immediately and debounce outside IME composition; output must match the current
revision and text. Back/dismissal cancels work. Long input uses the explicit
passage-size setting; dictionary input retains its separate 2,000-character limit.
Fresh captured text uses the lookup source; manual direction is session-specific.
Automatic output reuses the translation view in a separate pane without rebuilding
definitions. It requires configured resources; typing previews, positional word
lookups, history restoration and OCR hover never start automatic translation.
Autoplay occurs on new lookup results or the separate pin preference, never on
rendering, restoration or translation completion.

Windows OCR popups preserve source focus, including fullscreen and kanji use;
manual search accepts focus normally. Route popup navigation/actions only while
the source remains foreground, consume matching releases after dismissal, and
leave other input with the source. Popup actions yield to text fields. Unhandled
`nativeEvent` returns `(False, 0)` directly: PyQt's base call can crash handle creation.
Non-OCR shortcuts remain independently configurable, preserving OCR-only use.

Hover areas restore only on matching display geometry/scale. Explicit dismissal
pauses hover until the pointer leaves and returns; automatic hiding does not.
Outside clicks resume scanning after a pinned result. Cursor-leave dismissal is
opt-in and respects active drags, menus and Settings; corner windows are excluded.
Passage copying uses frozen per-display captures and a separate OCR mailbox so
hover jobs cannot replace it. Profile/provider changes discard pending clipboard
results. Preserve paragraph boundaries without changing lookup text or offsets.

### Lookup history

History is globally opt-in under `history/`, initially recording pinned and
manual/text lookups, with forever retention. `EncounterSession` identifies a visit
by language, encountered form, context and span. Result delivery starts hover
timing; identical OCR refreshes retain its deadline. Moving off a word or dismissing
ends the visit. Pinning stops the timer and may claim the same encounter. Rendering,
Back and saved-card restoration never create records; restoration also skips autoplay.
Preference changes cancel pending recording without backfilling the current visit.

A serial history worker owns `history.sqlite3` in managed app data (inside an
explicit dictionary-directory override for fixtures). It stores encounter text,
spans, ordered candidate word associations and plain definitions. Word identity
includes language, exact headword and reading. Dictionary records for one identity
share a card; distinct candidates remain distinct labels on that encounter.
Cards display the encountered form; shorter fallback prefixes are excluded.
Definitions are shared by word/source and replaced on the next encounter with
that source, so saved search wording may differ from installed dictionaries.
Deletion and retention remove orphan words, definitions and index entries.

Normalized character uni-, bi- and trigrams use ordinary SQLite B-tree indexes,
foreign keys and `instr`, without FTS extensions. Literal matches precede prepared
dictionary-backed base forms, definitions and context; recency breaks ties.
Only whole-query lexical matches contribute analyzer candidates. Sentence search
is literal. The worker retains its SearchEngine and reuses the language layer's
shared Turkish analyzer. History cards load in batches and retain unchanged items,
selection and scroll when refreshed. Storage/search never run on the GUI thread.

### Preferences and resources

Settings use the `wordcel/wordcel` Qt namespace; managed data/cache use platformdirs'
`wordcel` directory. Source and installed builds share them. Meikipop data stays
untouched. Prior-version settings/internal dictionary schemas are not migrated;
Yomitan archives without language metadata remain supported.

`config/inheritance.py` resolves `defaults/<group>/` and profile overrides.
First override snapshots defaults; re-enabling inheritance preserves custom values.
Profile duplication copies raw preferences. Popup combines appearance and behavior
editors but retains separate saved groups. Startup, connections and profile-cycle
shortcuts are global; language resources and analysis remain per profile.

Setup jobs are keyed by resource, retain progress across profile switches and
block only conflicting actions. Verify model sizes/hashes before installation.
Removal validates owned paths and never deletes linked external data. Removing
a language retains shared OCR/translation resources; mapped files await startup
cleanup. Model changes invalidate worker caches. Runtime-only translation setup
preserves models. Downloads, generated packs and environments stay outside Git.

### Audio and Anki

Yomitan audio lookup is GPL-3.0-or-later with bundled attribution. Support source
IDs, URL-encoded `{term}`/`{reading}`/`{language}` placeholders, `audioSourceList`
JSON and local `android.db`. Custom HTTP(S) sources may use local servers.
Explicit choices have no hidden fallback. Defaults prefer built-in recordings
before system speech; imports retain source order/URLs and require installed OS
voices. Wikimedia retains Japanese reading-qualified matching and attribution.
Downloaded clips remain available for Anki.

Each Anki save snapshots its headword group, context and settings, then queues
worker preparation of mapped fields only. `glossary-first` uses the first entry;
`glossary` uses all returned entries; `popup-selection-text` stays separate.
Sentence furigana uses exact headwords. Card HTML stays independent of popup
fonts/links; kanji exports use captured full data. Hover screenshots and OCR crops
come from the same frame.

Duplicate checks use native `dupe:` queries and exact deck IDs, including filtered
cards' original decks. Selected scopes always include the destination. Check before
preparation and recheck deck scopes after media upload; keep Anki's final guard.
AnkiConnect has no conditional transaction, so a concurrent insert remains possible.
Status results are keyed by lookup revision, groups and settings. Stale checks
cannot erase a newer save; live checks reconcile deleted notes. Saved state belongs
to each headword/reading, and its checkmark opens the notes. Anki unavailability
must not block lookup or permanently disable saving.

## Validation

After implementation changes, run once in the project environment:

```sh
python -m unittest discover -s tests
```

Use small fixtures for lookup, rendering, cancellation and imports. Real-model
checks are for analysis changes or specific failures. OCR accuracy, global input,
fullscreen, display scaling and clean-machine installation need user acceptance.
`WORDCEL_TIMING=1` reports stage timings without text, pixels or paths.

For a test handoff, inspect `git log @{upstream}..HEAD` and the corresponding diff,
plus uncommitted changes. Group changed behavior into a short checklist in the
conversation: action, expected result and relevant commits. Distinguish automated
checks from untested platform behavior. No changelog or standing test-status file.

## OCR providers

The shared desktop selects providers explicitly in
`gui/unified_ocr.py` (`ScanWorker.provider`), with language coverage in
`language/support.py`. Adding a provider also requires its Settings/setup
handling; dropping a directory into `ocr/providers/` does not register it here.
Keep recognition local, model setup explicit and initialization worker-bound.
Turkish setup prefers its default provider over other installed engines: PaddleOCR
on Windows, Apple Vision on macOS. Saved provider choices remain unchanged.
`ocr/windows_native.py` uses Windows.Media.Ocr through lazy PyWinRT imports.
Only installed system OCR languages are selectable; recognizers and bitmaps
stay on the scan worker. Normalized boxes reuse the shared Japanese hit lookup.
Japanese removes Windows' inserted single ASCII separators between Japanese
tokens and rebuilds source offsets, retaining boxes and Latin word spaces.
Windows language packs are managed in Windows Settings; Wordcel does not download them.

Providers use [ocr/interface.py](../src/wordcel/ocr/interface.py):
`Paragraph(full_text, words, box, is_vertical)` contains
`Word(text, separator, box, source_start=None)` records. Preserve the original
text and offsets. Boxes use normalized center x/y, width and height relative
to the input image: a pixel box `(x, y, w, h)` in an image `(W, H)` becomes
`((x + w/2)/W, (y + h/2)/H, w/W, h/H)`. Supply actual writing orientation;
a tall box alone does not establish vertical text.

### Optional Paddle ONNX export

Ordinary Paddle setup uses the native runtime. An optional ONNX export needs
a separate Python 3.12 conversion environment; keep the desktop on Paddle 3.2.2.
Install the OCR models first in Settings or with
`wordcel search --setup-ocr paddle`, then:

```powershell
py -3.12 -m venv .venv-ocr-export
.\.venv-ocr-export\Scripts\python -m pip install paddlepaddle==3.1.1 paddle2onnx==2.1.0 onnx==1.17.0
.\.venv-ocr-export\Scripts\python -m pip install --no-deps -e .
.\.venv-ocr-export\Scripts\python -m wordcel.scripts.export_turkish_ocr --source-dir "$env:USERPROFILE\.paddlex\official_models" --output build\turkish-onnx
.\.venv-desktop\Scripts\python -m wordcel.scripts.quick_lookup --setup-ocr paddle --onnx-dir build\turkish-onnx
```

Setup verifies source/export hashes and loads both models before activation.
Normal setup restores native Paddle. Conversion dependencies are not needed
at runtime.

## Packaging

Routine reinstalls are local Windows test builds with source commits pushed to
GitHub. Public releases follow user testing and an explicit release request;
mark new releases as latest and retain older releases, assets and tags.
Windows setup skips the license, welcome, destination and confirmation pages;
license notices remain bundled with the app.

Desktop releases contain the Windows setup EXE and two macOS DMGs, for Apple
silicon and Intel. Bundles include Python and core libraries; Paddle and
Stanza/Torch engines are installed explicitly alongside their model downloads.
`packaging/optional_runtimes.py` records exact upstream wheel URLs and SHA256s
from the build environment, analyzes their imports, then removes their owned
files from the app bundle. Shared core dependencies stay bundled. Engine setup
verifies downloads and native imports before publishing an immutable directory;
inference only activates installed packages. Windows upgrades
preserve settings/data; uninstall offers removal, also available unattended
through `/REMOVEUSERDATA=1`.

Storage exports/imports installed resources without settings or download caches.
Archives are platform-specific; optional engines also require the same build's
manifest. Import checks paths and hashes before publishing, preserves existing
resources and rolls back new entries on failure. Transfer jobs exclude setup
and removal jobs. Run core and optional-engine packaging checks separately;
the latter uses engine imports and small tensors, without downloading models.

macOS releases reuse one self-signed identity; PR builds are ad-hoc signed.
Create the release identity with OpenSSL 3 and
`bash packaging/create-macos-signing.sh /absolute/private/backup-directory`.
Store base64-encoded `signing.p12` as `MACOS_SIGNING_P12` and `password.txt`
contents as `MACOS_SIGNING_PASSWORD` in repository Actions secrets. Back up
both outside Git and reuse them across releases and architectures. Apple
notarization and Windows publisher signing still require release credentials.
Permission retention across macOS updates needs hands-on verification.

## Upstream work

Japanese rules were inherited from upstream Meikipop's
[Nazeka rules](https://github.com/wareya/nazeka/blob/master/dict/deconjugator.json).
Turkish analyzer fixes/context preferences and Persian spelling recovery were
adapted from [Anki Miner](https://github.com/0xzerolight/anki_miner/tree/808b5208bf93d919b3f18ea3aba66db5fd7fd0ea/anki_miner/languages).
Shared word/sentence policies were independently implemented with its registry
design as a reference. Pitch, input and Anki integration drew on
[Chibipop](https://github.com/stellarie/chibipop). Anki duplicate scopes and
preparation ordering follow [Mangatan](https://github.com/1Selxo/Mangatan/tree/6022576909b2cbc9a97286822f801d316b30371b/lib/services/mining).
The Screen AI adapter follows
[Meikikai's native bridge](https://github.com/hectahertz/meikikai/tree/50efb401/src/meikikai/ocr/providers/chrome_screen_ai).
Licenses and attributions ship in `src/wordcel/resources/licenses/`.
