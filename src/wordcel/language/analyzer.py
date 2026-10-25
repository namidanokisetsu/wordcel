from dataclasses import dataclass
import unicodedata


def normalize(text: str) -> str:
    return unicodedata.normalize("NFC", text).translate(str.maketrans("Iİ", "ıi")).lower()


@dataclass(frozen=True)
class Token:
    start: int
    end: int
    lemma: str
    pos: str | None = None
