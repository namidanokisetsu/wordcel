"""Per-block bidi policy using the HTML subset understood by QTextDocument."""
from dataclasses import dataclass, field
from html import escape, unescape
from html.parser import HTMLParser
import unicodedata


def direction(text):
    for char in text:
        bidi = unicodedata.bidirectional(char)
        if bidi in {"R", "AL"}:
            return "rtl"
        if bidi == "L":
            return "ltr"
    return "ltr"


@dataclass
class _Node:
    tag: str = ""
    attrs: list = field(default_factory=list)
    children: list = field(default_factory=list)

    def plain(self):
        if self.tag == "style":
            return ""
        return "".join(child.plain() if isinstance(child, _Node) else unescape(child) for child in self.children)

    def html(self):
        body = "".join(child.html() if isinstance(child, _Node) else child for child in self.children)
        if not self.tag:
            return body
        attrs = dict(self.attrs)
        if self.tag in {"p", "div", "h1", "h2", "h3", "h4", "li", "blockquote", "pre", "dt", "dd"}:
            flow = attrs.setdefault("dir", direction(self.plain()))
            attrs.setdefault("align", "right" if flow == "rtl" else "left")
        opening = "<" + self.tag + "".join(
            f' {key}="{escape(value, quote=True)}"' if value is not None else " " + key
            for key, value in attrs.items()) + ">"
        return opening if self.tag in _VOID else opening + body + "</" + self.tag + ">"


_VOID = {"br", "hr", "img", "meta", "link", "input", "wbr"}


class _Blocks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.root = _Node()
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)

    def handle_entityref(self, name):
        self.handle_data("&" + name + ";")

    def handle_charref(self, name):
        self.handle_data("&#" + name + ";")


def directional_html(html):
    parser = _Blocks()
    parser.feed(html)
    parser.close()
    return parser.root.html()
