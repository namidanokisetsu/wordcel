# Using Wordcel

## Get started

[Download](https://github.com/namidanokisetsu/wordcel/releases) Wordcel, choose a
language, and install the offered resources. Downloads can be skipped and added
later in **Settings**. See [supported languages](LANGUAGES.md) for coverage.

Click the tray/menu-bar icon to open **Search**; on macOS, the Dock icon also
works. Right-click for **Settings**, **Quit** and other actions. Closing Search
leaves Wordcel running; use **Quit** to exit. For macOS setup problems, see
[FAQ](#faq).

## Look up a word

- Hold **Shift** and point at a word on screen. Click while holding Shift to
  keep the result open. **Escape** closes it.
- For subtitles or a dialogue box, turn on **Hover scan** in the tray menu
  and select an area. Hover over words there without holding a key.
- For typed text, open **Search** from the tray.

For selected Japanese text, press **Ctrl+Shift+D** (**Command+Shift+D** on macOS).
Click another word in the captured text to look it up; **Translate** uses the
full selection. Text shortcuts can be changed or disabled in **Shortcuts**.

Point at the first character of Japanese or Chinese words. If subtitles change
while you're holding Shift, release it and press again to capture the new text.

Pinning shows full definitions. Click dictionary headings to collapse them or
kanji to see details.

To copy a passage, choose **Grab text** in the tray and drag within one display.
Release to copy; **Escape** or right-click cancels. Its optional shortcut is in
**Shortcuts > Grab text from screen** (preset **Ctrl+Shift+X**).

## Settings

Open **Settings** from the tray. **General** holds startup, history and storage;
the other pages cover lookup, dictionaries, shortcuts, appearance, audio,
translation and Anki.

The profile menu manages profiles. **Editing** selects whose settings you change;
it does not activate that profile. Each profile has its own preferences.

Use **Restore defaults…** for one page or **Reset profile settings…** for a profile.
Resets preserve profile identity, feature enablement, connections, credentials,
resources, history and Anki notes. Profile switching shortcuts are app-wide and
have a separate reset.

In **Dictionaries**, use **Import ZIPs** for Yomitan packs; extract any outer
bundle first. **Remove** removes a dictionary from every profile. Missing
dictionaries and models can be installed on their relevant settings pages.
Japanese recommendations include JMdict, KANJIDIC, BCCWJ and the WaDoku pitch
dictionary. WaDoku data is attributed to [Wadoku](https://www.wadoku.de) and
distributed under its [data licence](https://www.wadoku.de/wiki/display/WAD/Wadoku.de-Daten+Lizenz).

**General > Startup > Preload OCR** prepares scanning in the background by
default. Turn it off to load models on the first scan; loaded models stay in
memory until Wordcel exits. Dictionary-only mode skips preloading.

## Lookup history

Enable recording in **General > History**, then open **History** from the tray.
By default, it records pinned and manual/text lookups and keeps them forever.
Hover recording, retention, popup buttons and **Clear history** are in the same
settings page; a popup shortcut is in **Shortcuts > Popup**. Turning recording
off keeps existing history.

Search by word, reading, encountered form, stored meaning or sentence fragment.
Double-click a card for fresh dictionary results without autoplay or another
recorded visit. Right-click to copy, **Add to Anki** or **Delete**; Delete also
works on a selected card. History stores text locally, without screenshots,
audio or page addresses.

## Listen or translate

Use the popup's audio icons to hear a word or sentence. In **Audio**, enable and
reorder providers; recordings play before system speech by default. Use **+**
for additional providers or a Yomitan custom URL, including local JSON audio
servers. **Import Yomitan** reads sources from exported settings. System voices
come from your OS; browser-only voices may be unavailable.

Download a model in **Translation**, then open **Translate** from the tray,
choose languages and enter text. Translation runs offline after setup.
**Translate when no definition is found** and **Auto-translate sentences** are
off by default and configurable per profile. They apply to submitted text;
typing previews and OCR hover never trigger translation.

## Save to Anki

Install [AnkiConnect](https://ankiweb.net/shared/info/2055492159) and keep Anki open.

1. In your profile's **Anki** settings, tick **Enable Anki**, configure
   AnkiConnect, and click **Refresh**.
2. Choose your deck and note type, then map the fields. Use **Word** for the first field.
3. Click the popup's **+** icon to save. With duplicates prevented, the checkmark opens existing notes;
   with duplicates allowed, overlapping circles add another note.

Map sentence, screenshot and audio fields to include them on cards. Saves run
in the background; keep Wordcel open until they finish. **Anki tray
notifications** show save results.

## FAQ

### Wordcel won't open on macOS

Drag Wordcel from the downloaded DMG to **Applications** and open it there.
If macOS cannot verify the developer or check the app for malicious software,
go to **System Settings > Privacy & Security > Open Anyway**, then confirm
**Open**. Use this for downloads from the official releases linked above.
See [Apple's instructions](https://support.apple.com/en-us/102445).

### Scanning or shortcuts don't work on macOS

Allow Wordcel's permission requests. If skipped, enable it manually in
**System Settings > Privacy & Security** under:

- **Screen & System Audio Recording** (or **Screen Recording**): screen capture.
- **Input Monitoring**: scan keys, mouse buttons and global shortcuts.
- **Accessibility**: scan/pin controls and copying selected text.

Quit Wordcel from its menu-bar icon, then reopen it. If permissions are already
enabled but still fail, quit first, toggle the affected permission off and on,
and reopen. If needed, quit again, remove Wordcel with **−** and re-add
**Applications > Wordcel.app** with **+**, where available; enable it and reopen.
For source runs, grant permissions to the launching terminal or app instead.
Manual Search works without these permissions.

### Report a bug

[Open an issue](https://github.com/namidanokisetsu/wordcel/issues/new) and describe
what went wrong; screenshots help. Sign in to GitHub; no template required.

[Development notes](DEVELOPMENT.md) cover running from source and building the app.
