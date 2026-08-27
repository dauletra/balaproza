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

Один запрос есть у **каждой** страницы: ссылки «Авторлар мектебі» в
подвале. Их отдаёт глобальный контекст-процессор, и это цена того, что
список правится в админке, а не в коде.
"""

from django.urls import reverse

from core.tests.base import TestCase, login_as


class PagesStayWithinTheirQueryBudget(TestCase):

    def test_home_guest(self):
        """Двадцать два: ряды, жинақтар, книга недели, полоса жанров, две
        витрины тегов, баннер конкурса, секция «Байқаулар», счётчики
        масштаба и новые имена.

        Секция добавляет пять: `open_contests`/`finished_contests` — по
        два запроса каждая (выдача + присуждения), плюс один за
        `winner_stories` карточки завершённого конкурса в ряду.
        """
        with self.assertNumQueries(22):
            self.client.get(reverse('core:home'))

    def test_home_signed_in(self):
        """Плюс прогресс чтения, свои работы, бейдж уведомлений и сам вошедший.

        Последний — цена настоящего входа: сессия хранит только id, и кто
        за ним стоит, спрашивают у базы. Запрос один на весь запрос
        страницы (`request.user` кэширован), и он же приносит имя для
        приветствия — отдельного обращения за автором у шапки нет.
        """
        login_as(self.client)
        with self.assertNumQueries(28):
            self.client.get(reverse('core:home'))

    def test_catalog(self):
        """Двадцать один: выдача, счётчики шести пресетов, чипы, рейл.

        Счётчик пресета обязан быть настоящим (DEC-36) — неправдивый хуже
        отсутствующего, — но настоящий он и от `COUNT`. Пока пресеты
        считались через `len()`, каждый выполнял выдачу целиком и строил
        список ORM-объектов со всеми тегами: шесть раз ради шести цифр.

        Ещё два запроса ушли вместе с `CatalogState`: резолв жанра и тега
        вызывался с пустым слагом и всё равно шёл в базу.
        """
        with self.assertNumQueries(18):
            self.client.get(reverse('core:catalog'))

    def test_genre_page(self):
        with self.assertNumQueries(18):
            self.client.get(reverse('core:genre_detail', kwargs={'slug': 'fantezi'}))

    def test_search(self):
        with self.assertNumQueries(18):
            self.client.get(reverse('core:search_results') + '?q=жағалау')

    def test_story_page(self):
        """Девятнадцать: работа, главы, рекомендации, жинақтар, карточка
        автора с числом работ и «подписан ли я».

        Было 21 — `StoryComment.replies` стал `cached_property` (Ф15,
        Этап 2): раньше он звал `.select_related('author')` на каждый
        топ-уровневый комментарий и рвал кэш `prefetch_related`, то есть
        сам себе устраивал N+1 поверх уже сделанного prefetch.

        Стало 18: `related_stories` перестал делать две выборки («тот же
        жанр» и «добор популярным») — порядок выражен ключом сортировки, и
        второй `prefetch_related('tags')` ушёл вместе со вторым запросом."""
        with self.assertNumQueries(18):
            self.client.get(reverse('core:story_detail',
                                    kwargs={'slug': 'dalney-berega'}))

    def test_story_chapter_with_comments_and_poll(self):
        """Глава дороже произведения: к ней добавляются комментарии с
        ответами, ряд реакций и опрос. Было 34, стало 30 — те же две
        причины, что у `test_story_page`."""
        with self.assertNumQueries(30):
            self.client.get(reverse('core:story_detail',
                                    kwargs={'slug': 'dalney-berega'}) + '?chapter=3')

    def test_collections(self):
        """Пять на десять подборок с обложками — потому что состав приходит
        одним `prefetch_related`, а не запросом на карточку."""
        with self.assertNumQueries(6):
            self.client.get(reverse('core:collections'))

    def test_genre_index(self):
        """Один запрос на двенадцать жанров со счётчиками: счётчик —
        агрегат в том же SELECT, а не отдельный COUNT на строку."""
        with self.assertNumQueries(2):
            self.client.get(reverse('core:genre_index'))

    def test_contest_list(self):
        """Раздел конкурсов: две выборки (идущие и завершённые) плюс
        победители к ним.

        Карточка называет фазу, приз и победителей — номинации, этапы,
        жюри и условия ей не нужны, и список за них не платит. Число
        заявок приходит агрегатом: `COUNT` на карточку рос вместе с
        разделом, и это была половина всех запросов страницы.
        """
        with self.assertNumQueries(6):
            self.client.get(reverse('core:contest_list'))

    def test_contest_detail(self):
        """Страница конкурса — наоборот, со всем составом: условия,
        этапы, жюри, номинации, присуждения и список участников."""
        with self.assertNumQueries(8):
            self.client.get(reverse('core:contest_detail',
                                    kwargs={'slug': 'altyn-qalam'}))


class PersonalPagesStayWithinTheirQueryBudget(TestCase):
    """Страницы вошедшего: профиль, кабинет, библиотека, конкурсные заявки.

    Их здесь не было, и потому именно они разъехались сильнее всего. Свой
    профиль спрашивал список работ автора **шестнадцать раз** за один
    рендер: хелперы этого слоя отдают список, а не QuerySet, кэша у списка
    нет, и каждый сегмент, каждая сводка и каждая из пяти наград ходили в
    базу заново. Пятьдесят девять запросов на страницу — из этого. Ни один
    тест про содержимое такого не видел: все они оставались зелёными.

    Границы держат правило «посчитать один раз и передать»: работы автора,
    его заявки и полки библиотеки собираются в `AuthorFacts` и дальше
    только читаются.
    """

    def test_profile_me(self):
        """Свой профиль — самая дорогая страница портала: сегменты, четыре
        сводки, ряд знаков, каталог знаков, ступени оқылым, библиотека и
        конкурсная биография. Было 59."""
        login_as(self.client)
        with self.assertNumQueries(14):
            self.client.get(reverse('core:profile_me'))

    def test_profile_me_stats_tab(self):
        """Вкладка «Статистика» не добавляет запросов: своя статистика
        считается из тех же работ, что и публичная."""
        login_as(self.client)
        with self.assertNumQueries(14):
            self.client.get(reverse('core:profile_me') + '?tab=stats')

    def test_profile_other(self):
        """Чужой профиль дешевле своего: библиотеки и приватной сводки нет.
        Было 24."""
        with self.assertNumQueries(9):
            self.client.get(reverse('core:profile_other',
                                    kwargs={'username': 'aidana'}))

    def test_my_stories(self):
        """Кабинет: работы и полоса внимания по одному и тому же списку."""
        login_as(self.client)
        with self.assertNumQueries(11):
            self.client.get(reverse('core:my_stories'))

    def test_library(self):
        """Три вкладки — одна выборка: полки режутся из неё, а не
        спрашиваются по одной на вкладку ради счётчика в сегменте."""
        login_as(self.client)
        with self.assertNumQueries(8):
            self.client.get(reverse('core:library'))

    def test_my_submissions(self):
        """«Можно ли отозвать» больше не тянет конкурс со всем составом на
        каждую строку: `can_withdraw` принимает готовый объект. Было 20."""
        login_as(self.client)
        with self.assertNumQueries(5):
            self.client.get(reverse('core:my_submissions'))

    def test_contest_submit(self):
        """Форма подачи: конкурс берётся один раз вместо трёх, объём
        кандидата — из аннотации выдачи, а не походом за главами на
        каждую работу автора. Было 35.
        """
        login_as(self.client)
        with self.assertNumQueries(16):
            self.client.get(reverse('core:contest_submit',
                                    kwargs={'slug': 'altyn-qalam'}))
