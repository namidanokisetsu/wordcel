# Using Wordcel

Check the [FAQ](#faq) for quick fixes. Bug reports, suggestions and feature requests
are always welcome: [open an issue](https://github.com/namidanokisetsu/wordcel/issues/new).

## Get started

[Download](https://github.com/namidanokisetsu/wordcel/releases) and open Wordcel,
then choose a language. Setup offers dictionary lookup with optional screen
recognition. Fonts, word-form models and translation are separate choices;
add them later in **Settings**. See [supported languages](LANGUAGES.md).

Click Wordcel's tray/menu-bar icon to open **Search**. Right-click it for
**Settings** or **Quit**. Closing Search leaves Wordcel running.

## Look up a word

- Hold **Shift** and point at a word on screen. Click while holding Shift to
  keep the result open. **Escape** closes it.
- For subtitles or a dialogue box, turn on **Hover scan** in the tray menu
  and select an area. Hover over words there without holding a key.
- To type a word, open **Search**.

For selected Japanese text, press **Ctrl+Shift+D** (**Command+Shift+D** on macOS).
Click a word in the captured text to look it up. **Translate** uses the full
selection. Change or disable text shortcuts in **Shortcuts**.

Point at the first character of Japanese or Chinese words. If subtitles change
while you're holding Shift, release it and press again to capture the new text.

Pin a result to see full definitions. Click a dictionary heading to collapse it,
or a kanji to see its details. Click another kanji in the word at the top to switch
characters. Use the word breadcrumb or Back to return.
Hide dictionary names in **Popup > Content > Pinned > Dictionary labels**;
definitions stay visible while labels are hidden.

To copy a passage, choose **Grab text** in the tray and drag within one display.
Release to copy; **Escape** or right-click cancels. Its optional shortcut is in
**Shortcuts > Grab text from screen** (preset **Ctrl+Shift+X**).

## Settings

Expand **App settings** for Startup, Profile switching, History and Storage. Expand **Profile settings**
and choose a profile under **Editing** to change its settings without activating it.

Use **Reset [section]…** for the open section or **Reset profile settings…** for a profile.
Resets keep your profiles, enabled features, connections, credentials, downloaded
resources, history and Anki notes. **App settings > Profile switching** contains
the Next profile and Previous profile shortcuts, which apply across all profiles.

Reinstalling keeps settings and resources unless you remove them. On Windows,
choose to remove user data in the uninstaller. On macOS, quit Wordcel, delete
the app, and remove `~/Library/Application Support/wordcel`, `~/Library/Caches/wordcel`
and the `com.wordcel.wordcel` preferences domain (`defaults delete com.wordcel.wordcel`).
Files linked from other folders stay untouched.

In **Dictionaries**, use **Import ZIPs** to add Yomitan dictionaries. If a ZIP
contains other ZIPs, extract it first. Removing a dictionary removes it from
every profile. Download dictionaries here, OCR resources in **Lookup**, and
translation models in **Translation**.

Downloads continue when you close or minimize setup. Use **Cancel downloads** or
**Cancel** to stop them. **App settings > Storage** shows running jobs. Progress shows
the current step; estimated download time excludes verification and installation.

Japanese recommendations include JMdict, KANJIDIC, Jiten Global and the WaDoku pitch
dictionary. [Jiten frequency data](https://jiten.moe/frequency-dictionaries) uses
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
WaDoku data is attributed to [Wadoku](https://www.wadoku.de) and
distributed under its [data licence](https://www.wadoku.de/wiki/display/WAD/Wadoku.de-Daten+Lizenz).

**App settings > Startup > Preload OCR** loads the OCR model at startup. Turn it off
to load it on the first scan. The model stays in memory until Wordcel exits.
Dictionary-only mode skips preloading.

Enable **App settings > Startup > Start at login** on macOS to open Wordcel at your
next login. On Windows, use **Start with Windows**.

## Lookup history

Enable recording in **App settings > History**, then open **History** from the tray.
It saves pinned results and searches by default, with no expiry. Change what
gets recorded, set retention or clear history in **App settings > History**.
Turning recording off keeps existing history.

Search by word, reading, encountered form, stored meaning or sentence fragment.
Double-click a card to look it up again. This does not play audio or add another
history entry. Right-click to copy, save to Anki or delete. History saves text
on your computer, without screenshots, audio or page addresses.

## Listen or translate

Click the popup's audio icons to hear a word or sentence. Choose and reorder
sources in **Audio**. Recordings play before system speech by default. Use **+**
to add a source or custom Yomitan audio URL. **Import Yomitan** imports audio
sources from a Yomitan settings export. Browser-only voices may be unavailable.

Download a model in **Translation**, then open **Translate** from the tray,
choose languages and enter text. Translation runs offline after setup.
On Windows, **Runtime** selects Automatic, CPU, Vulkan or CUDA. Automatic uses
a compatible GPU when detected, otherwise CPU. Switching runtimes reuses models.
**Compact** is a smaller Q4 option; **Lightweight** and **Quality** retain Q8.
Use **Add model…** for another GGUF quantization from a public Hugging Face
repository or a local file. It must be compatible with llama.cpp and fit in memory.
Transfer estimates exclude verified cached files; interrupted downloads resume.
**Translate when no definition is found** and **Auto-translate sentences** are
off by default. Enable them per profile to translate submitted text automatically.
Typing or hovering over OCR text does not trigger translation.

## Save to Anki

Install [AnkiConnect](https://ankiweb.net/shared/info/2055492159) and keep Anki open.

1. In your profile's **Anki** settings, tick **Enable Anki**, configure
   AnkiConnect, and click **Refresh**.
2. Choose your deck and note type, then map the fields. Use **Word** for the first field.
3. Click the popup's **+** icon to save. For words already saved, the checkmark
   opens the existing note. If duplicates are allowed, overlapping circles let
   you add another note.

Map sentence, screenshot and audio fields to include them on cards. Keep Wordcel
open until saves finish. Turn on **Anki tray notifications** to see save results.

## FAQ

### OCR or Shift lookup doesn't work

- **Lookup > OCR model:** check that the selected model is installed and ready.
- **Shortcuts > Screen lookup key:** check for **Shift** or use your configured key.
- **Conflicts:** change the key if another app or shortcut uses it.

### Wordcel won't open on macOS

Move Wordcel from the DMG to **Applications**. If macOS blocks it, use
**System Settings > Privacy & Security > Open Anyway**, then **Open**.
[Apple's instructions](https://support.apple.com/en-us/102445).

### Scanning or shortcuts don't work on macOS

In **System Settings > Privacy & Security**, enable:

- **Screen Recording** (or **Screen & System Audio Recording**) for capture.
- **Input Monitoring** for scan keys, mouse buttons and shortcuts.
- **Accessibility** for pinning and copying selected text.

Quit and reopen Wordcel after changes. If it still fails, quit and toggle the
affected permission off and on. If needed, use **− / +** to remove and re-add
**Applications > Wordcel.app** where available, then enable it and reopen.

Source runs need permissions for the launching terminal or app. Manual Search needs none.

### Bugs, suggestions or feature requests

[Open an issue](https://github.com/namidanokisetsu/wordcel/issues/new) at any time.
For bugs, include what happened and how to reproduce it; screenshots help.
For suggestions, describe what you'd like to do. No template required.
