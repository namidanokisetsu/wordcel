import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from wordcel.dictionary.library import Entry
from wordcel.dictionary.search import SearchResult
from wordcel.gui.action_icons import POPUP_ACTIONS, action_button
from wordcel.gui.quick_lookup import LocalDictionaryBrowser, render_result


class DictionaryControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.browser = LocalDictionaryBrowser(selection_lookup=True)
        self.browser.setOpenLinks(False)
        self.browser.resize(300, 180)
        self.browser.show()
        self.lookups = []
        self.browser.word_selected.connect(self.lookups.append)

    def tearDown(self):
        self.browser.close()
        self.browser.deleteLater()
        self.app.processEvents()

    def point(self, text):
        cursor = self.browser.document().find(text)
        self.assertFalse(cursor.isNull())
        start = cursor.selectionStart()
        cursor.setPosition(start)
        left = self.browser.cursorRect(cursor).center()
        cursor.setPosition(start + 1)
        right = self.browser.cursorRect(cursor).center()
        return QPoint((left.x() + right.x()) // 2, left.y())

    def test_scrolling_an_expansion_link_never_looks_up_its_plus(self):
        self.browser.setHtml('<a name="top"></a>' + '<p>Definition</p>' * 30
                             + '<p><a href="expand:0">+</a></p>')
        self.app.processEvents()
        self.browser.verticalScrollBar().setValue(self.browser.verticalScrollBar().maximum())
        point = self.point("+")
        self.assertEqual(self.browser.anchorAt(point), "expand:0")
        clicked = []
        self.browser.anchorClicked.connect(clicked.append)
        self.browser.anchorClicked.connect(lambda _: self.browser.scrollToAnchor("top"))
        QTest.mouseClick(self.browser.viewport(), Qt.MouseButton.LeftButton, pos=point)
        self.assertEqual(len(clicked), 1)
        self.assertLessEqual(self.browser.verticalScrollBar().value(), self.browser.document().documentMargin())
        self.assertEqual(self.lookups, [])

    def test_expansion_and_collapse_keep_the_same_word_without_lookup(self):
        entry = Entry("fixture", "terakki", "", "Wiktionary", "tr", ("progress", "growth", "advance", "development"))
        result = SearchResult("terakki", "tr", "en", (entry,))
        expanded = {entry.source}
        collapsed = set()

        def render():
            self.browser.setHtml(render_result(result, expanded, collapsed=collapsed))

        def toggle(_):
            collapsed.symmetric_difference_update((entry.source,))
            render()

        self.browser.anchorClicked.connect(toggle)
        render()
        self.app.processEvents()
        self.assertIn("development", self.browser.toPlainText())
        for expected in (False, True):
            self.browser.verticalScrollBar().setValue(0)
            point = self.point("Wiktionary")
            self.assertEqual(self.browser.anchorAt(point), "collapse:0:0")
            QTest.mouseClick(self.browser.viewport(), Qt.MouseButton.LeftButton, pos=point)
            self.assertEqual("development" in self.browser.toPlainText(), expected)
            self.assertIn("terakki", self.browser.toPlainText())
        self.assertEqual(self.lookups, [])

    def test_double_clicking_definition_text_still_looks_it_up_once(self):
        self.browser.setHtml("<p>progress</p>")
        self.app.processEvents()
        point = self.point("progress")
        QTest.mouseDClick(self.browser.viewport(), Qt.MouseButton.LeftButton, pos=point)
        QTest.mouseRelease(self.browser.viewport(), Qt.MouseButton.LeftButton, pos=point)
        self.assertEqual(self.lookups, ["progress"])

    def test_hover_cursors_follow_links_text_and_empty_space(self):
        entry = Entry("fixture", "terakki", "", "Wiktionary", "tr", ("progress",))
        self.browser.setHtml(render_result(SearchResult("terakki", "tr", "en", (entry,))))
        self.app.processEvents()
        for point, shape in ((self.point("Wiktionary"), Qt.CursorShape.PointingHandCursor),
                             (self.point("progress"), Qt.CursorShape.IBeamCursor),
                             (self.browser.viewport().rect().bottomRight() - QPoint(2, 2),
                              Qt.CursorShape.ArrowCursor),
                             (self.point("Wiktionary"), Qt.CursorShape.PointingHandCursor)):
            QTest.mouseMove(self.browser.viewport(), point)
            self.assertEqual(self.browser.viewport().cursor().shape(), shape)

    def test_actions_never_inherit_the_reading_pane_cursor(self):
        self.browser.setHtml("<p>progress</p>")
        self.app.processEvents()
        QTest.mouseMove(self.browser.viewport(), self.point("progress"))
        self.assertEqual(self.browser.viewport().cursor().shape(), Qt.CursorShape.IBeamCursor)
        for name, description in POPUP_ACTIONS:
            with self.subTest(action=name):
                button = action_button(name, description, "#ffffff")
                button.setParent(self.browser.viewport())
                self.assertEqual(button.cursor().shape(), Qt.CursorShape.PointingHandCursor)
