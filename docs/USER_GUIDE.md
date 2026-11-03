# Using Wordcel

[Quickstart](#quickstart) · [Settings](#settings) · [FAQ](#faq) · [Supported languages](LANGUAGES.md)

## Quickstart

1. [Download](https://github.com/namidanokisetsu/wordcel/releases) and open Wordcel.
2. Choose a language and install a dictionary. Install OCR for screen lookup;
   translation is optional.
3. Try a lookup below. On macOS, use **Command** for **Ctrl**.

### Look up words

| Use case | What to do |
| --- | --- |
| Type or paste a word | Press **Ctrl+Shift+D**, enter text and press **Enter**. |
| Look up selected text | Select text in another app, then press **Ctrl+Shift+D**. |
| Read a game, image or video | Hold **Shift** and point at a word. Requires OCR. |
| Read subtitles hands-free | Choose **Hover scan** in the tray, select the subtitle area and hover over words. |
| Read full definitions | Click while holding **Shift** to pin. **Escape** closes it. |
| Copy a passage from an image | Choose **Grab text** in the tray, drag over text and release to copy. **Escape** cancels. |

- Point at the first character of Japanese or Chinese words.
- For new subtitles, release Shift and hold it again.
- Click a kanji for details; use Back to return to the word.
- Click a word in captured text to look it up.
- By default, popups close when the cursor leaves, including pinned results. Change this in **Popup**.

Click the tray/menu-bar icon for **Search**; right-click for **Settings** or **Quit**.
Closing Search leaves Wordcel running.

### Listen or translate

- **Listen:** click a word or sentence audio icon. Choose sources in **Audio**.
- **Translate:** download a model in **Translation**, then open **Translate**
  from the tray and enter text. You can also translate captured text from lookup.
  Works offline after setup.

### Save a word to Anki

Keep Anki open with [AnkiConnect](https://ankiweb.net/shared/info/2055492159) installed.

1. In **Settings > Anki**, enable Anki and click **Refresh**.
2. Choose a deck and note type. Map **Word** to the first field; optionally map
   sentence, screenshot and audio.
3. Click **+** in a result. A checkmark opens an existing note.

### Revisit a word

Enable recording in **App settings > History**, then open **History** from the tray.
Search by word or sentence. Double-click to look it up;
right-click to copy, save to Anki or delete. History stays on your computer.

## Settings

Choose a profile under **Editing** to change its settings without activating it.

| Task | Where |
| --- | --- |
| Install or change the OCR engine | **Lookup > OCR model** |
| Add a Yomitan dictionary ZIP | **Dictionaries > Import ZIPs** |
| Change scan keys or text shortcuts | **Shortcuts** |
| Change appearance or cursor-leave closing | **Popup** |
| Set audio sources or import Yomitan audio settings | **Audio** |
| Download a translation model | **Translation** |
| Start at login or preload OCR | **App settings > Startup** |
| Set profile-switching shortcuts | **App settings > Profile switching** |
| Manage downloads and stored resources | **App settings > Storage** |

- **Downloads:** continue when setup closes. Use **Cancel** to stop them.
- **Dictionaries:** extract ZIPs containing other ZIPs first. Removing a dictionary affects every profile.
- **Popup:** Compact view shows the first headword and dictionary without labels
  or extra details. The preview definition limit applies with Compact view on or off;
  pin to see full definitions.
- **Shortcuts:** change or disable bindings independently. Grab text, Hover scan
  and Translate have optional presets.
- **Translation:** enable automatic translation per profile for submitted text.
  **Add model…** accepts compatible GGUF files.
- **Resets and reinstalls:** keep your resources and saved data.

## FAQ

### OCR or Shift lookup does nothing

1. **Check the engine is installed:** open **Settings > Lookup > OCR model**.
   Confirm the selected engine is ready and finish any offered download.
2. **Try another engine on the same text.** On Windows, try **Windows OCR** if
   PaddleOCR fails. Windows OCR needs the relevant Windows language pack.
3. **Check your scan key** in **Shortcuts > Screen lookup key**. Try another key
   if an app already uses Shift or your chosen key.
4. **On macOS, check permissions below**, then quit and reopen Wordcel.

For lookup without OCR, press **Ctrl+Shift+D** and type a word.

### Wordcel won't open on macOS

Move it from the DMG to **Applications**. If blocked, use
**System Settings > Privacy & Security > Open Anyway**, then **Open**.
[Apple's instructions](https://support.apple.com/en-us/102445).

### Scanning or shortcuts don't work on macOS

In **System Settings > Privacy & Security**, enable these permissions for Wordcel:

| Permission | Needed for |
| --- | --- |
| Screen Recording / Screen & System Audio Recording | Capture |
| Input Monitoring | Scan keys, mouse buttons and shortcuts |
| Accessibility | Pinning and copying selected text |

Quit and reopen after changes. If it still fails, toggle the permission off and on
or remove and re-add Wordcel. Source runs need permissions for the launching
terminal or app. Manual Search needs none.

### Still stuck, or have a suggestion?

[Open an issue](https://github.com/namidanokisetsu/wordcel/issues/new) for bugs,
suggestions or feature requests. Include reproduction steps and OCR engines tried.
