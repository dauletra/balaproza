"""Custom template filter `page_range`."""

import unittest

from core.templatetags.balaproza import page_range


class PageRange(unittest.TestCase):

    def test_total_le_7_returns_all(self):
        self.assertEqual(page_range(1, 1), [1])
        self.assertEqual(page_range(5, 3), [1, 2, 3, 4, 5])
        self.assertEqual(page_range(7, 4), [1, 2, 3, 4, 5, 6, 7])

    def test_current_near_start_shows_first_5_then_gap_then_last(self):
        # 1 2 3 4 5 … 12
        self.assertEqual(page_range(12, 1), [1, 2, 3, 4, 5, 0, 12])
        self.assertEqual(page_range(12, 4), [1, 2, 3, 4, 5, 0, 12])

    def test_current_near_end_shows_first_then_gap_then_last_5(self):
        # 1 … 8 9 10 11 12
        self.assertEqual(page_range(12, 12), [1, 0, 8, 9, 10, 11, 12])
        self.assertEqual(page_range(12, 9),  [1, 0, 8, 9, 10, 11, 12])

    def test_middle_current_shows_first_gap_neighbours_gap_last(self):
        # 1 … 5 6 7 … 12
        self.assertEqual(page_range(12, 6), [1, 0, 5, 6, 7, 0, 12])
        self.assertEqual(page_range(20, 10), [1, 0, 9, 10, 11, 0, 20])

    def test_invalid_input_returns_empty_list(self):
        self.assertEqual(page_range(None, 1), [])
        self.assertEqual(page_range('abc', 1), [])
        self.assertEqual(page_range(10, 'x'), [])
