"""Explicit installation of openly published Yomitan dictionaries."""
from dataclasses import dataclass
from pathlib import Path
import tempfile
from urllib.request import urlopen

from .library import import_yomitan, language_code

from wordcel.language.support import DICTIONARY_LANGUAGES
from wordcel.utils.dictionary_download import download_archive


@dataclass(frozen=True)
class RecommendedDictionary:
    title: str
    language: str
    url: str
    website: str
    pack_title: str = ""
    index_url: str = ""
    exact_title: bool = False

    @property
    def identity(self):
        import hashlib
        return hashlib.sha256((self.language + ":" + self.url).encode()).hexdigest()

    def matches(self, metadata):
        title = self.pack_title or self.title
        return metadata["language"] == self.language and (
            metadata["title"] == title if self.exact_title else metadata["title"].startswith(title))


def recommendations(language):
    language = language_code(language)
    if language not in DICTIONARY_LANGUAGES:
        return ()
    # Mandarin headwords are published under Chinese; the cmn pack is a small supplement.
    archive_language = "zh" if language == "cmn" else language
    wiktionary = RecommendedDictionary("Wiktionary · English definitions", language,
            f"https://huggingface.co/datasets/daxida/wty-release/resolve/main/latest/dict/{archive_language}/en/wty-{archive_language}-en.zip?download=true",
            "https://yomidevs.github.io/wiktionary-to-yomitan/download/", f"wty-{archive_language}-en")
    if language == "ja":
        return (RecommendedDictionary("JMdict", "ja",
                "https://github.com/yomidevs/jmdict-yomitan/releases/latest/download/JMdict_english.zip",
                "https://github.com/yomidevs/jmdict-yomitan", "JMdict ["),
                wiktionary,
                RecommendedDictionary("Kanji · KANJIDIC", "ja",
                "https://github.com/yomidevs/jmdict-yomitan/releases/latest/download/KANJIDIC_english.zip",
                "https://github.com/yomidevs/jmdict-yomitan", "KANJIDIC"),
                RecommendedDictionary("Frequency · Jiten Global", "ja",
                "https://api.jiten.moe/api/frequency-list/download",
                "https://jiten.moe/frequency-dictionaries", "Jiten",
                "https://api.jiten.moe/api/frequency-list/index", exact_title=True),
                RecommendedDictionary("Pitch · WaDoku", "ja",
                "https://github.com/classicsc/wadoku-pitch-dictionary-for-yomitan/releases/latest/download/wadoku-pitch.zip",
                "https://github.com/classicsc/wadoku-pitch-dictionary-for-yomitan", "Wadoku Pitch Accent",
                "https://github.com/classicsc/wadoku-pitch-dictionary-for-yomitan/releases/latest/download/index.json"))
    return (wiktionary,)


def install_recommended(dictionary, directory, progress, cancelled):
    progress(f"Downloading {dictionary.title}…")
    with tempfile.TemporaryDirectory(prefix="wordcel-dictionary-") as folder:
        archive = Path(folder) / "dictionary.zip"
        download_archive(dictionary.url, archive, dictionary.title, progress, cancelled, urlopen)
        return import_yomitan(archive, directory, language=dictionary.language,
                             progress=progress, cancelled=cancelled.is_set,
                             resource_id=dictionary.identity, source=dictionary.website, origin="recommended")
