# Development

Repository rules: [AGENTS.md](../AGENTS.md). Usage: [user guide](USER_GUIDE.md).

## Run from source

Use Python 3.12. Quit Wordcel first: source and installed builds share
settings/data, and only one instance runs at a time.

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

Grant macOS permissions to the launching terminal or app. Install dictionaries
and models in Settings. Pass `--no-ocr` to the launcher for manual lookup only.
For the Python commands below, use `.\.venv-desktop\Scripts\python` on Windows
or `.venv/bin/python` on macOS.

## Code map

Paths are under `src/wordcel/`. Languages share input and rendering.

| Area | Modules |
| --- | --- |
| Dictionary import and search | `dictionary/` |
| Language analysis and coverage | `language/` |
| Popup and result state | `gui/quick_lookup.py`, `gui/lookup_session.py`, `gui/dictionary_browser.py` |
| Capture and OCR | `gui/desktop_input.py`, `gui/unified_ocr.py`, `ocr/` |
| Shortcuts | `gui/lookup_shortcuts.py`, `gui/text_shortcuts.py` |
| Profiles and resources | `config/profiles.py`, `gui/dictionary_manager.py`, `gui/data_manager.py`, `data_assets.py` |
| History | `history.py`, `gui/lookup_history.py` |
| Translation | `dictionary/translation.py`, `translation_catalog.py` |
| Audio and Anki | `audio/`, `gui/lookup_audio.py`, `anki.py`, `gui/anki.py`, `gui/lookup_anki.py` |

## Core contracts

- **Lookup:** exact entries and imported forms precede analysis. Preserve source
  spans, dictionary order and original records for audio and Anki. Unspaced lookup
  starts at the pointed character. Definitions come only from dictionaries;
  LLM output is restricted to translation, never lookup ranking.
- **Language analysis:** preserve Japanese deconjugation. Turkish uses shared
  Zeyrek analysis and precomputed rankings, never Stanza. Other languages may use
  Stanza; Windows Arabic optionally uses an isolated CAMeL worker with Stanza
  fallback. Keep NLP imports lazy and runtime analysis offline. Arabic matching
  preserves spelling distinctions and supplied vowels; roots never replace lemmas.
  Context ranks readings without removing alternatives. Keep expensive resource
  preparation out of runtime lookup.
- **Workers:** capture, OCR, lookup, downloads, history and Anki preparation stay
  off the UI thread. Reuse analyzers/providers and reject stale results by request,
  profile and resource revision. Preloading uses installed resources and yields
  to scans. Publish dictionary results before optional analysis updates.
- **Capture and input:** Windows OCR preserves source-app focus. Exclude the popup
  from capture; when exclusion fails, retain the clean hover frame until dismissal
  or source input. Other captures mask popup bounds. Window-capture fallback keeps
  screen coordinates and masks pixels outside the source window. Release capture
  resources on their worker. `LookupShortcuts` owns global listener lifecycle;
  text shortcuts remain independently disableable. Unhandled `nativeEvent` returns
  `(False, 0)` directly: the PyQt base call can crash. Passage capture uses frozen
  per-display images and a separate OCR mailbox; provider/profile changes discard
  pending clipboard results. Navigation never requests permissions.
- **Rendering:** pinning freezes results. Preserve selection, scroll, visible text
  anchors and geometry during disclosure, resizing, translation and Back. Derive
  layout from content and batch updates without rebuilding unchanged content.
  Preserve writing orientation and a reachable path to vertical popups. Suspend
  cursor-leave dismissal during resizing until the pointer returns inside.
  Autoplay runs only for new results or the explicit pin preference.
- **Definitions:** keep each dictionary's content in preference order. Normalize
  recognized structured senses while preserving unrecognized text and raw Anki
  records. Preview budgets apply per headword and source. Compact previews show
  complete senses without examples, synonyms or form supplements, even with an
  unlimited budget. Japanese readings share headings only when full dictionary
  content, rules and analyses match; retain original word/reading choices.
  Arabic headings use compatible vowelled readings, with direction per block.
  Anki Word uses the displayed Arabic heading; audio/history retain original IDs.
- **Shared UI:** configure Qt Fusion before widgets; use bundled fonts, shared
  drawn icons, layout metrics and palettes. Preserve explicit profile fonts and
  popup themes. Register fonts once at startup without downloads. Keep native
  tray, permissions, focus and shortcut integration.
- **Translation:** edits invalidate work and dismissal cancels it. Respect IME
  composition, passage limits and the separate 2,000-character dictionary limit.
  Automatic translation alongside dictionary results is opt-in and runs on
  submission, not typing or OCR hover. The Translate panel translates as you type.
  Custom servers stay loopback-only. The catalog owns model revisions, hashes and memory budgets;
  probe devices during setup, never inference. Runtime identity includes backend.
  Custom GGUFs use verified hashes, sizes and safe managed paths.
- **Profiles and resources:** editing does not activate a profile. Preferences use
  Qt's `wordcel/wordcel` namespace; data uses platformdirs' `wordcel` storage.
  Profiles share downloaded resources. Resets use explicit key sets and preserve
  identity, enabled features, connections, credentials, resources, history and
  Anki notes. Setup is explicit, cancellable and keyed by resource across profile
  switches. Closing setup does not cancel it. Verify sizes/hashes before activation,
  delete only owned paths and invalidate caches when resources change.
- **History:** recording is opt-in. Visits use language, encountered form, context
  and span; repeated OCR does not restart the hover timer. Rendering, Back and
  restoration never record visits. A serial worker owns `history.sqlite3` and its
  search engine; use ordinary SQLite indexes, without FTS extensions.
- **Audio and Anki:** preserve configured source order and attribution; no hidden
  fallback providers. `LookupAnki` owns save queues and duplicate state. Snapshot
  each save's word group, context and settings; prepare mapped fields only. Use
  exact deck IDs and native `dupe:` queries, checking before preparation and after
  uploads while retaining Anki's final guard. Failures must not block lookup or
  permanently disable saving.

## OCR providers

Register providers in `gui/unified_ocr.py` (`ScanWorker.provider`), coverage in
`language/support.py`, and setup in Settings. Initialization stays on a worker;
preserve saved engine choices and Japanese text offsets, boxes and Latin spaces.

The [OCR interface](../src/wordcel/ocr/interface.py) returns
`Paragraph(full_text, words, box, is_vertical)` containing
`Word(text, separator, box, source_start=None)` records. Boxes use normalized
center x/y, width and height: pixel `(x, y, w, h)` in image `(W, H)` becomes
`((x+w/2)/W, (y+h/2)/H, w/W, h/H)`. Preserve actual writing orientation;
a tall box alone does not establish vertical text.

## Validation

Run once after implementation changes, in the project environment:

```sh
python -m unittest discover -s tests
```

Use small fixtures; OCR fixtures need NumPy, not models. Real-model checks are
for analysis changes or specific failures. Global input, OCR accuracy, fullscreen,
scaling and installation need manual acceptance. `WORDCEL_TIMING=1` logs stage
timings without text, screenshots or paths.

Targeted diagnostics:

- `python -m wordcel.scripts.diagnose_capture` checks Windows capture with controlled
  windows and writes a text report without screenshots or OCR. It does not test
  the full hover workflow.
- Set `WORDCEL_NATIVE_CAPTURE_TEST=1`, then run
  `python -m unittest discover -s tests -p test_native_capture_workflow.py` for
  the native Windows workflow. Requires installed Japanese OCR and briefly covers
  the primary screen. `WORDCEL_TEST_OCR=windows` selects Windows OCR.
- `python -m wordcel.scripts.check_arabic --library <path> --mode <dictionary|stanza|morphology|context>`
  runs curated MSA smoke checks. Setup is separate; these are not corpus accuracy
  measurements.

## Packaging

Builds: [.github/workflows](../.github/workflows). Bundle and installer helpers:
[packaging](../packaging). Release policy: [AGENTS.md](../AGENTS.md).

- Ship a Windows EXE and Apple silicon/Intel DMGs. Bundle Python and core libraries;
  optional engines/models require explicit setup. `packaging/optional_runtimes.py`
  owns pinned wheel URLs/hashes. Validate core and optional engines separately.
- Keep Paddle in its isolated runtime site and Arabic morphology/context in their
  own worker. Morphology excludes Torch; context adds it. Prevent implicit model
  downloads. MeikiOCR/PaddleX OpenCV coexistence still requires frozen Windows
  validation in both installation orders before claiming support.
- Upgrades preserve settings/data. Uninstall may remove them with
  `/REMOVEUSERDATA=1`. Storage archives contain resources, not settings or caches;
  verify platform/manifests, paths and hashes, preserving resources on failure.
- macOS releases reuse one self-signed identity; PR builds use ad-hoc signing.
  See `packaging/create-macos-signing.sh` and `.github/workflows/sign-macos.yml`; keep signing secrets
  outside Git. Notarization and Windows publisher signing require credentials;
  macOS permission retention needs manual verification.
- Bundle font licences and data attribution from `src/wordcel/resources/licenses/`,
  including WaDoku's data licence, not only the converter's CC0 notice.
