# Using Wordcel

## Get started

[Download](https://github.com/namidanokisetsu/wordcel/releases) Wordcel, open it,
and choose a language. Setup offers dictionaries and an OCR model to download.
See [supported languages](LANGUAGES.md) for coverage.

Wordcel runs in the system tray. Right-click its icon to open **Search**,
**Translate**, **History** or **Settings**.

After the first language choice, Wordcel offers the resources needed for that
profile. You can skip downloads and install them later from the relevant
settings page; setup then returns to usable Search without opening a tutorial.

### macOS permissions

In **System Settings > Privacy & Security**, enable Wordcel under:

- **Screen & System Audio Recording** (called **Screen Recording** on older
  versions): capture text for OCR.
- **Input Monitoring**: detect scan keys, mouse buttons and global shortcuts.
- **Accessibility**: handle scan/pin controls and copy selected text from other apps.

Then choose **Quit** from Wordcel's menu-bar icon and reopen it. Closing the
search window does not quit Wordcel. If running from source, grant access to
the launching terminal or app shown in these lists.

If manual search works but OCR or **Command+Shift+D** does nothing, check these
permissions first. Manual Search and Settings remain available when access is
denied, with recovery actions shown beside the affected feature. See Apple's
[privacy settings guide](https://support.apple.com/guide/mac-help/change-privacy-security-settings-on-mac-mchl211c911f/mac).

## Look up a word

- Hold **Shift** and point at a word on screen. Click while holding Shift to
  keep the result open. **Escape** closes it.
- For subtitles or a dialogue box, turn on **Hover scan** in the tray menu
  and select an area. Hover over words there without holding a key.
- For typed text, open **Search** from the tray.

Select Japanese text and press **Ctrl+Shift+D** (**Command+Shift+D** on macOS)
to look up its first word.
Click the captured text in the search field to look up another word.
The highlight marks the match; **Translate** uses the full selection.

Point at the first character of Japanese or Chinese words. If subtitles change
while you're holding Shift, release it and press again to capture the new text.

Pinning a result shows its full definitions. Click a dictionary heading to
collapse it, or a kanji to see its details. Hover over an icon to see what it does.

To copy a passage, choose **Grab text** in the tray and drag across the dimmed
screen. Release to copy; **Escape** or right-click cancels. Enable its optional
shortcut in **Shortcuts > Grab text from screen** (preset **Ctrl+Shift+X**). Recognition uses
the active profile. Select within one display at a time.

## Settings

Settings has one page for each task: **General** for startup, initial profile,
history and storage; **Lookup** for OCR and capture; **Dictionaries** for
installed sources and resources; **Shortcuts** for lookup, capture, popup and
profile switching; **Appearance** for popup layout and content; **Audio** for
playback and sources; **Translation** for translation options and its
connection; and **Anki** for AnkiConnect, note mapping and saving.

Profile pages apply to the profile selected in **Editing**. The profile menu
can create, duplicate, rename, reorder, activate and delete profiles. Editing
a profile does not activate it; the header identifies the profile being edited
and the active profile. Each profile has its own preferences, including OCR,
dictionaries, shortcuts, appearance, audio, translation and Anki settings.

Each page has **Restore defaults…**. The confirmation names the page and scope.
The profile menu also has **Reset profile settings…**. These actions preserve
the profile's language and identity, feature enablement, connection assignments,
installed resources, history, credentials and Anki notes. They do not download
resources or request permissions. On **Shortcuts**, profile switching keys have
their own app-wide restore action.

In **Dictionaries**, use **Import ZIPs** to add Yomitan packs. If a bundle
contains several ZIPs, extract the outer archive first. Select a dictionary and
choose **Remove** to remove it from every profile. Use the resource controls on
the relevant page to install missing dictionaries, OCR or translation models.

**Startup > Preload OCR** prepares the active engine in the background by default.
Turn it off to load models on the first scan. Loaded models stay in memory until
Wordcel exits; dictionary-only mode skips preloading.

## Lookup history

Open **History** from the tray. Optional buttons for Search and OCR popups are
in **Settings > History**; a popup shortcut is in **Shortcuts > Popup**.
Recording is off until enabled; its
default scope is pinned and manual/text lookups. **Settings > History** also
offers hover recording after a display duration (initially 0.5 seconds), retention
and **Clear history**. Retention defaults to forever. Turning recording off keeps
existing encounters available and preserves your recording choices.

Search by word, reading, encountered form, stored meaning or sentence fragment;
Japanese fragments need no spaces. Meaning search uses the wording seen when
recorded, without translation or synonyms. Each visit has its own card showing
the encountered form. Double-click a card to open fresh dictionary
results without autoplay or recording another encounter. Copy from the card or its
right-click menu. The menu also offers **Add to Anki** and **Delete**; select a
card and press Delete to remove it.

History stores text locally, without screenshots, audio or page addresses.
Anki remains the destination for deliberate study.

## Listen or translate

In **Settings > Translation**, **Translate when no definition is found** and
**Auto-translate sentences** are off by default. These apply per profile to
submitted text when translation is set up. Sentence detection uses punctuation,
line breaks or three or more word groups. Automatic output keeps definitions and
click lookup available. Typing previews and OCR hover do not trigger translation.

Use the popup's audio icons to hear a word or sentence. Choose voices and
recordings in your profile's **Audio** settings.
Profiles default to built-in recordings before system speech, with providers chosen by language.
Source priority lists the providers directly; check or reorder them there. Saved
source choices are preserved. Use **+** for additional providers or a Yomitan custom URL. Custom URL (JSON) accepts the
same endpoint as Yomitan, including local audio servers. **Import Yomitan** reads
audio sources from an exported settings file; reorder sources to set priority.
System voices come from your operating system; browser-only voices may be unavailable.

Translation is enabled by default for existing profiles; its automatic
translation options remain individually configurable. Download a model in
**Translation**, then open **Translate** from the tray.
Choose the languages and enter text. Translation runs offline after setup.

## Save to Anki

Install [AnkiConnect](https://ankiweb.net/shared/info/2055492159) and keep Anki open.

1. Open your profile's **Anki** settings, tick **Enable Anki**, configure the
   inline AnkiConnect connection, and click **Refresh**.
2. Choose your deck and note type, then map the fields. Use **Word** for the first field.
3. Click the popup's **+** icon to save. With duplicates prevented, the checkmark opens existing notes;
   with duplicates allowed, overlapping circles add another note.

Map sentence, screenshot and audio fields if you want those on your cards. Saves run in the background;
turn on **Anki tray notifications** for save results.
Keep Wordcel open until queued saves finish.

[Development notes](DEVELOPMENT.md) cover running from source and building the app.
