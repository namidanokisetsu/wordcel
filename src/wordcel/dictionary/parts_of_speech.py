"""Explicit lexical labels, kept at the scope supplied by the dictionary."""
import re


_LABELS = {
    "n": "noun", "adj": "adjective", "v": "verb", "adv": "adverb",
    "pron": "pronoun", "prep": "preposition", "conj": "conjunction",
    "intj": "interjection", "num": "numeral", "propn": "proper noun",
    "noun (common) (futsuumeishi)": "noun",
    "noun or participle which takes the aux. verb suru": "suru",
    "adjective (keiyoushi)": "i-adjective",
    "adjectival nouns or quasi-adjectives (keiyodoshi)": "na-adjective",
    "adverb (fukushi)": "adverb",
    "expressions (phrases, clauses, etc.)": "expression",
    "noun (temporal) (jisoumeishi)": "noun",
    "noun (adverbial) (fukushitekimeishi)": "noun",
    "nouns which may take the genitive case particle 'no'": "noun",
    "adjectival nouns or quasi-adjectives (keiyōdōshi)": "na-adjective",
}
_PARTS = {"noun", "proper noun", "verb", "adjective", "adverb", "pronoun", "determiner",
          "article", "preposition", "postposition", "conjunction", "interjection", "numeral",
          "particle", "prefix", "suffix", "affix", "phrase", "expression", "name",
          "i-adjective", "na-adjective", "auxiliary verb", "copula", "counter", "suru"}


def tag_text(node):
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(tag_text(child) for child in node)
    return tag_text(node.get("content")) if isinstance(node, dict) else ""


def is_tag(node):
    data = node.get("data") if isinstance(node, dict) else None
    return (isinstance(data, dict) and data.get("content") != "forms-label"
            and (data.get("class") == "tag" or data.get("content") in ("tag", "part-of-speech-info")))


def leading_tags(definition):
    if not isinstance(definition, dict) or definition.get("type") != "structured-content":
        return []
    content = definition.get("content")
    content = content if isinstance(content, list) else [content]
    nodes = []
    for child in content:
        if isinstance(child, str) and not child.strip():
            continue
        if not is_tag(child):
            break
        nodes.append(child)
    return nodes


def part_of_speech(node):
    if not is_tag(node):
        return ""
    data = node["data"]
    kind = data.get("content", "")
    text = tag_text(node.get("content")).strip()
    category = re.sub(r"[-_]", "", str(data.get("category", ""))).casefold()
    if category and category not in ("pos", "partofspeech", "grammar"):
        return ""
    label = _LABELS.get(text.casefold(), text.casefold())
    if label in _PARTS:
        return label
    if label in ("transitive verb", "intransitive verb"):
        return "verb"
    if category in ("pos", "partofspeech") or kind == "part-of-speech-info":
        return text
    # JMdict verb classes are explicit POS descriptions, not prose definitions.
    if re.match(r"^(?:godan|ichidan|nidan|yodan|suru|kuru) verb\b", label):
        return "verb"
    return ""


def with_entry_part_of_speech(definitions, rules, source):
    """Recover legacy WTY entry labels without interpreting other exporters' rules."""
    if not re.fullmatch(r"wty-[a-z-]+", source, re.IGNORECASE):
        return definitions
    labels = list(dict.fromkeys(_LABELS[rule] for rule in rules if rule in ("n", "adj", "v", "adv")))
    if not labels:
        return definitions
    # Only inspect entry-level tags. A nested sense label cannot label the entry.
    if any(part_of_speech(node) for definition in definitions for node in leading_tags(definition)):
        return definitions
    nodes = [{"tag": "span", "data": {"content": "tag", "category": "partOfSpeech"},
              "content": label} for label in labels]
    for index, definition in enumerate(definitions):
        if isinstance(definition, dict) and definition.get("type") == "structured-content":
            children = definition.get("content")
            children = children if isinstance(children, list) else [children]
            return (*definitions[:index], dict(definition, content=[*nodes, *children]), *definitions[index + 1:])
    return definitions


def split_entry_part_of_speech(definitions):
    def leading(definition):
        return [node for node in leading_tags(definition) if part_of_speech(node)]

    if not definitions or any(leading(definition) for definition in definitions[1:]):
        return (), definitions
    nodes = leading(definitions[0])
    if not nodes:
        return (), definitions
    first = definitions[0]
    content = first.get("content")
    content = content if isinstance(content, list) else [content]
    identities = {id(node) for node in nodes}
    return nodes, (dict(first, content=[node for node in content if id(node) not in identities]), *definitions[1:])
