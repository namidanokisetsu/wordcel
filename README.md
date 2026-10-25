# Wordcel

[Download](https://github.com/namidanokisetsu/wordcel/releases/latest) · [User guide](docs/USER_GUIDE.md)

![Wordcel lookup demo](docs/images/lookup-demo.gif)

Wordcel is a Windows and macOS popup dictionary for games, subtitles and other screen text. Look up words by holding a shortcut or hovering over a chosen scan area, or search typed and selected text. You can hear pronunciations, translate sentences and longer passages, and save words to Anki with definitions, sentence context, screenshots and available audio.

Japanese dictionaries provide readings, pitch accent and kanji details. Choose the dictionaries and models to download during setup. OCR, lookup and translation then work offline, with optional online pronunciation recordings.


- App: Python, PyQt6, SQLite.
- Dictionaries: Yomitan.
- OCR: MeikiOCR, PaddleOCR PP-OCRv6, Chrome Screen AI, Windows OCR, Apple Vision.
- Translation: Hy-MT2 1.8B / 7B via llama.cpp.
- Word forms: Japanese deconjugation rules, Turkish Zeyrek, optional Stanza for other languages.
- Audio: system TTS, Wikimedia recordings, local audio databases.

Fork of [rtr46/meikipop](https://github.com/rtr46/meikipop). GPL-3.0.
