"""Model-free Arabic spelling, vocalization and display policies."""
import unicodedata


VOWELS = frozenset(chr(n) for n in range(0x064b, 0x0653)) | {"\u0670"}


def spelling(text):
    # NFC preserves hamza/madda as letters before removing only vowel marks.
    text = unicodedata.normalize("NFC", unicodedata.normalize("NFKC", text))
    return "".join(c for c in text if c not in VOWELS and c != "\u0640").translate(
        str.maketrans("کی", "كي"))


def has_vowels(text):
    return any(c in VOWELS for c in text)


def _clusters(text):
    result = []
    for char in unicodedata.normalize("NFC", unicodedata.normalize("NFKC", text)):
        if char == "\u0640":
            continue
        if char in VOWELS and result:
            result[-1][1].add(char)
        else:
            result.append((char.translate(str.maketrans("کی", "كي")), set()))
    return result


def compatible_vowels(supplied, candidate):
    """Supplied marks constrain a fully vocalized surface, never its lemma."""
    a, b = _clusters(supplied), _clusters(candidate)
    return len(a) == len(b) and all(x == y and marks <= other for (x, marks), (y, other) in zip(a, b))


def headword(term, reading):
    return reading if reading and spelling(term) == spelling(reading) and has_vowels(reading) else term


def display_headword(entry):
    return headword(entry.term, entry.reading) if entry.language == "ar" else entry.term
