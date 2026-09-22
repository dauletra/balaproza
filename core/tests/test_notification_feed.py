"""NOTIF — лента событий: что в ней видно и куда она ведёт.

Читающая сторона уведомлений. Пишущая — `test_notifications.py`: там
проверяется, что событие вообще заводится и кому, здесь — что человек
его увидит, прочтёт и попадёт по нему туда, куда обещано.

Два правила держат почти весь файл: **хранится момент, выводится
подпись** (BR-70a) и **уведомление ведёт к своему предмету и не
переписывает его имя** (BR-72a).
"""


import re
from datetime import timedelta
from html.parser import HTMLParser
from unittest import mock

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from core import data
from core.domain.contests import timing_line
from core.models import Notification, Story, User
from core.templatetags.qazaqnovel import outcome_label
from core.tests.base import TEMPLATES, TestCase, login_as, login_as_newcomer, user




NOTIFICATION_ITEM = TEMPLATES / 'components' / 'notification_item.html'


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


# ───────────────────────────────────────────────────────────────────────
# NOTIF — лента событий автора и бейдж непрочитанного
# ───────────────────────────────────────────────────────────────────────

class NotificationFeed(TestCase):

    def setUp(self):
        super().setUp()
        login_as(self.client)
        self.response = self.client.get(reverse('core:notifications'))

    def test_the_buckets_come_from_the_registry_and_match_the_data(self):
        grouped = data.notifications_for_user(user('aidana'))
        items = _aidana_notifications()
        for bucket in data.NOTIF_BUCKETS:
            with self.subTest(bucket=bucket):
                self.assertEqual(len(grouped[bucket]),
                                 sum(1 for n in items if n.bucket == bucket))
                self.assertTrue(grouped[bucket],
                                'у aidana должен быть непустым каждый бакет')
        for bucket in data.notifications_for_user(user('no-such-user')).values():
            self.assertEqual(bucket, [])
        # Секции строит реестр, а не три копии блока.
        keys = [s['key'] for s in self.response.context['sections']]
        self.assertEqual(keys, sorted(keys, key=data.NOTIF_BUCKETS.index))
        for section in self.response.context['sections']:
            with self.subTest(section=section['key']):
                self.assertEqual(section['label'],
                                 data.NOTIF_BUCKET_LABELS[section['key']])
        # `<ul>/<li>`: иначе скринридер не назовёт число событий в группе.
        self.assertContains(self.response, '<ul class="flex flex-col gap-3">')

    def test_an_empty_bucket_renders_no_heading(self):
        grouped = data.notifications_for_user(user('aidana'))
        lonely = {b: (items if b == 'today' else [])
                  for b, items in grouped.items()}
        # Патчится фасад: view ходит через `core.data`.
        with mock.patch.object(data, 'notifications_for_user',
                               return_value=lonely):
            response = self.client.get(reverse('core:notifications'))
        self.assertEqual([s['key'] for s in response.context['sections']],
                         ['today'])
        self.assertNotContains(response, data.NOTIF_BUCKET_LABELS['yesterday'])

    def test_every_kind_gets_its_own_words(self):
        for bucket in ('Бүгін', 'Кеше', 'Өткен аптада'):
            with self.subTest(bucket=bucket):
                self.assertContains(self.response, bucket)
        # `like` больше не говорит «ұнатты»: DEC-32 заменил одиночный лайк
        # главы пятью реакциями. Модерация называет исход, а не раздел.
        for words in ('пікір қалдырды', 'реакция қалдырды', 'саған жазылды',
                      'жаңа бөлім', 'Модерацияда', 'Байқау'):
            with self.subTest(words=words):
                self.assertContains(self.response, words)
        for notification in _aidana_notifications():
            with self.subTest(kind=notification.kind):
                self.assertIn(notification.kind, data.NOTIF_KINDS)
        self.assertContains(self.response, reverse(
            'core:profile_other', kwargs={'username': 'aygerim_k'}))

    def test_the_summary_counts_the_unread_and_offers_the_button(self):
        items = _aidana_notifications()
        unread = sum(1 for n in items if not n.read and n.bucket)
        self.assertGreater(unread, 0)
        self.assertEqual(data.unread_count_for_user(user('aidana')), unread)
        self.assertEqual(data.unread_count_for_user(user('ghost')), 0)
        self.assertContains(self.response, f'{unread} оқылмаған')
        self.assertContains(self.response, 'Барлығын оқылды деп белгілеу')

    def test_a_guest_gets_a_gate_and_a_newcomer_gets_an_empty_state(self):
        self.client.logout()
        gate = self.client.get(reverse('core:notifications'))
        self.assertEqual(gate.status_code, 200)
        self.assertContains(gate, 'кір')

        login_as_newcomer(self.client, 'lonely_user')
        empty = self.client.get(reverse('core:notifications'))
        self.assertContains(empty, 'Әзірге хабарлама жоқ')
        self.assertNotContains(empty, 'Барлығын оқылды')

    @override_settings(DEBUG=True)
    def test_the_header_says_nothing_about_data_that_is_not_on_screen(self):
        """DEC-17: шапка стояла выше ветвления по `page_state`, и в
        `?state=error` страница сообщала «жүктеу мүмкін болмады» и
        «4 оқылмаған» — с рабочей кнопкой «оқылды деп белгілеу».

        `DEBUG=True` обязателен: сами леса закрыты им (A5), и на живом
        сайте `?state=` ничего не меняет.
        """
        html = self.response.content.decode()
        self.assertIn('оқылмаған', html)
        self.assertIn('Барлығын оқылды деп белгілеу', html)
        self.assertNotIn('action="#"', html)   # без JS форма уходила в никуда
        for state in ('loading', 'error'):
            with self.subTest(state=state):
                broken = self.client.get(
                    reverse('core:notifications') + f'?state={state}'
                ).content.decode()
                self.assertNotIn('Барлығын оқылды деп белгілеу', broken)
                self.assertNotIn('оқылмаған.', broken)
                # Заголовок — часть структуры документа, а не данных.
                self.assertIn('<h1', broken)


class NotificationTimeIsDerived(TestCase):
    """Время выводится из момента, а не хранится строкой (BR-70a).

    Хранимые `when="5 күн бұрын"` и `bucket="past_week"` устаревали на
    следующий день — тот же класс ошибки, что `days_left=12` до DEC-45,
    только незаметнее: лента выглядит правдоподобной всегда.
    """

    def test_neither_the_label_nor_the_bucket_is_a_column(self):
        stored = {f.name for f in Notification._meta.get_fields()}
        for gone in ('when', 'bucket'):
            with self.subTest(field=gone):
                self.assertNotIn(gone, stored,
                                 f'`{gone}` снова стало полем — хранимое производное')

    def test_the_bucket_follows_the_calendar(self):
        for days, expected in {0: 'today', 1: 'yesterday', 2: 'past_week',
                               7: 'past_week', 8: '', 400: ''}.items():
            with self.subTest(days=days):
                self.assertEqual(
                    _notification(kind='like', days_ago=days).bucket, expected)

    def test_older_than_a_week_is_neither_shown_nor_counted(self):
        """Групп три; четвёртой «раньше» в FR-NOTIF-01 нет.

        Значит, событие старше недели в ленту не попадает — и в бейдж
        тоже, иначе шапка звала бы на страницу, где его нет.
        """
        _notification(kind='like', days_ago=30)
        grouped = data.notifications_for_user(user('ghost'))
        self.assertEqual([], [n for b in grouped.values() for n in b])
        self.assertEqual(0, data.unread_count_for_user(user('ghost')))

    def test_the_wording_of_kk_ago(self):
        self.assertEqual(data.kk_ago(0, 2), '2 сағат бұрын')
        self.assertEqual(data.kk_ago(0), 'бүгін')
        self.assertEqual(data.kk_ago(1), 'кеше')
        self.assertEqual(data.kk_ago(5), '5 күн бұрын')
        self.assertEqual(data.kk_ago(60), '2 ай бұрын')
        self.assertEqual(data.kk_ago(800), '2 жыл бұрын')
        # «26 сағат бұрын» человек переводит в дни сам — короче «кеше».
        self.assertEqual(data.kk_ago(1, 26), 'кеше')

    def test_the_freshest_comes_first_inside_a_bucket(self):
        """Порядок объявления в данных — не порядок ленты: сегодняшние
        события шли «2 сағат · 4 сағат · 9 сағат · 6 сағат»."""
        for bucket in data.notifications_for_user(user('aidana')).values():
            moments = [n.created_at for n in bucket]
            self.assertEqual(moments, sorted(moments, reverse=True))


class NotificationsLeadSomewhere(TestCase):
    """Уведомление ведёт к своему предмету (FR-NOTIF-05, BR-72a).

    Конкурсное событие знало о конкурсе только по имени внутри `text`
    и потому не вело никуда: прочитав «шорт-лист басталды», автор шёл
    искать конкурс через меню.
    """

    def setUp(self):
        super().setUp()
        login_as(self.client)
        self.response = self.client.get(reverse('core:notifications'))

    def _opens_at(self, notification):
        """Куда приводит клик по уведомлению.

        Ссылка ведёт не прямо на предмет, а через `notification_open`: по
        BR-71 метку «непрочитано» снимает именно открытие. Проверяется
        поэтому конечная точка, а не строка адреса в разметке, — заодно
        это ловит и саму таблицу соответствий `notification_href`.
        """
        url = reverse('core:notification_open', kwargs={'pk': notification.pk})
        self.assertContains(self.response, url)
        return self.client.get(url)

    def test_each_kind_lands_on_its_own_subject(self):
        contests = [n for n in _aidana_notifications() if n.kind == 'contest']
        self.assertTrue(contests, 'корпус потерял конкурсные уведомления')
        for notification in contests:
            with self.subTest(contest=notification.contest.slug):
                self.assertRedirects(
                    self._opens_at(notification),
                    reverse('core:contest_detail',
                            kwargs={'slug': notification.contest.slug}))

        moderation = [n for n in _aidana_notifications()
                      if n.kind == 'moderation' and n.story]
        self.assertTrue(moderation, 'корпус потерял уведомление о модерации')
        for notification in moderation:
            with self.subTest(story=notification.story.slug):
                # Работа на модерации не публична — вести на неё можно
                # только в авторский кабинет (BR-73).
                self.assertRedirects(
                    self._opens_at(notification),
                    reverse('core:manage_story',
                            kwargs={'slug': notification.story.slug}))

    def test_the_text_does_not_repeat_the_name_of_its_subject(self):
        """Имя предмета берётся у предмета, а не переписывается литералом.

        Второй литерал разошёлся бы с первым ровно так же, как хранимый
        `Author.works` разошёлся с числом произведений (DEC-40).
        """
        for notification in _aidana_notifications():
            if notification.kind == 'comment':
                continue  # у комментария `text` — цитата читателя, чужой UGC
            with self.subTest(kind=notification.kind):
                if notification.contest:
                    self.assertNotIn(notification.contest.name.strip('«»'),
                                     notification.text)
                if notification.story:
                    self.assertNotIn(notification.story.title, notification.text)

    def test_the_deadline_is_counted_by_the_contest(self):
        """FR-NOTIF-06: срок считает конкурс, а не текст уведомления."""
        contest = data.contest_by_slug('bolashak-mektebi')
        line = timing_line(contest.phase, contest.opens_on,
                           contest.closes_on, contest.results_on)
        self.assertTrue(line)
        self.assertContains(self.response, line)


class ModerationNotificationNamesItsOutcome(TestCase):
    """Исход модерации хранится и назван словом (BR-11).

    Поля не было вовсе: и одобрение, и отказ, и «ещё идёт» приходили
    одной строкой с зелёной галкой. Выводить исход из `Story.status`
    нельзя — статус живёт дальше события: автор правит работу и шлёт её
    снова, и вчерашний отказ начал бы говорить «Модерацияда». Тот же
    довод, по которому DEC-46 хранит `AwardGrant`.
    """

    def setUp(self):
        super().setUp()
        login_as(self.client)
        self.response = self.client.get(reverse('core:notifications'))

    def test_the_outcome_is_stored_and_labelled_by_the_registry(self):
        self.assertIn('outcome',
                      {f.name for f in Notification._meta.get_fields()})
        for outcome, label in data.MODERATION_OUTCOME_LABELS.items():
            with self.subTest(outcome=outcome or 'pending'):
                self.assertEqual(
                    outcome_label(_notification(kind='moderation', outcome=outcome)),
                    label)
        # Лучше пусто, чем чужая подпись: реестр — единственный источник.
        self.assertEqual(
            outcome_label(_notification(kind='moderation', outcome='whatever')), '')

    def test_the_outcome_belongs_to_moderation_and_agrees_with_the_story(self):
        for notification in _aidana_notifications():
            if notification.kind != 'moderation':
                with self.subTest(kind=notification.kind):
                    self.assertEqual(notification.outcome, '',
                                     'исход есть только у модерации')
                continue
            if not notification.story or notification.outcome not in (
                    'needs_work', 'rejected'):
                continue
            with self.subTest(story=notification.story.slug,
                              outcome=notification.outcome):
                # Непринятая работа не может лежать опубликованной.
                self.assertFalse(notification.story.is_public,
                                 'работа не прошла модерацию и при этом публична')

    def test_a_negative_outcome_carries_a_reason(self):
        """BR-11: автор узнаёт, что именно исправить.

        Без причины «Толықтыру қажет» сообщает ровно столько же, сколько
        «Қабылданбады», — то есть ничего, кроме факта неудачи.
        """
        negative = [n for n in _aidana_notifications()
                    if n.kind == 'moderation'
                    and n.outcome in ('needs_work', 'rejected')]
        self.assertTrue(negative, 'в корпусе нет ни одного отрицательного исхода')
        for notification in negative:
            with self.subTest(story=notification.story.slug):
                self.assertTrue(notification.text.strip(),
                                'исход без причины ничего не сообщает')
                self.assertContains(self.response, notification.text)
                self.assertContains(
                    self.response,
                    data.MODERATION_OUTCOME_LABELS[notification.outcome])

    def test_the_three_outcomes_are_distinguishable_by_word_and_colour(self):
        labels = [data.MODERATION_OUTCOME_LABELS[o]
                  for o in data.MODERATION_OUTCOMES]
        self.assertEqual(len(labels), len(set(labels)))

        chip = NOTIFICATION_ITEM.read_text(encoding='utf-8')
        # Срез обрывается на следующем `kind`: у `contest` тот же `warning`,
        # и без границы тест ловил бы соседа вместо второго исхода.
        moderation = chip.split("n.kind == 'moderation'", 1)[1].split(
            '{% elif n.kind', 1)[0]
        tokens = re.findall(r'bg-status-([a-z]+)-bg', moderation)
        self.assertEqual(len(tokens), len(set(tokens)),
                         f'два исхода носят один цвет: {tokens}')
        self.assertEqual(len(tokens), len(data.MODERATION_OUTCOMES) + 1,
                         'у какого-то исхода нет своей ветки цвета')

        # docs/ui.md: «толықтыру қажет» — приглашение, а не приговор.
        # Пока оба отрицательных исхода были одним `rejected`, возврат на
        # доработку приходил под красным `status-error` — токеном,
        # подписанным «Отказ и удаление» (DEC-39).
        branch = chip.split("n.outcome == 'needs_work'", 1)[1].split('{% el', 1)[0]
        self.assertNotIn('status-error', branch)
        self.assertIn('status-warning', branch)

    def test_a_hard_refusal_keeps_its_own_words_and_colour(self):
        """`rejected` остаётся твёрдым — иначе смягчение стало бы враньём.

        В демо-ленте его нет намеренно: свободной непубличной работы под
        него не осталось, а вешать отказ на ту же работу, которую только
        что попросили доработать, значит противоречить данным.
        """
        Notification.objects.filter(user__username='aidana').delete()
        _notification(username='aidana', kind='moderation', days_ago=2,
                      story=Story.objects.get(slug='aidana-kus'),
                      outcome='rejected', text='Ережеге қайшы келеді.')
        response = self.client.get(reverse('core:notifications'))
        self.assertContains(response, data.MODERATION_OUTCOME_LABELS['rejected'])
        self.assertNotContains(response,
                               data.MODERATION_OUTCOME_LABELS['needs_work'])
        self.assertContains(response, 'status-error')


class NotificationChipFollowsTheRegistry(TestCase):
    """Иконку выбирают по значению, а не по наличию формы (docs/ui.md).

    Конкурс носил `bookmark-filled` — глиф, который по DEC-09b означает
    активное «сохранено» и стоит на текущей главе и на кнопке «сақталды».
    Модерация носила `check`: галка утверждает «одобрено», хотя событие
    бывает отказом и ожиданием. Лайк носил пару `status-error-*` — токен,
    подписанный в `@theme` как «Отказ и удаление (DEC-39)».
    """

    def setUp(self):
        super().setUp()
        login_as(self.client)

    def _chip(self):
        """Блок выбора иконки — без окружающих комментариев.

        Сравнивать с текстом всего файла нельзя: объяснение правки само
        называет глифы, от которых она уводит.
        """
        body = NOTIFICATION_ITEM.read_text(encoding='utf-8')
        return body.split('{% endcomment %}\n    <span class="grid',
                          1)[1].split('</span>', 1)[0]

    def test_each_kind_wears_the_glyph_that_means_it(self):
        chip = self._chip()
        html = self.client.get(reverse('core:notifications')).content.decode()
        self.assertIn('icon-trophy', html)
        self.assertNotIn('bookmark', chip,
                         'залитая закладка по DEC-09b значит «сохранено»')
        self.assertIn('icon-shield', html)
        self.assertNotIn('name="check"', chip,
                         'галка утверждает «одобрено» независимо от исхода')
        for kind in data.NOTIF_KINDS:
            with self.subTest(kind=kind):
                self.assertIn(f"n.kind == '{kind}'", chip)

    def test_the_reaction_borrows_neither_the_error_token_nor_a_single_face(self):
        """`heart-filled` после DEC-32 — реакция «Жүрегім», одна из пяти.

        Совокупность в проекте уже подписана контурным `heart`: им помечен
        `Chapter.likes` в списке глав, а это сумма всех пяти.
        """
        chip = self._chip()
        # Веток у `like` две — цвет и глиф; берём каждую отдельно.
        colour = chip.split("n.kind == 'like'", 1)[1].split('{% elif', 1)[0]
        self.assertNotIn('status-error', colour,
                         'красный на лайке — это «ошибка», а не «сердце»')
        glyph = chip.split("{% elif n.kind == 'like' %}", 2)[2].split('{% elif', 1)[0]
        self.assertIn('name="heart"', glyph)
        self.assertNotIn('heart-filled', glyph)

        response = self.client.get(reverse('core:notifications'))
        self.assertContains(response, 'реакция қалдырды')
        self.assertNotContains(response, 'ұнатты')
        html = response.content.decode()
        for reaction in data.REACTIONS:
            with self.subTest(reaction=reaction.slug):
                self.assertNotIn(reaction.label, html)

    def test_unread_is_visible_and_announced(self):
        """Оба признака были сломаны одновременно, и страница выглядела
        рабочей. Фон задавался двумя классами на одном элементе —
        `bg-white` и `bg-slate-50/60`; побеждает та утилита, что стоит
        позже в собранном CSS, а `.bg-white` идёт после. Точка же несла
        `aria-label` на `<span>` без роли — атрибут, который скринридер
        игнорирует. Для незрячего непрочитанных не существовало.
        """
        body = NOTIFICATION_ITEM.read_text(encoding='utf-8')
        opening = body.split('<article', 1)[1].split('>', 1)[0]
        self.assertNotIn(
            'bg-white', opening.split('{% if n.read %}')[0],
            'фон непрочитанного перекрывается безусловным bg-white: две '
            'bg-утилиты на одном элементе разрешает не порядок в class, '
            'а порядок в собранном CSS')
        self.assertIn('{% if n.read %}bg-white{% else %}', opening)

        html = self.client.get(reverse('core:notifications')).content.decode()
        marker = '<span class="sr-only">оқылмаған</span>'
        self.assertIn(marker, html)
        self.assertNotIn('aria-label="оқылмаған"', html)
        # Отметка стоит только у непрочитанного — иначе она ничего не значит.
        self.assertEqual(html.count(marker), data.unread_count_for_user(user('aidana')))


class ReadingANotificationClearsIt(TestCase):
    """«Непрочитано» снимает открытие уведомления (BR-71).

    Метку не выставлял никто, кроме сида: колокольчик в шапке навсегда
    показывал число из демо-данных, а кнопка «Барлығын оқылды деп
    белгілеу» отвечала тостом «(демо)».
    """

    def setUp(self):
        super().setUp()
        login_as(self.client)
        self.unread = [n for n in _aidana_notifications() if not n.read]
        self.assertTrue(self.unread, 'корпус потерял непрочитанные')

    def _badge(self):
        return data.unread_count_for_user(user('aidana'))

    def _open(self, notification):
        return self.client.get(
            reverse('core:notification_open', kwargs={'pk': notification.pk}))

    def test_opening_one_clears_one_and_only_once(self):
        before = self._badge()
        self._open(self.unread[0])
        self.assertTrue(Notification.objects.get(pk=self.unread[0].pk).read)
        self.assertEqual(self._badge(), before - 1)
        self._open(self.unread[0])
        self.assertEqual(self._badge(), before - 1)

    def test_the_feed_itself_clears_nothing(self):
        """Строка, погасшая раньше, чем её прочли, — это ровно то
        состояние, ради которого бейдж и заводился."""
        before = self._badge()
        self.client.get(reverse('core:notifications'))
        self.assertEqual(self._badge(), before)

    def test_mark_all_needs_a_post_and_then_takes_the_button_away(self):
        before = self._badge()
        self.client.get(reverse('core:notifications_read_all'))
        self.assertEqual(self._badge(), before)
        self.client.post(reverse('core:notifications_read_all'))
        self.assertEqual(self._badge(), 0)
        self.assertNotContains(self.client.get(reverse('core:notifications')),
                               'Барлығын оқылды деп белгілеу')

    def test_nobody_clears_a_feed_that_is_not_theirs(self):
        """`user` в фильтре — закрытая дверь, а не удобство."""
        before = self._badge()
        target = self.unread[0]
        self.client.logout()
        self.client.post(reverse('core:notifications_read_all'))
        self._open(target)
        self.assertEqual(self._badge(), before)

        login_as(self.client, 'bekzhan_t')
        self._open(target)
        self.assertFalse(Notification.objects.get(pk=target.pk).read)


class NotificationsReachableWithoutDesktopHeader(TestCase):
    """Раздел открывается с телефона (FR-NOTIF-02).

    Единственная ссылка на уведомления лежала внутри `hidden … md:flex` —
    десктопного кластера шапки. В mobile bottom nav уведомлений нет
    намеренно, профиль на них не ссылается, и на телефоне
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
    SHOWN_AT = re.compile(
        r'\b(sm|md|lg|xl|2xl):(flex|block|grid|inline-flex|inline-block|table)\b')

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

    def test_the_link_survives_outside_the_desktop_cluster(self):
        login_as(self.client)
        for name in ('core:home', 'core:library', 'core:profile_me'):
            with self.subTest(page=name):
                self.assertTrue(
                    self._reachable_on(reverse(name)),
                    'ссылка на уведомления лежит только внутри поддерева, '
                    'скрытого до брейкпоинта: на телефоне раздел не открыть')

    def test_the_guard_actually_sees_the_desktop_cluster(self):
        """Страховка от теста, который проходит по недосмотру.

        Если бы `_desktop_only` не срабатывал ни на чём, предыдущий тест
        был бы зелёным при любой вёрстке.
        """
        self.assertTrue(
            self._desktop_only('ml-auto hidden items-center gap-6 md:flex'))
        self.assertFalse(
            self._desktop_only('ml-auto -mr-2 flex items-center md:hidden'))

    def test_the_badge_appears_only_when_there_is_something_to_count(self):
        login_as(self.client)
        self.assertContains(self.client.get(reverse('core:home')), 'оқылмаған')
        login_as_newcomer(self.client, 'no_notifs_user')
        self.assertNotContains(self.client.get(reverse('core:home')), 'оқылмаған')
        # Гостю считать нечего — колокольчик без сессии не рендерится.
        self.client.logout()
        home = self.client.get(reverse('core:home'))
        self.assertNotContains(home, 'Хабарламалар (')
        self.assertFalse(self._reachable_on(reverse('core:home')))
