"""Yomitan audio providers, ported to the shared Python worker (2026-10-28).

Copyright (C) 2023-2026 Yomitan Authors; 2017-2022 Yomichan Authors.
Adapted from ext/js/media/audio-downloader.js, GPL-3.0-or-later.
See resources/licenses/yomitan-audio.txt.
"""
from hashlib import sha256
from html.parser import HTMLParser
import re
from time import monotonic
from urllib.parse import quote, urlencode, urljoin

import requests

from wordcel.audio.online import OnlineAudio
from wordcel.audio.sources import CLASS_LANGUAGES, POD_LANGUAGES, source_key, source_label, source_type


class _Element:
    def __init__(self, tag="", attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    def find(self, *, tag=None, css=None, element_id=None):
        for child in self.children:
            if not isinstance(child, _Element):
                continue
            if ((tag is None or child.tag == tag) and
                    (css is None or css in child.attrs.get("class", "").split()) and
                    (element_id is None or child.attrs.get("id") == element_id)):
                yield child
            yield from child.find(tag=tag, css=css, element_id=element_id)

    def text(self):
        return "".join(child.text() if isinstance(child, _Element) else child for child in self.children)


class _Document(HTMLParser):
    VOID = frozenset("area base br col embed hr img input link meta param source track wbr".split())

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = _Element()
        self.stack = [self.root]
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        element = _Element(tag, attrs)
        self.stack[-1].children.append(element)
        if tag not in self.VOID:
            self.stack.append(element)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.stack.pop()

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def custom_url(template, term, reading, language):
    values = {"term": term, "reading": reading, "language": language}
    return re.sub(r"\{([^}]*)\}", lambda match: quote(values[match[1]], safe="")
                  if match[1] in values else match[0], template)


def audio_list(value):
    """Validate Yomitan's custom-audio-list-schema.json without a schema runtime."""
    if (not isinstance(value, dict) or set(value) != {"type", "audioSources"}
            or value["type"] != "audioSourceList" or not isinstance(value["audioSources"], list)):
        raise ValueError("Invalid Yomitan audio list")
    for source in value["audioSources"]:
        if (not isinstance(source, dict) or not set(source) <= {"url", "name"}
                or not isinstance(source.get("url"), str)
                or "name" in source and not isinstance(source["name"], str)):
            raise ValueError("Invalid Yomitan audio source")
    return value["audioSources"]


def audio_extension(data):
    for prefix, extension in ((b"OggS", "ogg"), (b"RIFF", "wav"), (b"fLaC", "flac")):
        if data.startswith(prefix):
            return extension
    return "m4a" if data[4:8] == b"ftyp" else "mp3"


class YomitanAudio(OnlineAudio):
    def lookup(self, term, language, iso3, cancelled=lambda: False, reading="", source="online"):
        kind = source_type(source)
        if kind in ("online", "wiktionary", "lingua-libre"):
            return super().lookup(term, language, iso3, cancelled, reading, provider=kind)
        if cancelled() or not term:
            return None
        key = (source_key(source), term, reading, language)
        cached = self.cache.get(key)
        if cached and monotonic() - cached[0] < cached[2]:
            self.cache.move_to_end(key)
            return cached[1]
        result, failed = None, False
        deadline = monotonic() + 12
        try:
            candidates = self._candidates(source, term, reading, language, cancelled, deadline)
            for candidate in candidates:
                try:
                    data = self._fetch(candidate["url"], cancelled=cancelled, deadline=deadline,
                                       audio=True, external=True)
                    if kind == "jpod101" and sha256(data).hexdigest() == (
                            "ae6398b5a27bc8c0a771df6c907ade794be15518174773c58c7c7ddd17098906"):
                        continue
                    name = candidate.get("name") or source_label(source)
                    result = (f"audio.{audio_extension(data)}", name, data, "", "")
                    break
                except (requests.RequestException, ValueError):
                    failed = True
        except (requests.RequestException, ValueError, InterruptedError):
            failed = True
        if cancelled():
            return None
        self.cache[key] = (monotonic(), result, 3600 if result else 10 if failed else 180)
        self.cache.move_to_end(key)
        while len(self.cache) > 128 or sum(len(item[1][2]) for item in self.cache.values() if item[1]) > 24 * 1024 * 1024:
            self.cache.popitem(last=False)
        return result

    def _candidates(self, source, term, reading, language, cancelled, deadline):
        kind = source_type(source)
        options = dict(cancelled=cancelled, deadline=deadline, external=True)
        if kind in ("custom", "custom-json"):
            url = custom_url(source.get("url", ""), term, reading, language)
            if kind == "custom":
                return [{"url": url}]
            return audio_list(self._fetch(url, **options))
        language = {"cmn": "zh", "fil": "tl", "nb": "no", "nn": "no"}.get(language, language).split("-", 1)[0]
        if kind in ("jpod101", "jisho") and language != "ja":
            return []
        if kind == "jpod101":
            if reading == term and re.fullmatch(r"[\u3041-\u3096\u3099-\u309e\u30a1-\u30fa\u30fc-\u30fe]+", term):
                term = ""
            params = {key: value for key, value in (("kanji", term), ("kana", reading)) if value}
            return [{"url": "https://assets.languagepod101.com/dictionary/japanese/audiomp3.php?" + urlencode(params)}]
        if kind == "jisho":
            url = "https://jisho.org/search/" + quote(term, safe="")
            dom = _Document(self._fetch(url, text=True, **options)).root
            audio = next(dom.find(element_id=f"audio_{term}:{reading}"), None)
            element = next(audio.find(tag="source"), None) if audio else None
            return [{"url": urljoin(url, element.attrs["src"])}] if element and element.attrs.get("src") else []
        if kind == "language-pod-101":
            name = POD_LANGUAGES.get(language) or CLASS_LANGUAGES.get(language)
            if name is None:
                return []
            suffix = "pod" if language in POD_LANGUAGES else "class"
            url = f"https://www.{name.lower()}{suffix}101.com/learningcenter/reference/dictionary_post"
            html = self._fetch(url, text=True, data={"post": "dictionary_reference", "match_type": "exact",
                                                    "search_query": term, "vulgar": "true"}, **options)
            dom = _Document(html).root
            results = []
            for row in dom.find(css="dc-result-row"):
                vocab = next(row.find(css="dc-vocab_kana" if language == "ja" else "dc-vocab"), None)
                if vocab is None or (language == "ja" and (not vocab.text() or reading != term and reading != vocab.text())) or (
                        language != "ja" and term != vocab.text()):
                    continue
                audio = next(row.find(tag="audio"), None)
                element = next(audio.find(tag="source"), None) if audio else None
                if element and element.attrs.get("src"):
                    candidate = {"url": urljoin(url, element.attrs["src"])}
                    if candidate not in results:
                        results.append(candidate)
            return results
        return []
