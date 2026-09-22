"""Отклик на главу: реакции и опрос автора.

Одиночного «нравится» у работы нет — есть пять реакций у главы, и они
отвечают на «что я почувствовал», а не «хорошо или плохо». Голос один и
переключается, а не копится.

Опрос заводит автор под своей главой: он спрашивает читателя о том, что
будет дальше, и потому его результат виден только проголосовавшему.
"""


from core.tests.base import STORY_SLUG, TestCase, login_as, user
from django.urls import reverse

from core import data
from core.models import ChapterReactionVote, PollVote, Story


class ReactionsReplaceTheSingleLike(TestCase):
    """FR-STORY-12 / DEC-32 / DEC-58: пять реакций вместо лайка. Кнопка
    рендерится эмодзи без подписи (DEC-52), но доступное имя не теряется —
    оно стоит в aria-label вместе со счётом."""

    def setUp(self):
        self.response = self.client.get(
            reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))

    def test_all_five_are_offered_as_emoji(self):
        html = self.response.content.decode()
        for reaction in data.REACTIONS:
            with self.subTest(reaction=reaction.slug):
                self.assertIn(reaction.emoji, html)
                self.assertIn(f'aria-label="{reaction.label},', html)
        self.assertNotContains(self.response, 'Бұл бөлім ұнады ма?')
        self.assertContains(self.response, reverse('core:login'))
        # Набор из пяти кнопок одинаков у первой главы и у сотой.
        self.assertEqual(5, len(data.reactions_of(data.chapter_of(STORY_SLUG, 1))))

    def test_the_chapter_counter_is_their_sum_and_the_top_one_reads_it(self):
        """«Алғашқы кездесу» собирает Жүрегім, «Депрессия» — Жыладым."""
        third = data.chapter_of(STORY_SLUG, 3)
        self.assertEqual(third.likes, sum(r.count for r in third.reactions.all()))
        self.assertEqual('juregim', third.top_reaction.slug)
        self.assertEqual('jyladym', data.chapter_of(STORY_SLUG, 4).top_reaction.slug)

    def test_the_chapter_list_shows_counts_but_offers_no_button(self):
        """Реакция требует прочтения (BR-REACT-04), поэтому ряд живёт
        только под текстом главы."""
        first = data.chapter_of(STORY_SLUG, 1)
        self.assertTrue(first.likes, 'нужна глава с реакциями для проверки')
        self.assertContains(self.response, f'{first.likes} реакция')
        self.assertContains(self.response, 'aria-label="Бөлімге реакция"', count=1)


class ChapterReactionVoting(TestCase):
    """BR-REACT-02/03 (Ф15, Этап 3): реакция ставится, повтор снимает,
    другой вид заменяет; Story.likes — агрегат по числу голосов, а не по
    сумме реакций (BR-14a) — смена вида его не трогает."""

    CHAPTER = 1

    def _url(self):
        return reverse('core:chapter_react',
                       kwargs={'slug': STORY_SLUG, 'chapter': self.CHAPTER})

    def _kind_count(self, kind):
        chapter = data.chapter_of(STORY_SLUG, self.CHAPTER)
        return chapter.reaction_counts.get(kind, 0)

    def _story_likes(self):
        return Story.objects.get(slug=STORY_SLUG).likes

    def test_a_first_vote_is_recorded_and_a_repeat_takes_it_back(self):
        login_as(self.client)
        likes_before, kind_before = self._story_likes(), self._kind_count('kuldim')

        self.client.post(self._url(), {'kind': 'kuldim'})
        self.assertEqual(self._kind_count('kuldim'), kind_before + 1)
        self.assertEqual(self._story_likes(), likes_before + 1)
        self.assertTrue(ChapterReactionVote.objects.filter(
            user__username='aidana', chapter__story__slug=STORY_SLUG,
            chapter__number=self.CHAPTER, kind='kuldim').exists())

        self.client.post(self._url(), {'kind': 'kuldim'})   # повтор снимает
        self.assertEqual(self._kind_count('kuldim'), kind_before)
        self.assertEqual(self._story_likes(), likes_before)
        self.assertFalse(ChapterReactionVote.objects.filter(
            user__username='aidana', chapter__story__slug=STORY_SLUG,
            chapter__number=self.CHAPTER).exists())

    def test_another_kind_replaces_the_vote_without_counting_twice(self):
        login_as(self.client)
        likes_before = self._story_likes()
        kuldim_before = self._kind_count('kuldim')
        jyladym_before = self._kind_count('jyladym')

        self.client.post(self._url(), {'kind': 'kuldim'})
        self.client.post(self._url(), {'kind': 'jyladym'})

        self.assertEqual(self._kind_count('kuldim'), kuldim_before)
        self.assertEqual(self._kind_count('jyladym'), jyladym_before + 1)
        self.assertEqual(self._story_likes(), likes_before + 1)  # голос один
        vote = ChapterReactionVote.objects.get(
            user__username='aidana', chapter__story__slug=STORY_SLUG,
            chapter__number=self.CHAPTER)
        self.assertEqual(vote.kind, 'jyladym')

    def test_an_htmx_request_gets_the_component_back_instead_of_a_redirect(self):
        """Без перезагрузки страницы: htmx подменяет сам компонент своим же
        ответом (`hx-swap="outerHTML"`), обычная отправка формы (JS
        выключен) остаётся PRG-редиректом."""
        login_as(self.client)
        plain = self.client.post(self._url(), {'kind': 'kuldim'})
        self.assertEqual(plain.status_code, 302)

        response = self.client.post(self._url(), {'kind': 'kuldim'},
                                    HTTP_HX_REQUEST='true')  # повтор снимает
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn(f'id="reactions-{self.CHAPTER}"', html)
        self.assertNotIn('aria-pressed="true"', html)

        response = self.client.post(self._url(), {'kind': 'shabyt'},
                                    HTTP_HX_REQUEST='true')
        html = response.content.decode()
        shabyt_count = self._kind_count('shabyt')
        self.assertIn(f'aria-label="Шабыт, {shabyt_count}"', html)
        self.assertIn('aria-pressed="true"', html)

    def test_neither_a_guest_nor_an_invented_kind_votes(self):
        likes_before = self._story_likes()
        self.client.post(self._url(), {'kind': 'kuldim'})
        self.assertEqual(self._story_likes(), likes_before)
        login_as(self.client)
        self.client.post(self._url(), {'kind': 'not-a-real-reaction'})
        self.assertFalse(ChapterReactionVote.objects.exists())

    def test_the_page_and_the_helper_report_the_picked_kind(self):
        """`Chapter.my_reaction` и `mine` в `reactions_of` отражают голос
        именно вошедшего — не жёсткий `False`, как до записи."""
        login_as(self.client)
        self.client.post(self._url(), {'kind': 'shabyt'})

        chapter = data.chapter_of(STORY_SLUG, self.CHAPTER, user('aidana'))
        self.assertEqual(chapter.my_reaction, 'shabyt')
        picked = [i['reaction'].slug for i in data.reactions_of(chapter) if i['mine']]
        self.assertEqual(picked, ['shabyt'])
        shabyt_count = next(i['count'] for i in data.reactions_of(chapter)
                            if i['reaction'].slug == 'shabyt')
        url = (reverse('core:story_detail', kwargs={'slug': STORY_SLUG})
               + f'?chapter={self.CHAPTER}')
        html = self.client.get(url).content.decode()
        self.assertIn(f'aria-label="Шабыт, {shabyt_count}"', html)
        self.assertIn('aria-pressed="true"', html)


class ChapterPollStates(TestCase):
    """FR-STORY-13 / DEC-33: необязательный опрос автора под главой."""

    OPEN_CHAPTER = 12    # последняя вышедшая — ответа ещё нет
    CLOSED_CHAPTER = 3   # следующая глава вышла, опрос закрыт

    def _get(self, chapter):
        url = reverse('core:story_detail', kwargs={'slug': STORY_SLUG}) + f'?chapter={chapter}'
        return self.client.get(url)

    def test_an_open_poll_asks_its_own_question(self):
        poll = data.poll_of(STORY_SLUG, self.OPEN_CHAPTER)
        self.assertFalse(poll.closed)
        self.assertEqual(100, sum(r['percent'] for r in poll.results))
        self.assertContains(self._get(self.OPEN_CHAPTER), poll.question)
        # Цельный текст тоже может нести опрос.
        self.assertContains(
            self.client.get(reverse('core:story_detail',
                                    kwargs={'slug': 'tunge-deiin'})),
            'Автордың сұрағы')

    def test_it_closes_when_the_next_chapter_ships_and_points_at_the_answer(self):
        poll = data.poll_of(STORY_SLUG, self.CLOSED_CHAPTER)
        self.assertTrue(poll.closed)
        self.assertEqual(self.CLOSED_CHAPTER + 1, poll.answer_chapter)
        closed = self._get(self.CLOSED_CHAPTER)
        self.assertContains(closed, 'Сұрақ жабылды')
        self.assertContains(closed, f'{self.CLOSED_CHAPTER + 1}-бөлімде')

    def test_a_guest_votes_through_login_and_a_reader_gets_the_ballot(self):
        guest = self._get(self.OPEN_CHAPTER)
        self.assertContains(guest, 'Жауап беру үшін')
        self.assertContains(guest, reverse('core:login'))
        login_as(self.client)
        signed_in = self._get(self.OPEN_CHAPTER)
        self.assertContains(signed_in, 'Дұрыс жауабы жоқ')
        self.assertNotContains(signed_in, 'Жауап беру үшін')

    def test_a_chapter_without_a_poll_shows_nothing_at_all(self):
        """Опрос необязателен — его отсутствие не пустое состояние
        (BR-POLL-01). Декоративный блок из трёх захардкоженных вариантов,
        одинаковых на всех произведениях, снят DEC-33."""
        self.assertIsNone(data.poll_of(STORY_SLUG, 5))
        self.assertNotContains(self._get(5), 'Автордың сұрағы')
        first = self._get(1)
        self.assertNotContains(first, 'Батыл қадам')
        self.assertNotContains(first, 'Кейіпкердің келесі таңдауы')


class ChapterPollVoting(TestCase):
    """Ф15 Этап 4: голос в открытом опросе — один на опрос, не меняется
    (BR-POLL-*); закрытый опрос голос не принимает (BR-POLL-05)."""

    OPEN_CHAPTER = 12    # последняя вышедшая — ответа ещё нет
    CLOSED_CHAPTER = 3   # следующая глава вышла, опрос закрыт

    def _url(self, chapter):
        return reverse('core:poll_vote', kwargs={'slug': STORY_SLUG, 'chapter': chapter})

    def test_the_first_vote_is_recorded_and_the_ballot_becomes_results(self):
        login_as(self.client)
        poll = data.poll_of(STORY_SLUG, self.OPEN_CHAPTER)
        option = poll.options[0]
        before = option.votes

        self.client.post(self._url(self.OPEN_CHAPTER), {'option': option.slug})

        poll = data.poll_of(STORY_SLUG, self.OPEN_CHAPTER, user('aidana'))
        self.assertEqual(poll.my_vote, option.slug)
        self.assertEqual(poll.option_set.get(slug=option.slug).votes, before + 1)
        self.assertTrue(PollVote.objects.filter(
            user__username='aidana', poll=poll, option__slug=option.slug).exists())

        url = (reverse('core:story_detail', kwargs={'slug': STORY_SLUG})
               + f'?chapter={self.OPEN_CHAPTER}')
        voted = self.client.get(url)
        self.assertContains(voted, 'сенің жауабың')
        self.assertNotContains(voted, 'Дұрыс жауабы жоқ — тек сенің болжамың.')

    def test_a_second_vote_does_not_change_the_first(self):
        login_as(self.client)
        poll = data.poll_of(STORY_SLUG, self.OPEN_CHAPTER)
        first, second = poll.options[0], poll.options[1]
        second_before = second.votes

        self.client.post(self._url(self.OPEN_CHAPTER), {'option': first.slug})
        self.client.post(self._url(self.OPEN_CHAPTER), {'option': second.slug})

        poll = data.poll_of(STORY_SLUG, self.OPEN_CHAPTER, user('aidana'))
        self.assertEqual(poll.my_vote, first.slug)
        self.assertEqual(poll.option_set.get(slug=second.slug).votes, second_before)
        self.assertEqual(
            PollVote.objects.filter(user__username='aidana', poll=poll).count(), 1)

    def test_a_guest_a_closed_poll_and_an_invented_option_are_all_refused(self):
        open_poll = data.poll_of(STORY_SLUG, self.OPEN_CHAPTER)
        self.client.post(self._url(self.OPEN_CHAPTER),
                         {'option': open_poll.options[0].slug})
        self.assertFalse(PollVote.objects.exists())

        login_as(self.client)
        closed = data.poll_of(STORY_SLUG, self.CLOSED_CHAPTER)
        self.assertTrue(closed.closed)
        option = closed.options[0]
        before = option.votes
        self.client.post(self._url(self.CLOSED_CHAPTER), {'option': option.slug})
        self.assertEqual(closed.option_set.get(slug=option.slug).votes, before)

        self.client.post(self._url(self.OPEN_CHAPTER),
                         {'option': 'not-a-real-option'})
        self.assertFalse(PollVote.objects.exists())
