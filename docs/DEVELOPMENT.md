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

## Architecture and constraints

Paths below are relative to `src/wordcel/`. Settings use the `wordcel/wordcel`
Qt namespace; managed data and caches use platformdirs' `wordcel` directory.
The Meikipop settings and data directory is untouched; setup starts fresh.
No prior-version settings or internal dictionary schemas are migrated. Yomitan archive
formats remain supported, including archives without language metadata.

The retired Japanese client, pickle dictionary builders, dynamic OCR discovery
and online Lens/websocket adapters are removed. Shared Yomitan definition
converters live in `dictionary/structured_content.py` and `dictionary/plain_content.py`.

| Area | Main modules | Contract |
| --- | --- | --- |
| Dictionary library | `dictionary/library.py`, `dictionary/search.py` | Indexed local Yomitan packs; atomic imports, explicit ordering and removal; cache invalidation follows library revisions. |
| Language handling | `language/profiles.py`, `language/support.py`, `language/*_analyzer.py` | Preserve text offsets and dictionary-supported alternatives. Keep language-specific analysis separate. |
| Results and settings | `gui/quick_lookup.py`, `gui/dictionary_manager.py` | Shared renderer; retain source labels, independent expansion, selection and Back. |
| Installed data | `data_assets.py`, `gui/data_manager.py` | Worker inventory and sizes; shared models precede per-language downloads. Reuse setup jobs and dictionary removal; never delete linked external data. |
| Screen lookup | `gui/unified_ocr.py`, `gui/lookup_session.py`, `ocr/` | Capture/OCR and lookup run off the UI thread. Reject stale results; pinning freezes the current result. |
| Translation | `dictionary/translation.py` | Explicit model setup; lazy local inference, cancellation and loopback-only custom servers. |

Japanese uses bundled deconjugation rules. Its headword/reading groups rank by
installed frequency ranks, kana preference and deconjugation cost. The result
limit applies to ranked groups, retaining their source records and dictionary order.
Full dictionary matches precede prefix scanning; shared search and OCR use the
existing maximum lookup length for that scan, including it in cache identity.
Exact Japanese compounds append shorter direct prefix matches in descending
length, retaining the longest match length and the shared group limit.
Manual Japanese search adds offline romkan2 reading candidates without changing
the input or OCR lookup. Fully converted readings must match the whole query;
deconjugation and ranking reuse Japanese lookup. English results retain precedence
and ambiguous romaji readings are appended. Phrase checks still require exact
headwords; explicit English-to-Japanese translation uses the existing translator.
Turkish uses Zeyrek 0.1.3, accent
recovery and precomputed lexicon rankings; exact entries and imported forms
retain precedence. Full morpheme paths remain attached to their analyses.
Turkish lookup never starts Stanza. Other supported languages can install an
optional Stanza fallback. Expanded tokens retain every word and
one original source span; fallback tests their joined lemmas and, for a single
expanded token, its individual lemmas. Exact entries and imported forms precede it.
Russian and Persian retain their spelling recovery. Arabic recovery removes
tatweel and ordinary vowel marks only after exact headword/reading lookup fails;
hamza, madda and distinct letters remain separate. Imports stay lazy and runtime
analysis stays offline.
Unspaced lookup starts at the pointed character, including Chinese and Japanese.
Non-Japanese prefix scanning reuses `max_lookup_length` and stops at source gaps;
combining marks stay attached. Full exact matches precede prefix scanning.
Activating Turkish prepares a shared analyzer in the background; parsing is
serialized on lookup workers. Missing definitions retain analyses separately
from dictionary entries. Disclosure edits batch layout updates, and Paddle
keeps stable per-language scan callbacks so unchanged pixels reuse OCR.
Disclosure preserves the scroll offset; streaming text retains its text anchor.
Japanese headword and compact-card kanji links share one detail pane below the
dictionary viewport. Selection replaces its contents without rebuilding the
dictionary document. A compact vertical splitter remembers the kanji height share. Kanji and translation
share divider thickness, styling and pane padding; dividers stay within their
splitter bounds. Translation headers use equal top insets.
Without a saved split, its position fits the rendered glyph block and pane header,
subject to available space. Opening and closing kanji never resize the popup.
Lookup prepares kanji data for every returned headword in result order.
Sticky headings retain the ruby and pitch object renderers and forward links
without navigating their own document.
Sticky scrolling batches viewport painting until heading and action anchors are
restored, so Qt's intermediate child movement is not displayed.
Snap scrolling keeps its section clipping during progress-bar dragging and maps
the pointer to the nearest reading stop without changing selection.
Wheel notches and arrows move by measured text lines within a section; page
stops use those same line boundaries. Viewport clipping excludes partial text
lines at the sticky heading and bottom edge while retaining oversized content.
Sticky heading height follows its laid-out fragment and source block, including
after width changes; it does not reserve extra padding over the first body line.
Kanji summaries merge exact duplicate values across available sources, retain
source attribution and show conflicting stroke counts separately. More appends
source-specific reference fields without rebuilding the summary. Unstructured
dictionary text stays verbatim; Anki exports retain complete source records.
Automatic popup fitting stays separate from the user's chosen reading size.
Pinning batches content and layout changes and completes fitting before repainting.
Nested document updates leave inherited paint suppression to the parent window.
Preview defaults to one definition without grammar labels; pinned results have no definition cutoff.
Dictionary display preferences only control whether a section starts collapsed.
Popup actions share the first visible sentence or headword line, reserving their
measured width. Taller actions align to the line top and reserve space below it;
smaller actions center on the line. Pinning preserves the text baseline. Icon actions use
one square button geometry; reading surfaces share a zero document margin.
Action SVGs render at the requested display scale; audio keeps natural proportions
and Close uses a smaller drawing within the shared button geometry.
Pinned dictionary footer actions share the heading actions' viewport right edge,
including the scrollbar gutter as it appears or disappears.
Reading fonts prefer antialiased outlines without grid hinting; family and size remain configurable.
Button visibility and sentence size are saved per profile.
Multiple headword/reading groups have their own audio and Anki controls anchored
to cached heading blocks. Anki exports and saved-note state belong to that group;
sentence actions and automatic pronunciation retain their existing scope.
Translation uses a separate reading surface and the existing worker; returning
keeps the dictionary document, selection and scroll intact.
Compact language labels and a viewport loading indicator keep streaming updates
separate from loading animation. The output indicator shows model startup before
translation. Back or dismissal cancels the request;
the fixed pane headers retain copy, language and swap actions. Source edits
invalidate requests immediately and debounce submission outside IME composition.
Previous output stays muted with its copy action disabled until replaced; streamed
and completed results must match the current revision and source text. Dismissal releases the translation
snapshot before another hover result. The stacked/horizontal splitter uses Qt
layout bounds and starts with equal panes until adjusted; editing and output
have independent scroll surfaces. Loading indicators stay inside their viewport.
The standalone translation shortcut is independently recorded and disabled by
default. Language choosers search native/English names and codes. Translation
accepts long input, splits it at paragraph, sentence or whitespace boundaries
within the explicit passage-size setting, and streams completed passages in order.
Dictionary input retains its separate 2,000-character limit. Cancellation stops
remaining passages and model output-limit failures remain explicit.
Sentence links use the full captured context, never the compact display text. Preview clicks only
pin; their mouse release never activates links exposed by the pinned layout.
Lookup autoplay runs on new lookup results, never on translation completion,
history restoration or rendering. Pin autoplay follows its separate preference.
Manual input stays in dictionary lookup, retaining available suggestions.
Clicking its text reuses language spans and Japanese prefix lookup, selecting
the returned match with UTF-16 input offsets while retaining the full sentence.
Translation requires an explicit action, including after a dictionary miss.
Windows OCR popups over a fullscreen source expand without activation and reject
mouse activation, keeping the source foreground and its taskbar hidden. The
existing Windows input hook routes unmodified arrows, Page Up/Down and Home/End
and configured popup actions to the pinned popup only while its source remains
foreground; matching releases are consumed even after dismissal. Other keyboard
input stays with the source.
Optional Windows fullscreen scan-key blocking consumes configured modifiers'
down/up pairs while still updating scan state. It defaults off per profile;
consumed modifiers remain available to popup shortcuts.
Wheel input over the popup is posted to its native window and suppressed at the
mouse hook. Native Z-order checks avoid synchronous hit-test messages from the hook.
Copy text uses these same configurable bindings without activating the popup;
an unpinned fullscreen preview routes only Copy text while a reading pane has a
selection. Source window and child-focus restoration on dismissal remains unchanged.
Manual search retains normal focus behavior. Borderless fullscreen uses the same
native monitor-bounds check. Side buttons page while over the popup and can be
disabled per profile.
Windows popups remember the source before showing, before a pin click can activate
them. Dismissal restores that source only while the popup still has focus;
temporary capture hiding never changes focus tracking. Windows also retains the
source child focus handle for restoration after editing; app-owned dialogs never
replace the source.
The text lookup shortcut opens selected text or a blank search input, without
falling back to clipboard contents. Foreground changes still cancel capture.
Unhandled native popup events return `(False, 0)` directly. Calling PyQt's base
`nativeEvent` can crash Windows handle creation; a hidden native-window fixture
covers creation, capture exclusion, focus tracking and mouse activation.
Settings groups lookup and popup bindings in Shortcuts, reusing the key recorder
and existing Anki shortcut storage. Saved bindings and disabled actions survive
profile switches. Popup actions yield to text fields, and native action repeats
are suppressed while navigation keys retain repeat scrolling. Escape retains
the existing dismissal path.
New keyboard holds do not start OCR while a popup is pinned, so modifier-based
popup actions cannot replace the result before their primary key arrives.

Keep OCR usable on its own. Non-OCR lookup actions and text shortcuts remain
independently configurable. Reuse shared rendering and input components;
preserve Japanese behavior when adding another language. Model weights,
dictionary packs, generated assets and environments stay outside Git.
Settings save screen, pin and text shortcuts independently. OCR component
validation only gates provider setup; rejected choices restore the saved controls.
Settings tracks setup jobs by resource. Dictionary imports can run alongside
model downloads; only conflicting resource actions and language removal are blocked.
Each job retains its own progress and completion state across profile changes.
Initial setup searches language names and codes, reuses installed resources,
and offers explicit OCR/translation choices plus the Japanese stroke-order font.
Translation stays unchecked under Customize. The practice window is unowned so
it cannot force the lookup popup behind it; its optional text shortcut reuses the
shared recorder and saved binding. Optional speech availability does not gate setup.
New profiles offer resources without a tutorial handoff. Settings keeps Tutorial
in its footer; sample-label selection uses the shared text lookup shortcut.
Translation models use resumable Hugging Face transfers into the download cache;
only files matching the pinned size and SHA256 move into the installed models.
Cursor-leave dismissal is an app-wide opt-in, including pinned popups but excluding
corner windows, including their translation view. Corner search retains its saved
size and tray edge; geometry,
selection drags, menus and Settings prevent unintended dismissal. A retained text
selection does not override enabled cursor-leave dismissal after the mouse is released.
The shared cursor grace area expands the current window frame in logical pixels.
Polling runs only while the cursor is outside; OCR's release timer uses the same
boundary and interaction guards when cursor-leave dismissal is enabled.
Coalesced global pointer movement also checks dismissal when an inactive popup
misses Qt leave events. Windows checks physical buttons so missed Qt releases
cannot leave a translation selection permanently blocking dismissal.
Lookup and copy shortcuts share selection routing across the visible dictionary,
translation and kanji panes, preferring the focused pane.
Copy confirmation uses the frame's content rectangle and layout margins because
styling the label can invalidate the layout's cached geometry before placement.
Data removal validates owned paths before deletion. Removing a language deletes
its packs, Stanza data and Japanese font, while shared OCR/translation data stays.
Paddle's shared download retains its existing `languages/tr/paddle` storage path.
Mapped files remain visible as pending removals and are collected on a startup worker.
Model changes invalidate OCR caches on their worker; dictionary refresh drops only
Stanza analyzers whose models were removed. Runtime-only translation setup preserves
installed models. Automatic translation reverses the pair when a saved target
matches the detected source; explicit manual directions retain validation.
Fresh captured sentences use the lookup source regardless of the last manual
swap. Their editing session retains its own direction separately from saved defaults.

Anki's popup action snapshots the lookup and saves once on a worker, including
glossary conversion and mapped media preparation. Native Anki duplicate checks
precede preparation, with prevent/allow policies and deck, deck-tree, selected-deck
or collection scopes per profile. Selected decks are checked in one request and
always include the destination; the final save retains Anki's native scope guard.
Only mapped glossaries, furigana and pitch are prepared; screenshots use fast,
lossless PNG encoding. `glossary-first` uses the first
entry, `glossary` uses every returned entry, and `popup-selection-text` remains
separate. Hover scanning retains the active monitor's full capture for Anki while
OCR uses only the selected area, with both images taken from the same frame.
The hover scan area persists globally with its screen geometry and scale;
restore it only on a matching display. Hover scanning starts disabled unless
explicitly enabled at startup; restoration requires a valid saved area. Its independently recorded toggle defaults to disabled.
Automatic popup hides keep hover scanning active inside the area; explicit
dismissal through Close or Escape pauses it until the pointer leaves and returns.
An outside click returns a pinned hover result to scanning within the same area,
including after saving to Anki; saved-note state remains attached to its word.
Successful saves retain their headword/reading and Anki settings across lookups;
their checkmarks open the saved notes in Anki's browser. Live checks reconcile
deleted notes; checks started before a save cannot erase its confirmation.
Sentence furigana uses exact dictionary
headwords only, without deconjugation or full result preparation. Card glossaries
are left-aligned with compact source labels and native HTML ruby; popup rendering
stays separate.
Existing-note indicators use batched native `dupe:` searches and exact deck IDs,
including original decks for filtered cards. Checks are worker-bound and keyed by
lookup revision, headword groups and settings; stale results never mark new words.
Unavailable Anki leaves mining usable. Allowing duplicates keeps the add action.
`kanji-details` uses the captured Japanese lookup data in headword order and shares
the full kanji content renderer, with card HTML independent of popup links and fonts.

**Do not add LLM explanation, rewriting, aggregation or reranking to dictionary
lookup.** The [experiment record](LLM_EXPERIMENTS.md) documents the measured
benefits, failures and decision that integration is unjustified. Explicit
sentence translation is a separate feature.

Language availability lives in [support.py](../src/wordcel/language/support.py)
and the translation model registry. Settings uses those definitions; avoid
maintaining a second exhaustive language table in documentation.

## Validation

After implementation changes, run the fixture suite once with the project
environment:

```sh
python -m unittest discover -s tests
```

Use small fixtures for lookup, rendering, cancellation and import changes.
Real-model checks are for analysis changes or specific failures, not routine
documentation work. OCR accuracy, global input, exclusive fullscreen, display
scaling and clean-machine installation still need platform acceptance.
`WORDCEL_TIMING=1` enables stage timings, including Anki preparation and requests,
without logging text, pixels or paths.

## OCR providers

The shared desktop selects providers explicitly in
`gui/unified_ocr.py` (`ScanWorker.provider`), with language coverage in
`language/support.py`. Adding a provider also requires its Settings/setup
handling; dropping a directory into `ocr/providers/` does not register it here.
Keep recognition local, model setup explicit and initialization worker-bound.
`ocr/windows_native.py` uses Windows.Media.Ocr through lazy PyWinRT imports.
Only installed system OCR languages are selectable; recognizers and bitmaps
stay on the scan worker. Normalized boxes reuse the shared Japanese hit lookup.
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
retain one public app release and its commit history; remove older app release
pages/assets and tags.
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

Turkish uses the shared app, Yomitan library and Zeyrek analyzer. Shared input
and dictionary selection live in `gui/desktop_input.py` and
`gui/dictionary_browser.py`; they have no separate language-specific window.

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
