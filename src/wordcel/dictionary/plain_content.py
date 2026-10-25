"""Yomitan plain text definition conversion."""
import re


def extract_text(node) -> str:
    """
    Recursively extract plain text from a structured-content node.
    Loses all formatting but preserves meaning for popup display.
    Inserts a space between block-level tags (div, li, tr) for readability.
    """
    if node is None:
        return ''
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return ''.join(extract_text(child) for child in node)
    if isinstance(node, dict):
        tag  = node.get('tag', '')
        content = node.get('content')
        # For ruby tags: show rb text only (skip rt pronunciation guides)
        if tag == 'ruby':
            if isinstance(content, list):
                for child in content:
                    if isinstance(child, dict) and child.get('tag') != 'rt':
                        return extract_text(child)
            return extract_text(content)
        if tag == 'rt':
            return ''
        inner = extract_text(content)
        # Add spacing around block elements
        if tag in ('div', 'li', 'tr', 'br'):
            return inner + ' '
        return inner
    return ''


def extract_glosses(definitions: list) -> list[str]:
    """
    Convert a yomitan definitions array into a flat list of gloss strings.
    Handles plain strings, {type:text}, {type:structured-content}, and
    ignores image-only and deinflection entries.
    """
    glosses = []
    for defn in definitions:
        if isinstance(defn, str):
            text = defn.strip()
            if text:
                glosses.append(text)
        elif isinstance(defn, dict):
            t = defn.get('type')
            if t == 'text':
                text = defn.get('text', '').strip()
                if text:
                    glosses.append(text)
            elif t == 'structured-content':
                text = extract_text(defn.get('content')).strip()
                # Collapse runs of whitespace
                text = re.sub(r'\s+', ' ', text)
                if text:
                    glosses.append(text)
            # type == 'image' or deinflection arrays: skip
        elif isinstance(defn, list):
            # Deinflection entry [uninflected_term, [rules]] — skip
            pass
    return glosses


# ── Frequency parsing ──────────────────────────────────────────────────────────
