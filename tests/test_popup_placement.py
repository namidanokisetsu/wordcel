import unittest
from PyQt6.QtCore import QPoint, QRect, QSize
from wordcel.gui.popup_style import expanded_geometry, popup_position


class PopupPlacementTests(unittest.TestCase):
    def test_vertical_text_uses_available_side_and_clamps_height(self):
        for area in (QRect(0, 0, 1920, 1040), QRect(-1920, -200, 1920, 1040)):
            size = QSize(480, 340)
            for left, right_side in ((200, True), (1600, False)):
                bounds = QRect(area.left() + left, area.bottom() - 100, 40, 80)
                point = bounds.center()
                x, y = popup_position(point.x(), point.y(), size, area, 'visual_novel_mode', bounds)
                result = QRect(QPoint(x, y), size)
                self.assertTrue(area.contains(result))
                self.assertFalse(result.intersects(bounds))
                self.assertEqual(result.left() > bounds.right(), right_side)
                self.assertEqual(result.bottom(), area.bottom())

    def test_vertical_expansion_preserves_edge_beside_source(self):
        area = QRect(0, 0, 1920, 1040)
        bounds = QRect(800, 200, 40, 600)
        for previous in (QRect(855, 210, 300, 100), QRect(485, 210, 300, 100)):
            result = expanded_geometry(previous, QSize(480, 340), area, QPoint(820, 210), bounds)
            self.assertFalse(result.intersects(bounds))
            self.assertEqual(result.top(), previous.top())
            if previous.left() > bounds.right():
                self.assertEqual(result.left(), previous.left())
            else:
                self.assertEqual(result.right(), previous.right())

    def test_vertical_popup_stays_on_narrow_screen_when_neither_side_fits(self):
        area = QRect(-600, 0, 600, 800)
        bounds = QRect(-320, 300, 40, 100)
        size = QSize(480, 340)
        x, y = popup_position(-300, 350, size, area, 'visual_novel_mode', bounds)
        self.assertTrue(area.contains(QRect(QPoint(x, y), size)))

    def test_clamps_flush_to_inclusive_screen_edges(self):
        for area in (QRect(0, 0, 1920, 1040), QRect(-1280, -200, 1280, 720)):
            size = QSize(480, 340)
            x, _ = popup_position(area.right(), area.top() + 100, size, area, 'flip_vertically')
            _, y = popup_position(area.left() + 100, area.bottom(), size, area, 'flip_horizontally')
            self.assertEqual(x + size.width(), area.right() + 1)
            self.assertEqual(y + size.height(), area.bottom() + 1)

    def test_above_subtitles_preserves_lower_edge(self):
        previous = QRect(1500, 890, 350, 100)
        result = expanded_geometry(previous, QSize(480, 340), QRect(0, 0, 1920, 1040), QPoint(1600, 1005))
        self.assertEqual(result.bottom(), previous.bottom())
        self.assertLess(result.top(), previous.top())
        self.assertLess(result.bottom(), 1005)

    def test_below_source_grows_down_when_space_allows(self):
        previous = QRect(200, 150, 350, 100)
        result = expanded_geometry(previous, QSize(480, 340), QRect(0, 0, 1920, 1040), QPoint(200, 120))
        self.assertEqual(result.top(), previous.top())

    def test_flipping_a_below_text_preview_does_not_cover_the_source(self):
        previous = QRect(200, 925, 350, 100)
        anchor = QPoint(200, 910)
        result = expanded_geometry(previous, QSize(480, 340), QRect(0, 0, 1920, 1040), anchor)
        self.assertLess(result.bottom(), anchor.y())

    def test_no_room_below_grows_up_and_clamps_to_negative_origin_display(self):
        area = QRect(-1280, -200, 1280, 720)
        previous = QRect(-200, 390, 190, 100)
        result = expanded_geometry(previous, QSize(480, 340), area)
        self.assertEqual(result.bottom(), previous.bottom())
        self.assertTrue(area.contains(result))
        self.assertTrue(area.contains(expanded_geometry(previous, QSize(2000, 2000), area)))
