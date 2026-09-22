"""Разговор под главой.

Комментарий привязан к главе, а не к работе: под двенадцатой частью не
место спорам о первой. Ответ ровно один уровень вглубь — ветка на три
этажа на телефоне не читается.

Отдаётся разговор окном в двадцать верхнеуровневых реплик со своими
ответами: у популярной работы их однажды станет тысяча, и страница
вместе с ними.
"""


from core.tests import factories as make
from core.tests.base import STORY_SLUG, TestCase, login_as, login_as_newcomer, user
from django.test import Client
from django.urls import reverse

from core import data
from core.domain.story import COMMENTS_PAGE
from core.models import Story, StoryComment


class CommentsAreAnchoredToTheirChapter(TestCase):
    """Комментарий швартуется к главе; `chapter_number=None` означает
    разговор о работе целиком и виден под любой главой."""

    def _url(self, chapter=None):
        url = reverse('core:story_detail', kwargs={'slug': STORY_SLUG})
        return f'{url}?chapter={chapter}' if chapter else url

    def test_a_chapter_shows_its_own_comments_and_the_general_ones(self):
        third = self.client.get(self._url(3))
        self.assertContains(third, '3-бөлім пікірлері')
        self.assertContains(third, 'үшінші бөлімдегі қарттың сұрағы')
        self.assertNotContains(self.client.get(self._url(1)),
                               'үшінші бөлімдегі қарттың сұрағы')
        for number in (1, 2, 3):
            with self.subTest(chapter=number):
                self.assertContains(self.client.get(self._url(number)),
                                    'Келесі бөлім жұма күні шығады')

    def test_a_guest_gets_the_gate_and_an_author_gets_the_form(self):
        guest = self.client.get(self._url())
        self.assertContains(guest, 'Пікір қалдыру үшін')
        self.assertNotContains(guest, '<textarea')
        self.assertNotContains(guest, 'open-report')

        login_as(self.client)
        signed_in = self.client.get(self._url())
        self.assertNotContains(signed_in, 'Пікір қалдыру үшін')
        self.assertContains(signed_in, '<textarea')
        self.assertContains(signed_in, 'open-report')


class CommentMenu(TestCase):
    """Меню трёх точек: набор пунктов зависит от того, чей комментарий.

    Кнопка три месяца висела без обработчика — ни события, ни цели.
    """

    # У dalney-berega гл.3: комментарий aidana (свой для демо-логина)
    # и комментарий aygerim_k (чужой).
    URL_KW = {'slug': STORY_SLUG}

    def _get(self):
        url = reverse('core:story_detail', kwargs=self.URL_KW) + '?chapter=3'
        return self.client.get(url)

    def test_a_guest_gets_only_the_link_item(self):
        response = self._get()
        self.assertContains(response, 'Пікір мәзірі')
        self.assertContains(response, 'Сілтемені көшіру')
        self.assertNotContains(response, 'Шағым жіберу')
        self.assertNotContains(response, "report_url: '")

    def test_a_reader_reports_a_stranger_and_deletes_their_own(self):
        """На свой комментарий жаловаться некому — его удаляют."""
        login_as(self.client)
        response = self._get()
        self.assertContains(response, 'Шағым жіберу')
        self.assertContains(response, "report_url: '")
        html = response.content.decode()
        own = next(c for c in data.comments_of_chapter(STORY_SLUG, 3)
                   if c.belongs_to('aidana'))
        block = html[html.index(f'id="comment-{own.id}"'):]
        block = block[:block.index('</article>')]
        self.assertIn('Жою', block)
        self.assertNotIn('Шағым жіберу', block)

    def test_the_anchor_is_the_primary_key(self):
        """Скопированная ссылка обязана работать и завтра.

        В стабе якорь считался из текста crc32-суммой — потому что ключа
        не было, а `hash()` рандомизируется от запуска к запуску. Теперь
        якорь и есть первичный ключ строки: устойчивее не бывает.
        """
        comment = data.comments_of_chapter(STORY_SLUG, 3)[0]
        self.assertIsInstance(comment.id, int)
        self.assertContains(self._get(), f'id="comment-{comment.id}"')

    def test_the_icons_say_what_they_mean(self):
        """Три точки — иконка контейнера («ещё варианты»), а не действия.

        На «Шағым жіберу» они стояли в двух местах сразу, и в меню
        комментария получалось «ещё варианты → ещё варианты». Жалоба
        помечена флажком, модерация — щитом: галочка говорит «готово»,
        а фраза — «защищено правилами».
        """
        login_as(self.client)
        html = self._get().content.decode()
        self.assertIn('#icon-flag', html)
        self.assertNotIn('#icon-dots-vertical', html)
        trigger_at = html.index('aria-label="Пікір мәзірі"')
        self.assertIn('#icon-dots-horizontal', html[trigger_at:trigger_at + 400])
        notice_at = html.index('модерация ережелерімен')
        self.assertIn('#icon-shield', html[notice_at - 500:notice_at])


class CommentLike(TestCase):
    """Лайк комментария переключается (Ф15, POST), гость уходит на логин."""

    def test_a_guest_sees_the_button_and_is_gated_to_login(self):
        response = self.client.get(
            reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))
        self.assertContains(response, 'aria-label="Ұнату"')
        self.assertContains(response, reverse('core:login'))
        comment = data.comments_of_chapter(STORY_SLUG, 1)[0]
        before = comment.likes
        self.client.post(reverse('core:comment_like',
                                 kwargs={'slug': STORY_SLUG,
                                         'comment_id': comment.pk}))
        comment.refresh_from_db()
        self.assertEqual(comment.likes, before)

    def test_post_toggles_the_like_and_the_count(self):
        # `likes` — пересчёт по настоящим CommentLike (не +1 к сид-числу):
        # у демо-комментария «87 ұнату» ни разу не было настоящей строки
        # голоса, и первый реальный лайк отвечает правде, а не сумме с
        # выдуманной историей.
        login_as(self.client, 'aidana')
        comment = data.comments_of_chapter(STORY_SLUG, 1)[0]  # sayyn, не aidana
        url = reverse('core:comment_like',
                      kwargs={'slug': STORY_SLUG, 'comment_id': comment.pk})

        self.client.post(url)
        comment.refresh_from_db()
        self.assertEqual(comment.likes, 1)
        self.assertTrue(comment.like_set.filter(user__username='aidana').exists())

        self.client.post(url)  # повторный клик снимает
        comment.refresh_from_db()
        self.assertEqual(comment.likes, 0)
        self.assertFalse(comment.like_set.filter(user__username='aidana').exists())


class CommentReplies(TestCase):
    """Один уровень ответов — на ответ ответить нельзя."""

    def test_the_reply_form_belongs_to_the_signed_in(self):
        url = reverse('core:story_detail', kwargs={'slug': STORY_SLUG})
        guest = self.client.get(url)
        self.assertContains(guest, 'Жауап беру')
        self.assertNotContains(guest, 'пікіріне жауап жаз')
        login_as(self.client)
        self.assertContains(self.client.get(url), 'пікіріне жауап жаз')

    def test_reply_itself_has_no_reply_button(self):
        """Инвариант вложенности держит компонент, а не сторона вызова."""
        login_as(self.client)
        url = reverse('core:story_detail', kwargs={'slug': STORY_SLUG}) + '?chapter=2'
        html = self.client.get(url).content.decode()
        reply = data.comments_of_chapter(STORY_SLUG, 2)[-1].replies[0]
        block = html[html.index(f'id="comment-{reply.id}"'):]
        block = block[:block.index('</article>')]
        self.assertNotIn('Жауап беру', block)


class CommentAuthorLinks(TestCase):
    """Имя и аватар ведут на профиль; аватар красится по username."""

    def test_the_name_leads_to_the_profile_and_no_link_is_dead(self):
        response = self.client.get(
            reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))
        author = data.comments_of_chapter(STORY_SLUG, 1)[0].author
        self.assertContains(response, reverse('core:profile_other',
                                              kwargs={'username': author.username}))
        self.assertNotContains(response, '<a href="#" class="font-sans text-[13px]')


# ═════════════════════ Ф15, Этап 2: комментарии (POST) ═════════════════════

class CommentCreatePersists(TestCase):

    SLUG = 'dalney-berega'

    def setUp(self):
        login_as(self.client, 'aidana')

    def test_top_level_comment_is_saved_and_bumps_the_story_counter(self):
        story = Story.objects.get(slug=self.SLUG)
        before = story.comments
        r = self.client.post(
            reverse('core:comment_create', kwargs={'slug': self.SLUG}),
            {'text': 'Керемет оқылды!', 'chapter': '3'})
        comment = StoryComment.objects.get(story=story, text='Керемет оқылды!')
        self.assertEqual(comment.author.username, 'aidana')
        self.assertEqual(comment.chapter_number, 3)
        self.assertIsNone(comment.parent)
        story.refresh_from_db()
        self.assertEqual(story.comments, before + 1)
        self.assertRedirects(
            r, reverse('core:story_detail', kwargs={'slug': self.SLUG})
            + f'?chapter=3#comment-{comment.pk}')

    def test_reply_to_a_top_level_comment_is_saved(self):
        top = next(c for c in data.comments_of_chapter(self.SLUG, 3) if c.replies)
        self.client.post(
            reverse('core:comment_create', kwargs={'slug': self.SLUG}),
            {'text': 'Келісемін.', 'chapter': '3', 'parent': str(top.pk)})
        reply = StoryComment.objects.get(text='Келісемін.')
        self.assertEqual(reply.parent_id, top.pk)

    def test_a_forged_parent_an_empty_text_and_a_guest_save_nothing(self):
        url = reverse('core:comment_create', kwargs={'slug': self.SLUG})
        # Ответ сам уже на верхнем уровне не лежит, одна вложенность.
        existing_reply = next(c.replies[0]
                              for c in data.comments_of_chapter(self.SLUG, 3)
                              if c.replies)
        # 'kronchessii' — другая работа: приклеить ответ к чужому дереву,
        # прислав его parent id, нельзя.
        foreign_parent = StoryComment.objects.filter(
            story__slug='kronchessii', parent__isnull=True).first()
        cases = {
            'ответ на ответ': {'text': 'Жауапқа жауап.', 'chapter': '3',
                               'parent': str(existing_reply.pk)},
            'чужое дерево': {'text': 'Бөтен ағашқа.', 'chapter': '3',
                             'parent': str(foreign_parent.pk)},
            'пустой текст': {'text': '   ', 'chapter': '3'},
        }
        before = StoryComment.objects.count()
        for label, payload in cases.items():
            with self.subTest(case=label):
                self.client.post(url, payload)
                self.assertEqual(StoryComment.objects.count(), before)
        Client().post(url, {'text': 'Қонақтың пікірі.', 'chapter': '3'})
        self.assertEqual(StoryComment.objects.count(), before)


class CommentDeleteRemovesIt(TestCase):

    SLUG = 'dalney-berega'

    def test_owner_can_delete_their_own_top_level_comment_and_its_replies(self):
        # Верхнеуровневый комментарий с ответами — удаление каскадное,
        # счётчик работы обязан упасть на число всех удалённых строк, не
        # только на одну.
        top = next(c for c in data.comments_of_chapter(self.SLUG, 3) if c.replies)
        removed_ids = [top.pk] + [r.pk for r in top.replies]
        login_as(self.client, top.author.username)
        story = Story.objects.get(slug=self.SLUG)
        before = story.comments

        r = self.client.post(reverse(
            'core:comment_delete', kwargs={'slug': self.SLUG, 'comment_id': top.pk}))

        self.assertFalse(StoryComment.objects.filter(pk__in=removed_ids).exists())
        story.refresh_from_db()
        self.assertEqual(story.comments, before - len(removed_ids))
        self.assertRedirects(
            r, reverse('core:story_detail', kwargs={'slug': self.SLUG}) + '?chapter=3')

    def test_neither_a_get_nor_a_stranger_nor_a_guest_deletes_anything(self):
        target = next(c for c in data.comments_of_chapter(self.SLUG, 3)
                      if not c.replies)
        url = reverse('core:comment_delete',
                      kwargs={'slug': self.SLUG, 'comment_id': target.pk})

        login_as(self.client, target.author.username)
        self.client.get(url)
        self.assertTrue(StoryComment.objects.filter(pk=target.pk).exists())

        stranger = next(a.username for a in data.all_authors()
                        if a.username != target.author.username)
        login_as(self.client, stranger)
        self.client.post(url)
        self.assertTrue(StoryComment.objects.filter(pk=target.pk).exists())

        Client().post(url)
        self.assertTrue(StoryComment.objects.filter(pk=target.pk).exists())


class TheConversationComesInAWindow(TestCase):
    """Разговор отдавался целиком — со всеми ответами и метками «я это
    лайкал». На популярной работе страница росла вместе с обсуждением,
    причём росла она в телефоне у читателя, а не на сервере.

    Окно в двадцать верхнеуровневых реплик: ответы живут при своих
    репликах и страницей не разрываются — половина разговора без второй
    половины не читается.
    """

    SLUG = 'window-talk'

    def setUp(self):
        super().setUp()
        self.story = make.story(slug=self.SLUG, author=make.user(),
                                     chapters=1)
        self.readers = [make.user() for _ in range(3)]
        self.comments = [
            data.add_comment(self.story, self.readers[i % 3],
                             text=f'Пікір {i}', chapter_number=1)
            for i in range(COMMENTS_PAGE + 5)
        ]

    def _page(self, number=None):
        url = reverse('core:story_detail', kwargs={'slug': self.SLUG}) + '?chapter=1'
        if number:
            url = f'{url}&page={number}'
        return self.client.get(url)

    def test_the_first_page_holds_the_window_and_no_more(self):
        page = self._page()

        self.assertEqual(len(page.context['comments']), COMMENTS_PAGE)
        self.assertEqual(page.context['comments_pages'], 2)

    def test_the_rest_waits_on_the_second(self):
        page = self._page(2)

        self.assertEqual(len(page.context['comments']), 5)
        self.assertEqual([c.text for c in page.context['comments']],
                         [c.text for c in self.comments[COMMENTS_PAGE:]])

    def test_the_heading_counts_the_whole_conversation(self):
        """«20» над первой страницей из двух было бы неправдой."""
        page = self._page()

        self.assertEqual(page.context['comments_total'], COMMENTS_PAGE + 5)
        self.assertContains(page, f'>{COMMENTS_PAGE + 5}</span>')

    def test_the_pagination_carries_the_chapter_and_the_anchor(self):
        """Без главы вторая страница открывала бы первую с чужими
        репликами, без якоря — верх работы, до которого реплики надо
        снова прокручивать."""
        page = self._page()

        self.assertContains(page, 'chapter=1&amp;page=2#pikirler')

    def test_a_short_conversation_gets_no_pagination_at_all(self):
        short = make.story(slug='short-talk', author=make.user(),
                                chapters=1)
        data.add_comment(short, self.readers[0], text='Бір ғана пікір',
                         chapter_number=1)

        page = self.client.get(
            reverse('core:story_detail', kwargs={'slug': 'short-talk'}) + '?chapter=1')

        self.assertEqual(page.context['comments_pages'], 1)
        self.assertNotContains(page, 'aria-label="Беттер"')

    def test_garbage_and_overshoot_open_the_work_instead_of_404(self):
        """`?page=99` это старая ссылка или опечатка — то же, что делает
        каталог: не-число читается первой страницей, слишком большое —
        последней."""
        self.assertEqual(self._page('garbage').context['comments_page'], 1)
        self.assertEqual(self._page(99).context['comments_page'], 2)
        self.assertEqual(self._page(0).context['comments_page'], 1)

    def test_a_reply_stays_with_its_parent_and_takes_no_slot(self):
        parent = self.comments[0]
        data.add_comment(self.story, self.readers[1], text='Жауап',
                         chapter_number=1, parent=parent)

        page = self._page()

        self.assertEqual(page.context['comments_total'], COMMENTS_PAGE + 5)
        shown = next(c for c in page.context['comments'] if c.pk == parent.pk)
        self.assertEqual([r.text for r in shown.replies], ['Жауап'])


class TheAuthorOfACommentSeesItAfterPosting(TestCase):
    """С окном новая реплика уезжает на последнюю страницу, и возврат на
    первую означал бы, что человек написал комментарий и не увидел
    написанного — а якорь на первой странице не нашёл бы ничего."""

    SLUG = 'lands-right'

    def setUp(self):
        super().setUp()
        self.story = make.story(slug=self.SLUG, author=make.user(),
                                     chapters=1)
        for i in range(COMMENTS_PAGE):
            data.add_comment(self.story, make.user(),
                             text=f'Бұрынғы {i}', chapter_number=1)
        self.reader = login_as_newcomer(self.client, 'lands_right_reader')

    def test_a_new_comment_lands_on_its_own_page(self):
        response = self.client.post(
            reverse('core:comment_create', kwargs={'slug': self.SLUG}),
            {'text': 'Соңғы пікір', 'chapter': '1'})

        fresh = StoryComment.objects.get(text='Соңғы пікір')
        self.assertEqual(
            response.url,
            f"{reverse('core:story_detail', kwargs={'slug': self.SLUG})}"
            f'?chapter=1&page=2#comment-{fresh.pk}')

    def test_liking_a_comment_returns_to_the_page_it_lives_on(self):
        # Двадцати реплик хватает ровно на одну страницу — двадцать первая
        # и есть та, ради которой лайк обязан помнить, где она лежит.
        far = data.add_comment(self.story, make.user(),
                               text='Екінші беттегі', chapter_number=1)

        response = self.client.post(
            reverse('core:comment_like',
                    kwargs={'slug': self.SLUG, 'comment_id': far.pk}))

        self.assertIn('page=', response.url)
        self.assertTrue(response.url.endswith(f'#comment-{far.pk}'))

    def test_a_reply_lands_on_the_page_of_its_parent(self):
        parent = StoryComment.objects.filter(story=self.story).order_by('pk').first()

        response = self.client.post(
            reverse('core:comment_create', kwargs={'slug': self.SLUG}),
            {'text': 'Жауабым', 'chapter': '1', 'parent': str(parent.pk)})

        self.assertNotIn('page=', response.url)
