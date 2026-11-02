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
| Profiles and resources | `config/profiles.py`, `gui/dictionary_manager.py`, `gui/data_manager.py`, `data_assets.py` |
| History | `history.py`, `gui/lookup_history.py` |
| Translation | `dictionary/translation.py` |
| Audio and Anki | `audio/`, `gui/lookup_audio.py`, `anki.py`, `gui/anki.py` |

## Contracts

- **Lookup:** exact entries and imported forms precede analysis. Preserve source
  offsets, dictionary order and full records for Anki. Unspaced lookup starts at
  the pointed character. Japanese uses bundled deconjugation; Turkish uses shared
  Zeyrek analysis and precomputed rankings, never Stanza. Other languages may use
  Stanza. Keep NLP imports lazy and runtime analysis offline. LLM output belongs
  only in translation, never dictionary definitions or ranking.
- **Workers:** capture, OCR, lookup, downloads, history and Anki preparation stay
  off the UI thread. Reuse analyzers/providers and reject stale results by request,
  profile and resource revision. OCR preloading uses installed resources only and
  yields to scans. Shortcut changes must not block the UI.
- **Popup:** pinning freezes results. Preserve document, selection, scroll and
  geometry during disclosure and translation. Derive layout from content bounds;
  batch updates instead of rebuilding unchanged content. Autoplay runs on new
  results or the explicit pin preference, never restoration or rendering.
  Separate ranks from multiple frequency dictionaries occupy a new line;
  single-dictionary and combined ranks stay inline without source labels.
  Pitch has no source labels.
- **Input:** Windows OCR keeps source-app focus; manual search accepts focus.
  Unhandled `nativeEvent` must return `(False, 0)` directly because the PyQt base
  call can crash. macOS uses a narrow Cocoa tray adapter; listeners confirm
  readiness and retry after permission changes. Navigation must not request
  permissions. Keep text shortcuts independently disableable. Passage capture
  uses frozen per-display images and a separate OCR mailbox; profile/provider
  changes discard pending clipboard results.
- **Translation:** edits invalidate pending work; dismissal cancels it. Respect
  IME composition, the passage-size setting and the separate 2,000-character
  dictionary limit. Automatic translation is opt-in for submitted text only;
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
  local sources. Each Anki save snapshots its word group, context and settings,
  then prepares mapped fields only. Use exact deck IDs and native `dupe:` queries,
  check before preparation and again after uploads, and retain Anki's final guard.
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
  Python and core libraries; install Paddle and Stanza/Torch explicitly with their
  models. `packaging/optional_runtimes.py` records exact wheel URLs/hashes and
  removes optional engines from bundles. Validate core and optional engines
  separately, without model downloads. Torch is 2.2.2 on Intel macOS and 2.8.0
  elsewhere.
- MeikiOCR/PaddleX OpenCV overlap still needs frozen Windows validation in both
  engine installation orders. Do not treat the combination as supported yet.
- Upgrades preserve settings/data. Uninstall can remove them, including through
  `/REMOVEUSERDATA=1`. Storage archives contain resources, not settings or caches;
  they are platform-specific and optional engines require a matching manifest.
  Verify paths/hashes, preserve existing resources and roll back failed imports.
- macOS releases reuse one self-signed identity; PR builds use ad-hoc signing.
  Create it with OpenSSL 3 and
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
WaDoku pitch data uses the
[conversion](https://github.com/classicsc/wadoku-pitch-dictionary-for-yomitan) and
[WaDoku data licence](https://www.wadoku.de/wiki/display/WAD/Wadoku.de-Daten+Lizenz).
Licences and attributions ship in `src/wordcel/resources/licenses/`.
