"""Clipboard formatting without changing lookup text or source offsets."""
import re

from wordcel.ocr.providers.postprocessing import _are_lines_adjacent


def passage_text(paragraphs, language, provider=None):
    blocks = [p for p in paragraphs if p.full_text.strip()]
    vertical = bool(blocks) and all(p.is_vertical for p in blocks)
    blocks.sort(key=(lambda p: (-p.box.center_x, p.box.center_y)) if vertical else
                (lambda p: (p.box.center_y - p.box.height / 2, p.box.center_x)))
    groups = []
    for block in blocks:
        # Native providers return lines; other adapters already return paragraphs.
        if (provider in ("windows", "vision") and groups and
                groups[-1][-1].is_vertical == block.is_vertical and
                _are_lines_adjacent(groups[-1][-1], block)):
            groups[-1].append(block)
        else:
            groups.append([block])

    def unwrap(text):
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        result = ""
        for line in lines:
            separator = " "
            if language in ("ja", "zh") and result and not (result[-1].isascii() and line[0].isascii()):
                separator = ""
            result += (separator if result else "") + line
        return result

    return "\n\n".join(unwrap(part) for group in groups
                        for part in re.split(r"\n\s*\n", "\n".join(p.full_text for p in group)) if part.strip())
