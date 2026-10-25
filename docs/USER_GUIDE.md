# Using Wordcel

## Get started

[Download](https://github.com/namidanokisetsu/wordcel/releases) Wordcel, open it,
and choose a language. Setup offers dictionaries and an OCR model to download.
See [supported languages](LANGUAGES.md) for coverage.

Wordcel runs in the system tray. Right-click its icon to open **Search**,
**Translate** or **Settings**.

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

## Settings

Choose your profile in Settings to change its dictionaries, OCR, audio or Anki
options. In **Dictionaries**, use **Import ZIPs** to add Yomitan packs.
If a bundle contains several ZIPs, extract the outer archive first.

Shared shortcuts are under **App > Shortcuts**. **Storage** manages downloads.

## Listen or translate

Use the popup's audio icons to hear a word or sentence. Choose voices and
recordings in your profile's **Audio** settings.

Download a model in **Translation**, then open **Translate** from the tray.
Choose the languages and enter text. Translation runs offline after setup.

## Save to Anki

Install [AnkiConnect](https://ankiweb.net/shared/info/2055492159) and keep Anki open.

1. Open your profile's **Anki** settings, tick **Enable Anki**, and click **Refresh**.
2. Choose your deck and note type, then map the fields. Use **Word** for the first field.
3. Click the popup's **+** icon to save. The checkmark opens the saved note.

Map sentence, screenshot and audio fields if you want those on your cards.

[Development notes](DEVELOPMENT.md) cover running from source and building the app.
