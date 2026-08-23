"""Бюджет запросов на страницу: защита от N+1, которую не видно глазами.

Зелёные тесты про содержимое остаются зелёными и при сотне запросов на
страницу — разница только в том, что страница открывается полсекунды
вместо тридцати миллисекунд. Поэтому число запросов проверяется числом.

Так и нашлись две настоящие ошибки перехода на модели:

- карточка каталога спрашивает время чтения, а оно считалось по главам —
  сорок два запроса на двадцать одну работу, пока `Story.total_chars` не
  научился брать готовую аннотацию выдачи;
- `Collection.stories` делал свой `select_related` и потому игнорировал
  `prefetch_related` вызывающей стороны: десять подборок на главной —
  десять лишних запросов.

Границы — не рекорд, а потолок с запасом. Их можно поднять осознанно,
когда на странице появится новый блок; нельзя — «чтобы тест прошёл».
"""

from django.urls import reverse

from core.tests.base import TestCase


def _login(client):
    s = client.session
    s['signed_in'] = True
    s['user_name'] = 'Айдана'
    s['user_username'] = 'aidana'
    s.save()


class PagesStayWithinTheirQueryBudget(TestCase):

    def test_home_guest(self):
        """Одиннадцать: ряды, жинақтар, книга недели, полоса жанров, две
        витрины тегов."""
        with self.assertNumQueries(11):
            self.client.get(reverse('core:home'))

    def test_home_signed_in(self):
        """Плюс прогресс чтения и работы автора."""
        _login(self.client)
        with self.assertNumQueries(15):
            self.client.get(reverse('core:home'))

    def test_catalog(self):
        """Двадцать шесть: выдача, счётчики шести пресетов, чипы, рейл.

        Пресеты и есть основная статья расхода — каждый считает свою
        выдачу. Это осознанно: счётчик пресета обязан быть настоящим
        (DEC-36), а неправдивый счётчик хуже отсутствующего.
        """
        with self.assertNumQueries(26):
            self.client.get(reverse('core:catalog'))

    def test_genre_page(self):
        with self.assertNumQueries(23):
            self.client.get(reverse('core:genre_detail', kwargs={'slug': 'fantezi'}))

    def test_search(self):
        with self.assertNumQueries(23):
            self.client.get(reverse('core:search_results') + '?q=жағалау')

    def test_story_page(self):
        with self.assertNumQueries(18):
            self.client.get(reverse('core:story_detail',
                                    kwargs={'slug': 'dalney-berega'}))

    def test_story_chapter_with_comments_and_poll(self):
        """Глава дороже произведения: к ней добавляются комментарии с
        ответами, ряд реакций и опрос."""
        with self.assertNumQueries(31):
            self.client.get(reverse('core:story_detail',
                                    kwargs={'slug': 'dalney-berega'}) + '?chapter=3')

    def test_collections(self):
        """Пять на десять подборок с обложками — потому что состав приходит
        одним `prefetch_related`, а не запросом на карточку."""
        with self.assertNumQueries(5):
            self.client.get(reverse('core:collections'))

    def test_genre_index(self):
        """Один запрос на двенадцать жанров со счётчиками: счётчик —
        агрегат в том же SELECT, а не отдельный COUNT на строку."""
        with self.assertNumQueries(1):
            self.client.get(reverse('core:genre_index'))
