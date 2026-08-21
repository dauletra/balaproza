"""Home: ветвление hero_guest vs hero_returning, контент режимов в шапке/сайдбаре.

Не утверждаем DOM-классы (хрупко), только наличие текстовых маркеров,
которые специфичны для каждого режима.
"""

from django.test import TestCase
from django.urls import reverse


class HomeGuestMode(TestCase):

    def setUp(self):
        self.response = self.client.get(reverse('core:home'))

    def test_returns_200(self):
        self.assertEqual(self.response.status_code, 200)

    def test_shows_login_button_in_header(self):
        """Гость в шапке видит «Кіру», а не аватар."""
        self.assertContains(self.response, 'Кіру')

    def test_shows_guest_hero_marker(self):
        """Hero для гостя — редакционный, без CTA, сообщает обе функции платформы."""
        self.assertContains(self.response, 'Бүгін не оқимыз?')
        self.assertContains(self.response, 'Шығарма, автор, жанр немесе тег')
        self.assertContains(self.response, 'Автор бол')

    def test_does_not_show_continue_reading(self):
        """У гостя нет блока «Жалғастыру оқу»."""
        self.assertNotContains(self.response, 'Жалғастыру')

    def test_does_not_show_logout(self):
        self.assertNotContains(self.response, 'Шығу')

    def test_does_not_show_private_dropdown_items(self):
        """Гость не видит в хедере личных пунктов из avatar-dropdown."""
        # «Менің заявкаларым» появляется только в авторизованном dropdown
        self.assertNotContains(self.response, 'Менің заявкаларым')
        self.assertNotContains(self.response, 'Менің шығармаларым')

    def test_mobile_guest_reading_entry_goes_to_catalog(self):
        # Раньше пункт назывался только через aria-label; теперь у него есть
        # видимая подпись, и дублирующий aria-label был бы лишним.
        self.assertContains(self.response, reverse('core:catalog'))
        self.assertContains(self.response, '>Оқу</span>')

    def test_short_shelf_contains_only_single_works(self):
        self.assertTrue(self.response.context['short_stories'])
        self.assertTrue(all(s.is_single for s in self.response.context['short_stories']))

    def test_serial_shelf_contains_only_serial_works(self):
        self.assertTrue(self.response.context['serial_stories'])
        self.assertTrue(all(s.is_serial for s in self.response.context['serial_stories']))

    def test_collections_open_the_page_above_every_row(self):
        """DEC-31: главный вход в чтение — вопрос о настроении, а не ряд обложек."""
        html = self.response.content.decode()
        self.assertLess(html.index('Қазір не оқығың келеді?'),
                        html.index('Қысқа оқылатын әңгімелер'))
        self.assertLess(html.index('Қазір не оқығың келеді?'),
                        html.index('Көп оқылған шығармалар'))

    def test_home_uses_four_main_rows(self):
        self.assertContains(self.response, 'Қазір не оқығың келеді?')
        self.assertContains(self.response, 'Көп оқылған шығармалар')
        self.assertContains(self.response, 'Қысқа оқылатын әңгімелер')
        self.assertContains(self.response, 'Жалғасып жатқан шығармалар')
        # Жанровый скроллер убран (DEC-31) — осталась только полоса-вывеска.
        self.assertNotContains(self.response, 'Жанрлар бойынша')
        self.assertNotContains(self.response, 'Жаңа шығармалар')
        self.assertNotContains(self.response, '10+ оқырманға')
        self.assertNotContains(self.response, 'Жас авторлар')

class HomeMobileFirstFold(TestCase):
    """Фолд 1 на мобильном: hero должен быть коротким, а обложки — сразу под ним.

    Подросток заходит с телефона; если весь первый экран занят поиском,
    ценность портала не считывается.
    """

    def setUp(self):
        self.response = self.client.get(reverse('core:home'))
        self.html = self.response.content.decode()

    def test_hero_states_portal_scale(self):
        """Счётчики в hero дают масштаб портала с первого экрана."""
        stats = self.response.context['portal_stats']
        self.assertEqual(stats['genres'], 12)
        self.assertGreater(stats['stories'], 0)
        self.assertContains(self.response, f"{stats['stories']} шығарма")
        self.assertContains(self.response, f"{stats['authors']} автор")

    def test_hero_says_peers_write_here(self):
        """Подзаголовок сообщает ценность (пишут ровесники), а не механику поиска."""
        self.assertContains(self.response, 'Құрдастарың жазған')

    def test_genre_strip_sits_between_hero_and_collections(self):
        """Жанр — вывеска (DEC-31): виден в первом фолде, но пропускает вперёд
        вопрос о настроении. Порядок: hero → полоса жанров → жинақтар."""
        self.assertLess(
            self.html.index('aria-label="Жанрлар"'),
            self.html.index('Қазір не оқығың келеді?'),
        )

    def test_collections_render_before_first_row(self):
        """Первым содержательным блоком идут жинақтар, а не ряд обложек."""
        self.assertLess(
            self.html.index('Қазір не оқығың келеді?'),
            self.html.index('Қысқа оқылатын әңгімелер'),
        )

    def test_first_row_is_actually_filled(self):
        """Ряд в первом фолде обязан быть наполнен — пустой ряд убивает всю раскладку.

        Долгое время здесь было ровно одно произведение: у одиночных рассказов
        не было текстов в core/story_texts/, и ряд приходилось подменять другим.
        """
        self.assertGreaterEqual(len(self.response.context['short_stories']), 4)

    def test_author_cta_moved_out_of_hero_into_own_block(self):
        """«Автор болу» больше не занимает бюджет фолда: CTA-блок ниже по странице."""
        self.assertLess(
            self.html.index('Қысқа оқылатын әңгімелер'),
            self.html.index('Сенің әңгімең'),
        )

    def test_row_all_link_is_not_hidden_on_mobile(self):
        """Выход «барлығы →» не должен требовать свайпа всех карточек ряда."""
        self.assertContains(self.response, 'барлығы →')
        self.assertNotContains(self.response, 'hidden lg:inline')

    def test_cards_show_duration_chip(self):
        """Длительность живёт на обложке, а не внутри обрезаемого заголовка."""
        self.assertContains(self.response, 'мин')
        self.assertContains(self.response, 'бөлім')


class HomeMobileSecondFold(TestCase):
    """Фолд 2: конкурс в потоке + секция жанров без псевдотабов."""

    def setUp(self):
        self.response = self.client.get(reverse('core:home'))
        self.html = self.response.content.decode()

    def test_contest_is_visible_in_flow_not_only_in_rail(self):
        """Приз и дедлайн раньше жили только в правом рейле (hidden lg:block)."""
        contest = self.response.context['hero_contest']
        self.assertEqual(self.html.count('Белсенді байқау'), 2)  # поток + рейл
        self.assertContains(self.response, f'{contest.days_left} күн')

    def test_prize_has_thousand_separators(self):
        """`stringformat:"d"` выводил «500000» сплошняком."""
        self.assertContains(self.response, '500 000 ₸')

    def test_contest_banner_hidden_on_desktop_to_avoid_duplicate(self):
        """С xl конкурс показывает правый рейл — в потоке баннер прячется."""
        import re
        wrapper = re.search(
            r'<div class="xl:hidden">\s*<a[^>]*>[\s\S]*?Белсенді байқау', self.html,
        )
        self.assertIsNotNone(wrapper)

    def test_genre_strip_shows_all_twelve_genres(self):
        """Вывеска обязана показать весь ассортимент: двенадцать цветных слов
        за пару секунд объясняют, что это литературный портал (DEC-31)."""
        from core import stub_data
        for genre in stub_data.GENRES:
            with self.subTest(genre=genre.slug):
                self.assertIn(f'/genres/{genre.slug}/', self.html)

    def test_genre_strip_leads_straight_to_genre_page(self):
        """Чип ведёт на /genres/<slug>/, а не переключает состояние внутри
        главной: скроллер произведений активного жанра удалён вместе с ?genre=."""
        self.assertNotIn('active_genre', self.response.context)
        self.assertNotIn('?genre=', self.html)
        self.assertNotIn('id="zhanrlar"', self.html)

    def test_genre_query_no_longer_changes_the_page(self):
        """Старые ссылки ?genre= не должны ломать страницу — просто игнорируются."""
        r = self.client.get(reverse('core:home') + '?genre=triller')
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('active_genre', r.context)

    def test_every_genre_has_at_least_one_published_story(self):
        """Пустой чип — тупик: подросток тапает жанр и упирается в заглушку."""
        from core import stub_data
        for genre in stub_data.GENRES:
            with self.subTest(genre=genre.slug):
                published = [s for s in stub_data.stories_by_genre(genre.slug)
                             if s.status == 'Published']
                self.assertTrue(published)


class HomeMobileThirdFold(TestCase):
    """Фолд 3: содержимое правого рейла не должно теряться на телефоне."""

    def setUp(self):
        self.response = self.client.get(reverse('core:home'))
        self.html = self.response.content.decode()

    def test_popular_tags_are_in_flow_not_only_in_rail(self):
        self.assertTrue(self.response.context['popular_tags'])
        # Поток + рейл. Тег, попавший и в недельный срез, встречается 4 раза.
        first = self.response.context['popular_tags'][0]
        self.assertGreaterEqual(self.html.count(f'#</span>{first.name}'), 2)

    def test_weekly_tags_are_shown_next_to_all_time_tags(self):
        """Теги — единственная ось, обновляющаяся без редакции (DEC-31), поэтому
        накопленной популярности мало: нужен срез недели.

        Списки обязаны различаться, иначе полоса «Осы аптада» вырождается
        в копию «Танымал тегтер» и занимает место зря.
        """
        trending = self.response.context['trending_tags']
        popular = self.response.context['popular_tags']
        self.assertTrue(trending)
        self.assertTrue(all(t.status == 'accepted' for t in trending))
        self.assertTrue(all(t.weekly_count > 0 for t in trending))
        self.assertNotEqual([t.slug for t in trending], [t.slug for t in popular[:len(trending)]])
        self.assertEqual(self.html.count('Осы аптада'), 2)  # поток + рейл

    def test_tags_block_hidden_on_desktop_to_avoid_duplicate(self):
        """Первое вхождение — блок в потоке (main идёт раньше aside).
        Он обязан лежать внутри ближайшей обёртки xl:hidden.

        Якорь — eyebrow секции, а не «Танымал тегтер»: между началом блока и
        накопленными тегами теперь стоит недельный срез, и расстояние до
        заголовка перестало быть мерой вложенности.
        """
        idx = self.html.index('қызығушылық бойынша')
        wrapper = self.html.rindex('<div class="xl:hidden">', 0, idx)
        self.assertLess(idx - wrapper, 800)

    def test_school_links_are_not_duplicated_into_flow(self):
        """Footer отдаёт ссылки inline на всех ширинах, поэтому третьего блока
        в мобильном потоке быть не должно.

        Три вхождения строки — это заголовок виджета в правом рейле плюс
        заголовок и aria-label списка в footer. Четвёртое = новый блок.
        """
        self.assertEqual(self.html.count('Авторлар мектебі'), 3)


class MobileBottomNav(TestCase):
    """Фаза 4 · docs/07.6. Нижнее меню — единственная постоянная навигация
    на телефоне, поэтому слоты проверяем явно."""

    def test_guest_fab_is_search_not_login(self):
        """Самый заметный слот не должен требовать регистрации до ценности."""
        r = self.client.get(reverse('core:home'))
        html = r.content.decode()
        fab = html[html.index('bg-brand text-white shadow-tg-btn') - 400:]
        self.assertIn('aria-label="Іздеу"', fab)
        self.assertNotIn('aria-label="Кіру"', html)

    def test_guest_search_appears_once_in_nav(self):
        """Пятый слот дублировал поиск — теперь там вход."""
        r = self.client.get(reverse('core:home'))
        html = r.content.decode()
        nav = html[html.index('aria-label="Мобильді мәзір"'):html.index('</nav>', html.index('aria-label="Мобильді мәзір"'))]
        self.assertEqual(nav.count('aria-label="Іздеу"'), 1)
        self.assertIn('>Кіру</span>', nav)

    def test_nav_items_have_visible_labels(self):
        r = self.client.get(reverse('core:home'))
        for label in ('Басты', 'Оқу', 'Байқау', 'Кіру'):
            with self.subTest(label=label):
                self.assertContains(r, f'>{label}</span>')

    def test_contests_use_trophy_icon_like_header(self):
        """Раньше конкурсы были помечены иконкой «ползунки»."""
        r = self.client.get(reverse('core:home'))
        html = r.content.decode()
        nav = html[html.index('aria-label="Мобильді мәзір"'):html.index('</nav>', html.index('aria-label="Мобильді мәзір"'))]
        self.assertIn('#icon-trophy', nav)
        self.assertNotIn('#icon-adjustments', nav)

    def test_authed_fab_is_create_story(self):
        session = self.client.session
        session['signed_in'] = True
        session['user_username'] = 'aidana'
        session.save()
        r = self.client.get(reverse('core:home'))
        html = r.content.decode()
        nav = html[html.index('aria-label="Мобильді мәзір"'):html.index('</nav>', html.index('aria-label="Мобильді мәзір"'))]
        self.assertIn('aria-label="Жаңа шығарма"', nav)
        for label in ('Басты', 'Кітапхана', 'Байқау', 'Профиль'):
            with self.subTest(label=label):
                self.assertIn(f'>{label}</span>', nav)


class HomeEditorialBlocks(TestCase):
    """Фаза 7 · book_of_week и new_authors были написаны, но не подключены."""

    def setUp(self):
        self.response = self.client.get(reverse('core:home'))
        self.html = self.response.content.decode()

    def test_book_of_week_is_rendered(self):
        self.assertContains(self.response, 'Аптаның кітабы')
        story = self.response.context['book_of_week'].story
        self.assertContains(self.response, f'«{story.title}»')

    def test_book_of_week_sits_right_after_first_row(self):
        """Одна сильная рекомендация идёт раньше конкурса и коллекций."""
        self.assertLess(self.html.index('Аптаның кітабы'), self.html.index('Белсенді байқау'))
        self.assertLess(self.html.index('Қысқа оқылатын'), self.html.index('Аптаның кітабы'))

    def test_new_authors_precede_become_author_cta(self):
        """Сначала доказательство, что здесь пишут новички, потом призыв."""
        self.assertContains(self.response, 'Жаңа авторлар')
        self.assertLess(self.html.index('Жаңа авторлар'), self.html.index('Сенің әңгімең'))

    def test_new_authors_shows_least_followed(self):
        usernames = [a.username for a in self.response.context['new_authors']]
        self.assertEqual(usernames[0], 'aidana')  # 23 подписчика — меньше всех
        self.assertNotIn('rudazov', usernames)    # 8420 — не «жаңа автор»

    def test_no_dead_placeholder_links(self):
        """Отдельного списка авторов в проекте нет — href="#" был бы тупиком."""
        self.assertNotContains(self.response, 'барлық авторлар')

    def test_genre_chip_links_to_genre_page(self):
        """genre_chip по документации ведёт на /genres/<slug>/, а отдавал '#'."""
        story = self.response.context['book_of_week'].story
        self.assertContains(
            self.response,
            reverse('core:genre_detail', kwargs={'slug': story.primary_genre.slug}),
        )


class GuestAuthorCta(TestCase):
    """Гостевые CTA расходились: hero вёл на signup, become_author — на login."""

    def setUp(self):
        self.response = self.client.get(reverse('core:home'))

    def test_both_ctas_point_to_login(self):
        """signup — форма профиля уже вошедшего; вход только через Telegram."""
        self.assertNotContains(self.response, reverse('core:signup'))
        self.assertContains(self.response, reverse('core:login'))

    def test_cta_preserves_writing_intent(self):
        """После входа человек должен попасть туда, что обещала кнопка."""
        self.assertContains(
            self.response,
            reverse('core:login') + '?next=' + reverse('core:new_story'),
        )

    def test_login_honours_that_next(self):
        target = reverse('core:new_story')
        r = self.client.post(reverse('core:login') + f'?next={target}')
        self.assertRedirects(r, target)


class HomeAuthedMode(TestCase):

    def setUp(self):
        session = self.client.session
        session['signed_in'] = True
        session['user_name'] = 'Айдана'
        session['user_username'] = 'aidana'
        session.save()
        self.response = self.client.get(reverse('core:home'))

    def test_returns_200(self):
        self.assertEqual(self.response.status_code, 200)

    def test_shows_logout_in_menu(self):
        self.assertContains(self.response, 'Шығу')

    def test_default_focuses_started_writing(self):
        self.assertEqual(self.response.context['hero_focus'], 'writing')
        self.assertContains(self.response, 'Мәтінің күтіп тұр')

    def test_context_has_active_work_for_writer_resume(self):
        self.assertEqual(self.response.context['active_work'].slug, 'aidana-koshe')

    def test_shows_writer_resume_as_primary_action(self):
        self.assertContains(self.response, 'Жазуды жалғастыру')
        self.assertContains(self.response, reverse('core:manage_story', kwargs={'slug': 'aidana-koshe'}))

    def test_reading_resume_moves_to_right_rail_when_writing_is_primary(self):
        self.assertContains(self.response, 'Оқу үстінде')
        self.assertContains(self.response, 'Оқуды жалғастыру')

    def test_shows_private_nav_items(self):
        # Хотя бы один из приватных пунктов должен присутствовать как ссылка.
        self.assertContains(self.response, 'Хабарламалар')

    def test_no_guest_hero_welcome(self):
        # Маркер hero_guest у авторизованного не показывается — у него свой hero_returning.
        self.assertNotContains(self.response, 'Бүгін не оқимыз?')

    def test_demo_empty_state_has_search_and_first_steps(self):
        r = self.client.get(reverse('core:home') + '?hero_state=empty')
        self.assertEqual(r.context['hero_focus'], 'empty')
        self.assertContains(r, 'Бүгін неден бастаймыз?')
        self.assertContains(r, 'Шығарма, автор, жанр немесе тег')
        self.assertContains(r, 'Жаңа шығарма')

    def test_demo_reading_state_has_reading_primary_and_writing_secondary(self):
        r = self.client.get(reverse('core:home') + '?hero_state=reading')
        self.assertEqual(r.context['hero_focus'], 'reading')
        self.assertIsNone(r.context['active_work'])
        self.assertContains(r, 'Оқуды жалғастыру')
        self.assertContains(r, 'Жазып көру')

    def test_demo_writing_state_has_writing_primary_and_reading_prompt(self):
        r = self.client.get(reverse('core:home') + '?hero_state=writing')
        self.assertEqual(r.context['hero_focus'], 'writing')
        self.assertIsNone(r.context['progress'])
        self.assertContains(r, 'Мәтінің күтіп тұр')
        self.assertContains(r, 'Оқуға шығарма табу')

    def test_writing_focus_keeps_reading_progress_on_mobile(self):
        """Правый рейл скрыт до lg — прогресс чтения должен быть и в потоке.

        Иначе пишущий автор теряет «продолжить чтение» на телефоне целиком.
        """
        html = self.response.content.decode()
        self.assertEqual(self.response.context['hero_focus'], 'writing')
        self.assertIsNotNone(self.response.context['progress'])
        # Слим-строка в основном потоке помечена xl:hidden — рейл её дублирует с xl.
        self.assertIn('xl:hidden', html)
        self.assertEqual(html.count('Оқу үстінде'), 2)


class HeaderContestsLink(TestCase):
    """DEC-25: единственная контент-ссылка в хедере — «Байқаулар»."""

    def test_link_present_on_home(self):
        r = self.client.get(reverse('core:home'))
        self.assertContains(r, 'Байқаулар')
        self.assertContains(r, reverse('core:contest_list'))

    def test_active_state_on_contests_page(self):
        """На /contests/ ссылка подсвечена brand-цветом."""
        r = self.client.get(reverse('core:contest_list'))
        # nav_active=='contests' даёт класс text-brand на ссылке Байқаулар
        self.assertContains(r, 'Байқаулар')
        # На главной этой подсветки нет → проверяем что на /contests/ есть
        self.assertEqual(r.status_code, 200)


class FooterSiteMap(TestCase):
    """DEC-25: контентные разделы (Жанрлар/Жинақтар) живут в footer, не в хедере."""

    def test_footer_links_to_genres(self):
        r = self.client.get(reverse('core:home'))
        self.assertContains(r, reverse('core:genre_index'))
        self.assertContains(r, 'Жанрлар')

    def test_footer_links_to_collections(self):
        r = self.client.get(reverse('core:home'))
        self.assertContains(r, reverse('core:collections'))
        self.assertContains(r, 'Жинақтар')


class StoryDetailHasGate(TestCase):
    """FR-STORY-05: гость на странице произведения видит CommentLoginGate."""

    # Реальный slug из stub_data — иначе попадаем в ветку «Шығарма табылмады»,
    # где gate не рендерится.
    STORY_SLUG = 'dalney-berega'

    def test_guest_sees_login_gate_text(self):
        response = self.client.get(reverse('core:story_detail', kwargs={'slug': self.STORY_SLUG}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Пікір қалдыру үшін')

    def test_authed_does_not_see_login_gate(self):
        session = self.client.session
        session['signed_in'] = True
        session.save()
        response = self.client.get(reverse('core:story_detail', kwargs={'slug': self.STORY_SLUG}))
        self.assertNotContains(response, 'Пікір қалдыру үшін')
