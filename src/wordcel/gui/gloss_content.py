"""Shared definition normalization and structured rendering."""
from html import escape
import re
from urllib.parse import quote

from PyQt6.QtGui import QTextDocument

from wordcel.config.config import config
from wordcel.dictionary.structured_content import StructuredContentConverter
from wordcel.gui.action_icons import disclosure_html
from wordcel.gui.popup_style import surface_colors
from wordcel.gui.ruby import TAG_PREFIX, ruby_html


class _GlossConverter(StructuredContentConverter):
    """Prune structured previews before conversion, retaining lists and emphasis."""
    _tag_labels = {
        "noun (common) (futsuumeishi)": "noun",
        "noun or participle which takes the aux. verb suru": "suru",
        "transitive verb": "transitive", "intransitive verb": "intransitive",
        "female given name or forename": "female name", "female given name": "female name",
        "male given name or forename": "male name", "male given name": "male name",
        "given name or forename, gender not specified": "given name",
        "family or surname": "surname", "place name": "place",
        "adjective (keiyoushi)": "i-adjective",
        "adjectival nouns or quasi-adjectives (keiyodoshi)": "na-adjective",
        "adverb (fukushi)": "adverb", "expressions (phrases, clauses, etc.)": "expression",
        "other surface forms and readings": "forms", "unclassified": "unclassified",
    }

    @staticmethod
    def _is_tag(node):
        data = node.get("data") if isinstance(node, dict) else None
        return (isinstance(data, dict) and data.get("content") != "forms-label"
                and (data.get("class") == "tag" or data.get("content") == "tag"))

    def _tags_to_html(self, nodes):
        if not self.grammar:
            return ""
        labels, descriptions = [], []
        for node in nodes:
            html = super()._node_to_html(node.get("content"))
            document = QTextDocument()
            document.setHtml(html)
            description = document.toPlainText().strip()
            if description:
                descriptions.append(description)
                if not re.fullmatch(r"JMdict Sense #\d+", description, re.IGNORECASE):
                    labels.append(self._tag_labels.get(description, description))
        if not labels:
            return ""
        description = " · ".join(dict.fromkeys(descriptions))
        label = " · ".join(dict.fromkeys(labels))
        return (f'<div class="metadata"><a href="{TAG_PREFIX}{quote(description, safe="")}" '
                f'style="color:{self.colors["muted"]};text-decoration:none">'
                f'<small>[{escape(label)}]</small></a></div>')

    def __init__(self, expanded=False, limit=360, preview=False, generic_source=False, term="",
                 details_expanded=(), detail_prefix="", definitions=(), definition_furigana=False, preview_definitions=2,
                 grammar=True, hidden_sections=(), compact=None):
        super().__init__()
        self.preview_definitions = preview_definitions
        self.definition_furigana = definition_furigana
        self.grammar = grammar
        self.hidden_sections = hidden_sections
        self.colors = surface_colors(config.color_background, config.color_foreground)
        self.expanded = expanded
        self.preview = preview
        self.compact = preview if compact is None else compact
        self.generic_source = generic_source
        self.term = term
        self.first_source = ""
        self._preview_source_complete = False
        self.remaining = limit
        self.clipped = False
        self.supplements = []
        self.details_expanded = details_expanded
        self._detail_keys = {}
        def index_details(node):
            if isinstance(node, (list, tuple)):
                for child in node:
                    index_details(child)
            elif isinstance(node, dict):
                if node.get("tag") == "details":
                    self._detail_keys[id(node)] = f"{detail_prefix}:{len(self._detail_keys)}"
                index_details(node.get("content"))
        index_details(definitions)

    def _details_to_html(self, node):
        from wordcel.dictionary.wiktionary_sections import section_kind
        if section_kind(node) in self.hidden_sections:
            return ""
        if self.compact:
            self.clipped = True
            return ""
        key = self._detail_keys[id(node)]
        children = node.get("content", [])
        children = children if isinstance(children, list) else [children]
        summary = next((child for child in children if isinstance(child, dict)
                        and child.get("tag") == "summary"), None)
        opened = key in self.details_expanded
        expanded, remaining = self.expanded, self.remaining
        self.expanded, self.remaining = True, None
        try:
            label = (self._node_to_html(summary.get("content")) if summary else "") or "More"
            body = self._node_to_html([child for child in children if child is not summary]) if opened else ""
        finally:
            self.expanded, self.remaining = expanded, remaining
        return (f'<div><a name="details-{key}"></a><a href="details:{key}" '
                f'title="{"Collapse" if opened else "Expand"}"><small>'
                f'{disclosure_html(opened, self.colors["muted"], round(config.font_size_definitions * .6))} '
                f'{label}</small></a></div>{body}')

    def _ruby_to_html(self, content):
        parts, base = [], []
        nodes = content if isinstance(content, list) else [content]
        for child in nodes:
            tag = child.get("tag") if isinstance(child, dict) else None
            if tag == "rp":
                continue
            if tag == "rt":
                reading = self._node_to_html(child.get("content"))
                text = "".join(base)
                parts.append((ruby_html(text, reading) if self.definition_furigana else
                              f'{text} [{reading}]') if text and reading else text)
                base = []
            else:
                base.append(self._node_to_html(child))
        return "".join(parts + base)

    def _node_to_html(self, node):
        if self._preview_source_complete:
            return ""
        if isinstance(node, str):
            node = re.sub(r"\n[ \t]*\n+", "\n", node)
            if not self.expanded and self.remaining is not None:
                text = node[:self.remaining]
                self.remaining -= len(text)
                if len(text) < len(node):
                    self.clipped = True
                    text += "…" if text else ""
                node = text
            return super()._node_to_html(node).replace('\n', '<br>') if node.strip() else node
        if isinstance(node, list):
            parts = []
            index = 0
            while index < len(node):
                child = node[index]
                if not self.expanded and self.remaining is not None and self.remaining <= 0:
                    self.clipped = True
                    break
                tags = []
                while index < len(node) and self._is_tag(node[index]):
                    tags.append(node[index])
                    index += 1
                if tags:
                    parts.append(self._tags_to_html(tags))
                else:
                    parts.append(self._node_to_html(child))
                    index += 1
            return "".join(parts)
        if isinstance(node, dict):
            if self._is_tag(node):
                return self._tags_to_html((node,))
            tag = node.get("tag")
            data = node.get("data")
            if (tag in ("span", "ruby") and not node.get("style") and not node.get("dir")
                    and (not isinstance(data, dict) or not (data.get("class") or data.get("content")))):
                return (self._ruby_to_html(node.get("content")) if tag == "ruby"
                        else self._node_to_html(node.get("content")))
            if node.get("tag") == "details":
                return self._details_to_html(node)
            node = dict(node)
            tag, content = node.get("tag", ""), node.get("content")
            data = node.get("data", {})
            kind = str(data.get("content", "")) if isinstance(data, dict) else ""
            semantic_kind = re.sub(r"[-_]", "", kind).lower()
            if kind == "backlink" or semantic_kind == "formslabel":
                return ""
            if semantic_kind in ("forms", "formstable", "formslist"):
                self.clipped = True
                if self.expanded or not self.compact:
                    supplement = dict(node, data={})
                    self.supplements.append(("Forms", self._node_to_html(supplement)))
                return ""
            if semantic_kind == "attribution":
                return ""
            if not self.expanded and self.compact and semantic_kind in ("explanation", "extrainfo"):
                self.clipped = True
                return ""
            if kind == "section-heading":
                if not self.expanded and self.compact:
                    return ""
                return f'<p style="margin:6px 0 2px;font-weight:bold">{self._node_to_html(content)}</p>'
            style = node.get("style", {})
            style = style if isinstance(style, dict) else {}
            heading_text = content[0] if isinstance(content, list) and len(content) == 1 else content
            # Turkdict repeats the headword for each homonym inside a source.
            # The shared lexical heading already identifies these sense groups.
            if (self.generic_source and tag == "div" and heading_text == self.term
                    and style.get("fontWeight") == "bold" and style.get("marginTop") == "0.3em"):
                return ""
            source_heading = (isinstance(heading_text, str) and heading_text.strip() in
                              ("Tureng", "Wiktionary", "TDK", "KeNet", "Etymology")
                              and (tag in ("b", "strong") or style.get("fontWeight") in ("bold", "700")))
            if source_heading and self.generic_source:
                if not self.first_source:
                    self.first_source = heading_text.strip()
                    return ""
                if self.compact:
                    self._preview_source_complete = True
                    self.clipped = True
                    return ""
                return f'<p class="source"><small>{escape(heading_text.strip())}</small></p>'
            # Turkdict's exporter retains this presentation signature for
            # examples, translations and sense context, but no CSS class name.
            turkdict_example = (tag == "div" and style.get("fontSize") == "0.9em"
                                and style.get("marginTop") == "0.1em")
            if not self.expanded:
                if self.compact and kind in ("forms", "attribution", "extra-info"):
                    self.clipped = True
                    return ""
                if self.compact and ("example" in kind.lower() or turkdict_example):
                    self.clipped = True
                    return ""
                # Turkdict exports numbered senses as divs rather than list items.
                numbered_senses = (self.preview and isinstance(content, list) and bool(content) and all(
                    isinstance(child, dict) and child.get("tag") == "div"
                    and isinstance(child.get("content"), list) and child["content"]
                    and isinstance(child["content"][0], str)
                    and re.match(r"\d+\.\s", child["content"][0]) for child in content))
                marked_senses = (isinstance(content, list) and bool(content) and all(
                    isinstance(child, dict) and isinstance(child.get("data"), dict)
                    and "meaning" in child["data"] for child in content))
                if ((tag in ("ol", "ul") and kind != "glossary") or kind == "glosses" or numbered_senses or marked_senses) and isinstance(content, list):
                    senses = [child for child in content if (not isinstance(child, str) or child.strip())
                              and not (isinstance(child, dict) and isinstance(child.get("data"), dict)
                                       and child["data"].get("content") == "section-heading")]
                    maximum = self.preview_definitions if self.preview else 0
                    if maximum and len(senses) > maximum:
                        node["content"] = senses[:maximum]
                        self.clipped = True
            if kind == "glossary":
                children = node.get("content")
                children = children if isinstance(children, list) else [children]
                return "; ".join(filter(None, (self._node_to_html(
                    child.get("content") if isinstance(child, dict) and child.get("tag") == "li" else child)
                    for child in children)))
            source_class = data.get("class", "") if isinstance(data, dict) else ""
            if source_class == "tag" or kind == "tag":
                return self._tags_to_html((node,))
            if kind == "tags":
                return self._node_to_html(content)
            if tag in ("td", "th"):
                labels = {"form-pri": "common", "form-valid": "valid", "form-rare": "rare",
                          "form-out": "obsolete", "form-irr": "irregular"}
                if source_class in labels:
                    node["content"] = labels[source_class]
            if kind in ("sense-groups", "sense-group"):
                tag = node["tag"] = "div"
            if kind == "sense-group" and isinstance(content, list):
                # Keep leading POS tags beside the first sense, not on an empty-height line.
                children = list(content)
                for index, child in enumerate(children):
                    if not isinstance(child, dict):
                        break
                    child_data = child.get("data", {})
                    if not isinstance(child_data, dict):
                        break
                    if child_data.get("content") == "sense" and index:
                        children[index] = dict(child, tag="span")
                        break
                    if child_data.get("class") != "tag" and child_data.get("content") != "tag":
                        break
                node["content"] = children
            # Keep a small, safe subset of typography. Dictionary CSS must not
            # inject attributes, override the theme or stretch the popup.
            safe_style = {}
            if tag == "ol" and isinstance(content, list) and len(content) > 9:
                safe_style["marginLeft"] = "20px"
            for name, values in (("fontStyle", ("italic", "normal")),
                                 ("fontWeight", ("bold", "normal", "400", "700"))):
                if style.get(name) in values:
                    safe_style[name] = style[name]
            if kind in ("bold-text", "example-keyword"):
                safe_style["fontWeight"] = "bold"
            if tag in ("td", "th"):
                safe_style.update(borderStyle="solid", borderWidth="1px", borderColor=self.colors["border"],
                                  padding="4px", color=config.color_foreground)
                if tag == "th":
                    safe_style["backgroundColor"] = self.colors["hover"]
            size = style.get("fontSize", "")
            if isinstance(size, str) and re.fullmatch(r"0?\.[7-9]em", size):
                safe_style["fontSize"] = size
            if tag in ("div", "p", "details", "summary"):
                node["tag"] = "div"
                safe_style.update(marginTop="1px", marginBottom="1px")
            node["style"] = safe_style
            # No source-controlled attributes reach the converter.
            node["data"] = {}
            return super()._node_to_html(node)
        return super()._node_to_html(node)

    def glosses(self, definitions):
        parts = []
        for definition in definitions:
            if isinstance(definition, str):
                content = definition.strip()
            elif isinstance(definition, dict) and definition.get("type") == "image":
                content = dict(definition, tag="img")
            elif isinstance(definition, dict) and definition.get("type") in ("text", "structured-content"):
                content = definition.get("text" if definition["type"] == "text" else "content")
            else:
                continue
            rendered = self._node_to_html(content)
            if rendered and (re.sub(r"<[^>]*>", "", rendered).strip() or '<img ' in rendered):
                parts.append(rendered)
        return parts


def _section(label, content):
    kind = {"Meaning": "glosses", "意味": "glosses", "Explanation": "explanation",
            "解説": "explanation", "Example sentences": "examples"}.get(label, "extra-info")
    return {"tag": "div", "data": {"content": kind}, "content": [
        {"tag": "div", "data": {"content": "section-heading"}, "content": label},
        {"tag": "div", "content": content}]}


def normalize_definitions(definitions, source):
    result = []
    for definition in definitions:
        if isinstance(definition, str):
            senses = _numbered_text_senses(definition)
            if senses:
                result.extend(senses)
                continue
        if source == "Bunpro Dictionary" and isinstance(definition, dict):
            content = definition.get("content")
            if definition.get("type") == "structured-content" and isinstance(content, list):
                if content and all(isinstance(child, dict) and child.get("tag") == "a" for child in content):
                    result.append({"type": "structured-content", "content": {
                        "tag": "div", "data": {"content": "attribution"}, "content": content}})
                    continue
                sections, label, children = [], None, []
                for child in content:
                    heading = re.fullmatch(r"【\s*(.*?)\s*】", child) if isinstance(child, str) else None
                    if heading:
                        if label is not None:
                            sections.append(_section(label, children))
                        elif children:
                            sections.extend(children)
                        label, children = heading[1], []
                    else:
                        children.append(child)
                if label is not None:
                    sections.append(_section(label, children))
                    definition = {"type": "structured-content", "content": sections}
        elif source.startswith("日本語文法辞典") and isinstance(definition, str):
            chunks = re.split(r"(?m)^\s*\[([^\]\n]+)\][ \t]*\n?", definition)
            if len(chunks) > 1:
                sections = [{"tag": "div", "data": {"content": "extra-info"}, "content": chunks[0].strip()}]
                sections.extend(_section(chunks[i], chunks[i + 1].strip())
                                for i in range(1, len(chunks) - 1, 2))
                definition = {"type": "structured-content", "content": sections}
        result.append(definition)
    return tuple(result)


def _numbered_text_senses(text):
    # Some exports, including Wordset, pack numbered POS-marked senses into one string.
    headings = list(re.finditer(r"(?m)^[ \t]*(\d+)\. pos: ([^\r\n]+)\r?\n", text))
    if (not headings or text[:headings[0].start()].strip()
            or [int(match[1]) for match in headings] != list(range(1, len(headings) + 1))):
        return ()
    senses = []
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        lines = [line.strip() for line in text[heading.end():end].splitlines() if line.strip()]
        if not lines or lines[0].startswith(("ex:", "syn:")):
            return ()
        content = [{"tag": "span", "data": {"class": "tag"}, "content": heading[2].strip()}]
        for line in lines:
            if line.startswith("ex:"):
                content.append({"tag": "div", "data": {"content": "examples"},
                                "style": {"fontStyle": "italic"}, "content": line[3:].strip()})
            elif line.startswith("syn:"):
                content.append({"tag": "div", "data": {"content": "extra-info"},
                                "content": "Synonyms: " + line[4:].strip()})
            else:
                content.append({"tag": "div", "content": line})
        senses.append({"type": "structured-content", "content": content})
    return tuple(senses)
