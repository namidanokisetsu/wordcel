# Development

Repository rules: [AGENTS.md](../AGENTS.md). Usage: [user guide](USER_GUIDE.md).

## Run from source

Use Python 3.12. Quit any running Wordcel first: source and installed builds
share settings/data, and only one instance runs at a time.

Windows:

```powershell
py -3.12 -m venv .venv-desktop
.\.venv-desktop\Scripts\python -m pip install -e .
.\start-wordcel.cmd
```

macOS:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -e .
./start-wordcel.command
```

Grant macOS permissions to the launching terminal or app. Download dictionaries
and models in Settings. `wordcel`, `wordcel search` and `wordcel-search` use the
same desktop app; `python -m wordcel.scripts.quick_lookup --no-ocr` skips OCR.

## Code map

Paths below are under `src/wordcel/`. All languages share input and rendering.

| Area | Modules |
| --- | --- |
| Dictionary import, search and updates | `dictionary/` |
| Language support and analysis | `language/` |
| Popup and result state | `gui/quick_lookup.py`, `gui/lookup_session.py`, `gui/dictionary_browser.py` |
| Capture and OCR | `gui/desktop_input.py`, `gui/unified_ocr.py`, `ocr/` |
| Global shortcuts | `gui/lookup_shortcuts.py`, `gui/text_shortcuts.py` |
| Profiles and resources | `config/profiles.py`, `gui/dictionary_manager.py`, `gui/data_manager.py`, `data_assets.py` |
| History | `history.py`, `gui/lookup_history.py` |
| Translation | `dictionary/translation.py` |
| Audio and Anki | `audio/`, `gui/lookup_audio.py`, `anki.py`, `gui/anki.py`, `gui/lookup_anki.py` |

## Contracts

- **Shared UI:** configure Qt Fusion before creating widgets. Controls use bundled
  Noto Sans at 13 logical pixels; default Japanese text uses Noto Sans JP and Arabic
  uses bundled Noto Naskh Arabic with Noto Sans for Latin text (OFL; Arabic font SHA256
  `67b5a525a661b607971fbd3f96a81b89d3a768e74534fca84f18ac97e6fab72f`). Preserve
  explicit profile fonts and fall back without overwriting unavailable choices.
  Use shared drawn icons and layout metrics, not font symbols or platform offsets.
  Settings follow the system light/dark preference with shared palettes; popup
  themes remain profile-specific. Tray, permissions, focus and shortcuts retain
  native integration. Font registration happens once at startup, without downloads.
  Startup registration uses the per-user Windows Run key or a macOS LaunchAgent.
  macOS opens the current app bundle in the background at login; source registration
  preserves the virtual environment's Python path. Disabling removes the entry.
  Fonts and OFL licences come from [Google Fonts](https://github.com/google/fonts/tree/2fe1e8c6b137fb13041a7cfca6fdcd8a910ea4dc/ofl)
  (`notosans`, `notosansjp`, `notonaskharabic`); include them in wheels and desktop bundles.
- **Lookup:** exact entries and imported forms precede analysis. Preserve source
  offsets, dictionary order and full records for Anki. Unspaced lookup starts at
  the pointed character. Japanese uses bundled deconjugation; Turkish uses shared
  Zeyrek analysis and precomputed rankings, never Stanza. Other languages may use
  Stanza. Expanded clitics prefer lexical words over function words; contiguous
  elisions retain their original span. Korean KAIST morphemes use XPOS to remove
  endings and plural particles and restore dictionary predicate endings.
  Persian and fallback Stanza Arabic lemmas reuse spelling recovery. Arabic form traversal
  retains source readings and grammatical rules and stops at compatible lexical
  entries. Older packs use available grammar labels until explicit reimport adds
  form metadata; no runtime migration or corpus scan is needed.
  Arabic future-prefix recovery requires an attested verb-form redirect. Expanded
  model words also try their attested surface forms after their proposed lemma.
  Arabic imports add indexed unvocalized aliases for terms/readings and forms;
  `arabic_alias_version=1` requires explicit reimport of older packs. Remove only
  vowels/tatweel, retaining hamza, madda, ta marbuta and alif maqsura distinctions.
  Windows Arabic analysis uses CAMeL Tools 1.6.0 / CALIMA MSA R13 in one lazy,
  authenticated CPU worker shared across search engines, with 120-second idle exit.
  The primary analyzer has strict normalization. CALIMA's folded stem index is also
  queried, admitting only outputs whose Arabic spelling and supplied marks match.
  Lexical matching tolerates omitted predictable vowels, not conflicting ones.
  Roots never substitute for lemmas. Preserve analyses' original surface spans.
  Definitions remain dictionary-only. Missing CAMeL resources retain Stanza fallback.
  Keep NLP imports lazy and runtime analysis offline. LLM output belongs only in
  translation, never dictionary definitions or ranking.
  OCR previews require dictionary entries, kanji or spelling suggestions;
  standalone Turkish analysis remains available in manual search.
  Display normalization recognizes numbered plain-text `pos:`, `ex:` and `syn:`
  records by format, including Wordset, and feeds shared structured definitions
  to the renderer. Unrecognized text and original records for Anki stay intact.
- **Workers:** capture, OCR, lookup, downloads, history and Anki preparation stay
  off the UI thread. Reuse analyzers/providers and reject stale results by request,
  profile and resource revision. OCR preloading uses installed resources only and
  yields to scans. Shortcut changes must not block the UI.
  Windows screen capture uses popup exclusion. If unavailable, hover retains the
  clean OCR frame while its preview is visible, including its Anki snapshot, and
  ignores captures already in flight. Dismissal, source clicks, wheel input and
  unconsumed source keys discard that frame and allow fresh capture. Popup input
  and pinning retain their normal behavior. Source changes without input remain
  frozen until dismissal. Other desktop captures blank the popup's physical bounds;
  covered source text is unavailable in those captures, including Anki snapshots.
  A desktop capture failure can use a worker-owned Windows Graphics Capture
  session for the source window. Source captures retain screen coordinates and
  blank pixels outside that window, including in Anki snapshots. Capture failures
  keep the popup visible and retry setup on a new source or scan session. Session
  invalidation releases capture resources on the worker; native exclusion errors
  appear in the opt-in timing trace. Capture errors also appear outside hidden popups.
- **Popup:** pinning freezes results. Preserve document, selection, scroll and
  geometry during disclosure and translation. Keep visible text anchored during
  resizing and text scaling; resize source excerpts without rebuilding definitions.
  OCR hits retain writing orientation. With the default-on profile preference
  `vertical_popup_sides`, vertical previews open beside the captured lookup point.
  Keep the path to the facing popup edge available until first entry, including
  across blank OCR space and pinning; then resume normal cursor-leave dismissal.
  Suspend cursor-leave dismissal during resizing until the released pointer returns
  inside the popup, including when minimum size or screen bounds clamp the drag.
  Kanji uses the shared content stack; the existing breadcrumb and Back restore
  the word document, selection and scroll. Copy only the clicked headword and
  furigana, keeping its visible baseline anchored across the transition. Switch
  between prepared kanji records without a new lookup. Shrink glyph ink bounds to
  fit the remaining height and half the content width; never enlarge past the
  rendered font size (96 px, or 128 px for stroke order).
  Keep each dictionary's content in preference order, with meanings, readings
  and examples grouped within each source. Align glyph ink to the first rendered
  text line; derive spacing from definition text size.
  Retain the originating headword through history and translation.
  Derive layout from content bounds;
  batch updates instead of rebuilding unchanged content. Autoplay runs on new
  results or the explicit pin preference, never restoration or rendering.
  Separate ranks from multiple frequency dictionaries occupy a new line;
  single-dictionary and combined ranks stay inline without source labels.
  Pitch has no source labels. Pitch and plain readings share the profile's
  `font_size_reading`, independent of headword size; text scale applies to both.
  Japanese readings share a heading only when complete dictionary sets, raw
  definitions, usage rules and analyses match. Cache presentation groups per
  result; retain original `(term, reading)` records for audio and Anki choices.
  Arabic headings use compatible vocalized dictionary readings directly, without
  Latin readings or ruby. Keep different readings separate. Direction is per block:
  Arabic content is RTL, English definitions and metadata LTR. Preserve structured
  dictionary direction attributes. Anki Word uses the displayed Arabic headword;
  audio/history identities retain the original dictionary term and reading.
  Arabic lookup publishes dictionary results before morphology/context updates.
  Updates share request cancellation and revision checks, preserve the reading
  position, and retain heading order while selecting or scrolled. Context ranks
  attested readings before model-only lemma matches without removing alternatives.
  Multiple grammar analysis chains use shared disclosure in every language,
  keyed to the headword group. Single chains stay inline; expansion keeps the
  existing reading position and requires no new analysis.
- **Input:** Windows OCR keeps source-app focus; manual search accepts focus.
  Unhandled `nativeEvent` must return `(False, 0)` directly because the PyQt base
  call can crash. macOS uses a narrow Cocoa tray adapter; listeners confirm
  readiness and retry after permission changes. Navigation must not request
  permissions. `LookupShortcuts` owns global listener bindings, retries and shutdown.
  Keep text shortcuts independently disableable. Passage capture
  uses frozen per-display images and a separate OCR mailbox; profile/provider
  changes discard pending clipboard results.
- **Translation:** edits invalidate pending work; dismissal cancels it. Respect
  IME composition, the passage-size setting and the separate 2,000-character
  dictionary limit. Language selection uses an anchored child inside the panel,
  without a modal window or nested event loop. Automatic translation is opt-in
  for submitted text only;
  typing, OCR hover, positional lookup and history restoration never trigger it.
  Keep custom translation servers loopback-only.
  `translation_catalog.py` owns model IDs, revisions, hashes, sizes and memory
  budgets. Existing Q8 selections stay unchanged. Q4 passed a bounded eight-prompt
  Japanese/Turkish comparison on arm64. Fresh setup recommends Q4 with 3 GiB
  available after a 2 GiB system
  reserve; unknown memory recommends no download. Budgets include 8K context
  and inference buffers. Driver/device probes run on a setup worker. Windows
  Automatic selects verified CUDA/Vulkan support, otherwise CPU; macOS stays
  native. Runtime directories, manifests and server reuse include backend
  identity. Inference uses installed metadata without probing or downloading.
  Recommended models share the runtime with user-selected single-file GGUFs.
  Custom identities bind SHA256, size and safe paths; Hub files also pin a
  publisher commit. Import copies local files into managed storage. Custom models
  retain their choice across profiles and exports without Hy-MT2 language limits.
- **Profiles and data:** use independent preferences in Qt's `wordcel/wordcel`
  namespace and platformdirs' `wordcel` storage. Editing does not activate a
  profile. Duplication copies mutable connection records but shares downloaded
  resources. Resets use explicit key sets and keep identity, enabled features,
  connections, resources, history, credentials and Anki notes. They never request
  permissions, download resources or clear the whole namespace.
- **Resources:** setup is explicit, cancellable and keyed by resource across
  profile switches. Verify sizes/hashes before activation. Delete only owned
  paths; keep external data and shared resources. Model changes invalidate caches;
  mapped files wait for startup cleanup. First run allows skipping downloads and
  opens lookup without a tutorial. Imported packs remain user-managed. Bundle
  WaDoku's data licence, not just the converter's CC0 notice.
  First run leaves fonts, Stanza and translation unchecked. Setup requests
  validate one operation before deriving job identity and worker dispatch.
  Coalesce worker progress before Qt delivery; lock aliases share one visible job.
  Item counts describe batches; percentages and rate-based estimates describe only
  the current transfer. Verification/install stages remain separate and untimed.
  Closing setup hides it without cancelling; cancellation is explicit.
  Engine wheels and translation archives share verified resumable downloads;
  URL/hash/size metadata and HTTP validators bind partials. Publication follows
  size/SHA256 checks; Hugging Face retains its model downloader. Dictionary
  installs/updates share transport with separate import/revision validation.
- **History:** recording is opt-in. A visit is identified by language, encountered
  form, context and span; repeated OCR must not restart its hover timer. Rendering,
  Back and restoration never record a visit. A serial worker owns `history.sqlite3`
  and its search engine. Use ordinary SQLite indexes, without FTS extensions;
  deletion/retention clean up orphan records. Refresh cards without losing scroll
  or selection.
- **Audio and Anki:** preserve explicit audio source order, URLs and attribution;
  do not add hidden fallback providers. Support Yomitan placeholders, JSON and
  local sources. `LookupAnki` owns popup save queues and duplicate state; the window
  renders button states and handles layout. Each save snapshots its word group,
  context and settings, then prepares mapped fields only. Use exact deck IDs and
  native `dupe:` queries, check before preparation and again after uploads, and
  retain Anki's final guard.
  Concurrent inserts remain possible. Key status by word/reading and revision;
  Anki failures must not block lookup or permanently disable saving.

## Test

Run once after implementation changes, in the project environment:

```sh
python -m unittest discover -s tests
```

Use small fixtures; OCR fixtures need NumPy but no models. Real-model tests are
for analysis changes or specific failures. Global input, OCR accuracy, fullscreen,
scaling and installation need manual acceptance. `WORDCEL_TIMING=1` logs stage
timings without text, screenshots or paths. Handoff rules are in AGENTS.md.

Windows capture can be checked independently with
`python -m wordcel.scripts.diagnose_capture`. It compares opaque/translucent popup
exclusion, masked desktop capture and WGC against controlled windows, using the
production capture code. It writes `wordcel-capture-report.txt` without screenshots
or source text and does not load app settings or OCR models. Other windows covering
the fixtures can invalidate the pixel checks. Build the standalone checker with
`python -m PyInstaller --noconfirm packaging/capture-check.win.spec`; the EXE writes
its report beside itself. This checks capture only, not the full hover/OCR workflow.
For the native Windows workflow check, set `WORDCEL_NATIVE_CAPTURE_TEST=1` and run
`python -m unittest discover -s tests -p test_native_capture_workflow.py`.
It uses temporary settings/dictionaries and installed Japanese OCR, with native
capture/rendering and injected shortcut events. It briefly covers the primary screen.
It checks failed exclusion with retained hover, source refresh, pinning and Shift,
plus normal live capture. `WORDCEL_TEST_OCR=windows` selects Windows OCR instead
of MeikiOCR.

Arabic's bounded comparison uses `tests/fixtures/arabic_msa.json` (60 curated MSA
cases): `python -m wordcel.scripts.check_arabic --library <path> --mode <dictionary|stanza|morphology|context>`.
`--ocr-component <path>` runs real Screen AI on controlled text images;
`--test-root <path>` isolates downloaded resources, and `--output <file>` saves
results. Setup is separate. Measure warm uncached lookup and the worker's actual
Windows PID, not the venv launcher. Targets: morphology <512 MiB/<200 ms;
context <2 GiB/<1 s. Curated fixtures are smoke checks, not corpus accuracy claims.

## OCR providers

Register providers in `gui/unified_ocr.py` (`ScanWorker.provider`), language
coverage in `language/support.py`, and setup in Settings. Keep initialization
worker-bound. Turkish defaults to PaddleOCR on Windows and Apple Vision on macOS;
preserve saved choices. Windows native OCR uses installed system language packs.
Japanese whitespace normalization must retain Latin spaces, boxes and offsets.

Use [ocr/interface.py](../src/wordcel/ocr/interface.py):
`Paragraph(full_text, words, box, is_vertical)` contains
`Word(text, separator, box, source_start=None)` records. Boxes are normalized
center x/y, width and height. Convert pixel `(x, y, w, h)` in image `(W, H)` to
`((x+w/2)/W, (y+h/2)/H, w/W, h/H)`. Preserve text offsets and actual writing
orientation; a tall box does not establish vertical text.

<details>
<summary>Optional Paddle ONNX export</summary>

Normal setup uses native Paddle 3.2.2. Export in a separate Python 3.12 environment
after installing OCR models in Settings or with `wordcel search --setup-ocr paddle`:

```powershell
py -3.12 -m venv .venv-ocr-export
.\.venv-ocr-export\Scripts\python -m pip install paddlepaddle==3.1.1 paddle2onnx==2.1.0 onnx==1.17.0
.\.venv-ocr-export\Scripts\python -m pip install --no-deps -e .
.\.venv-ocr-export\Scripts\python -m wordcel.scripts.export_turkish_ocr --source-dir "$env:USERPROFILE\.paddlex\official_models" --output build\turkish-onnx
.\.venv-desktop\Scripts\python -m wordcel.scripts.quick_lookup --setup-ocr paddle --onnx-dir build\turkish-onnx
```

Setup verifies hashes and loads both models before activation. Normal setup
restores native Paddle; conversion dependencies are not needed at runtime.

</details>

## Packaging

Build workflows are in [.github/workflows](../.github/workflows); bundle and
installer helpers are in [packaging](../packaging). Release policy is in AGENTS.md.

- Desktop releases contain the Windows EXE and Apple silicon/Intel DMGs. Bundle
  Python and core libraries; install Stanza/Torch explicitly with their models.
  Arabic has separate morphology/context wheel manifests for Windows x64/Python
  3.12. The small morphology component excludes Torch; context adds CPU Torch and
  Transformers 4.57.6. Both load only in the Arabic worker, never `activate()`.
  Its pinned runtime manifest is component-specific: only morphology imports and
  their dependencies are installed for CALIMA. `docopt` supplies no upstream wheel;
  copy its module/licence from the verified sdist without running setup.py.
  Download CALIMA R13 and the MSA BERT archive explicitly with pinned sizes/hashes;
  exclude ranking caches, other dialects and translation models. The worker supplies
  a temporary empty CAMeL catalogue and offline Hub flags to prevent implicit fetches.
  Paddle's pinned packages are collected into a separate runtime site and its
  OCR worker prepends that site before importing Paddle or OpenCV. Source setup
  uses the same isolated site under app data. Worker replies contain only plain
  recognition text and word boxes; PaddleX objects and images stay in the worker.
  `packaging/optional_runtimes.py`
  records exact wheel URLs/hashes and removes optional engines from bundles.
  Validate core and optional engines separately, without model downloads. Torch
  is 2.2.2 on Intel macOS and 2.8.0 elsewhere.
- MeikiOCR/PaddleX OpenCV overlap still needs frozen Windows validation in both
  engine installation orders. Do not treat the combination as supported yet.
- Upgrades preserve settings/data. Uninstall can remove them, including through
  `/REMOVEUSERDATA=1`. Storage archives contain resources, not settings or caches;
  they are platform-specific and optional engines require a matching manifest.
  Verify paths/hashes, preserve existing resources and roll back failed imports.
- macOS releases reuse one self-signed identity; PR builds use ad-hoc signing.
  If hosted ARM runners are unavailable, validate a local ARM build and use
  `sign-macos.yml` to verify its archive hash, sign it and create the DMG on Intel.
  Create the identity with OpenSSL 3 and
  `bash packaging/create-macos-signing.sh /absolute/private/backup-directory`.
  Store base64 `signing.p12` as `MACOS_SIGNING_P12` and `password.txt` contents as
  `MACOS_SIGNING_PASSWORD` in Actions secrets. Back up both outside Git.
  Notarization and Windows publisher signing need release credentials; macOS
  permission retention needs manual verification.

## Credits

Rules and integration references:
[Nazeka](https://github.com/wareya/nazeka/blob/master/dict/deconjugator.json),
[Anki Miner](https://github.com/0xzerolight/anki_miner/tree/808b5208bf93d919b3f18ea3aba66db5fd7fd0ea/anki_miner/languages),
[Chibipop](https://github.com/stellarie/chibipop),
[Mangatan](https://github.com/1Selxo/Mangatan/tree/6022576909b2cbc9a97286822f801d316b30371b/lib/services/mining),
[Meikikai](https://github.com/hectahertz/meikikai/tree/50efb401/src/meikikai/ocr/providers/chrome_screen_ai).

[Jiten frequency data](https://jiten.moe/frequency-dictionaries):
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
[WaDoku](https://www.wadoku.de) pitch data uses the
[conversion](https://github.com/classicsc/wadoku-pitch-dictionary-for-yomitan) and
[WaDoku data licence](https://www.wadoku.de/wiki/display/WAD/Wadoku.de-Daten+Lizenz).
Licences and attributions ship in `src/wordcel/resources/licenses/`.
