"""Custom template filters `page_range` и `compact_count`."""

import unittest

from core.templatetags.balaproza import compact_count, page_range


class CompactCount(unittest.TestCase):

    def test_under_1000_stays_as_is(self):
        self.assertEqual(compact_count(0), '0')
        self.assertEqual(compact_count(840), '840')
        self.assertEqual(compact_count(999), '999')

    def test_thousands_get_one_decimal_with_comma(self):
        self.assertEqual(compact_count(1000), '1,0 мың')
        self.assertEqual(compact_count(8920), '8,9 мың')
        self.assertEqual(compact_count(9999), '10,0 мың')

    def test_ten_thousand_and_above_drops_decimal(self):
        self.assertEqual(compact_count(10000), '10 мың')
        self.assertEqual(compact_count(12482), '12 мың')

    def test_invalid_input_passes_through(self):
        self.assertEqual(compact_count(None), None)
        self.assertEqual(compact_count('abc'), 'abc')


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
