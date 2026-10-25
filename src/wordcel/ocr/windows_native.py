"""Offline Windows OCR using installed system language packs."""
from functools import lru_cache
import re
import sys

from PIL import Image

from wordcel.ocr.interface import BoundingBox, Paragraph, Word
from wordcel.ocr.providers.postprocessing import _merge_bounding_boxes


@lru_cache(maxsize=1)
def supported_languages():
    if sys.platform != "win32":
        return ()
    try:
        from winrt.windows.media.ocr import OcrEngine
        return tuple(language.language_tag for language in OcrEngine.available_recognizer_languages)
    except (ImportError, OSError) as error:
        raise RuntimeError("Windows OCR is unavailable. Reinstall Wordcel's Windows dependencies.") from error


def _language_id(code, supported):
    def normalize(value):
        value = value.replace("_", "-").lower()
        return {"cmn": "zh", "fil": "tl", "zh-tw": "zh-hant", "zh-hk": "zh-hant"}.get(value, value)
    requested = normalize(code)
    available = {normalize(value): value for value in supported}
    if requested in available:
        return available[requested]
    parts = requested.split("-")
    script = next((part for part in parts[1:] if len(part) == 4), None)
    for key, value in available.items():
        if key.split("-")[0] == parts[0] and (script is None or script in key.split("-")):
            return value
    raise RuntimeError(f"Install the {code} OCR language pack in Windows Settings > Time & language.")


def supports_language(code, supported=None):
    try:
        _language_id(code, supported_languages() if supported is None else supported)
        return True
    except RuntimeError:
        return False


_JAPANESE_PAIR = re.compile(r"[\u3001-\u30ff\u3400-\u9fff\uf900-\ufaff\uff66-\uff9f\U00020000-\U000323af]{2}")


def _paragraph(line, size, language=None):
    text = line.text.strip()
    if not text or not line.words:
        return None
    width, height = size
    boxes = []
    for word in line.words:
        rect = word.bounding_rect
        left, top = max(0, rect.x / width), max(0, rect.y / height)
        right, bottom = min(1, (rect.x + rect.width) / width), min(1, (rect.y + rect.height) / height)
        boxes.append(BoundingBox((left + right) / 2, (top + bottom) / 2,
                                 max(0, right - left), max(0, bottom - top)))
    words, offset = [], 0
    for index, (word, box) in enumerate(zip(line.words, boxes)):
        start = text.find(word.text, offset)
        if start < 0:
            words = [Word(text, "", _merge_bounding_boxes(boxes), 0)]
            break
        end = start + len(word.text)
        following = text.find(line.words[index + 1].text, end) if index + 1 < len(line.words) else len(text)
        words.append(Word(word.text, text[end:max(end, following)], box, start))
        offset = end
    if language and language.split("-", 1)[0] == "ja":
        # Windows inserts ASCII spaces between Japanese OCR tokens, even glyphs.
        offset = words[0].source_start
        parts = [text[:offset]]
        for index, word in enumerate(words):
            separator = word.separator
            if (word.separator == " " and index + 1 < len(words)
                    and _JAPANESE_PAIR.fullmatch(word.text[-1:] + words[index + 1].text[:1])):
                separator = ""
            words[index] = Word(word.text, separator, word.box, offset)
            parts.append(word.text + separator)
            offset += len(parts[-1])
        text = "".join(parts)
    # Orientation follows the word centers rather than the line's aspect ratio.
    vertical = len(boxes) > 1 and abs(boxes[-1].center_y - boxes[0].center_y) * height > abs(boxes[-1].center_x - boxes[0].center_x) * width
    return Paragraph(text, words, _merge_bounding_boxes(boxes), vertical)


class WindowsOCR:
    def __init__(self, language):
        if sys.platform != "win32":
            raise RuntimeError("Windows OCR is available on Windows only.")
        from winrt.windows.globalization import Language
        from winrt.windows.media.ocr import OcrEngine
        self.engine = OcrEngine.try_create_from_language(Language(_language_id(language, supported_languages())))
        if self.engine is None:
            raise RuntimeError(f"Windows OCR could not start for {language}.")
        self.max_dimension = OcrEngine.max_image_dimension
        self.language = language

    def scan(self, image):
        from winrt.windows.graphics.imaging import BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap
        if not isinstance(image, Image.Image) or min(image.size) < 1:
            raise ValueError("Screen recognition needs a nonempty image.")
        if max(image.size) > self.max_dimension:
            ratio = self.max_dimension / max(image.size)
            image = image.resize(tuple(max(1, round(value * ratio)) for value in image.size))
        pixels = image.convert("RGBA").tobytes("raw", "BGRA")
        bitmap = SoftwareBitmap.create_copy_with_alpha_from_buffer(
            pixels, BitmapPixelFormat.BGRA8, image.width, image.height, BitmapAlphaMode.IGNORE)
        try:
            # ScanWorker owns this recognizer; blocking never reaches the Qt thread.
            result = self.engine.recognize_async(bitmap).get()
            return [paragraph for line in result.lines if (paragraph := _paragraph(line, image.size, self.language))]
        finally:
            bitmap.close()
