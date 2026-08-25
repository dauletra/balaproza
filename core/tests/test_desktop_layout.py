"""Фаза 5 · десктопная раскладка.

Правый рейл — единственный элемент, который сужает колонку контента, поэтому
его брейкпоинт держим в одном месте и проверяем, что все спутники (мобильные
дубли блоков рейла) переключаются вместе с ним. Рассинхрон даёт либо дырку
в контенте, либо один и тот же блок дважды на экране.
"""

import re
import unittest
from pathlib import Path

from core.tests.base import TestCase, login_as
from django.urls import reverse

TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "templates"

# Ширина контейнера, паддинги и рейл — из base.html.
CONTAINER_MAX = 1280
PADDING_LG = 48 * 2
RAIL = 300
GAP = 24
CONTENT_MAX = 860  # ширина колонки рядом с рейлом; она же max-w у <main>
CARD_GAP = 14
MOBILE_CARD = 138


def _main_column(viewport: int, *, rail: bool) -> int:
    inner = min(viewport, CONTAINER_MAX) - PADDING_LG
    return min(inner - (RAIL + GAP) if rail else inner, CONTENT_MAX)


def _card_width(column: int, columns: int) -> float:
    return (column - CARD_GAP * (columns - 1)) / columns


class BookGridSizing(unittest.TestCase):
    """Обложки не должны быть мельче мобильных — это витрина книг."""

    COLUMNS = 5

    def test_cards_never_smaller_than_on_phone(self):
        cases = [
            (1024, False),   # рейла ещё нет
            (1280, True),
            (1440, True),
            (1920, True),
        ]
        for viewport, rail in cases:
            with self.subTest(viewport=viewport):
                width = _card_width(_main_column(viewport, rail=rail), self.COLUMNS)
                self.assertGreaterEqual(round(width), MOBILE_CARD)

    def test_six_columns_would_regress(self):
        """Фиксируем причину, по которой колонок пять, а не шесть."""
        self.assertLess(round(_card_width(_main_column(1280, rail=True), 6)), MOBILE_CARD)

    def test_rail_at_lg_would_regress(self):
        """И причину, по которой рейл переехал с lg на xl: 1024px с рейлом."""
        self.assertLess(round(_card_width(_main_column(1024, rail=True), 6)), 100)


class ContentColumnWidth(unittest.TestCase):
    """Колонка контента одинакова с рейлом и без него.

    Раньше `<main>` был просто `flex-1`: как только рейл прятался (ниже xl или
    на странице без `has_right_rail`), контент забирал его 324px и становился
    ШИРЕ, чем на большом экране. Тот же ряд из пяти карточек выглядел крупнее
    на меньшем мониторе — ритм сетки ломался на ровном месте.
    """

    def test_cap_equals_column_next_to_rail(self):
        inner = CONTAINER_MAX - PADDING_LG
        self.assertEqual(inner - (RAIL + GAP), CONTENT_MAX)

    def test_main_carries_the_cap(self):
        base = (TEMPLATES_DIR / "base.html").read_text(encoding="utf-8")
        self.assertIn(f'max-w-[{CONTENT_MAX}px]', base)
        self.assertIn('<main class="mx-auto w-full min-w-0', base)

    def test_column_never_widens_when_the_rail_disappears(self):
        with_rail = _main_column(CONTAINER_MAX, rail=True)
        for viewport in (1024, 1279, 1280, 1440, 1920):
            with self.subTest(viewport=viewport):
                self.assertLessEqual(_main_column(viewport, rail=False), with_rail)

    def test_no_page_overrides_the_cap(self):
        """Свой max-w шире 860 в шаблоне страницы вернёт тот же разнобой."""
        for path in (TEMPLATES_DIR / "pages").rglob("*.html"):
            for value in re.findall(r'max-w-\[(\d+)px\]', path.read_text(encoding="utf-8")):
                with self.subTest(template=path.name, value=value):
                    self.assertLessEqual(int(value), CONTENT_MAX)


class RailBreakpointConsistency(unittest.TestCase):

    def test_aside_uses_xl(self):
        base = (TEMPLATES_DIR / "base.html").read_text(encoding="utf-8")
        self.assertIn('<aside class="hidden w-[300px] shrink-0 xl:block">', base)

    def test_no_template_still_gates_rail_content_on_lg(self):
        """Мобильные дубли блоков рейла обязаны прятаться на том же брейкпоинте.

        Списком идут файлы, где lg:hidden относится к рейлу; сетки карточек
        и декоративные элементы переключаются по своим правилам и сюда
        не попадают.
        """
        rail_companions = [
            "pages/home.html",
            "partials/home/hero_returning.html",
            "pages/catalog/catalog.html",
            "partials/catalog/_filter_sheet.html",
            "pages/story/story_detail.html",
        ]
        for name in rail_companions:
            with self.subTest(template=name):
                text = (TEMPLATES_DIR / name).read_text(encoding="utf-8")
                self.assertNotIn('lg:hidden', text)


class HeaderAlignment(TestCase):
    """Шапка, контент и футер должны начинаться на одной вертикали."""

    def test_header_container_matches_page_container(self):
        header = (TEMPLATES_DIR / "partials/header.html").read_text(encoding="utf-8")
        base = (TEMPLATES_DIR / "base.html").read_text(encoding="utf-8")
        footer = (TEMPLATES_DIR / "partials/footer.html").read_text(encoding="utf-8")

        for name, text in (("header", header), ("base", base), ("footer", footer)):
            with self.subTest(template=name):
                self.assertIn("max-w-[1280px]", text)
                self.assertIn("lg:px-12", text)

    def test_header_no_longer_uses_its_own_padding(self):
        header = (TEMPLATES_DIR / "partials/header.html").read_text(encoding="utf-8")
        self.assertNotIn("lg:px-[125px]", header)
        self.assertNotIn("max-w-[1440px]", header)


class RailContentHasMobileEquivalent(TestCase):
    """Ничего важного не должно жить только в правом рейле.

    Рейл рендерится с xl, поэтому любой эксклюзивный виджет пропадает на
    телефоне и планшете целиком. Проверяем по подписям показателей, а не по
    заголовкам виджетов: заголовок мобильной копии может отличаться, а данные —
    нет. Обратная ошибка тоже ловится вручную: мобильная копия обязана быть
    под xl:hidden, иначе на десктопе блок покажется дважды.
    """

    PAGES = [
        ('/me/',                        ['Шығарма', 'Реакциялар', 'Оқылым']),
        ('/u/rudazov/',                 ['Шығарма', 'Жазылушы', 'Реакциялар', 'Оқылым']),
        ('/contests/bolashak-mektebi/', ['Сыйақы', 'Өтінім', 'Қазылар']),
        ('/story/dalney-berega/',       ['Автор', 'Бөлім']),
        ('/catalog/',                   ['Сүзгілер']),
        ('/',                           ['Белсенді байқау', 'Танымал тегтер']),
    ]

    def setUp(self):
        login_as(self.client)

    def test_no_widget_is_rail_exclusive(self):
        for url, labels in self.PAGES:
            html = self.client.get(url).content.decode()
            start = html.find('<aside')
            end = html.find('</aside>', start) if start != -1 else -1
            outside = html[:start] + html[end:] if start != -1 else html
            for label in labels:
                with self.subTest(url=url, label=label):
                    self.assertIn(label, outside)


class ProfileStatsNotDuplicated(TestCase):
    """Четыре числа профиля рендерились и в теле (FR-PROF-01), и в рейле."""

    def setUp(self):
        login_as(self.client)

    def test_stats_render_once(self):
        html = self.client.get('/me/').content.decode()
        self.assertNotIn('Қысқа сан', html)
        self.assertEqual(html.count('>Реакциялар</dt>'), 1)


class MoneyFormatting(TestCase):
    """`stringformat:"d"` печатал «500000» сплошняком — всюду фильтр `spaced`."""

    def test_prize_is_spaced_on_every_surface(self):
        for url in ('/', '/contests/', '/contests/bolashak-mektebi/'):
            with self.subTest(url=url):
                html = self.client.get(url).content.decode()
                if '₸' in html:
                    self.assertNotIn('500000', html)

    def test_no_template_still_uses_raw_stringformat_for_money(self):
        for path in TEMPLATES_DIR.rglob("*.html"):
            text = path.read_text(encoding="utf-8")
            with self.subTest(template=path.name):
                self.assertNotIn('prize_kzt|stringformat:"d"', text)


class HomeRowSize(TestCase):

    def test_rows_carry_five_stories(self):
        r = self.client.get(reverse('core:home'))
        for key in ('top_stories', 'serial_stories', 'short_stories'):
            with self.subTest(row=key):
                self.assertLessEqual(len(r.context[key]), 5)

    def test_grid_is_five_columns(self):
        scroller = (TEMPLATES_DIR / "partials/home/_book_scroller.html").read_text(encoding="utf-8")
        self.assertIn("lg:grid-cols-5", scroller)
        self.assertNotIn("lg:grid-cols-6", scroller)

    def test_skeleton_grid_matches_content_grid(self):
        """Иначе при подстановке контента страница дёргается."""
        home = (TEMPLATES_DIR / "pages/home.html").read_text(encoding="utf-8")
        for match in re.findall(r'lg:grid-cols-(\d)', home):
            self.assertEqual(match, '5')
