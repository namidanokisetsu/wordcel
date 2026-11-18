"""Adapt Meikipop's mida + VOCR6 pipeline to Wordcel's lookup geometry."""
# SPDX-License-Identifier: GPL-3.0-or-later
# Based on rtr46/meikipop commit d1bbfd2d.
from concurrent.futures import ThreadPoolExecutor
import os
import re

from wordcel.ocr.interface import BoundingBox, Paragraph, Word
from wordcel.ocr.providers.postprocessing import group_lines_into_paragraphs
from . import models


JAPANESE = re.compile(r"[぀-ゟ゠-ヿ一-龯]")
THREADS = min(4, os.cpu_count() or 1)


class MidaVocr6:
    def __init__(self):
        if not models.ready():
            raise RuntimeError("Download the mida + VOCR6 models in Settings before scanning.")
        if models.needs_engine():
            from wordcel.optional_runtimes import require
            require(models.PROVIDER)

        import onnxruntime as ort
        from .mida_detector import MidaDetector
        from .vocr_onnx import Recognizer

        detector, recognizer = (models.root() / model[0] for model in models.MODELS)
        self.detector = MidaDetector(detector, threads=THREADS)
        options = ort.SessionOptions()
        options.intra_op_num_threads = options.inter_op_num_threads = 1
        options.log_severity_level = 3
        options.add_session_config_entry("session.intra_op.allow_spinning", "0")
        self.recognizer = Recognizer(recognizer, options)
        self.pool = ThreadPoolExecutor(max_workers=THREADS, thread_name_prefix="vocr6-line")

    def scan(self, image):
        import numpy as np

        if not image.width or not image.height:
            return []
        rgb = np.asarray(image.convert("RGB"))
        lines = self.pool.map(lambda crop: self.read_line(rgb, crop), self.detector.detect(rgb))
        return group_lines_into_paragraphs([line for line in lines if line is not None])

    def read_line(self, rgb, crop):
        from .vocr_onnx import grey_of, line_dark

        x, y, width, height = crop
        grey = grey_of(rgb[y:y + height, x:x + width])
        characters = self.recognizer.read(grey, invert=line_dark(grey))
        text = "".join(character.text for character in characters)
        if not JAPANESE.search(text):
            return None

        image_height, image_width = rgb.shape[:2]

        def box(left, right):
            return BoundingBox((left + right) / (2 * image_width), (y + height / 2) / image_height,
                               (right - left) / image_width, height / image_height)

        words = [Word(character.text, "", box(x + character.x0, x + min(width, max(character.x1, character.x0 + 1))))
                 for character in characters]
        return Paragraph(text, words, box(x, x + width), False)
