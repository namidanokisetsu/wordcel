# Using Wordcel

[Download](https://github.com/namidanokisetsu/wordcel/releases) · [Supported languages](LANGUAGES.md)

Having trouble? See [Troubleshooting](#troubleshooting).

## Get started

Choose a language and install a dictionary. For screen lookup, choose an engine
in **Settings > Lookup > OCR model** and complete any offered download.

## Look up words

Press **Ctrl+Shift+D** and type or paste a word. Results appear as you type.
To look up selected text in another app, select it and use the same shortcut.
On macOS, use **Command+Shift+D**.

For text in a game, image or video, hold **Shift** and point at a word.
Point at the first character of Japanese or Chinese words. Release Shift and
hold it again to capture new text.

Click while holding **Shift** to pin the popup and read the full definitions.
Press **Escape** to close it. Click a word in captured text to look it up,
or a kanji for details.

For subtitles, enable **Hover scan** in the tray menu, select an area when
prompted, then hover over words. To copy a passage from the screen, choose
**Grab text** and drag over it; **Escape** cancels selection.

Click the tray/menu-bar icon to open Search; right-click for the menu.
Closing Search leaves Wordcel running. Choose **Quit** in the menu to exit.

## Audio, translation and saved words

- **Listen:** click a word or sentence audio icon. Choose sources in **Audio**;
  right-click word audio for other readings and sources.
- **Translate:** download a model in **Translation**, then open **Translate** from
  the tray and type or paste text. You can also translate captured text from
  the popup. Translation works offline after setup.
- **Anki:** keep Anki open with [AnkiConnect](https://ankiweb.net/shared/info/2055492159).
  In **Settings > Anki**, enable it, click **Refresh**, select a deck and note type,
  and map **Word** to the first field. Sentence, screenshot and audio are optional.
  Click **+** in a result to save; a checkmark opens an existing note.
- **History:** enable recording in **App settings > History**, then open
  **History** from the tray. Double-click to look up a saved word; right-click
  to copy, save to Anki or delete. History stays on your computer.

## Essential settings

Choose a profile under **Editing** to change it without activating it.

| Setting | Where |
| --- | --- |
| OCR engine | **Lookup > OCR model** |
| Yomitan dictionaries | **Dictionaries > Import ZIPs** |
| Keyboard and mouse shortcuts | **Shortcuts** |
| Appearance, vertical placement and cursor-leave closing | **Popup** |
| Audio sources | **Audio** |
| Translation models and optional automatic translation | **Translation** |
| Start at login, preload OCR | **App settings > Startup** |
| Profile shortcuts | **App settings > Profile switching** |
| Downloads and stored resources | **App settings > Storage** |

**Compact view** shows meanings from the first headword and dictionary; pin for
examples, synonyms, forms and the full entry. **Meanings** limits senses per
headword and dictionary in either preview mode; **All** keeps every meaning.
Popups stay open when the cursor leaves unless cursor-leave closing is enabled.

For inflected or attached words, install **word-form support** in
**Dictionaries** if offered for your language.

Downloads continue when setup closes. Dictionary removal affects all profiles.
Resets and reinstalls keep resources and saved data.

## Troubleshooting

**Screen lookup does nothing:** confirm the engine is ready in **Lookup > OCR model**,
then try another engine and check **Shortcuts > Screen lookup key**. Windows OCR
requires the relevant Windows language pack. Manual Search works without OCR.

**macOS won't open Wordcel:** move it from the DMG to **Applications**, then use
**System Settings > Privacy & Security > Open Anyway** if blocked.
[Apple's instructions](https://support.apple.com/en-us/102445).

**macOS scanning or shortcuts fail:** enable these permissions in
**System Settings > Privacy & Security**, then quit and reopen Wordcel:

| Permission | Needed for |
| --- | --- |
| Screen Recording / Screen & System Audio Recording | Capture |
| Input Monitoring | Scan keys, mouse buttons and shortcuts |
| Accessibility | Scan controls and copying selected text |

If needed, toggle the permission or remove and re-add Wordcel. Source runs need
permissions for the launching terminal or app. Manual Search needs none.

[Report an issue](https://github.com/namidanokisetsu/wordcel/issues/new) with your
Wordcel version, operating system, steps to reproduce, and what you expected
versus what happened.
