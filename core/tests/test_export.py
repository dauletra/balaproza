"""Выгрузка своих текстов: что в файле и чего в нём быть не может.

Вопрос тут один и простой: человек нажал «забрать своё» — получил ли он
**всё** своё и **только** своё. Остальное (заголовок файла, пометки,
имя) проверяется потому, что файл открывают вне портала, где объяснить
уже некому.

Сборку документа и доступ к нему проверяют отдельно. Первая — чистая
функция без базы, и её дешевле спрашивать напрямую; вторая — про
адрес и вошедшего, и там важен ответ сервера, а не текст.
"""

from datetime import date
from urllib.parse import unquote

from django.urls import reverse

from core import data
from core.domain.export import portfolio_filename, portfolio_markdown
from core.tests import factories as f
from core.tests.base import TestCase, login_as, login_as_newcomer

TODAY = date(2026, 9, 19)


def _body(response) -> str:
    return response.content.decode()


class TheFileCarriesEverythingTheAuthorWrote(TestCase):
    """Своё — целиком: и опубликованное, и то, что читателю не показано."""

    def setUp(self):
        super().setUp()
        self.author = f.user(pen_name='Айдана')
        self.published = f.story(author=self.author, chapters=1,
                                 title='Жарияланған әңгіме')
        self.draft = f.story(author=self.author, chapters=2, published=False,
                             title='Әлі жоба')

    def _portfolio(self) -> str:
        return portfolio_markdown(
            author=self.author.public_name, username=self.author.username,
            exported_on=TODAY, works=data.export_portfolio(self.author))

    def test_both_the_published_and_the_unpublished_are_there(self):
        text = self._portfolio()

        self.assertIn('Жарияланған әңгіме', text)
        self.assertIn('Әлі жоба', text)

    def test_an_unpublished_chapter_is_marked_not_dropped(self):
        """Глава, которой читатель не видит, для автора существует ровно
        так же, как остальные, — пометка только про видимость."""
        text = self._portfolio()

        self.assertIn('оқырманға көрінбейді', text)
        # Опубликованная пометки не несёт: помечается исключение.
        published_head = [line for line in text.splitlines()
                          if line.startswith('## ') and 'көрінбейді' not in line]
        self.assertTrue(published_head)

    def test_the_working_copy_is_what_gets_exported(self):
        """Не одобренная ревизия: автор забирает написанное, включая
        правку, которую модератор ещё не видел."""
        chapter = self.published.chapter_set.get()
        data.save_chapter(self.published, chapter.pk, title=chapter.title,
                          body='Түзетілген мәтін.', poll_question='',
                          poll_options=[])

        self.assertIn('Түзетілген мәтін.', self._portfolio())

    def test_a_work_without_text_does_not_vanish(self):
        """Иначе автор пересчитает свои вещи и не досчитается."""
        f.story(author=self.author, chapters=0, published=False,
                title='Бос шығарма')

        text = self._portfolio()

        self.assertIn('Бос шығарма', text)
        self.assertIn('Мәтін әлі жазылмаған', text)

    def test_the_header_says_whose_it_is_and_when(self):
        text = self._portfolio()

        self.assertIn('# Айдана', text)
        self.assertIn(f'@{self.author.username}', text)
        # ISO: файл живёт в папке загрузок рядом с прошлыми выгрузками,
        # и «5 жел» там не отвечает даже на вопрос «какого года».
        self.assertIn('2026-09-19', text)
        self.assertIn('2 шығарма', text)

    def test_nobody_elses_work_gets_in(self):
        stranger = f.user()
        f.story(author=stranger, chapters=1, title='Бөтен шығарма')

        self.assertNotIn('Бөтен шығарма', self._portfolio())

    def test_the_whole_portfolio_costs_two_queries(self):
        """Один запрос на работы и один на все их главы. Без предзагрузки
        портфель из пятнадцати работ стоил бы шестнадцати."""
        with self.assertNumQueries(2):
            data.export_portfolio(self.author)


class AnEmptyPortfolioIsStillAFile(TestCase):
    """Пустой ответ хуже пустого файла: человек не понял бы, сработало ли."""

    def test_it_says_there_is_nothing_yet(self):
        newcomer = f.user()

        text = portfolio_markdown(
            author=newcomer.public_name, username=newcomer.username,
            exported_on=TODAY, works=data.export_portfolio(newcomer))

        self.assertIn('0 шығарма', text)
        self.assertIn('Әзірге жазылған шығарма жоқ', text)


class TheFileNameSurvivesTheDownloadsFolder(TestCase):

    def test_it_carries_the_name_and_the_date(self):
        """Вторая выгрузка через месяц не должна затирать первую."""
        self.assertEqual(portfolio_filename('aidana', TODAY),
                         'qazaqnovel-aidana-2026-09-19.md')


class TheDownloadIsForTheSignedInAuthorOnly(TestCase):

    def setUp(self):
        super().setUp()
        self.url = reverse('core:export_texts')

    def test_a_guest_is_sent_to_the_door(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('core:login'), response['Location'])

    def test_it_comes_back_as_a_file(self):
        login_as(self.client)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertIn('text/markdown', response['Content-Type'])
        disposition = unquote(response['Content-Disposition'])
        self.assertIn('attachment', disposition)
        self.assertIn('qazaqnovel-aidana-', disposition)

    def test_it_holds_the_signed_in_authors_own_work(self):
        """Ника в адресе нет вовсе — портфель собирается по вошедшему, и
        подставить чужой нечем."""
        author = login_as(self.client)
        mine = author.stories.first()

        text = _body(self.client.get(self.url))

        self.assertIn(mine.title, text)

    def test_a_newcomer_gets_their_empty_file(self):
        """Пустой портфель — не ошибка: у человека просто ещё ничего нет."""
        login_as_newcomer(self.client)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertIn('Әзірге жазылған шығарма жоқ', _body(response))
