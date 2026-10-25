"""Yomitan structured HTML definition conversion."""
import re


_CHAR_MAP = {
    'fontWeight': 'font-weight',
    'fontStyle': 'font-style',
    'fontSize': 'font-size',
    'color': 'color',
    'backgroundColor': 'background-color',
    'textDecorationLine': 'text-decoration',
    'fontFamily': 'font-family',
    'textTransform': 'text-transform',
    'fontVariant': 'font-variant',
    'whiteSpace': 'white-space',
    'lineHeight': 'line-height',
    'wordSpacing': 'word-spacing',
}

# vertical-align: Qt only supports these values; others (text-bottom, text-top)
# are silently ignored, so we filter to the supported set.
_VERTICAL_ALIGN_SUPPORTED = {
    'baseline', 'sub', 'super', 'middle', 'top', 'bottom'
}

# Block-level: only meaningful on block elements (div, p, li, etc.)
# Qt ignores these when set on a span.
_BLOCK_MAP = {
    'marginTop': 'margin-top',
    'marginBottom': 'margin-bottom',
    'marginLeft': 'margin-left',
    'marginRight': 'margin-right',
    'padding': 'padding',
    'paddingTop': 'padding-top',
    'paddingBottom': 'padding-bottom',
    'paddingLeft': 'padding-left',
    'paddingRight': 'padding-right',
    'textAlign': 'text-align',
    'textIndent': 'text-indent',
}

# Border properties: Qt only supports these on table / td / th.
# On any other element we fall back to [bracket] notation.
_BORDER_KEYS = {'borderStyle', 'borderWidth', 'borderColor'}

# Tags that carry block formatting
_BLOCK_TAGS = {
    'div', 'ol', 'ul', 'li', 'details', 'summary',
    'table', 'thead', 'tbody', 'tfoot', 'tr',
}
# Tags that carry inline/character formatting
_INLINE_TAGS = {'span', 'b', 'strong', 'i', 'em', 'u', 's', 'sub', 'sup', 'small'}
# Table cell tags — can have Qt borders
_CELL_TAGS = {'td', 'th'}
# All tags we render (unknown tags get their wrapper dropped)
_RENDERED_TAGS = _BLOCK_TAGS | _INLINE_TAGS | _CELL_TAGS


def _esc(text: str) -> str:
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


# ── CSS builder ────────────────────────────────────────────────────────────────

def _style_to_props(style_obj: dict) -> tuple[dict, dict, bool]:
    """
    Split a yomitan style object into:
      char_props  — character-level CSS {prop: value}
      block_props — block-level CSS {prop: value}
      has_border  — True if any border sub-property is present
    """
    char_props: dict = {}
    block_props: dict = {}
    has_border = False

    for k, v in style_obj.items():
        if not isinstance(v, str):
            continue
        if k in _CHAR_MAP:
            css_prop = _CHAR_MAP[k]
            if css_prop == 'vertical-align':
                if v in _VERTICAL_ALIGN_SUPPORTED:
                    char_props[css_prop] = v
            else:
                char_props[css_prop] = v
        elif k in _BLOCK_MAP:
            block_props[_BLOCK_MAP[k]] = v
        elif k in _BORDER_KEYS:
            has_border = True
        # anything else (border-radius, cursor, display, flex, …) → silently dropped

    return char_props, block_props, has_border


def _synthesize_border(style_obj: dict) -> str:
    """
    Build a `border: width style color` shorthand from individual sub-properties.
    Returns an empty string if none are present.
    """
    width = style_obj.get('borderWidth', '1px')
    style = style_obj.get('borderStyle', 'solid')
    color = style_obj.get('borderColor', '')
    if style_obj.get('borderStyle') or style_obj.get('borderWidth'):
        return f'border:{width} {style} {color}'.rstrip()
    return ''


def _props_to_css(props: dict) -> str:
    return ';'.join(f'{k}:{v}' for k, v in props.items())


# ── Structured-content → Qt HTML converter ────────────────────────────────────

class StructuredContentConverter:
    """
    Converts a yomitan structured-content tree to Qt-compatible HTML.

    Design principles:
      - Only emit CSS Qt can actually render (see maps above)
      - Collapse no-op wrappers aggressively to keep HTML small
      - Border on non-table elements → [bracket] fallback
      - Ruby: configurable via use_ruby flag
    """

    def __init__(self, use_ruby: bool = True):
        self.use_ruby = use_ruby

    # ── Ruby ──────────────────────────────────────────────────────────────

    def _ruby_to_html(self, content) -> str:
        """
        Option 4: collect base text and all rt text, produce base（rt）.
        When use_ruby is False, only the base text is returned.
        """
        base_parts: list = []
        rt_parts: list = []

        nodes = content if isinstance(content, list) else ([content] if content else [])
        for child in nodes:
            if not isinstance(child, dict):
                if child:
                    base_parts.append(_esc(str(child)))
                continue
            tag = child.get('tag', '')
            if tag == 'rt':
                if self.use_ruby:
                    rt_parts.append(self._node_to_html(child.get('content')))
            elif tag == 'rp':
                pass
            else:
                base_parts.append(self._node_to_html(child))

        base = ''.join(base_parts)
        if self.use_ruby:
            rt = ''.join(rt_parts).strip()
            return f'{base}（{rt}）' if rt else base
        return base

    # ── Anchor ────────────────────────────────────────────────────────────

    def _anchor_to_html(self, node: dict) -> str:
        """
        Cross-reference links: extract data.alt text if present (e.g. ［例］,
        ［対］), otherwise render inner content. Qt cannot follow
        dictionary-internal hrefs so we never emit a live <a> tag.
        """
        content = node.get('content')

        def find_alt(n) -> str:
            if isinstance(n, list):
                for child in n:
                    r = find_alt(child)
                    if r:
                        return r
            elif isinstance(n, dict):
                data = n.get('data', {})
                alt = data.get('alt', '') if isinstance(data, dict) else ''
                if alt:
                    return alt
                return find_alt(n.get('content'))
            return ''

        alt = find_alt(content)
        if alt:
            return _esc(alt)
        return self._node_to_html(content)

    # ── Main converter ────────────────────────────────────────────────────

    def _node_to_html(self, node) -> str:  # noqa: C901
        if node is None:
            return ''
        if isinstance(node, str):
            return _esc(node)
        if isinstance(node, list):
            return ''.join(self._node_to_html(child) for child in node)
        if not isinstance(node, dict):
            return ''

        tag = node.get('tag', '')
        content = node.get('content')
        style = node.get('style', {})

        # ── Special tags handled before style resolution ─────────────────

        if tag == 'img':
            from wordcel.dictionary.media import IMAGE_URI
            path = node.get('path', '')
            if isinstance(path, str) and IMAGE_URI.fullmatch(path):
                width, height = node.get('width'), node.get('height')
                dimensions = ''
                if (isinstance(width, int) and isinstance(height, int)
                        and width > 0 and height > 0):
                    scale = min(1, 320 / width)
                    dimensions = f' width="{round(width * scale)}" height="{round(height * scale)}"'
                return f'<img src="{path}"{dimensions}>'
            alt = node.get('alt') or node.get('title') or ''
            return f'<i>{_esc(alt)}</i>' if alt else ''

        if tag == 'ruby':
            return self._ruby_to_html(content)

        if tag in ('rt', 'rp'):
            return ''  # consumed inside _ruby_to_html

        if tag == 'br':
            return '<br>'

        if tag == 'a':
            return self._anchor_to_html(node)

        # ── Render inner content first ────────────────────────────────────
        inner = self._node_to_html(content)

        # ── No-op wrapper collapsing ──────────────────────────────────────
        # If a span or div carries no style and no data, it is a structural
        # no-op. Drop the wrapper entirely to keep the HTML lean.
        # We still process the children above so inner is always correct.
        if not style and tag in ('span', 'div'):
            data = node.get('data', {})
            if not (isinstance(data, dict) and data):
                return inner

        # ── Style resolution ─────────────────────────────────────────────
        char_props, block_props, has_border = _style_to_props(style)

        if tag in _CELL_TAGS:
            # Table cells: synthesize border shorthand (Qt supports it here)
            border_css = _synthesize_border(style)
            if not border_css:
                border_css = 'border:1px solid'  # default so table is legible
            cell_props = {**char_props, **block_props}
            cell_props['border'] = border_css.split(':', 1)[1]  # just the value
            # Rebuild properly
            all_props = {**char_props, **block_props, 'border': border_css.split(':', 1)[1]}
            css = _props_to_css(all_props)

        elif tag == 'table':
            border_css = _synthesize_border(style)
            all_props = {**char_props, **block_props}
            if border_css:
                all_props['border'] = border_css.split(':', 1)[1]
            css = _props_to_css(all_props)

        elif tag in _BLOCK_TAGS:
            css = _props_to_css({**char_props, **block_props})

        else:
            # span and unknown inline tags: only char-level
            css = _props_to_css(char_props)

        # ── Border fallback for non-table elements ────────────────────────
        # Qt ignores border-* on spans/divs. Signal the border visually by
        # wrapping the content in square brackets instead.
        if has_border and tag not in _CELL_TAGS and tag != 'table':
            inner = f'[{inner}]'

        style_attr = f' style="{css}"' if css else ''
        if tag in _CELL_TAGS:
            for attribute in ('colSpan', 'rowSpan'):
                value = node.get(attribute)
                if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 100:
                    style_attr += f' {attribute.lower()}="{value}"'

        if tag in _RENDERED_TAGS:
            return f'<{tag}{style_attr}>{inner}</{tag}>'

        # Unknown tag: drop wrapper, keep content
        return inner

    # ── Public API ────────────────────────────────────────────────────────

    def to_html(self, definition: dict) -> str:
        """
        Convert a {type:'structured-content', content:...} object to
        Qt-compatible HTML. Collapses runs of spaces left by block elements.
        """
        html = self._node_to_html(definition.get('content'))
        html = re.sub(r' {2,}', ' ', html)
        return html.strip()

    def extract_glosses(self, definitions: list) -> list:
        """
        Convert a yomitan definitions array to gloss strings.
          plain string / {type:'text'}     → HTML-escaped plain text
          {type:'structured-content'}      → Qt HTML
          {type:'image'} / deinflection    → skipped
        """
        glosses = []
        for defn in definitions:
            if isinstance(defn, str):
                text = defn.strip()
                if text:
                    glosses.append(_esc(text))
            elif isinstance(defn, dict):
                t = defn.get('type')
                if t == 'text':
                    text = defn.get('text', '').strip()
                    if text:
                        glosses.append(_esc(text))
                elif t == 'structured-content':
                    html = self.to_html(defn)
                    if html:
                        glosses.append(html)
                elif t == 'image':
                    html = self._node_to_html(dict(defn, tag='img'))
                    if html:
                        glosses.append(html)
            # deinflection arrays and image-only entries: skip
        return glosses
