"""Shared Wordcel popup frame, independent of dictionary and OCR imports."""

from PyQt6.QtGui import QColor

PANE_PADDING = 4
FRAME_PADDING = 6
DIVIDER_WIDTH = 2
POPUP_GAP = 15


def surface_colors(background, foreground):
    bg, fg = QColor(background), QColor(foreground)
    def mix(amount):
        return QColor(*(round(b + (f-b)*amount) for b, f in zip(bg.getRgb()[:3], fg.getRgb()[:3]))).name()
    return {"muted": mix(.7), "border": mix(.25), "hover": mix(.12), "scroll": mix(.45)}


def frame_stylesheet(background, foreground, opacity, font_family):
    color = QColor(background)
    border = surface_colors(background, foreground)["border"]
    return f'''
        QFrame {{
            background-color: rgba({color.red()}, {color.green()}, {color.blue()}, {opacity});
            color: {foreground};
            border-radius: 8px;
            border: 1px solid {border};
        }}
        QLabel {{
            background-color: transparent;
            border: none;
            font-family: "{font_family}";
        }}
        hr {{ border: none; height: 1px; }}
    '''


def popup_position(x, y, popup_size, screen_geo, mode, vertical=False):
    """Pointer-relative placement within the screen bounds."""
    offset = POPUP_GAP
    # --- Positioning logic based on mode ---

    if vertical:
        right = screen_geo.right() + 1 - x - offset
        left = x - screen_geo.left() - offset
        use_right = right >= popup_size.width() or right >= left
        final_x = x + offset if use_right else x - popup_size.width() - offset
        final_y = y - popup_size.height() / 2

    elif mode == 'visual_novel_mode':
        # --- Vertical Position (VN Mode) ---
        screen_height = screen_geo.height()
        cursor_y_in_screen = y - screen_geo.top()
        is_below = True
        if cursor_y_in_screen > (2 * screen_height / 3):  # Lower third
            is_below = False  # Place above
        elif cursor_y_in_screen < (screen_height / 3):  # Upper third
            is_below = True  # Place below
        else:  # Middle third
            is_below = cursor_y_in_screen < (screen_height / 2)
        final_y = (y + offset) if is_below else (y - popup_size.height() - offset)

        # Vertical Push
        if final_y < screen_geo.top(): final_y = screen_geo.top()
        if final_y + popup_size.height() > screen_geo.bottom() + 1:
            final_y = screen_geo.bottom() + 1 - popup_size.height()

        # --- Horizontal Position (VN Mode) ---
        screen_width = screen_geo.width()
        cursor_x_in_screen = x - screen_geo.left()
        # Define anchor points for interpolation
        pos_right = x + offset
        pos_center = x - popup_size.width() / 2.0
        pos_left = x - popup_size.width() - offset

        # Interpolate smoothly between right, center, and left alignment
        if cursor_x_in_screen < screen_width / 2.0:
            ratio = cursor_x_in_screen / (screen_width / 2.0)
            final_x = pos_right * (1 - ratio) + pos_center * ratio
        else:
            ratio = (cursor_x_in_screen - (screen_width / 2.0)) / (screen_width / 2.0)
            final_x = pos_center * (1 - ratio) + pos_left * ratio

    elif mode == 'flip_horizontally':
        # X: Flip, Y: Push
        preferred_x = x + offset
        final_x = preferred_x if preferred_x + popup_size.width() <= screen_geo.right() + 1 else x - popup_size.width() - offset

        final_y = y + offset
        if final_y + popup_size.height() > screen_geo.bottom() + 1: final_y = screen_geo.bottom() + 1 - popup_size.height()
        if final_y < screen_geo.top(): final_y = screen_geo.top()

    elif mode == 'flip_vertically':
        # X: Push, Y: Flip
        final_x = x + offset
        if final_x + popup_size.width() > screen_geo.right() + 1: final_x = screen_geo.right() + 1 - popup_size.width()
        if final_x < screen_geo.left(): final_x = screen_geo.left()

        preferred_y = y + offset
        final_y = preferred_y if preferred_y + popup_size.height() <= screen_geo.bottom() + 1 else y - popup_size.height() - offset

    else:  # 'flip_both'
        # X: Flip
        preferred_x = x + offset
        final_x = preferred_x if preferred_x + popup_size.width() <= screen_geo.right() + 1 else x - popup_size.width() - offset

        # Y: Flip
        preferred_y = y + offset
        final_y = preferred_y if preferred_y + popup_size.height() <= screen_geo.bottom() + 1 else y - popup_size.height() - offset

    # Final clamp to ensure the popup is always fully visible.
    # This acts as a safeguard against any edge cases.
    final_x = max(screen_geo.left(), min(final_x, screen_geo.right() + 1 - popup_size.width()))
    final_y = max(screen_geo.top(), min(final_y, screen_geo.bottom() + 1 - popup_size.height()))

    return int(final_x), int(final_y)


def popup_entry_path_contains(geometry, anchor, point, *, vertical=True):
    """The triangle from the lookup point to the facing popup edge."""
    if anchor is None:
        return False
    along, across = (anchor.x(), anchor.y()) if vertical else (anchor.y(), anchor.x())
    target, position = (point.x(), point.y()) if vertical else (point.y(), point.x())
    near, far = (geometry.left(), geometry.right()) if vertical else (geometry.top(), geometry.bottom())
    start, end = (geometry.top(), geometry.bottom()) if vertical else (geometry.left(), geometry.right())
    if near <= along <= far:
        return False
    edge = near if along < near else far
    progress = (target - along) / (edge - along)
    return (0 <= progress <= 1
            and across + progress * (start - across) <= position <= across + progress * (end - across))


def lookup_geometry(anchor, requested, expanded_size, area, preference="more_room", vertical=False, *, expand_down=False):
    from PyQt6.QtCore import QRect, QSize

    offset = POPUP_GAP
    sides = ("left", "right") if vertical else ("above", "below")
    position = anchor.x() if vertical else anchor.y()
    start, end = (area.left(), area.right() + 1) if vertical else (area.top(), area.bottom() + 1)
    room = (max(0, position - offset - start), max(0, end - position - offset))
    required = expanded_size.width() if vertical else expanded_size.height()
    side = int(room[1] >= room[0])
    if preference in sides and room[sides.index(preference)] >= required:
        side = sides.index(preference)
    width = min(requested.width(), area.width(), max(1, room[side]) if vertical else area.width())
    height = min(requested.height(), area.height(), area.height() if vertical else max(1, room[side]))
    # Place the compact preview at the top of the expanded area for downward growth.
    reserved_height = height
    if expand_down:
        available_height = area.height() if vertical else max(1, room[side])
        reserved_height = min(max(height, expanded_size.height()), available_height)
    x, y = popup_position(anchor.x(), anchor.y(), QSize(width, reserved_height), area, "visual_novel_mode", vertical)
    if vertical:
        x = position + offset if side else position - offset - width
    else:
        y = position + offset if side else position - offset - reserved_height
    x = max(area.left(), min(x, area.right() + 1 - width))
    y = max(area.top(), min(y, area.bottom() + 1 - height))
    return QRect(x, y, width, height)


def expanded_geometry(previous, requested, area, anchor=None, vertical=False, *, expand_down=False):
    from PyQt6.QtCore import QRect
    width, height = min(requested.width(), area.width()), min(requested.height(), area.height())
    x, y = previous.x(), previous.y()
    if anchor is not None:
        if vertical:
            if previous.right() < anchor.x():
                width = min(width, previous.right() + 1 - area.left())
                x = previous.right() + 1 - width
            else:
                width = min(width, area.right() + 1 - x)
            if expand_down:
                height = min(height, area.bottom() + 1 - y)
        elif previous.bottom() < anchor.y():
            if expand_down:
                height = min(height, max(previous.height(), anchor.y() - POPUP_GAP - y))
            else:
                height = min(height, previous.bottom() + 1 - area.top())
                y = previous.bottom() + 1 - height
        else:
            height = min(height, area.bottom() + 1 - y)
    elif y + height > area.bottom() + 1:
        y = previous.bottom() + 1 - height
    x = max(area.left(), min(x, area.right() + 1 - width))
    y = max(area.top(), min(y, area.bottom() + 1 - height))
    return QRect(x, y, width, height)
