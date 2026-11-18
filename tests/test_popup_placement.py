import unittest
from PyQt6.QtCore import QPoint, QRect, QSize
from wordcel.gui.popup_style import expanded_geometry, lookup_geometry, popup_entry_path_contains, popup_position


class PopupPlacementTests(unittest.TestCase):
    def test_vertical_text_uses_available_side_and_clamps_height(self):
        for area in (QRect(0, 0, 1920, 1040), QRect(-1920, -200, 1920, 1040)):
            size = QSize(480, 340)
            for left, right_side in ((200, True), (1600, False)):
                point = QPoint(area.left() + left, area.bottom() - 60)
                x, y = popup_position(point.x(), point.y(), size, area, 'visual_novel_mode', vertical=True)
                result = QRect(QPoint(x, y), size)
                self.assertTrue(area.contains(result))
                self.assertFalse(result.contains(point))
                self.assertEqual(result.left() > point.x(), right_side)
                gap = result.left() - point.x() if right_side else point.x() - result.right() - 1
                self.assertEqual(gap, 15)
                self.assertEqual(result.bottom(), area.bottom())

    def test_vertical_expansion_preserves_edge_beside_source(self):
        area = QRect(0, 0, 1920, 1040)
        anchor = QPoint(820, 210)
        for previous in (QRect(855, 210, 300, 100), QRect(485, 210, 300, 100)):
            result = expanded_geometry(previous, QSize(480, 340), area, anchor, vertical=True)
            self.assertFalse(result.contains(anchor))
            self.assertEqual(result.top(), previous.top())
            if previous.left() > anchor.x():
                self.assertEqual(result.left(), previous.left())
            else:
                self.assertEqual(result.right(), previous.right())

    def test_vertical_popup_stays_on_narrow_screen_when_neither_side_fits(self):
        area = QRect(-600, 0, 600, 800)
        size = QSize(480, 340)
        x, y = popup_position(-300, 350, size, area, 'visual_novel_mode', vertical=True)
        self.assertTrue(area.contains(QRect(QPoint(x, y), size)))

    def test_entry_path_connects_source_to_both_popup_edges_only(self):
        anchor = QPoint(600, 400)
        for geometry, direction in ((QRect(615, 200, 480, 400), 1), (QRect(105, 200, 480, 400), -1)):
            self.assertTrue(popup_entry_path_contains(geometry, anchor, anchor))
            self.assertTrue(popup_entry_path_contains(geometry, anchor, anchor + QPoint(direction * 8, 20)))
            self.assertFalse(popup_entry_path_contains(geometry, anchor, anchor + QPoint(-direction * 8, 0)))
            self.assertFalse(popup_entry_path_contains(geometry, anchor, anchor + QPoint(0, 30)))

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

    def test_expanding_a_below_text_preview_stops_at_screen_edge(self):
        previous = QRect(200, 925, 350, 100)
        anchor = QPoint(200, 910)
        result = expanded_geometry(previous, QSize(480, 340), QRect(0, 0, 1920, 1040), anchor)
        self.assertEqual(result.top(), previous.top())
        self.assertEqual(result.bottom(), 1039)

    def test_preferred_side_must_fit_expanded_size_in_either_orientation(self):
        area = QRect(-100, -100, 1000, 800)
        preview, expanded = QSize(200, 72), QSize(480, 340)
        for vertical, point, preference in ((False, QPoint(400, 90), 'above'),
                                              (True, QPoint(100, 300), 'left')):
            with self.subTest(vertical=vertical):
                place = lambda preferred: lookup_geometry(point, preview, expanded, area, preferred, vertical)
                self.assertEqual(place(preference), place('more_room'))
                self.assertTrue(place(preference).left() > point.x() if vertical else place(preference).top() > point.y())

    def test_preference_can_override_more_room_and_expansion_keeps_its_edge(self):
        area = QRect(0, 0, 1200, 1000)
        preview, expanded = QSize(200, 72), QSize(480, 340)
        for vertical, point, preference in ((False, QPoint(400, 400), 'above'),
                                              (True, QPoint(520, 320), 'left')):
            with self.subTest(vertical=vertical):
                previous = lookup_geometry(point, preview, expanded, area, preference, vertical)
                result = expanded_geometry(previous, QSize(1300, 1100), area, point, vertical)
                if vertical:
                    self.assertEqual(result.right(), point.x() - 16)
                    self.assertEqual(result.left(), area.left())
                else:
                    self.assertEqual(result.bottom(), point.y() - 16)
                    self.assertEqual(result.top(), area.top())

    def test_downward_growth_above_text_keeps_headword_and_source_in_place(self):
        area = QRect(0, 0, 1000, 800)
        source = QPoint(500, 560)
        expanded = QSize(480, 340)
        preview = lookup_geometry(source, QSize(480, 100), expanded, area, expand_down=True)
        result = expanded_geometry(preview, QSize(480, 500), area, source, expand_down=True)
        self.assertEqual(result.topLeft(), preview.topLeft())
        self.assertEqual(result.size(), expanded)
        self.assertEqual(result.bottom(), source.y() - 16)
        self.assertTrue(popup_entry_path_contains(preview, source, source - QPoint(0, 40), vertical=False))
        self.assertFalse(popup_entry_path_contains(preview, source, source + QPoint(0, 40), vertical=False))

    def test_downward_growth_beside_vertical_text_keeps_top_and_facing_edge(self):
        area = QRect(0, 0, 1200, 800)
        source = QPoint(1000, 750)
        expanded = QSize(480, 340)
        preview = lookup_geometry(source, QSize(480, 100), expanded, area, vertical=True, expand_down=True)
        result = expanded_geometry(preview, QSize(580, 450), area, source, vertical=True, expand_down=True)
        self.assertEqual(result.topRight(), preview.topRight())
        self.assertEqual(result.bottom(), area.bottom())

    def test_no_room_below_grows_up_and_clamps_to_negative_origin_display(self):
        area = QRect(-1280, -200, 1280, 720)
        previous = QRect(-200, 390, 190, 100)
        result = expanded_geometry(previous, QSize(480, 340), area)
        self.assertEqual(result.bottom(), previous.bottom())
        self.assertTrue(area.contains(result))
        self.assertTrue(area.contains(expanded_geometry(previous, QSize(2000, 2000), area)))
