"""NOTIF — лента событий автора и бейдж непрочитанного.

Два правила этого раздела: **хранится момент, выводится подпись**
(BR-70a) — «5 күн бұрын» в колонке устаревало назавтра, — и
**уведомление ведёт к своему предмету и не переписывает его имя**
(BR-72a).
"""

import re
from datetime import timedelta
from html.parser import HTMLParser
from pathlib import Path
from unittest import mock

from core.tests.base import TestCase, login_as, login_as_newcomer
from django.urls import reverse
from django.utils import timezone

from core import data
from core.models import Notification, Story, User

TEMPLATES = Path(__file__).resolve().parents[2] / 'templates'


def _aidana_notifications():
    """Лента демо-автора из базы — то же, что видит страница."""
    return list(Notification.objects.filter(user__username='aidana')
                .order_by('-created_at'))


def _notification(username='ghost', **fields):
    """Уведомление для проверки ветки, которой нет в демо-ленте.

    Создаётся в базе, а не подменяется в модуле: транзакция теста откатит
    его, и следующий тест увидит корпус нетронутым.
    """
    days = fields.pop('days_ago', 0)
    user, _ = User.objects.get_or_create(username=username)
    return Notification.objects.create(
        user=user, created_at=timezone.now() - timedelta(days=days), **fields)


TEMPLATES = Path(__file__).resolve().parents[2] / 'templates'


class NotificationsHelpers(TestCase):

    def test_groups_into_buckets(self):
        g = data.notifications_for_user('aidana')
        for b in data.NOTIF_BUCKETS:
            self.assertIn(b, g)
        # Раскладка сходится с самими данными: числа-литералы здесь
        # устаревали бы при каждой правке демо-ленты.
        items = _aidana_notifications()
        for b in data.NOTIF_BUCKETS:
            self.assertEqual(len(g[b]), sum(1 for n in items if n.bucket == b))
        self.assertTrue(all(g[b] for b in data.NOTIF_BUCKETS),
                        'у aidana должен быть непустым каждый из трёх бакетов')

    def test_unknown_user_empty_buckets(self):
        g = data.notifications_for_user('no-such-user')
        for b in data.NOTIF_BUCKETS:
            self.assertEqual(g[b], [])

    def test_unread_count(self):
        items = _aidana_notifications()
        expected = sum(1 for n in items if not n.read and n.bucket)
        self.assertEqual(data.unread_count_for_user('aidana'), expected)
        self.assertGreater(expected, 0)

    def test_unread_zero_for_unknown(self):
        self.assertEqual(data.unread_count_for_user('ghost'), 0)

    def test_notification_kinds_within_set(self):
        for n in _aidana_notifications():
            with self.subTest(kind=n.kind):
                self.assertIn(n.kind, data.NOTIF_KINDS)


class NotificationTime(TestCase):
    """Время уведомления выводится из `days_ago`, а не хранится строкой (BR-70a).

    Хранимые `when="5 күн бұрын"` и `bucket="past_week"` устаревали на
    следующий день — тот же класс ошибки, что `days_left=12` до DEC-45,
    только незаметнее: лента выглядит правдоподобной всегда.
    """

    def test_time_fields_are_not_stored(self):
        stored = {f.name for f in Notification._meta.get_fields()}
        for gone in ('when', 'bucket'):
            self.assertNotIn(
                gone, stored,
                f'`{gone}` снова стало полем — это хранимое производное (BR-70a)')

    def test_bucket_follows_the_calendar(self):
        cases = {0: 'today', 1: 'yesterday', 2: 'past_week',
                 7: 'past_week', 8: '', 400: ''}
        for days, expected in cases.items():
            with self.subTest(days=days):
                n = _notification(kind='like', days_ago=days)
                self.assertEqual(n.bucket, expected)

    def test_older_than_a_week_is_not_shown_and_not_counted(self):
        """Групп три; четвёртой «раньше» в FR-NOTIF-01 нет.

        Значит, событие старше недели в ленту не попадает — и в бейдж
        тоже, иначе шапка звала бы на страницу, где его нет.
        """
        _notification(kind='like', days_ago=30)
        grouped = data.notifications_for_user('ghost')
        self.assertEqual([], [n for b in grouped.values() for n in b])
        self.assertEqual(0, data.unread_count_for_user('ghost'))

    def test_wording_of_kk_ago(self):
        self.assertEqual(data.kk_ago(0, 2), '2 сағат бұрын')
        self.assertEqual(data.kk_ago(0), 'бүгін')
        self.assertEqual(data.kk_ago(1), 'кеше')
        self.assertEqual(data.kk_ago(5), '5 күн бұрын')
        self.assertEqual(data.kk_ago(60), '2 ай бұрын')
        self.assertEqual(data.kk_ago(800), '2 жыл бұрын')

    def test_hours_only_refine_today(self):
        """«26 сағат бұрын» человек переводит в дни сам — короче «кеше»."""
        self.assertEqual(data.kk_ago(1, 26), 'кеше')

    def test_freshest_first_inside_a_bucket(self):
        """Порядок объявления в данных — не порядок ленты.

        Сегодняшние события шли «2 сағат · 4 сағат · 9 сағат · 6 сағат».
        """
        for bucket in data.notifications_for_user('aidana').values():
            moments = [n.created_at for n in bucket]
            self.assertEqual(moments, sorted(moments, reverse=True))


class NotificationsLeadSomewhere(TestCase):
    """Уведомление ведёт к своему предмету (FR-NOTIF-05, BR-72a).

    Конкурсное событие знало о конкурсе только по имени внутри `text`
    и потому не вело никуда: прочитав «шорт-лист басталды», автор шёл
    искать конкурс через меню.
    """

    def setUp(self):
        login_as(self.client)
        self.response = self.client.get(reverse('core:notifications'))

    def test_contest_notification_links_to_its_contest(self):
        contest_notifs = [n for n in _aidana_notifications()
                          if n.kind == 'contest']
        self.assertTrue(contest_notifs, 'стаб потерял конкурсные уведомления')
        for n in contest_notifs:
            with self.subTest(contest=n.contest.slug):
                self.assertTrue(n.contest, 'конкурсное уведомление без конкурса')
                self.assertContains(
                    self.response,
                    reverse('core:contest_detail', kwargs={'slug': n.contest.slug}))

    def test_moderation_notification_links_to_the_story(self):
        mods = [n for n in _aidana_notifications()
                if n.kind == 'moderation' and n.story]
        self.assertTrue(mods, 'стаб потерял уведомление о модерации')
        for n in mods:
            with self.subTest(story=n.story.slug):
                # Работа на модерации не публична — вести на неё можно
                # только в авторский кабинет (BR-73).
                self.assertContains(
                    self.response,
                    reverse('core:manage_story', kwargs={'slug': n.story.slug}))

    def test_text_does_not_repeat_the_name_of_its_subject(self):
        """Имя предмета берётся у предмета, а не переписывается литералом.

        Второй литерал разошёлся бы с первым ровно так же, как хранимый
        `Author.works` разошёлся с числом произведений (DEC-40).
        """
        for n in _aidana_notifications():
            if n.kind == 'comment':
                continue  # у комментария `text` — цитата читателя, чужой UGC
            with self.subTest(kind=n.kind):
                if n.contest:
                    self.assertNotIn(n.contest.name.strip('«»'), n.text)
                if n.story:
                    self.assertNotIn(n.story.title, n.text)

    def test_contest_notification_names_the_deadline(self):
        """FR-NOTIF-06: срок считает конкурс, а не текст уведомления."""
        contest = data.contest_by_slug('bolashak-mektebi')
        self.assertTrue(contest.timing_line)
        self.assertContains(self.response, contest.timing_line)


class NotificationsGuest(TestCase):

    def test_guest_sees_gate(self):
        r = self.client.get(reverse('core:notifications'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'кір')


class NotificationsAuthed(TestCase):

    def setUp(self):
        login_as(self.client)
        self.response = self.client.get(reverse('core:notifications'))

    def test_200(self):
        self.assertEqual(self.response.status_code, 200)

    def test_shows_three_buckets(self):
        self.assertContains(self.response, 'Бүгін')
        self.assertContains(self.response, 'Кеше')
        self.assertContains(self.response, 'Өткен аптада')

    def test_renders_all_notifications(self):
        # Уникальные тексты по типам. `like` больше не говорит «ұнатты»:
        # DEC-32 заменил одиночный лайк главы пятью реакциями, и действия
        # с таким именем в интерфейсе нет. Модерация называет исход
        # (`MODERATION_OUTCOME_LABELS`), а не раздел.
        self.assertContains(self.response, 'пікір қалдырды')   # comment
        self.assertContains(self.response, 'реакция қалдырды')  # like
        self.assertContains(self.response, 'саған жазылды')    # follower
        self.assertContains(self.response, 'жаңа бөлім')       # new_chapter
        self.assertContains(self.response, 'Модерацияда')      # moderation, решения нет
        self.assertContains(self.response, 'Байқау')           # contest

    def test_unread_summary_shows_count(self):
        unread = data.unread_count_for_user('aidana')
        self.assertContains(self.response, f'{unread} оқылмаған')

    def test_mark_all_button_present_when_has_items(self):
        self.assertContains(self.response, 'Барлығын оқылды деп белгілеу')

    def test_notification_links_to_actor_profile(self):
        # actor=aygerim_k для первого comment
        self.assertContains(self.response, reverse('core:profile_other', kwargs={'username': 'aygerim_k'}))


class NotificationsEmpty(TestCase):

    def setUp(self):
        login_as_newcomer(self.client, 'lonely_user')

    def test_empty_state_shown(self):
        r = self.client.get(reverse('core:notifications'))
        self.assertContains(r, 'Әзірге хабарлама жоқ')
        # Кнопки «Mark all» не должно быть в пустом стейте
        self.assertNotContains(r, 'Барлығын оқылды')


class ModerationNotificationNamesItsOutcome(TestCase):
    """Исход модерации хранится и назван словом (BR-11).

    Поля не было вовсе: и одобрение, и отказ, и «ещё идёт» приходили
    одной строкой с зелёной галкой. Выводить исход из `Story.status`
    нельзя — статус живёт дальше события: автор правит работу и шлёт её
    снова, и вчерашний отказ начал бы говорить «Модерацияда». Тот же
    довод, по которому DEC-46 хранит `AwardGrant`.
    """

    def setUp(self):
        login_as(self.client)
        self.response = self.client.get(reverse('core:notifications'))

    def test_outcome_is_stored_not_derived(self):
        self.assertIn('outcome',
                      {f.name for f in Notification._meta.get_fields()})

    def test_label_comes_from_the_registry(self):
        for outcome, label in data.MODERATION_OUTCOME_LABELS.items():
            with self.subTest(outcome=outcome or 'pending'):
                n = _notification(kind='moderation', outcome=outcome)
                self.assertEqual(n.outcome_label, label)

    def test_unknown_outcome_says_nothing(self):
        """Лучше пусто, чем чужая подпись: реестр — единственный источник."""
        n = _notification(kind='moderation', outcome='whatever')
        self.assertEqual(n.outcome_label, '')

    def test_both_outcomes_are_rendered(self):
        for outcome in data.MODERATION_OUTCOMES:
            grants = [n for n in _aidana_notifications()
                      if n.kind == 'moderation' and n.outcome == outcome]
            if not grants:
                continue
            with self.subTest(outcome=outcome):
                self.assertContains(
                    self.response, data.MODERATION_OUTCOME_LABELS[outcome])

    def test_negative_outcome_carries_a_reason(self):
        """BR-11: автор узнаёт, что именно исправить.

        Без причины «Толықтыру қажет» сообщает ровно столько же, сколько
        «Қабылданбады», — то есть ничего, кроме факта неудачи.
        """
        negative = [n for n in _aidana_notifications()
                    if n.kind == 'moderation' and n.outcome in ('needs_work', 'rejected')]
        self.assertTrue(negative, 'в стабе нет ни одного отрицательного исхода')
        for n in negative:
            with self.subTest(story=n.story.slug, outcome=n.outcome):
                self.assertTrue(n.text.strip(), 'исход без причины ничего не сообщает')
                self.assertContains(self.response, n.text)

    def test_outcome_does_not_contradict_the_story_status(self):
        """Непринятая работа не может лежать опубликованной."""
        for n in _aidana_notifications():
            if n.kind != 'moderation' or not n.story:
                continue
            if n.outcome not in ('needs_work', 'rejected'):
                continue
            with self.subTest(story=n.story.slug, outcome=n.outcome):
                self.assertFalse(
                    n.story.is_public,
                    'работа не прошла модерацию и при этом публична — '
                    'противоречие в данных')

    def test_return_for_work_is_not_painted_as_an_error(self):
        """docs/13 §13.5: «толықтыру қажет» — приглашение, а не приговор.

        Пока оба отрицательных исхода были одним `rejected`, возврат на
        доработку приходил под пpо́шенным красным `status-error` —
        токеном, подписанным «Отказ и удаление» (DEC-39).
        """
        chip = NotificationIconsFollowTheRegistry.ITEM.read_text(encoding='utf-8')
        branch = chip.split("n.outcome == 'needs_work'", 1)[1].split('{% el', 1)[0]
        self.assertNotIn('status-error', branch)
        self.assertIn('status-warning', branch)

    def test_hard_refusal_keeps_its_own_words_and_colour(self):
        """`rejected` остаётся твёрдым — иначе смягчение стало бы враньём.

        В демо-ленте его нет намеренно: свободной непубличной работы под
        него не осталось, а вешать отказ на ту же работу, которую только
        что попросили доработать, значит противоречить данным. Ветку
        проверяем подменой, как и «событие старше недели».
        """
        Notification.objects.filter(user__username='aidana').delete()
        _notification(username='aidana', kind='moderation', days_ago=2,
                      story=Story.objects.get(slug='aidana-kus'),
                      outcome='rejected', text='Ережеге қайшы келеді.')
        r = self.client.get(reverse('core:notifications'))
        self.assertContains(r, data.MODERATION_OUTCOME_LABELS['rejected'])
        self.assertNotContains(r, data.MODERATION_OUTCOME_LABELS['needs_work'])
        self.assertContains(r, 'status-error')

    def test_three_outcomes_are_distinguishable(self):
        """Ни одна пара исходов не совпадает ни словом, ни цветом."""
        labels = [data.MODERATION_OUTCOME_LABELS[o]
                  for o in data.MODERATION_OUTCOMES]
        self.assertEqual(len(labels), len(set(labels)))

        chip = NotificationIconsFollowTheRegistry.ITEM.read_text(encoding='utf-8')
        # Срез обрывается на следующем `kind`: у `contest` тот же `warning`,
        # и без границы тест ловил бы соседа вместо второго исхода.
        moderation = chip.split("n.kind == 'moderation'", 1)[1].split('{% elif n.kind', 1)[0]
        tokens = re.findall(r'bg-status-([a-z]+)-bg', moderation)
        self.assertEqual(len(tokens), len(set(tokens)),
                         f'два исхода носят один цвет: {tokens}')
        self.assertEqual(len(tokens), len(data.MODERATION_OUTCOMES) + 1,
                         'у какого-то исхода нет своей ветки цвета')

    def test_outcome_only_belongs_to_moderation(self):
        for n in _aidana_notifications():
            if n.kind == 'moderation':
                continue
            with self.subTest(kind=n.kind):
                self.assertEqual(n.outcome, '',
                                 'исход есть только у модерации')


class StoryMetricIsCalledAReaction(TestCase):
    """Метрика произведения — сумма реакций по главам, а не лайки (DEC-32).

    Слово «ұнату» стояло на шести поверхностях: карточка каталога, строка
    кабинета, шапка произведения, «Аптаның кітабы», плитка профиля и
    список глав. Ни одна из них не показывала лайки — все показывали
    `Chapter.likes`, то есть сумму пяти реакций.

    Иконка при этом расходилась на том же числе: `thumbs-up` в трёх
    местах, `heart` в четвёртом. `thumbs-up` вдобавок означает ровно тот
    жест, который DEC-32 убрал.

    **Лайк комментария (BR-31) — другое понятие и остаётся лайком.**
    Читатель действительно нажимает «ұнату» под комментарием; там нет ни
    глав, ни пяти реакций. Тест обязан различать эти два случая, иначе
    следующий проход по «ұнату» сравняет и его.
    """

    SURFACES = [
        ('core:catalog',      {},                        'карточка каталога'),
        ('core:my_stories',   {},                        'строка кабинета'),
        ('core:story_detail', {'slug': 'dalney-berega'}, 'шапка произведения'),
        ('core:home',         {},                        'Аптаның кітабы'),
        ('core:profile_me',   {},                        'плитка профиля'),
    ]

    def setUp(self):
        login_as(self.client)

    def test_no_surface_calls_the_sum_a_like(self):
        for name, kwargs, label in self.SURFACES:
            with self.subTest(surface=label):
                html = self.client.get(reverse(name, kwargs=kwargs)).content.decode()
                # Вырезаем комментарии: их «Ұнату» законен (BR-31).
                without_comments = html.replace('aria-label="Ұнату"', '')
                self.assertNotIn('ұнату', without_comments)
                self.assertNotIn('ұнатты', without_comments)

    def test_comment_keeps_its_like(self):
        """BR-31 не отменён: под комментарием по-прежнему лайк."""
        html = self.client.get(
            reverse('core:story_detail', kwargs={'slug': 'dalney-berega'})).content.decode()
        self.assertIn('aria-label="Ұнату"', html)

    def test_one_glyph_for_one_metric(self):
        """`thumbs-up` означал жест, который DEC-32 убрал."""
        offenders = []
        for path in (TEMPLATES / 'components').glob('*.html'):
            body = path.read_text(encoding='utf-8')
            if 'story.likes' in body and 'thumbs-up' in body:
                offenders.append(path.name)
        for path in (TEMPLATES / 'pages').rglob('*.html'):
            body = path.read_text(encoding='utf-8')
            if 'story.likes' in body and 'thumbs-up' in body:
                offenders.append(path.name)
        self.assertFalse(offenders,
                         f'сумма реакций под иконкой лайка: {offenders}')


class ReactionNotificationDoesNotSayLike(TestCase):
    """После DEC-32 одиночного лайка главы нет — есть пять реакций.

    Уведомление продолжало говорить «ұнатты», описывая действие, которого
    в интерфейсе не осталось. Названия конкретной реакции строка не несёт:
    раскладку «чем зацепило» автор смотрит в самой главе.
    """

    def setUp(self):
        login_as(self.client)
        self.response = self.client.get(reverse('core:notifications'))

    def test_wording_is_neutral(self):
        self.assertContains(self.response, 'реакция қалдырды')
        self.assertNotContains(self.response, 'ұнатты')

    def test_no_single_reaction_is_named(self):
        html = self.response.content.decode()
        for r in data.REACTIONS:
            with self.subTest(reaction=r.slug):
                self.assertNotIn(r.label, html)

    def test_icon_is_the_aggregate_heart_not_the_reaction(self):
        """`heart-filled` после DEC-32 — реакция «Жүрегім», одна из пяти.

        Совокупность в проекте уже подписана контурным `heart`: им
        помечен `Chapter.likes` в списке глав, а это сумма всех пяти.
        """
        chip = NotificationIconsFollowTheRegistry.ITEM.read_text(encoding='utf-8')
        like = chip.split("{% elif n.kind == 'like' %}", 2)[2].split('{% elif', 1)[0]
        self.assertIn('name="heart"', like)
        self.assertNotIn('heart-filled', like)


class NotificationsHeaderFollowsTheState(TestCase):
    """Шапка не говорит о данных, которых на экране нет (DEC-17).

    Она стояла выше ветвления по `page_state`, поэтому в `?state=error`
    страница одновременно сообщала «жүктеу мүмкін болмады» и «4 оқылмаған»
    — с рабочей кнопкой «барлығын оқылды деп белгілеу».
    """

    def setUp(self):
        login_as(self.client)

    def _get(self, state=''):
        url = reverse('core:notifications') + (f'?state={state}' if state else '')
        return self.client.get(url).content.decode()

    def test_content_state_keeps_the_summary(self):
        html = self._get()
        self.assertIn('оқылмаған', html)
        self.assertIn('Барлығын оқылды деп белгілеу', html)

    def test_error_state_drops_summary_and_action(self):
        html = self._get('error')
        self.assertNotIn('Барлығын оқылды деп белгілеу', html)
        self.assertNotIn('оқылмаған.', html)

    def test_loading_state_drops_summary_and_action(self):
        html = self._get('loading')
        self.assertNotIn('Барлығын оқылды деп белгілеу', html)
        self.assertNotIn('оқылмаған.', html)

    def test_heading_survives_every_state(self):
        """Заголовок — часть структуры документа, а не часть данных."""
        for state in ('', 'loading', 'error'):
            with self.subTest(state=state or 'content'):
                self.assertIn('<h1', self._get(state))

    def test_mark_all_posts_somewhere_real(self):
        """`action="#"` без JS отправлял форму в никуда."""
        self.assertNotIn('action="#"', self._get())


class NotificationsRenderFromTheRegistry(TestCase):
    """Секции строит реестр `NOTIF_BUCKETS`, а не три копии блока."""

    def setUp(self):
        login_as(self.client)
        self.response = self.client.get(reverse('core:notifications'))

    def test_sections_follow_the_registry_order(self):
        keys = [s['key'] for s in self.response.context['sections']]
        self.assertEqual(keys, [b for b in data.NOTIF_BUCKETS if keys.count(b)])
        self.assertEqual(keys, sorted(keys, key=data.NOTIF_BUCKETS.index))

    def test_empty_bucket_renders_no_heading(self):
        grouped = data.notifications_for_user('aidana')
        lonely = {b: (items if b == 'today' else []) for b, items in grouped.items()}
        # Патчится фасад: view ходит через `core.data`, а не в `stub_data`.
        with mock.patch.object(data, 'notifications_for_user', return_value=lonely):
            r = self.client.get(reverse('core:notifications'))
        self.assertEqual([s['key'] for s in r.context['sections']], ['today'])
        self.assertNotContains(r, data.NOTIF_BUCKET_LABELS['yesterday'])

    def test_labels_come_from_the_registry(self):
        for s in self.response.context['sections']:
            with self.subTest(bucket=s['key']):
                self.assertEqual(s['label'], data.NOTIF_BUCKET_LABELS[s['key']])

    def test_group_is_a_list(self):
        """`<ul>/<li>`: иначе скринридер не называет число событий в группе."""
        self.assertContains(self.response, '<ul class="flex flex-col gap-3">')


class NotificationIconsFollowTheRegistry(TestCase):
    """Иконку выбирают по значению, а не по наличию формы (docs/04 §4.2).

    Конкурс носил `bookmark-filled` — глиф, который по DEC-09b означает
    активное «сохранено» и стоит на текущей главе и на кнопке «сақталды».
    Модерация носила `check`: галка утверждает «одобрено», хотя событие
    бывает отказом и ожиданием. Лайк носил пару `status-error-*` — токен,
    подписанный в `@theme` как «Отказ и удаление (DEC-39)».
    """

    ITEM = TEMPLATES / 'components' / 'notification_item.html'

    def _chip(self):
        """Блок выбора иконки — без окружающих комментариев.

        Сравнивать с текстом всего файла нельзя: объяснение правки само
        называет глифы, от которых она уводит.
        """
        body = self.ITEM.read_text(encoding='utf-8')
        return body.split('{% endcomment %}\n    <span class="grid', 1)[1].split('</span>', 1)[0]

    def _rendered(self):
        login_as(self.client)
        return self.client.get(reverse('core:notifications')).content.decode()

    def test_contest_wears_the_trophy(self):
        self.assertIn('icon-trophy', self._rendered())
        self.assertNotIn('bookmark', self._chip(),
                         'залитая закладка по DEC-09b значит «сохранено»')

    def test_moderation_wears_the_shield(self):
        self.assertIn('icon-shield', self._rendered())
        self.assertNotIn('name="check"', self._chip(),
                         'галка утверждает «одобрено» независимо от исхода')

    def test_like_does_not_borrow_the_error_token(self):
        like = self._chip().split("n.kind == 'like'", 1)[1].split('{% elif', 1)[0]
        self.assertNotIn('status-error', like,
                         'красный на лайке — это «ошибка», а не «сердце»')

    def test_every_kind_still_has_an_icon(self):
        """Правка иконок не должна оставить тип без глифа."""
        chip = self._chip()
        for kind in data.NOTIF_KINDS:
            with self.subTest(kind=kind):
                self.assertIn(f"n.kind == '{kind}'", chip)


class UnreadIsVisibleAndAnnounced(TestCase):
    """Непрочитанное отличимо и глазами, и на слух.

    Оба признака были сломаны одновременно, и страница выглядела рабочей.
    Фон задавался двумя классами на одном элементе — `bg-white` и
    `bg-slate-50/60`; побеждает та утилита, что стоит позже в собранном
    CSS, а `.bg-white` идёт после. Подсветка не появлялась никогда.
    Точка же несла `aria-label` на `<span>` без роли — атрибут, который
    скринридер игнорирует. Для незрячего непрочитанных не существовало.
    """

    ITEM = TEMPLATES / 'components' / 'notification_item.html'

    def test_background_is_exclusive_not_layered(self):
        body = self.ITEM.read_text(encoding='utf-8')
        opening = body.split('<article', 1)[1].split('>', 1)[0]
        self.assertNotIn(
            'bg-white', opening.split('{% if n.read %}')[0],
            'фон непрочитанного перекрывается безусловным bg-white: две '
            'bg-утилиты на одном элементе разрешает не порядок в class, '
            'а порядок в собранном CSS',
        )
        self.assertIn('{% if n.read %}bg-white{% else %}', opening)

    def test_unread_dot_is_announced_by_text(self):
        login_as(self.client)
        html = self.client.get(reverse('core:notifications')).content.decode()
        self.assertIn('<span class="sr-only">оқылмаған</span>', html)
        self.assertNotIn('aria-label="оқылмаған"', html)

    def test_read_notification_carries_no_marker(self):
        """Отметка стоит только у непрочитанного — иначе она ничего не значит."""
        unread = data.unread_count_for_user('aidana')
        login_as(self.client)
        html = self.client.get(reverse('core:notifications')).content.decode()
        self.assertEqual(html.count('<span class="sr-only">оқылмаған</span>'), unread)


class NotificationsReachableWithoutDesktopHeader(TestCase):
    """Раздел открывается с телефона (FR-NOTIF-02).

    Единственная ссылка на уведомления лежала внутри `hidden … md:flex` —
    десктопного кластера шапки. В mobile bottom nav уведомлений нет
    намеренно (07 §7.6), профиль на них не ссылается, и на телефоне
    раздел не открывался ниоткуда: страница существовала, входа не было.

    Проверка идёт обходом DOM, а не поиском подстроки: важно не то, что
    ссылка есть в разметке, а то, что она лежит вне поддерева, скрытого
    до `md`. Конкретная вёрстка мобильного кластера при этом не
    закрепляется — тест утверждает достижимость, а не расположение.
    """

    VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
            'link', 'meta', 'source', 'track', 'wbr'}

    # `hidden` + возврат к display на брейкпоинте = «только с этой ширины».
    DESKTOP_ONLY = re.compile(r'\bhidden\b')
    SHOWN_AT = re.compile(r'\b(sm|md|lg|xl|2xl):(flex|block|grid|inline-flex|inline-block|table)\b')

    class _Scan(HTMLParser):
        def __init__(self, void, is_desktop_only, href):
            super().__init__(convert_charrefs=True)
            self.void = void
            self.is_desktop_only = is_desktop_only
            self.href = href
            self.stack = []        # [(tag, скрыт ли до брейкпоинта)]
            self.reachable = False

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            hidden = self.is_desktop_only(attrs.get('class') or '')
            buried = hidden or any(h for _, h in self.stack)
            if tag == 'a' and attrs.get('href') == self.href and not buried:
                self.reachable = True
            if tag not in self.void:
                self.stack.append((tag, buried))

        def handle_endtag(self, tag):
            for i in range(len(self.stack) - 1, -1, -1):
                if self.stack[i][0] == tag:
                    del self.stack[i:]
                    return

    def _desktop_only(self, cls):
        return bool(self.DESKTOP_ONLY.search(cls) and self.SHOWN_AT.search(cls))

    def _reachable_on(self, url):
        parser = self._Scan(self.VOID, self._desktop_only,
                            reverse('core:notifications'))
        parser.feed(self.client.get(url).content.decode())
        return parser.reachable

    def test_link_survives_outside_the_desktop_cluster(self):
        login_as(self.client)
        for name in ('core:home', 'core:library', 'core:profile_me'):
            with self.subTest(page=name):
                self.assertTrue(
                    self._reachable_on(reverse(name)),
                    'ссылка на уведомления лежит только внутри поддерева, '
                    'скрытого до брейкпоинта: на телефоне раздел не открыть',
                )

    def test_the_guard_actually_sees_the_desktop_cluster(self):
        """Страховка от теста, который проходит по недосмотру.

        Если бы `_desktop_only` не срабатывал ни на чём, предыдущий тест
        был бы зелёным при любой вёрстке.
        """
        self.assertTrue(self._desktop_only('ml-auto hidden items-center gap-6 md:flex'))
        self.assertFalse(self._desktop_only('ml-auto -mr-2 flex items-center md:hidden'))

    def test_guest_gets_no_bell(self):
        """Гостю считать нечего — колокольчик без сессии не рендерится."""
        self.assertFalse(self._reachable_on(reverse('core:home')))


class HeaderUnreadBadge(TestCase):

    def test_authed_aidana_sees_unread_badge(self):
        login_as(self.client)
        r = self.client.get(reverse('core:home'))
        # Бейдж непрочитанных — из data.unread_count_for_user
        self.assertContains(r, 'оқылмаған')

    def test_authed_no_notifs_no_badge_number(self):
        login_as_newcomer(self.client, 'no_notifs_user')
        r = self.client.get(reverse('core:home'))
        # У этого юзера 0 — текст «оқылмаған» в aria-label не должен появиться
        self.assertNotContains(r, 'оқылмаған')

    def test_guest_no_bell_at_all(self):
        r = self.client.get(reverse('core:home'))
        self.assertNotContains(r, 'Хабарламалар (')
