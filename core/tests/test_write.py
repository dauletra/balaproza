"""WRITE: авторский кабинет — my_stories, new, manage, settings, chapter_editor."""

import re
from dataclasses import replace

from django.core.files.uploadedfile import SimpleUploadedFile
from django.template.loader import render_to_string
from django.test import Client, TestCase
from django.urls import reverse

from core import data
from core.models import Chapter, Story, Tag
from core.tests.base import login_as, login_as_newcomer
from core.templatetags.balaproza import spaced


# ───────────────────────── Кабинет: my_stories_of / writer_stats ─────────

class MyStoriesHelper(TestCase):

    def test_my_stories_filters_by_username(self):
        result = data.my_stories_of('aidana')
        self.assertEqual(len(result), 5)
        for s in result:
            self.assertEqual(s.author.username, 'aidana')

    def test_my_stories_unknown_user_is_empty(self):
        self.assertEqual(data.my_stories_of('no-such-user'), [])

    def test_writer_stats_aggregates_correctly(self):
        stats = data.writer_stats('aidana')
        mine = data.my_stories_of('aidana')
        self.assertEqual(stats['total'], len(mine))
        self.assertEqual(stats['views'], sum(s.views for s in mine))
        self.assertEqual(stats['likes'], sum(s.likes for s in mine))
        self.assertEqual(stats['followers'], data.author_by_username('aidana').followers)

    def test_writer_stats_counts_statuses(self):
        stats = data.writer_stats('aidana')
        self.assertEqual(stats['published'], 2)
        self.assertEqual(stats['on_moderation'], 1)
        self.assertEqual(stats['ongoing'], 1)


# ───────────────────────── My stories ─────────────────────────

class MyStoriesGuest(TestCase):

    def test_guest_sees_gate(self):
        r = self.client.get(reverse('core:my_stories'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'тек авторланғандарға')
        # Стори не выводим
        self.assertNotContains(r, 'Таң алдында')


class MyStoriesAuthedHasItems(TestCase):

    def setUp(self):
        login_as(self.client)
        self.response = self.client.get(reverse('core:my_stories'))

    def test_200(self):
        self.assertEqual(self.response.status_code, 200)

    def test_lists_every_story(self):
        for s in data.my_stories_of('aidana'):
            with self.subTest(story=s.slug):
                self.assertContains(self.response, s.title)

    def test_shows_status_badges_for_each(self):
        # У «aidana» три статуса: два one-shot'а Жарияланды, сериал
        # Жазылып жатыр и один на модерации. «Аяқталды» у неё нет —
        # после DEC-37 его носит только дописанный сериал, а её единственный
        # ещё пишется. Все пять бейджей показывает /_design/components/.
        self.assertContains(self.response, 'Жарияланды')
        self.assertContains(self.response, 'Жазылып жатыр')
        self.assertContains(self.response, 'Модерацияда')

    def test_does_not_show_empty_state(self):
        self.assertNotContains(self.response, 'Әлі шығарма жоқ')

    def test_each_card_links_to_manage(self):
        for s in data.my_stories_of('aidana'):
            with self.subTest(story=s.slug):
                self.assertContains(
                    self.response,
                    reverse('core:manage_story', kwargs={'slug': s.slug}),
                )

    def test_has_new_story_cta(self):
        self.assertContains(self.response, reverse('core:new_story'))


class MyStoriesAuthedEmpty(TestCase):
    """Если у пользователя нет произведений (например другой username)."""

    def setUp(self):
        login_as_newcomer(self.client, 'no-such-user', name='Тест')
        self.response = self.client.get(reverse('core:my_stories'))

    def test_shows_empty_state(self):
        self.assertContains(self.response, 'Әлі шығарма жоқ')

    def test_empty_state_has_cta(self):
        # CTA-кнопка в empty state
        self.assertContains(self.response, 'Жаңа шығарма жазу')
        self.assertContains(self.response, reverse('core:new_story'))


class DraftBadgeIsNotAnError(TestCase):
    """DEC-39: «Жоба» — нейтральный бейдж, а не красный.

    `NotPublished` — дефолт нового произведения (BR-10), то есть первое, что
    видит автор, создав работу. Красным помечено то, что действительно
    означает отказ или необратимое действие, а не нормальный этап пути.
    """

    def test_draft_is_neutral(self):
        html = render_to_string('components/status_badge.html', {'key': 'NotPublished'})
        self.assertIn('Жоба', html)
        self.assertIn('bg-slate-100', html)
        self.assertNotIn('status-error', html)

    def test_rejection_still_reads_as_error(self):
        html = render_to_string(
            'components/badge.html', {'kind': 'error', 'label': 'Қабылданбады'})
        self.assertIn('status-error', html)

    def test_other_statuses_keep_their_semantics(self):
        expected = {
            'Published':    'status-published',
            'OnProcess':    'status-warning',
            'Completed':    'status-info',
            'OnModeration': 'status-attention',
        }
        for key, token in expected.items():
            with self.subTest(status=key):
                html = render_to_string('components/status_badge.html', {'key': key})
                self.assertIn(token, html)


class SingleStoryTextButtonOpensExistingText(TestCase):
    """«Мәтін» у одночастного ведёт в его главу, а не в пустой редактор.

    Обе ветки кнопки указывали на `chapter_new`. У `single` глава ровно одна,
    и автор, нажав «Мәтін», получал чистый редактор: сохранение завело бы
    вторую главу у книги, у которой текст один по определению.
    """

    SINGLE_WITH_TEXT = 'aidana-koshe'
    SERIAL = 'aidana-tan'

    def setUp(self):
        login_as(self.client)
        self.response = self.client.get(reverse('core:my_stories'))

    def _edit_url(self, slug, number):
        return reverse('core:chapter_edit', kwargs={'slug': slug, 'chapter': number})

    def _new_url(self, slug):
        return reverse('core:chapter_new', kwargs={'slug': slug})

    def test_every_single_with_text_links_to_that_chapter(self):
        for story in data.my_stories_of('aidana'):
            if not story.text_chapter:
                continue
            with self.subTest(story=story.slug):
                self.assertContains(
                    self.response, self._edit_url(story.slug, story.text_chapter))
                self.assertNotContains(self.response, self._new_url(story.slug))

    def test_serial_still_offers_a_new_chapter(self):
        self.assertContains(self.response, self._new_url(self.SERIAL))

    def test_manage_page_edits_the_same_chapter(self):
        response = self.client.get(
            reverse('core:manage_story', kwargs={'slug': self.SINGLE_WITH_TEXT}))
        self.assertContains(response, self._edit_url(self.SINGLE_WITH_TEXT, 1))
        self.assertNotContains(response, self._new_url(self.SINGLE_WITH_TEXT))


class MyStoryRowMetricsAreAnnounced(TestCase):
    """Метрики строки должны звучать словами (a11y).

    Значение в `stat_pill` помечено aria-hidden, а иконка декоративная. Пока
    подпись не передавалась, все четыре цифры уходили из озвучки целиком:
    карточка читалась как «Таң алдында, Жазылып жатыр, Мәтін, Басқару».
    """

    def setUp(self):
        login_as(self.client)
        self.response = self.client.get(reverse('core:my_stories'))

    def test_metrics_carry_spoken_labels(self):
        # Просмотры — за две недели (DEC-36), а не накопленные
        story = data.story_by_slug('aidana-tan')   # 310 / 87 / 12
        self.assertContains(self.response, f'{spaced(story.recent_views)} оқылым')
        self.assertContains(self.response, f'{spaced(story.likes)} реакция')
        self.assertContains(self.response, f'{spaced(story.comments)} пікір')

    def test_labels_are_reachable_by_screen_readers(self):
        # sr-only, а не aria-label: у <span> с role=generic имя не выставляется
        views = spaced(data.story_by_slug('aidana-tan').recent_views)
        self.assertContains(self.response, f'class="sr-only">{views} оқылым')

    def test_counts_are_exact_not_compacted(self):
        # Авторский кабинет показывает точное число, «1,0 мың» здесь не годится
        self.assertNotContains(self.response, '1,0 мың')


class WriteHasNoAuthorStatsRail(TestCase):
    """DEC-48: агрегаты автора живут в профиле, а не в кабинете.

    Рейл `right_rail/writer.html` повторял четыре плитки
    `partials/profile/_stats.html` — и на страницах одного произведения
    читался как статистика этого произведения: в шапке «1 042 оқылым»,
    в рейле «Оқылым 2 117», без единого слова о том, что второе про весь
    портфель. Кнопку «Жаңа шығарма» он дублировал из шапки списка, а его
    разбивка по статусам роняла черновик (2+1+1 под «Шығарма 5») вопреки
    BR-ACH-07.
    """

    WRITE_URLS = (
        ('core:my_stories',    {}),
        ('core:new_story',     {}),
        ('core:manage_story',  {'slug': 'aidana-tan'}),
        ('core:story_settings', {'slug': 'aidana-tan'}),
        ('core:chapter_new',   {'slug': 'aidana-tan'}),
    )

    def setUp(self):
        login_as(self.client)

    def test_no_rail_on_any_write_page(self):
        for name, kwargs in self.WRITE_URLS:
            with self.subTest(url=name):
                r = self.client.get(reverse(name, kwargs=kwargs))
                self.assertNotContains(r, '<aside')

    def test_no_author_totals_leak_onto_a_single_story_page(self):
        """Числа автора не стоят рядом с числами произведения."""
        stats = data.writer_stats('aidana')
        story = data.story_by_slug('aidana-tan')
        self.assertNotEqual(stats['views'], story.views)   # иначе тест пуст
        body = self.client.get(
            reverse('core:manage_story', kwargs={'slug': 'aidana-tan'})
        ).content.decode()
        self.assertIn(spaced(story.views), body)
        self.assertNotIn(spaced(stats['views']), body)

    def test_no_aside_for_guest(self):
        response = Client().get(reverse('core:my_stories'))
        self.assertNotContains(response, '<aside')

    def test_unknown_story_has_no_rail(self):
        response = self.client.get(
            reverse('core:manage_story', kwargs={'slug': 'no-such-story'}))
        self.assertContains(response, 'Шығарма табылмады')
        self.assertNotContains(response, '<aside')

    def test_the_only_way_to_totals_is_the_profile(self):
        r = self.client.get(reverse('core:my_stories'))
        self.assertContains(r, reverse('core:profile_me') + '?tab=stats')


# ───────────────────────── New story ─────────────────────────

class NewStoryForm(TestCase):

    def setUp(self):
        login_as(self.client)
        self.response = self.client.get(reverse('core:new_story'))

    def test_200(self):
        self.assertEqual(self.response.status_code, 200)

    def test_has_required_fields(self):
        """FR-WRITE-01: три поля — атау, формат, негізгі жанр."""
        self.assertContains(self.response, 'name="title"')
        self.assertContains(self.response, 'name="format"')
        self.assertContains(self.response, 'name="genre_primary"')

    def test_asks_nothing_about_a_story_that_does_not_exist_yet(self):
        """Аннотация, доп. жанр, теги и согласие уехали дальше по пути.

        Форма из восьми полей стояла между автором и первой строкой текста
        и спрашивала о работе, которой ещё нет: тег к ненаписанному рассказу
        не выбирается, аннотация к нему не пишется. Обязательность аннотации
        не отменена — она проверяется при отправке на модерацию
        (FR-WRITE-09), а не при создании черновика.
        """
        for field in ('annotation', 'genre_secondary', 'tags', 'agree'):
            with self.subTest(field=field):
                self.assertNotContains(self.response, f'name="{field}"')

    def test_consent_is_stated_not_ticked(self):
        # Чекбокса нет, но правила остаются на виду и остаются ссылкой.
        self.assertContains(self.response, reverse('core:legal_publishing'))

    def test_format_is_offered_as_cards(self):
        # docs/13 §13.11: формат перестраивает читательскую страницу целиком,
        # парой радио между аннотацией и жанром он подавался слабее жанра.
        self.assertContains(self.response, 'id="format-single"')
        self.assertContains(self.response, 'id="format-serial"')

    def test_primary_action_leads_to_writing(self):
        self.assertContains(self.response, 'Жазуға кірісу')

    def test_genre_select_lists_all_12(self):
        for g in data.all_genres():
            with self.subTest(genre=g.slug):
                self.assertContains(self.response, f'value="{g.slug}"')

    def test_status_is_not_asked_at_creation(self):
        """BR-10: новое произведение — всегда черновик, выбирать нечего.

        Форма предлагала `OnProcess` и `Completed` — оба публичные. «Аяқталды»
        стояло вариантом для произведения с нулём бөлім, а у `single` статус
        вообще один (BR-10a). Дефолт при создании — `NotPublished`, и он не
        выбирается, а сообщается.
        """
        self.assertNotContains(self.response, 'name="status"')
        self.assertNotContains(self.response, 'value="OnProcess"')
        self.assertNotContains(self.response, 'value="Completed"')

    def test_says_the_work_starts_as_a_draft(self):
        # Убрать выбор мало: автор должен понимать, в каком состоянии
        # окажется работа. Слово — каноническое из status_badge (BR-10).
        self.assertContains(self.response, 'жоба')



class NewStoryGuestSeesGate(TestCase):

    def test_guest_sees_login_hint_no_form(self):
        r = self.client.get(reverse('core:new_story'))
        self.assertNotContains(r, 'name="title"')
        # Формулировка общая для всех гейтов: «<повод> кір.» (components/auth_gate.html)
        self.assertContains(r, 'Жаңа шығарма жариялау үшін')
        self.assertContains(r, reverse('core:login'))


# ───────────────────────── Manage story ─────────────────────────

class ManageStoryKnown(TestCase):

    SLUG = 'aidana-tan'   # 8 глав у Айданы

    def setUp(self):
        login_as(self.client)
        self.response = self.client.get(reverse('core:manage_story', kwargs={'slug': self.SLUG}))

    def test_200(self):
        self.assertEqual(self.response.status_code, 200)

    def test_shows_title_and_status(self):
        """Бейдж показывает статус ЭТОЙ работы.

        Проверка искала «Жарияланды» и проходила по слову из разбивки
        в правом рейле, а не по бейджу: у `aidana-tan` статус `OnProcess`,
        и бейдж всё это время говорил «Жазылып жатыр». Ровно та подмена,
        из-за которой рейл и убрали (DEC-48) — слово про портфель автора
        читалось как слово про произведение.
        """
        story = data.story_by_slug(self.SLUG)
        self.assertEqual(story.status, 'OnProcess')
        self.assertContains(self.response, story.title)
        self.assertContains(self.response, 'Жазылып жатыр')

    def test_lists_each_chapter_with_edit_link(self):
        chapters = data.chapters_of(self.SLUG)
        self.assertGreater(len(chapters), 0)
        for c in chapters:
            with self.subTest(chapter=c.number):
                self.assertContains(self.response, c.title)
                edit_url = reverse('core:chapter_edit', kwargs={'slug': self.SLUG, 'chapter': c.number})
                self.assertContains(self.response, f'href="{edit_url}"')

    def test_action_buttons_present(self):
        # «Бөлім қосу», «Баптаулар», «Сайтта қарау»
        self.assertContains(self.response, reverse('core:chapter_new', kwargs={'slug': self.SLUG}))
        self.assertContains(self.response, reverse('core:story_settings', kwargs={'slug': self.SLUG}))
        self.assertContains(self.response, reverse('core:story_detail', kwargs={'slug': self.SLUG}))

    def test_has_delete_trigger(self):
        self.assertContains(self.response, 'open-delete-confirm')


class ManageStoryUnknown(TestCase):

    def test_unknown_slug_renders_not_found(self):
        r = self.client.get(reverse('core:manage_story', kwargs={'slug': 'no-such-story'}))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Шығарма табылмады')


class ManageStoryEmptyChapters(TestCase):

    SLUG = 'aidana-erteg'   # OnModeration, 3 chapters в .chapters но без записей в CHAPTERS_BY_STORY

    def setUp(self):
        login_as(self.client)
        self.response = self.client.get(reverse('core:manage_story', kwargs={'slug': self.SLUG}))

    def test_shows_empty_chapters_cta(self):
        # У 'aidana-erteg' нет глав в CHAPTERS_BY_STORY → empty state в списке
        self.assertContains(self.response, 'Әлі бөлім жоқ')


# ───────────────────────── Story settings ─────────────────────────

class StorySettingsForm(TestCase):

    SLUG = 'aidana-tan'

    def setUp(self):
        login_as(self.client)
        self.response = self.client.get(reverse('core:story_settings', kwargs={'slug': self.SLUG}))

    def test_200(self):
        self.assertEqual(self.response.status_code, 200)

    def test_prefilled_title(self):
        story = data.story_by_slug(self.SLUG)
        # значение title попадает в value инпута
        self.assertContains(self.response, f'value="{story.title}"')

    def test_primary_genre_preselected(self):
        story = data.story_by_slug(self.SLUG)
        # Селектор содержит selected на текущем жанре
        self.assertContains(self.response, f'value="{story.primary_genre.slug}" selected')

    def test_status_radio_preselected(self):
        # 'aidana-tan' — публичный сериал (OnProcess), радио «Мәртебесі»
        # для него рендерится и отмечает текущий статус.
        self.assertContains(self.response, 'checked')

    def test_no_second_danger_zone(self):
        """Опасная зона осталась одна — на странице управления.

        Две одинаковые красные секции на соседних экранах делают удаление
        фоном: то, что встречается на каждом шагу, перестаёт читаться как
        необратимое. Вход в удаление остаётся из manage_story и из меню
        строки списка (my_story_menu).

        Сама модалка (Ф15) смонтирована глобально в base.html и слушает
        событие на каждой странице — имя события само по себе больше не
        отличает «есть кнопка» от «нет». Проверяем триггер (`$dispatch`).
        """
        self.assertNotContains(self.response, "$dispatch('open-delete-confirm'")
        manage = self.client.get(
            reverse('core:manage_story', kwargs={'slug': self.SLUG}))
        self.assertContains(manage, "$dispatch('open-delete-confirm'")

    def test_audience_radios_are_offered(self):
        """BR-10b: отметку выбирает автор, и выбирает он её здесь."""
        self.assertContains(self.response, 'name="audience"')
        for key, _mark, _hint in data.STORY_AUDIENCES:
            with self.subTest(audience=key):
                self.assertContains(self.response, f'value="{key}"')

    def test_current_audience_is_preselected(self):
        story = data.story_by_slug(self.SLUG)
        body = self.response.content.decode()
        # Ровно один радио группы отмечен, и это текущая отметка работы.
        checked = re.findall(
            r'id="audience-([^"]+)"[^>]*?\bchecked\b', body, flags=re.S)
        self.assertEqual(checked, [story.audience])


class StorySettingsStatusIsOnlyForPublicSerials(TestCase):
    """BR-10a/BR-11: радио «Мәртебесі» — не всем.

    Оно рендерилось всегда и в ветке `else` подставляло черновику отмеченным
    «Аяқталды» — статус, которого у произведения с нулём бөлім быть не может.
    У `single` допустимый статус один, а перевести работу в публичный может
    только модератор, не автор.
    """

    def setUp(self):
        login_as(self.client)

    def _get(self, slug):
        return self.client.get(reverse('core:story_settings', kwargs={'slug': slug}))

    def test_draft_gets_no_status_radio(self):
        story = data.story_by_slug('aidana-kus')
        self.assertEqual(story.status, 'NotPublished')
        self.assertNotContains(self._get('aidana-kus'), 'name="status"')

    def test_moderation_gets_no_status_radio(self):
        story = data.story_by_slug('aidana-erteg')
        self.assertEqual(story.status, 'OnModeration')
        self.assertNotContains(self._get('aidana-erteg'), 'name="status"')

    def test_single_gets_no_status_radio(self):
        story = data.story_by_slug('aidana-koshe')
        self.assertTrue(story.is_single and story.is_public)
        self.assertNotContains(self._get('aidana-koshe'), 'name="status"')

    def test_public_serial_keeps_it(self):
        story = data.story_by_slug('aidana-tan')
        self.assertTrue(story.is_public and not story.is_single)
        self.assertContains(self._get('aidana-tan'), 'name="status"')

    def test_audience_is_offered_even_where_status_is_not(self):
        # Отметка нужна именно черновику — без неё он из черновика не выйдет.
        self.assertContains(self._get('aidana-kus'), 'name="audience"')


class AudienceIsChosenNotDefaulted(TestCase):
    """BR-10b: у `Story.audience` нет значения по умолчанию.

    Поле хранилось с дефолтом «10+», не спрашивалось ни в одной форме, и при
    этом раскладывало работы по оси «Жасың» каталога (DEC-38). Чек-лист
    кабинета рисовал за это решение зелёную галку — галку за несделанное.
    """

    def test_model_has_no_default_mark(self):
        """Пустая строка — «автор ещё не выбрал», и это состояние схемы,
        а не обход дефолта."""
        self.assertFalse(Story._meta.get_field('audience').has_default())
        self.assertEqual(Story().audience, '')

    def test_every_non_draft_story_carries_a_mark(self):
        for s in Story.objects.all():
            if s.status == 'NotPublished':
                continue
            with self.subTest(story=s.slug):
                self.assertIn(
                    s.audience, data.AUDIENCE_ORDER,
                    f'{s.slug} вышла из черновика без возрастной отметки',
                )

    def test_form_labels_differ_from_catalog_labels(self):
        # В каталоге подпись называет вилку читателя («10-13»), в форме —
        # отметку работы. Одна константа на оба места означала бы, что автор
        # ставит работе метку «10-13», то есть «старше не читают».
        form = {mark for _k, mark, _h in data.STORY_AUDIENCES}
        catalog = {label for key, label in data.CATALOG_AUDIENCE_FILTERS if key}
        self.assertNotEqual(form, catalog)
        self.assertEqual(
            [k for k, _m, _h in data.STORY_AUDIENCES],
            list(data.AUDIENCE_ORDER),
        )


class ManageStoryChecklistIsHonestAboutAudience(TestCase):
    """Пункт чек-листа не может быть зелёным за несделанное (BR-10b)."""

    def setUp(self):
        login_as(self.client)

    def test_draft_without_a_mark_shows_it_as_missing(self):
        self.assertEqual(data.story_by_slug('aidana-kus').audience, '')
        r = self.client.get(reverse('core:manage_story', kwargs={'slug': 'aidana-kus'}))
        self.assertContains(r, 'Жас белгісін қой')

    def test_marked_story_shows_the_mark(self):
        story = data.story_by_slug('aidana-tan')
        r = self.client.get(reverse('core:manage_story', kwargs={'slug': 'aidana-tan'}))
        self.assertContains(r, f'Жас белгісі: {story.audience}')


class PublishChecklistIsActionable(TestCase):
    """FR-WRITE-09: чек-лист ведёт к полю, а не отчитывается о прошлом.

    Прежний список был описью: шесть строк, ни одна не кликалась, и над
    ними не было перехода, ради которого список вообще нужен.
    """

    def setUp(self):
        login_as(self.client)

    def test_every_unfinished_item_carries_a_link(self):
        story = data.story_by_slug('aidana-kus')
        for item in data.publish_checklist(story):
            with self.subTest(item=item['key']):
                self.assertIn(item['target'], ('settings', 'text'))
        r = self.client.get(reverse('core:manage_story', kwargs={'slug': 'aidana-kus'}))
        for item in r.context['checklist']:
            with self.subTest(item=item['key']):
                self.assertTrue(item['href'], f'{item["key"]} ведёт в никуда')

    def test_text_item_points_at_the_editor(self):
        r = self.client.get(reverse('core:manage_story', kwargs={'slug': 'aidana-kus'}))
        text = next(i for i in r.context['checklist'] if i['key'] == 'text')
        self.assertEqual(
            text['href'],
            reverse('core:chapter_new', kwargs={'slug': 'aidana-kus'}),
        )

    def test_single_text_item_opens_the_existing_text(self):
        # У одночастного «дописать текст» — это правка существующей главы,
        # а не создание второй: тот же разбор, что в my_story_row.
        slug = 'aidana-koshe'
        story = data.story_by_slug(slug)
        self.assertTrue(story.is_single and story.text_chapter)
        r = self.client.get(reverse('core:manage_story', kwargs={'slug': slug}))
        text = next(i for i in r.context['checklist'] if i['key'] == 'text')
        self.assertEqual(text['href'], reverse(
            'core:chapter_edit',
            kwargs={'slug': slug, 'chapter': story.text_chapter}))

    def test_optional_items_are_marked_optional(self):
        # Обложка и теги улучшают карточку, но не держат публикацию.
        required = {i['key'] for i in data.publish_checklist(
            data.story_by_slug('aidana-kus')) if i['required']}
        self.assertEqual(required, {'text', 'annotation', 'audience'})


class SubmitForReviewIsOnlyForReadyDrafts(TestCase):
    """BR-11: перевод в публичный статус начинается здесь и только отсюда."""

    def setUp(self):
        login_as(self.client)

    def _get(self, slug):
        return self.client.get(reverse('core:manage_story', kwargs={'slug': slug}))

    def test_draft_missing_required_items_cannot_submit(self):
        story = data.story_by_slug('aidana-kus')
        # Черновик без единого бөлім и без возрастной отметки.
        self.assertFalse(data.can_submit_for_review(story))
        r = self._get('aidana-kus')
        self.assertFalse(r.context['can_submit'])
        self.assertContains(r, 'disabled')
        self.assertContains(r, 'Модерацияға жіберу')

    def test_public_story_gets_no_submit_button(self):
        story = data.story_by_slug('aidana-tan')
        self.assertTrue(story.is_public)
        self.assertFalse(data.can_submit_for_review(story))
        self.assertNotContains(self._get('aidana-tan'), 'Модерацияға жіберу')

    def test_story_already_on_moderation_gets_no_submit_button(self):
        story = data.story_by_slug('aidana-erteg')
        self.assertEqual(story.status, 'OnModeration')
        self.assertFalse(data.can_submit_for_review(story))
        self.assertNotContains(self._get('aidana-erteg'), 'Модерацияға жіберу')

    def test_a_complete_draft_can_submit(self):
        draft = data.story_by_slug('aidana-kus')
        self.assertEqual(
            data.missing_for_review(draft), ['text', 'audience'])
        # Черновик с закрытыми обязательными пунктами. Берётся работа с
        # написанным текстом и возвращается в черновики **в памяти**:
        # проверяется чек-лист, а не запись — сохранять нечего.
        ready = data.story_by_slug('aidana-tan')
        ready.status = 'NotPublished'
        self.assertEqual(data.missing_for_review(ready), [])
        self.assertTrue(data.can_submit_for_review(ready))

    def test_readiness_and_status_are_different_questions(self):
        # Готовая, но уже отправленная работа отправляться повторно не должна.
        ready = data.story_by_slug('aidana-tan')
        ready.status = 'OnModeration'
        self.assertEqual(data.missing_for_review(ready), [])
        self.assertFalse(data.can_submit_for_review(ready))


# ───────────────────────── Chapter editor ─────────────────────────

class ChapterEditorNew(TestCase):

    SLUG = 'aidana-tan'

    def setUp(self):
        login_as(self.client)
        self.response = self.client.get(reverse('core:chapter_new', kwargs={'slug': self.SLUG}))

    def test_200(self):
        self.assertEqual(self.response.status_code, 200)

    def test_title_marks_as_new(self):
        self.assertContains(self.response, 'Жаңа бөлім')

    def test_form_fields_empty(self):
        # Поля без value
        self.assertContains(self.response, 'name="title"')
        self.assertContains(self.response, 'name="body"')

    def test_has_both_save_buttons(self):
        # Сохранить как черновик / отправить на модерацию
        self.assertContains(self.response, 'Жоба ретінде сақтау')
        self.assertContains(self.response, 'Модерацияға жіберу')

    def test_submit_button_does_not_promise_publication(self):
        """BR-11: автор не публикует, публикует модератор.

        Кнопка называлась «Жариялау», а тост рядом говорил «модерацияға
        жіберілді». Тост говорил правду. Слово «тексеруге» тоже не годится —
        docs/16 §16.3 отводит ему оттенок экзамена.
        """
        body = self.response.content.decode()
        self.assertNotIn('>\n                    Жариялау', body)
        self.assertNotIn('Тексеруге жіберу', body)
        self.assertIn('Модерацияға жіберу', body)

    def test_char_counter_is_live(self):
        """Счётчик знаков считает набираемое, а не сохранённое.

        Статичное `{{ current.char_count }}` не двигалось при вводе, хотя
        соседняя аннотация через components/textarea.html считала живьём:
        две механики одного и того же на одном экране.
        """
        body = self.response.content.decode()
        self.assertIn('x-text="count"', body)
        self.assertIn('count = $event.target.value.length', body)

    def test_actions_stay_in_view(self):
        """FR-WRITE-05: панель действий липкая.

        Textarea в 20 строк уводит кнопки за нижний край, и автор, дописав
        абзац, не видит ни одного способа сохранить. `bottom-24` разводит
        панель с плавающей пилюлей mobile_nav (docs/07 §7.6).
        """
        body = self.response.content.decode()
        self.assertIn('sticky bottom-24', body)
        self.assertIn('md:bottom-0', body)

    def test_unsaved_state_is_reported_not_faked(self):
        """Индикатор отчитывается о вводе, а не изображает автосохранение.

        «Жоба сақталды» на этой странице не должно быть вовсе (Ф15): это
        первый заход в редактор ещё не созданной главы, и сообщать про
        сохранение того, что ни разу не сохранялось, — та же ложь, что
        рисовал прежний фейковый submit. Появляется текст только на
        уже существующей главе (`ChapterEditorEdit.test_shows_saved_state`)
        — это серверная истина, а не таймер, изображающий автосохранение.
        """
        body = self.response.content.decode()
        self.assertIn('dirty: false', body)
        self.assertIn('@input="dirty = true"', body)
        self.assertIn('Сақталмаған өзгеріс бар', body)
        self.assertNotIn('Жоба сақталды', body)
        # Ничего похожего на таймер, который «сохраняет» сам.
        self.assertNotIn('setInterval', body)


class ChapterEditorEdit(TestCase):

    SLUG = 'aidana-tan'
    CH = 1

    def setUp(self):
        login_as(self.client)
        self.response = self.client.get(
            reverse('core:chapter_edit', kwargs={'slug': self.SLUG, 'chapter': self.CH})
        )

    def test_200(self):
        self.assertEqual(self.response.status_code, 200)

    def test_prefilled_chapter_title(self):
        ch = data.chapter_of(self.SLUG, self.CH)
        self.assertContains(self.response, f'value="{ch.title}"')

    def test_prefilled_chapter_body(self):
        ch = data.chapter_of(self.SLUG, self.CH)
        # Первые слова длинного текста из core/story_texts
        self.assertContains(self.response, 'Бірде ерте таңда')

    def test_shows_saved_state(self):
        """У существующей главы «Жоба сақталды» — серверная истина, не
        таймер: глава лежит в базе, значит она уже была сохранена."""
        self.assertContains(self.response, 'Жоба сақталды')


class ChapterEditorUnknownStory(TestCase):

    def test_unknown_slug_renders_not_found(self):
        login_as(self.client)
        r = self.client.get(reverse('core:chapter_new', kwargs={'slug': 'no-such-story'}))
        self.assertContains(r, 'Шығарма табылмады')


class TagInputMovedOffCreation(TestCase):
    """docs/11 · Фаза 2 не отменена — `tag_input` переехал в баптаулар.

    Компонент остался ровно тем же и живёт на story_settings (покрыт
    `TagInputOnStorySettings`). С формы создания он ушёл вместе с аннотацией
    и доп. жанром: тег к ненаписанному рассказу не выбирается, а автокомплит
    с блок-листом был самым тяжёлым элементом первого экрана автора.
    """

    def setUp(self):
        login_as(self.client)
        self.response = self.client.get(reverse('core:new_story'))

    def test_renders(self):
        self.assertEqual(self.response.status_code, 200)

    def test_no_tag_input_on_the_creation_form(self):
        self.assertNotContains(self.response, 'id="tag-input-accepted"')
        self.assertNotContains(self.response, 'id="tag-input-blocked"')

    def test_creation_form_does_not_ship_the_tag_dictionary(self):
        # Словарь тегов и блок-лист — заметный кусок разметки; на экране,
        # где теги не выбираются, он ехал бы вхолостую.
        self.assertNotIn('accepted_tags', self.response.context)
        self.assertNotIn('blocked_patterns', self.response.context)

    def test_settings_still_offers_it(self):
        r = self.client.get(
            reverse('core:story_settings', kwargs={'slug': 'aidana-tan'}))
        self.assertContains(r, 'id="tag-input-accepted"')


class TagInputOnStorySettings(TestCase):
    """docs/11 · Фаза 2: tag_input на странице настроек — initial из stub."""

    # У aidana-tan есть теги, включая pending 'experimental'
    SLUG = 'aidana-tan'

    def setUp(self):
        login_as(self.client)
        self.response = self.client.get(reverse('core:story_settings', kwargs={'slug': self.SLUG}))

    def test_renders(self):
        self.assertEqual(self.response.status_code, 200)

    def test_initial_tags_passed_to_alpine(self):
        """В initial-массив Alpine попадают существующие теги стори."""
        # Имена тегов aidana-tan: 'саяхат', 'жасөспірім', 'арман', 'эксперимент'
        for name in ('саяхат', 'жасөспірім', 'арман', 'эксперимент'):
            with self.subTest(tag=name):
                self.assertContains(self.response, name)


# ───────────────────────── Кабинет отвечает «что дальше» (DEC-40) ─────────

class MyStoriesAreOrderedByLastTouch(TestCase):
    """Свежее сверху. Порядок был порядком объявления в STORIES."""

    def test_helper_sorts_recent_first(self):
        mine = data.my_stories_of('aidana')
        days = [s.updated_days_ago for s in mine if s.updated_days_ago is not None]
        self.assertEqual(days, sorted(days))

    def test_stories_without_a_date_go_last(self):
        mine = data.my_stories_of('aidana')
        known = [i for i, s in enumerate(mine) if s.updated_days_ago is not None]
        unknown = [i for i, s in enumerate(mine) if s.updated_days_ago is None]
        if known and unknown:
            self.assertLess(max(known), min(unknown))

    def test_page_renders_them_in_that_order(self):
        login_as(self.client)
        body = self.client.get(reverse('core:my_stories')).content.decode()
        positions = [body.index(s.title) for s in data.my_stories_of('aidana')]
        self.assertEqual(positions, sorted(positions))

    def test_row_shows_when_it_was_touched(self):
        login_as(self.client)
        response = self.client.get(reverse('core:my_stories'))
        self.assertContains(response, data.story_by_slug('aidana-tan').updated_label)


class AttentionStripAnswersWhatToDoNext(TestCase):
    """FR-WRITE-08: сигналы, которые лежали в данных и нигде не сходились."""

    def setUp(self):
        login_as(self.client)
        self.response = self.client.get(reverse('core:my_stories'))

    def test_moderation_is_surfaced(self):
        self.assertContains(self.response, 'модерацияда')

    def test_unread_comments_link_to_notifications(self):
        unread = sum(len([n for n in items if n.kind == 'comment' and not n.read])
                     for items in data.notifications_for_user('aidana').values())
        self.assertGreater(unread, 0, 'корпус потерял непрочитанные пікір')
        self.assertContains(self.response, f'{unread} жаңа пікір')
        self.assertContains(self.response, reverse('core:notifications'))

    def test_empty_draft_is_surfaced(self):
        self.assertContains(self.response, 'жоба бастамада тұр')

    def test_single_item_links_to_that_work(self):
        moderated = [s for s in data.my_stories_of('aidana')
                     if s.status == 'OnModeration']
        self.assertEqual(len(moderated), 1)
        self.assertContains(
            self.response,
            reverse('core:manage_story', kwargs={'slug': moderated[0].slug}))

    def test_author_without_signals_gets_no_strip(self):
        login_as_newcomer(self.client, 'no-such-user')
        self.assertNotContains(
            self.client.get(reverse('core:my_stories')), 'Назарыңды күтеді')

    def test_guest_gets_no_strip(self):
        self.assertNotContains(
            self.client_class().get(reverse('core:my_stories')), 'Назарыңды күтеді')


class NonPublicRowsReplaceZeroesWithProgress(TestCase):
    """«0 · 0 · 0» — три нуля вместо ответа на единственный вопрос к работе."""

    def setUp(self):
        login_as(self.client)
        self.response = self.client.get(reverse('core:my_stories'))

    def test_moderation_says_how_long_it_waits(self):
        story = data.story_by_slug('aidana-erteg')
        self.assertContains(self.response, f'{story.updated_days_ago} күн тексеруде')

    def test_draft_says_it_has_no_chapters(self):
        self.assertContains(self.response, 'әлі бір бөлім жоқ')

    def test_no_zero_metric_pills_on_those_rows(self):
        # Именно начало подписи: «310 оқылым» тоже содержит «0 оқылым»
        self.assertNotContains(self.response, 'class="sr-only">0 оқылым')
        self.assertNotContains(self.response, 'class="sr-only">0 реакция')
        self.assertNotContains(self.response, 'class="sr-only">0 пікір')


class MyStoryMenuOffersTheMissingActions(TestCase):
    """Из списка нельзя было ни посмотреть работу, ни открыть баптаулар, ни удалить."""

    def setUp(self):
        login_as(self.client)
        self.response = self.client.get(reverse('core:my_stories'))

    def test_every_row_offers_settings_and_delete(self):
        for story in data.my_stories_of('aidana'):
            with self.subTest(story=story.slug):
                self.assertContains(
                    self.response,
                    reverse('core:story_settings', kwargs={'slug': story.slug}))
        self.assertContains(self.response, 'open-delete-confirm')

    def test_public_works_can_be_viewed_as_a_reader(self):
        for story in data.my_stories_of('aidana'):
            url = reverse('core:story_detail', kwargs={'slug': story.slug})
            with self.subTest(story=story.slug, public=story.is_public):
                if story.is_public:
                    self.assertContains(self.response, url)
                else:
                    self.assertNotContains(self.response, url)

    def test_public_check_is_not_a_literal(self):
        # DEC-37: сериал в работе публичен, хотя статус не 'Published'
        serial = data.story_by_slug('aidana-tan')
        self.assertEqual(serial.status, 'OnProcess')
        self.assertTrue(serial.is_public)


class WriterStatsBreakdownSumsToTotal(TestCase):
    """Разбивка по статусам обязана давать в сумме `total`.

    Черновик считался только в `total`, и «Барлығы 5» стояло над
    разбивкой 2+1+1. Слагаемые, не дающие целого, — то же враньё, что и
    хранимый счётчик, только разложенное на части.
    """

    def test_every_author(self):
        for a in data.all_authors():
            s = data.writer_stats(a.username)
            with self.subTest(author=a.username):
                self.assertEqual(
                    s['published'] + s['ongoing'] + s['on_moderation'] + s['draft'],
                    s['total'],
                )

    def test_every_status_lands_in_exactly_one_bucket(self):
        buckets = {
            'published':     ('Published', 'Completed'),
            'ongoing':       ('OnProcess',),
            'on_moderation': ('OnModeration',),
            'draft':         ('NotPublished',),
        }
        covered = [st for group in buckets.values() for st in group]
        self.assertEqual(len(covered), len(set(covered)))
        # Все пять статусов BR-10 разложены, ни один не потерян.
        self.assertEqual(
            set(covered),
            {'Published', 'Completed', 'OnProcess', 'OnModeration', 'NotPublished'},
        )


# ═════════════════════ Ф15, Этап 1: запись (POST) ══════════════════════════
# До этой точки в файле — только GET/рендер. Ни один из этих тестов не
# существовал до Этапа 1: до него формы ничего не сохраняли (docs/20).

class NewStoryCreatesADraft(TestCase):

    def setUp(self):
        login_as(self.client)
        self.genre = data.all_genres()[0]

    def test_creates_a_draft_owned_by_the_author_and_redirects_to_the_editor(self):
        r = self.client.post(reverse('core:new_story'), {
            'title': 'Сынақ шығармасы', 'format': 'serial',
            'genre_primary': self.genre.slug,
        })
        story = Story.objects.get(title='Сынақ шығармасы')
        self.assertEqual(story.author.username, 'aidana')
        self.assertEqual(story.status, 'NotPublished')
        self.assertEqual(story.format, 'serial')
        self.assertEqual(story.primary_genre_id, self.genre.pk)
        self.assertRedirects(
            r, reverse('core:chapter_new', kwargs={'slug': story.slug}))

    def test_slug_is_transliterated_and_url_safe(self):
        # Story.slug — ASCII (маршрут <slug:slug> кириллицу не матчит),
        # заголовок — казахский (domain/slugs.py).
        self.client.post(reverse('core:new_story'), {
            'title': 'Тау бөктеріндегі үй', 'format': 'single',
            'genre_primary': self.genre.slug,
        })
        story = Story.objects.get(title='Тау бөктеріндегі үй')
        self.assertRegex(story.slug, r'^[-a-zA-Z0-9_]+$')
        self.assertTrue(story.slug)

    def test_a_second_story_with_the_same_title_gets_a_distinct_slug(self):
        for _ in range(2):
            self.client.post(reverse('core:new_story'), {
                'title': 'Қайталанған атау', 'format': 'serial',
                'genre_primary': self.genre.slug,
            })
        slugs = set(Story.objects.filter(title='Қайталанған атау')
                    .values_list('slug', flat=True))
        self.assertEqual(len(slugs), 2)

    def test_missing_required_field_creates_nothing(self):
        before = Story.objects.count()
        r = self.client.post(reverse('core:new_story'), {
            'title': '', 'format': 'serial', 'genre_primary': self.genre.slug,
        })
        self.assertEqual(Story.objects.count(), before)
        self.assertRedirects(r, reverse('core:new_story'))

    def test_guest_post_creates_nothing(self):
        guest = Client()
        before = Story.objects.count()
        guest.post(reverse('core:new_story'), {
            'title': 'Қонақтың шығармасы', 'format': 'serial',
            'genre_primary': self.genre.slug,
        })
        self.assertEqual(Story.objects.count(), before)


class StorySettingsSavesFields(TestCase):

    SLUG = 'aidana-kus'  # NotPublished, 0 бөлім, audience='' — aidana-нікі

    def setUp(self):
        login_as(self.client)
        self.genre = data.all_genres()[0]

    def _post(self, **overrides):
        payload = {
            'title': 'Жаңа атау', 'annotation': 'Жаңа аннотация мәтіні.',
            'format': 'serial', 'genre_primary': self.genre.slug,
            'genre_secondary': '', 'audience': '10+', 'tags': '',
        }
        payload.update(overrides)
        return self.client.post(
            reverse('core:story_settings', kwargs={'slug': self.SLUG}), payload)

    def test_saves_title_annotation_and_audience(self):
        r = self._post()
        story = Story.objects.get(slug=self.SLUG)
        self.assertEqual(story.title, 'Жаңа атау')
        self.assertEqual(story.annotation, 'Жаңа аннотация мәтіні.')
        self.assertEqual(story.audience, '10+')
        self.assertRedirects(
            r, reverse('core:story_settings', kwargs={'slug': self.SLUG}))

    def test_missing_title_saves_nothing(self):
        self._post(title='')
        story = Story.objects.get(slug=self.SLUG)
        self.assertNotEqual(story.title, '')
        self.assertNotEqual(story.audience, '10+')

    def test_cannot_switch_to_single_with_more_than_one_chapter(self):
        story = Story.objects.get(slug=self.SLUG)
        Chapter.objects.create(story=story, number=1, title='1', body='т')
        Chapter.objects.create(story=story, number=2, title='2', body='т')
        self._post(format='single')
        story.refresh_from_db()
        self.assertEqual(story.format, 'serial')

    def test_status_field_outside_the_allowed_set_is_ignored(self):
        # 'aidana-kus' — черновик, радио «Мәртебесі» на этой странице у
        # него вообще не рендерится (BR-10a) — POST в обход формы не
        # должен провести статус мимо модерации.
        self._post(status='Published')
        story = Story.objects.get(slug=self.SLUG)
        self.assertEqual(story.status, 'NotPublished')


class StorySettingsCoverUpload(TestCase):
    """Тот же валидатор, что у User.avatar (BR-46) — SVG не проходит.

    `story.cover = cover; story.save()` — прямое присваивание, не
    ModelForm, поэтому `RASTER_ONLY` не срабатывает сам по себе (тот же
    пробел, что был у `avatar` до Ф15 Этапа 6) — закрыто явным вызовом
    во view.
    """

    SLUG = 'aidana-kus'

    def setUp(self):
        login_as(self.client)
        self.genre = data.all_genres()[0]

    def _post(self, **overrides):
        payload = {
            'title': 'Жаңа атау', 'annotation': 'Жаңа аннотация мәтіні.',
            'format': 'serial', 'genre_primary': self.genre.slug,
            'genre_secondary': '', 'audience': '10+', 'tags': '',
        }
        payload.update(overrides)
        return self.client.post(
            reverse('core:story_settings', kwargs={'slug': self.SLUG}), payload)

    def test_svg_is_refused(self):
        cover = SimpleUploadedFile('мұқаба.svg', b'<svg/>',
                                   content_type='image/svg+xml')
        self._post(cover=cover)
        story = Story.objects.get(slug=self.SLUG)
        self.assertFalse(story.cover)

    def test_svg_refusal_also_blocks_the_rest_of_the_form(self):
        """Ошибка одного поля — весь POST no-op, не частичное сохранение."""
        before = Story.objects.get(slug=self.SLUG).title
        cover = SimpleUploadedFile('мұқаба.svg', b'<svg/>',
                                   content_type='image/svg+xml')
        self._post(cover=cover, title='Басқа атау')
        self.assertEqual(Story.objects.get(slug=self.SLUG).title, before)

    def test_png_is_accepted(self):
        cover = SimpleUploadedFile('мұқаба.png', b'\x89PNG demo',
                                   content_type='image/png')
        self._post(cover=cover)
        story = Story.objects.get(slug=self.SLUG)
        self.assertTrue(story.cover.name.startswith(f'covers/{self.SLUG}'))


class StorySettingsTagResolution(TestCase):

    SLUG = 'aidana-kus'

    def setUp(self):
        login_as(self.client)
        self.genre = data.all_genres()[0]

    def _post(self, tags):
        return self.client.post(
            reverse('core:story_settings', kwargs={'slug': self.SLUG}),
            {'title': 'Атау', 'annotation': 'Аннотация.', 'format': 'serial',
             'genre_primary': self.genre.slug, 'audience': '10+', 'tags': tags})

    def test_existing_accepted_tag_is_reused_not_duplicated(self):
        before = Tag.objects.filter(slug='mektep').count()
        self._post('мектеп')
        story = Story.objects.get(slug=self.SLUG)
        self.assertEqual(Tag.objects.filter(slug='mektep').count(), before)
        self.assertIn('mektep', story.tags.values_list('slug', flat=True))

    def test_new_name_creates_a_pending_tag(self):
        self._post('жаңа-тег-осында')
        story = Story.objects.get(slug=self.SLUG)
        tag = story.tags.get(name='жаңа-тег-осында')
        self.assertEqual(tag.status, 'pending')

    def test_blocked_pattern_is_dropped_silently(self):
        patterns = data.blocked_tag_patterns_list()
        if not patterns:
            self.skipTest('блок-лист демо-корпуса пуст')
        self._post(patterns[0])
        story = Story.objects.get(slug=self.SLUG)
        self.assertEqual(story.tags.count(), 0)


class ChapterEditorSavesADraft(TestCase):

    SLUG = 'aidana-kus'

    def setUp(self):
        login_as(self.client)

    def test_draft_action_creates_a_chapter_without_changing_status(self):
        r = self.client.post(
            reverse('core:chapter_new', kwargs={'slug': self.SLUG}),
            {'title': '1-бөлім', 'body': 'Бір кездері...', 'action': 'draft'})
        story = Story.objects.get(slug=self.SLUG)
        chapter = story.chapter_set.get(number=1)
        self.assertEqual(chapter.title, '1-бөлім')
        self.assertEqual(chapter.char_count, len('Бір кездері...'))
        self.assertEqual(story.status, 'NotPublished')
        self.assertRedirects(r, reverse(
            'core:chapter_edit', kwargs={'slug': self.SLUG, 'chapter': 1}))

    def test_empty_body_saves_nothing(self):
        self.client.post(
            reverse('core:chapter_new', kwargs={'slug': self.SLUG}),
            {'title': '1-бөлім', 'body': '  ', 'action': 'draft'})
        story = Story.objects.get(slug=self.SLUG)
        self.assertEqual(story.chapter_set.count(), 0)

    def test_written_chapters_show_up_in_the_count(self):
        """«N бөлім» на карточке — то, что автор написал.

        Раньше число было колонкой, которую заполняли при создании работы,
        а запись главы её не трогала: автор писал три бөлім и видел «0».
        Проверяется в обоих видах — у одиночного объекта и в выдаче
        каталога, где число приезжает аннотацией.
        """
        for number in (1, 2, 3):
            self.client.post(
                reverse('core:chapter_new', kwargs={'slug': self.SLUG}),
                {'title': f'{number}-бөлім', 'body': 'Мәтін.', 'action': 'draft'})

        story = Story.objects.get(slug=self.SLUG)
        self.assertEqual(story.chapters, 3)
        self.assertEqual(story.reading_meta_label, '3 бөлім')

        from_feed = next(s for s in data.my_stories_of('aidana')
                         if s.slug == self.SLUG)
        self.assertEqual(from_feed.chapters, 3)

    def test_editing_an_existing_chapter_does_not_duplicate_it(self):
        self.client.post(
            reverse('core:chapter_new', kwargs={'slug': self.SLUG}),
            {'title': '1-бөлім', 'body': 'Бастапқы мәтін.', 'action': 'draft'})
        self.client.post(
            reverse('core:chapter_edit', kwargs={'slug': self.SLUG, 'chapter': 1}),
            {'title': '1-бөлім (өңделген)', 'body': 'Жаңа мәтін.', 'action': 'draft'})
        story = Story.objects.get(slug=self.SLUG)
        self.assertEqual(story.chapter_set.count(), 1)
        self.assertEqual(story.chapter_set.get(number=1).title, '1-бөлім (өңделген)')


class ChapterEditorSavesAPoll(TestCase):

    SLUG = 'aidana-kus'

    def setUp(self):
        login_as(self.client)

    def test_two_or_more_options_create_a_poll(self):
        self.client.post(
            reverse('core:chapter_new', kwargs={'slug': self.SLUG}), {
                'title': '1-бөлім', 'body': 'Мәтін.', 'action': 'draft',
                'poll_question': 'Кім жеңеді?',
                'poll_option': ['Біріншісі', 'Екіншісі'],
            })
        chapter = Story.objects.get(slug=self.SLUG).chapter_set.get(number=1)
        self.assertEqual(chapter.poll.question, 'Кім жеңеді?')
        self.assertEqual(chapter.poll.option_set.count(), 2)

    def test_a_single_option_does_not_create_a_poll(self):
        # BR-POLL-02: кемінде екі нұсқа — біреуімен таңдау мағынасыз.
        self.client.post(
            reverse('core:chapter_new', kwargs={'slug': self.SLUG}), {
                'title': '1-бөлім', 'body': 'Мәтін.', 'action': 'draft',
                'poll_question': 'Сұрақ?', 'poll_option': ['Жалғыз нұсқа'],
            })
        chapter = Story.objects.get(slug=self.SLUG).chapter_set.get(number=1)
        self.assertFalse(hasattr(chapter, 'poll'))


class ChapterEditorSubmitsForReview(TestCase):

    SLUG = 'aidana-kus'

    def setUp(self):
        login_as(self.client)

    def test_incomplete_checklist_keeps_the_draft(self):
        # 'aidana-kus' без жас белгісі — чек-лист толық емес БЖ.
        self.client.post(
            reverse('core:chapter_new', kwargs={'slug': self.SLUG}),
            {'title': '1-бөлім', 'body': 'Мәтін.', 'action': 'submit_review'})
        story = Story.objects.get(slug=self.SLUG)
        self.assertEqual(story.status, 'NotPublished')
        self.assertTrue(story.has_chapters)  # глава при этом сохранилась

    def test_complete_checklist_sends_it_to_moderation(self):
        Story.objects.filter(slug=self.SLUG).update(audience='10+')
        self.client.post(
            reverse('core:chapter_new', kwargs={'slug': self.SLUG}),
            {'title': '1-бөлім', 'body': 'Мәтін.', 'action': 'submit_review'})
        story = Story.objects.get(slug=self.SLUG)
        self.assertEqual(story.status, 'OnModeration')


class ManageStorySubmitsForReview(TestCase):

    SLUG = 'aidana-kus'

    def setUp(self):
        login_as(self.client)

    def test_post_without_a_ready_checklist_keeps_the_draft(self):
        r = self.client.post(reverse('core:manage_story', kwargs={'slug': self.SLUG}))
        story = Story.objects.get(slug=self.SLUG)
        self.assertEqual(story.status, 'NotPublished')
        self.assertRedirects(
            r, reverse('core:manage_story', kwargs={'slug': self.SLUG}))

    def test_post_with_a_ready_checklist_sends_it_to_moderation(self):
        story = Story.objects.get(slug=self.SLUG)
        story.audience = '10+'
        story.save(update_fields=['audience'])
        Chapter.objects.create(story=story, number=1, title='1-бөлім', body='Мәтін бар.')
        self.client.post(reverse('core:manage_story', kwargs={'slug': self.SLUG}))
        story.refresh_from_db()
        self.assertEqual(story.status, 'OnModeration')


class DeleteStoryRemovesIt(TestCase):

    SLUG = 'aidana-kus'

    def setUp(self):
        login_as(self.client)

    def test_get_does_not_delete(self):
        self.client.get(reverse('core:delete_story', kwargs={'slug': self.SLUG}))
        self.assertTrue(Story.objects.filter(slug=self.SLUG).exists())

    def test_post_deletes_and_redirects_to_my_stories(self):
        r = self.client.post(reverse('core:delete_story', kwargs={'slug': self.SLUG}))
        self.assertFalse(Story.objects.filter(slug=self.SLUG).exists())
        self.assertRedirects(r, reverse('core:my_stories'))


class OwnershipIsEnforced(TestCase):
    """Ф15, Этап 1: `story_by_slug_for_author` фильтрует по автору — чужой
    slug и несуществующий неотличимы снаружи (IDOR)."""

    def setUp(self):
        login_as(self.client)  # aidana
        self.foreign = Story.objects.exclude(author__username='aidana').first()

    def test_manage_story_of_a_foreign_slug_shows_not_found(self):
        r = self.client.get(
            reverse('core:manage_story', kwargs={'slug': self.foreign.slug}))
        self.assertContains(r, 'Шығарма табылмады')

    def test_story_settings_post_does_not_touch_a_foreign_story(self):
        original_title = self.foreign.title
        self.client.post(
            reverse('core:story_settings', kwargs={'slug': self.foreign.slug}),
            {'title': 'Басып алынды', 'annotation': '', 'format': 'serial',
             'genre_primary': self.foreign.primary_genre.slug,
             'audience': '10+', 'tags': ''})
        self.foreign.refresh_from_db()
        self.assertEqual(self.foreign.title, original_title)

    def test_chapter_editor_post_does_not_create_a_chapter_on_a_foreign_story(self):
        before = self.foreign.chapter_set.count()
        self.client.post(
            reverse('core:chapter_new', kwargs={'slug': self.foreign.slug}),
            {'title': 'Бөтен бөлім', 'body': 'Мәтін', 'action': 'draft'})
        self.assertEqual(self.foreign.chapter_set.count(), before)

    def test_delete_post_does_not_remove_a_foreign_story(self):
        self.client.post(
            reverse('core:delete_story', kwargs={'slug': self.foreign.slug}))
        self.assertTrue(Story.objects.filter(pk=self.foreign.pk).exists())


class AttentionSpeaksOnlyWhenThereIsSomething(TestCase):
    """Полоса «что требует внимания» (FR-WRITE-08) — сигналы, а не опись.

    `slug` заполнен только когда элемент один: вести «3 шығарма
    модерацияда» в одну из трёх было бы враньём.
    """

    def test_signals_come_in_the_order_of_the_authors_day(self):
        kinds = [i['kind'] for i in data.writer_attention('aidana')]
        self.assertEqual(kinds, ['moderation', 'comments', 'draft'])

    def test_nothing_to_say_about_a_stranger(self):
        self.assertEqual(data.writer_attention('no-such-user'), [])

    def test_a_single_item_points_at_itself(self):
        for item in data.writer_attention('aidana'):
            with self.subTest(kind=item['kind']):
                if item['count'] > 1 or item['kind'] == 'comments':
                    self.assertEqual(item['slug'], '')
                else:
                    self.assertIsNotNone(data.story_by_slug(item['slug']))
