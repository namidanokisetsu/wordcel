"""HTML rendering helpers for dictionary results."""
from collections import OrderedDict
from html import escape
from itertools import product
from urllib.parse import quote
import re
import unicodedata

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFontMetricsF, QTextLayout, QTextOption

from wordcel.config.config import config
from wordcel.gui.action_icons import disclosure_html
from wordcel.gui.gloss_content import _GlossConverter, normalize_definitions
from wordcel.gui.popup_style import surface_colors
from wordcel.gui.ruby import ruby_html


def _metadata(entries, combine_frequencies=True, show_frequencies=True, pitch="", inline=False, show_inflections=True,
              inflection_key="", details_expanded=()):
    size = max(10, min(config.font_size_definitions - 1, config.font_size_header - 4))
    font_style = f"font-size:{size}px;" if inline else ""
    frequencies, inflections = OrderedDict(), OrderedDict()
    raw_frequencies, chains = [], []
    for entry in entries:
        raw_frequencies.extend(entry.frequencies if show_frequencies else ())
        for frequency in entry.frequencies if show_frequencies else ():
            label = frequency.label or (f"{frequency.rank:g}" if frequency.rank is not None else "")
            if (frequency.rank is not None and frequency.mode == "rank-based"
                    and re.fullmatch(r"[\d,.]+", label)):
                label = f"#{label}"
            frequencies.setdefault((frequency.source, label), None)
        chain = []
        for step in entry.inflection:
            label = (re.sub(r"\([^)]*\)", lambda match: match[0] if " OR " in match[0] else "",
                            str(step)) if entry.language == "ja" else str(step)).strip()
            if label and not label.startswith("stem-"):
                inflections.setdefault(label, entry.language)
                chain.append(label)
        if chain:
            chains.append(chain)
    parts = [pitch] if pitch else []
    body = ""
    if frequencies:
        muted = surface_colors(config.color_background, config.color_foreground)["muted"]
        if combine_frequencies:
            from wordcel.dictionary.metadata import harmonic_rank
            rank = harmonic_rank(raw_frequencies)
            if rank is not None:
                detail = "; ".join(source + ": " + label for source, label in frequencies)
                parts.append(f'<a href="frequency:{quote(detail)}" style="{font_style}color:{muted}">#{max(1, round(rank)):,}</a>')
        else:
            by_source = OrderedDict()
            for source, label in frequencies:
                by_source.setdefault(source, []).append(label)
            multiple_sources = len(by_source) > 1
            if inline and multiple_sources:
                parts.append("<br>")
            parts.extend(f'<a href="frequency:{quote(source + ": " + ", ".join(labels))}" '
                         f'style="{font_style}color:{muted}">'
                         f'{escape(_source_name(source)) + " " if multiple_sources else ""}'
                         f'{escape("/".join(labels))}</a>'
                         for source, labels in by_source.items())
    if inflections and not inline and show_inflections:
        description = " · ".join(inflections)
        label = description
        variants = list(dict.fromkeys(" · ".join(path) for chain in chains
                                     for path in product(*(_inflection_options(step) for step in chain))))
        if inflection_key and len(variants) > 1:
            common = set.intersection(*(set(re.findall(r"[\w-]+", variant)) for variant in variants))
            features = [word for word in ("past", "non-past", "present", "future", "singular", "dual", "plural",
                                         "definite", "indefinite", "locative", "accusative", "dative",
                                         "genitive", "ablative", "instrumental") if word in common]
            summary = " · ".join((*features, f"{len(variants)} forms"))
            opened = inflection_key in details_expanded
            muted = surface_colors(config.color_background, config.color_foreground)["muted"]
            parts.append(f'<a href="{inflection_key}" title="{"Collapse" if opened else "Expand"}" '
                         f'style="color:{muted}">'
                         f'{disclosure_html(opened, muted, round(config.font_size_definitions * .6))} '
                         f'{escape(summary)}</a>')
            if opened:
                body = (f'<div style="font-size:{size}px;color:{muted}"><ol>'
                        + "".join(f'<li>{escape(variant)}</li>' for variant in variants) + '</ol></div>')
        else:
            parts.append(escape(label))
    if inline:
        muted = surface_colors(config.color_background, config.color_foreground)["muted"]
        return (f'<span style="font-size:{size}px;font-weight:normal;color:{muted}">'
                + " ".join(parts) + '</span>') if parts else ""
    return '<p class="metadata"><small>' + " · ".join(parts) + '</small></p>' + body if parts else ""


def _inflection_options(step):
    if " OR " in step and step.startswith("(") and step.endswith(")"):
        depth = 0
        for index, char in enumerate(step):
            depth += (char == "(") - (char == ")")
            if depth == 0:
                if index == len(step) - 1:
                    step = step[1:-1]
                break
    return tuple(dict.fromkeys(option.strip() for option in step.split(" OR ") if option.strip()))


def _source_name(source):
    return re.sub(r"\s*\[\d{4}[^\]]*\]", "", source).replace("Jitendex.org", "Jitendex").strip()


def _compact_context(text, font, width):
    text = " ".join(text.split())
    layout = QTextLayout(text, font)
    option = QTextOption()
    option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    layout.setTextOption(option)
    layout.beginLayout()
    line = layout.createLine()
    if line.isValid():
        line.setLineWidth(max(1, width))
    length = line.textLength() if line.isValid() else 0
    layout.endLayout()
    # Qt text offsets count UTF-16 units, including emoji and astral kanji.
    encoded = text.encode("utf-16-le")
    first = encoded[:length * 2].decode("utf-16-le").rstrip()
    rest = encoded[length * 2:].decode("utf-16-le").lstrip()
    if not rest:
        return first
    return first + "\n" + QFontMetricsF(font).elidedText(rest, Qt.TextElideMode.ElideRight, max(1, width))


def _dictionary_section_key(term, reading, source):
    return "section:" + repr((term, reading, source))


def render_result(result, expanded=(), preview=False, overlay_actions=False, show_source=True,
                  headword_furigana=False, combine_frequencies=True, source_text=None, details_expanded=(),
                  definition_furigana=False, collapsed=(), kanji_details=(),
                  preview_frequency=True, preview_pitch=True, preview_definitions=1,
                  pinned_frequency=True, pinned_pitch=True, grammar=None, separate_headwords=False,
                  headword_actions=0, hidden_sections=None, dictionary_labels=True, compact=None):
    """Share lexical headings while preserving the configured dictionary order."""
    preview_definitions = max(0, min(50, preview_definitions))
    compact = preview if compact is None else preview and compact
    maximum = preview_definitions if preview else 0
    grammar_tags = not preview if grammar is None else grammar
    show_inflections = grammar is not False
    reading_size = config.font_size_reading
    muted = surface_colors(config.color_background, config.color_foreground)["muted"]
    clearance = 96 if overlay_actions is True else int(overlay_actions)
    if source_text is None:
        source_text = result.text if result.translation else ""
    heading_clearance = max(headword_actions, 0 if show_source and source_text else clearance)
    groups, sources = OrderedDict(), list(dict.fromkeys(entry.source for entry in result.entries))
    for entry in result.entries:
        if compact and (entry.source != sources[0] or groups and (entry.term, entry.reading) not in groups):
            continue
        groups.setdefault((entry.term, entry.reading), OrderedDict()).setdefault(entry.source, []).append(entry)
    parts = [f'<style>body {{color:{config.color_foreground};}} '
             f'a,h2 {{color:{config.color_highlight_word};text-decoration:none;}} '
             f'h2 {{font-size:{config.font_size_header}px;font-weight:normal;margin:0 {heading_clearance}px 0 0;}} '
             'p {margin:2px 0;} ol,ul {margin:2px 0 4px 8px;padding:0;} '
             'li {margin:1px 0;} hr {margin:6px 0;} '
             f'.metadata {{margin:0;color:{muted};}} .source {{margin:4px 0 1px;color:{muted};}}</style>']
    if show_source and source_text:
        parts.append(f'<p style="margin:0 {clearance}px 4px 0;font-size:{config.font_size_sentence}px">'
                     f'<a href="sentence:translate" title="Translate sentence" style="color:{muted}">'
                     f'{escape(source_text).replace(chr(10), "<br>")}</a></p>')
        if result.translation:
            parts.append("<hr>")
    if result.translation:
        parts.append(f'<p><a name="scroll-section-translation"></a>'
                     f'{escape(result.translation).replace(chr(10), "<br>")}</p>')
        if result.entries:
            parts.append("<hr>")
    anchored = set()
    for group_index, ((term, reading), dictionaries) in enumerate(groups.items()):
        if group_index and separate_headwords:
            parts.append("<hr>")
        first_source = next(source for source in sources if source in dictionaries)
        section = f'<a name="scroll-section-{group_index}-{sources.index(first_source)}"></a>'
        parts.append(section)
        display_term = term
        if (result.source == "ru" and reading and unicodedata.normalize("NFC", reading.replace("\u0301", ""))
                == unicodedata.normalize("NFC", term)):
            display_term, reading = reading, ""
        display_reading = f"[{reading}]" if result.source == "ja" else reading
        kanji = {entry.character for entry in result.kanji}
        display_term_html = "".join(
            f'<a href="headkanji:{group_index}:{quote(character, safe="")}" title="Kanji" '
            f'style="color:{config.color_highlight_word}">{escape(character)}</a>'
            if character in kanji and not compact else escape(character) for character in display_term)
        group_entries = tuple(entry for entries in dictionaries.values() for entry in entries)
        pitches = (tuple(pitch for entry in group_entries for pitch in entry.pitches)
                   if result.source == "ja" and (preview_pitch if preview else pinned_pitch) else ())
        pitch = ""
        if pitches:
            from wordcel.dictionary.pitch import render_pitches
            pitch = render_pitches(pitches, inline=True, separator=" ",
                                   font_size=reading_size)
        metadata = _metadata(group_entries, combine_frequencies, show_frequencies=preview_frequency if preview else pinned_frequency,
                             pitch=pitch, inline=True)
        metadata = " " + metadata if metadata else ""
        reading_html = (f' <span style="color:{config.color_highlight_reading};font-size:'
                        f'{reading_size}px">{escape(display_reading)}</span>'
                        if reading and reading != term and not any(pitch.reading == reading for pitch in pitches) else "")
        if result.source == "ja" and headword_furigana and reading and reading != term:
            parts.append(f'<h2><a name="scroll-headword-{group_index}"></a>'
                         f'{ruby_html(escape(term), escape(reading), config.color_highlight_word, kanji=kanji if not compact else (), kanji_group=group_index)}{metadata}</h2>')
        else:
            parts.append(f'<h2><a name="scroll-headword-{group_index}"></a>{display_term_html}{reading_html}{metadata}</h2>')
        parts.append(_metadata(group_entries, show_frequencies=False, show_inflections=show_inflections,
                               inflection_key=f"inflections:{group_index}", details_expanded=details_expanded))
        for source in sources:
            if source not in dictionaries:
                continue
            index, entries = sources.index(source), dictionaries[source]
            section_key = _dictionary_section_key(term, reading, source)
            full = not maximum or (source in expanded or section_key in expanded) and not preview
            more = bool(maximum and len(entries) > maximum)
            hidden = dictionary_labels and (source in collapsed or section_key in collapsed) and not compact
            generic_source = source in ("Turkish Bilingual", "Turkish Monolingual", "Turkish Etymology")
            normalized = [normalize_definitions(entry.definitions, source) for entry in entries]
            limit = 240 if result.source == "ja" and compact and not full else None
            from wordcel.dictionary.wiktionary_sections import is_wiktionary
            hidden_details = (hidden_sections or {}).get(source, ()) if is_wiktionary(source) else ()
            converter = _GlossConverter(expanded=full, limit=limit, hidden_sections=hidden_details,
                                        preview=preview, compact=compact, preview_definitions=preview_definitions,
                                        generic_source=generic_source, term=term,
                                        details_expanded=details_expanded, detail_prefix=f"{group_index}:{index}",
                                        definition_furigana=definition_furigana,
                                        grammar=grammar_tags,
                                        definitions=tuple(definition for definitions in normalized for definition in definitions))
            definitions = []
            visible_entries = () if hidden else (normalized if full else normalized[:maximum])
            for entry_definitions in visible_entries:
                more = more or bool(maximum and len(entry_definitions) > maximum)
                definitions.extend(converter.glosses(entry_definitions if full else entry_definitions[:maximum]))
            if not full:
                more = more or len(definitions) > maximum
                definitions = definitions[:maximum]
            more = more or converter.clipped
            if source not in anchored:
                parts.append(f'<a name="dictionary-{index}"></a>')
                anchored.add(source)
            if not compact:
                section = (f'<a name="scroll-section-{group_index}-{index}"></a>'
                           if source != first_source else "")
                if dictionary_labels:
                    label = converter.first_source or _source_name(source)
                    parts.append(f'<p class="source">{section}<a href="collapse:{group_index}:{index}" '
                                 f'title="{"Expand" if hidden else "Collapse"}" style="color:{muted}">'
                                 f'<small>{disclosure_html(not hidden, muted, round(config.font_size_definitions * .6))} '
                                 f'{escape(label)}</small></a></p>')
                else:
                    parts.append(section)
            if len(definitions) > 1:
                opening = '<ol style="margin-left:20px">' if len(definitions) > 9 else "<ol>"
                parts.append(opening + "".join(f"<li>{gloss}</li>" for gloss in definitions) + "</ol>")
            else:
                parts.append("".join(f"<div>{gloss}</div>" for gloss in definitions))
            for label, supplement in converter.supplements:
                if label:
                    parts.append(f'<p class="source"><small>{label}</small></p>')
                parts.append(supplement)
            if more and not full and not hidden and not preview:
                parts.append(f'<p class="metadata"><a href="expand:{group_index}:{index}" style="text-decoration:underline">More</a></p>')
    if result.analyses and not result.entries:
        from wordcel.language.turkish_analyzer import grammar_labels
        lemmas = OrderedDict()
        for reading in result.analyses:
            lemmas.setdefault(reading.lemma, []).append(reading)
        for lemma, readings in lemmas.items():
            parts.append(f'<h2>{escape(lemma)}</h2>')
            if show_inflections:
                parts.append(f'<p class="metadata">{escape(" · ".join(grammar_labels(readings)))}</p>')
    if result.suggestions:
        parts.append('<p>Did you mean: ' + " · ".join(
            f'<a href="suggest:{index}">{escape(str(word))}</a>'
            for index, word in enumerate(result.suggestions)) + "</p>")
    unmatched_text = result.text.strip() if not (result.entries or result.translation or result.kanji or result.analyses) else ""
    if unmatched_text and not (show_source and source_text):
        parts.append(f'<p>{escape(unmatched_text).replace(chr(10), "<br>")}</p>')
    if result.message and not (unmatched_text and result.message == "No entry found."):
        parts.append(f"<p>{escape(result.message)}</p>")
    if result.kanji and not compact:
        from wordcel.gui.kanji_panel import render_kanji
        parts.append('<a name="kanji"></a>'
                     + render_kanji(result.kanji, compact_only=True))
    if not result.entries and not result.translation and not result.kanji and not result.message and result.text:
        if not unmatched_text:
            parts.append("<p>No entry found.</p>")
    return "".join(parts)
