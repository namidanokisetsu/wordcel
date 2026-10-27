# Using Wordcel

## Get started

[Download](https://github.com/namidanokisetsu/wordcel/releases) Wordcel, open it,
and choose a language. Setup offers dictionaries and an OCR model to download.
See [supported languages](LANGUAGES.md) for coverage.

Wordcel runs in the system tray. Right-click its icon to open **Search**,
**Translate**, **History** or **Settings**.

On macOS, allow Screen Recording, Input Monitoring and Accessibility in
**System Settings > Privacy & Security**, then reopen Wordcel.

## Look up a word

- Hold **Shift** and point at a word on screen. Click while holding Shift to
  keep the result open. **Escape** closes it.
- For subtitles or a dialogue box, turn on **Hover scan** in the tray menu
  and select an area. Hover over words there without holding a key.
- For typed text, open **Search** from the tray.

Point at the first character of Japanese or Chinese words. If subtitles change
while you're holding Shift, release it and press again to capture the new text.

Pinning a result shows its full definitions. Click a dictionary heading to
collapse it, or a kanji to see its details. Hover over an icon to see what it does.

To copy a passage, choose **Grab text** in the tray and drag across the dimmed
screen. Release to copy; **Escape** or right-click cancels. Enable its optional
shortcut in **Shortcuts > Grab text from screen** (preset **Ctrl+Shift+X**). Recognition uses
the active profile. Select within one display at a time.

## Settings

Choose your profile in Settings to change its dictionaries, OCR, audio or Anki
options. In **Dictionaries**, use **Import ZIPs** to add Yomitan packs.
If a bundle contains several ZIPs, extract the outer archive first.
Select a dictionary and choose **Remove** to remove it from every profile.
Use **Choose recommendation** to download individual missing recommendations.
The list labels ZIP imports and recommended downloads; older installs may have
an unknown source. Recommended dictionaries are downloads, not built in.

Choose a profile or **Shared defaults** in **Editing**, then select a category.
Shared defaults apply to profiles that use them for popup, shortcuts or audio
playback. Clear **Use shared defaults** in a profile to customize a group; its
custom values are retained if you switch back to shared defaults. Profile settings
include dictionaries, OCR, audio sources and Anki. Search settings to jump to a
control. Switching profiles keeps the current category. **App-wide** settings
apply regardless of the selected profile.

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

Use the popup's audio icons to hear a word or sentence. Choose voices and
recordings in your profile's **Audio** settings.
Profiles default to built-in recordings before system speech, with providers chosen by language.
Source priority lists the providers directly; check or reorder them there. Saved
source choices are preserved. Use **+** for additional providers or a Yomitan custom URL. Custom URL (JSON) accepts the
same endpoint as Yomitan, including local audio servers. **Import Yomitan** reads
audio sources from an exported settings file; reorder sources to set priority.
System voices come from your operating system; browser-only voices may be unavailable.

Download a model in **Translation**, then open **Translate** from the tray.
Choose the languages and enter text. Translation runs offline after setup.

## Save to Anki

Install [AnkiConnect](https://ankiweb.net/shared/info/2055492159) and keep Anki open.

1. Open your profile's **Anki** settings, tick **Enable Anki**, and click **Refresh**.
2. Choose your deck and note type, then map the fields. Use **Word** for the first field.
3. Click the popup's **+** icon to save. With duplicates prevented, the checkmark opens existing notes;
   with duplicates allowed, overlapping circles add another note.

Map sentence, screenshot and audio fields if you want those on your cards. Saves run in the background;
turn on **Anki tray notifications** for save results.
Keep Wordcel open until queued saves finish.

[Development notes](DEVELOPMENT.md) cover running from source and building the app.
