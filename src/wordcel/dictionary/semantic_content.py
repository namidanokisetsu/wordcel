"""Map exporter annotations to the shared presentation roles without changing source records."""
import re


_NAMED_ROLES = {
    "語義": "sense", "語義G": "sense",
    "語義番号": "sense-number", "語義Gnum": "sense-number",
    "用例": "examples", "用例G": "examples",
    "見出部": "preamble",
}


def annotate_jmdict_form(text):
    """Explain yomitan-import's legacy forms notation without replacing its text."""
    labels = {"★": "Common form", "🅁": "Rare form", "⚠": "Irregular form", "⛬": "Outdated form"}
    text = text.strip()
    match = re.fullmatch(r"(.+?)（([★🅁⚠⛬](?: \| [★🅁⚠⛬])*)）", text)
    spelling = match[1] if match else text

    def annotation(value, description):
        return {"tag": "span", "data": {"content": "form-notation", "description": description},
                "content": value}

    parts = [annotation(spelling, "Ateji") if re.fullmatch(r"〈[^〈〉]+〉", spelling) else spelling]
    if match:
        parts.append("（")
        for index, symbol in enumerate(match[2].split(" | ")):
            if index:
                parts.append(" | ")
            parts.append(annotation(symbol, labels[symbol]))
        parts.append("）")
    return parts


def normalize_content(node):
    if isinstance(node, list):
        return [normalize_content(child) for child in node]
    if not isinstance(node, dict):
        return node
    result = dict(node)
    if "content" in node:
        result["content"] = normalize_content(node["content"])
    data = node.get("data")
    if isinstance(data, dict) and "content" not in data:
        role = _NAMED_ROLES.get(data.get("name"))
        if role:
            result["data"] = dict(data, content=role)
    return result
