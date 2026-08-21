# 14 · Карта реализации: требование → код

> `Обновлён: 2026-08-21` · `Сверен с кодом: f1f896b`

Этот документ отвечает на два вопроса, на которые остальное ТЗ не отвечает: **где живёт то, что описано требованием**, и **что придётся обновить, если это изменить**.

Он существует потому, что за три месяца ТЗ разошлось с кодом в тринадцати местах, и ни одно расхождение не было заметно при чтении документов. Карта делает связь явной: меняя view или шаблон, видно, какие FR/BR/DEC затрагиваются; читая требование, видно, чем оно реализовано и чем закрыто тестом.

> **Правило сопровождения.** Изменение, затрагивающее FR / BR / DEC, обновляет соответствующий модуль ТЗ **в том же коммите**. Карта — место, где проверяется, какой именно модуль.

---

## 14.1 Топология проекта

Расклад слоёв — фактический, не целевой (DEC-29).

| Слой | Где | Правило |
|------|-----|---------|
| Данные | `core/stub_data.py` + `core/story_texts/` | Python-литералы. После Ф14 — Django-модели, контракт в [12](12-domain-model-contract.md) |
| View | `core/views.py` (≈40 функций) | **Тонкие**: читают из `stub_data`, собирают контекст, рендерят. Бизнес-логики нет |
| Маршруты | `core/urls.py`, `app_name='core'` | Все URL проекта, кроме `/admin/` |
| Общий контекст | `core/context_processors.py` | `auth_state`, `nav_state`, `site_links` |
| Фильтры | `core/templatetags/balaproza.py` | `compact_count`, `spaced`, `page_range` |
| Шаблоны | корневая `templates/` (109 файлов) | 50 компонентов · 28 партиалов · 27 страниц · `base.html` · `404/500` |
| Токены | `static_src/input.css`, блок `@theme` | Единственный источник цветов, радиусов, теней ([02](02-design-system.md)) |
| Тесты | `core/tests/` (16 файлов, 425 тестов) | Контракт поведения, описан в [15](15-testing-contract.md) |

**Шаблоны — не в `core/templates/`, а в корневой `templates/`.** Это задано `TEMPLATES.DIRS` в `config/settings.py`.

### Сквозные механизмы `base.html`

Подключены один раз и доступны всем страницам:

| Механизм | Файл | Как пользоваться |
|----------|------|------------------|
| Спрайт иконок | `components/icons/_sprite.html` | `{% include "components/icon.html" with name="..." size=... %}` |
| Тосты | `components/toast_host.html` | `$dispatch('toast', {kind, text})` |
| Quick-search | `components/search_popup.html` | Cmd+K или `$dispatch('open-search')` |
| Правый рейл | блок `right_rail` | Рендерится только при `has_right_rail=True` в контексте |

### Глобальные Alpine-события

| Событие | Payload | Кто слушает |
|---------|---------|-------------|
| `toast` | `{kind: success\|info\|warning\|error, text}` | `toast_host` |
| `open-search` | — | `search_popup` |
| `open-report` | `{target: 'story:slug'}` | `report_modal` |
| `open-catalog-filters` | — | `catalog/_filter_sheet` |
| `open-delete-confirm` | `{name, confirm_url}` | `delete_confirm_modal` |

---

## 14.2 AUTH · Авторизация

| Требование | View | Шаблон | Тест |
|-----------|------|--------|------|
| FR-AUTH-01, 02 | `login_view` | `pages/auth/login.html` | `test_auth.LoginFlow`, `test_auth_links.LoginPage` |
| FR-AUTH-03…06 | `signup`, `signup_success` | `pages/auth/signup.html`, `signup_success.html` | `test_auth.SignupFlow`, `test_auth_links.SignupPage/SignupSuccessPage` |
| FR-AUTH-07 | context processor `auth_state` | `partials/header.html` | `test_context.AuthState` |

**Стаб-авторизация.** Модели `User` нет. `login_view` кладёт в сессию `signed_in`, `user_name`, `user_username` (по умолчанию `aidana`). `auth_state` отдаёт в шаблоны `signed_in`, `current_user_name`, `current_user_username`, `unread_notifications`.

Защита от open-redirect — `_safe_next(request)`: принимает только относительные пути, отвергает `//evil.com/`. Это не декоративная проверка, а закрытый тестом инвариант (`test_auth`).

## 14.3 HOME · Главная

Один view `home`, одна страница `pages/home.html`, десять партиалов в `partials/home/`.

| Требование | Партиал | Тест |
|-----------|---------|------|
| FR-HOME-01 (гость) | `partials/home/hero_guest.html` | `test_home.HomeGuestMode` |
| FR-HOME-01 (авторизованный, 3 режима `hero_focus`) | `partials/home/hero_returning.html` | `test_home.HomeAuthedMode` |
| FR-HOME-02 (короткие) | `partials/home/book_row.html` | `test_home.HomeMobileFirstFold` |
| FR-HOME-03 (книга недели) | `partials/home/book_of_week.html` | `test_home.HomeEditorialBlocks` |
| FR-HOME-04 (конкурс) | `partials/home/contest_banner.html` | `test_home.HomeMobileSecondFold` |
| FR-HOME-05 (жинақтар — главный вход) | `partials/home/collections.html` | `test_home.HomeEditorialBlocks`, `test_catalog.CollectionsAreAdminOnly` |
| FR-HOME-06 (жанровая полоса-вывеска) | `partials/home/genre_strip.html` | `test_home.HomeMobileSecondFold` |
| FR-HOME-07 (ещё два ряда) | `partials/home/book_row.html` | `test_desktop_layout.HomeRowSize` |
| FR-HOME-08 (теги: неделя + всё время) | `partials/home/popular_tags.html` | `test_home.HomeMobileThirdFold` |
| FR-HOME-09 (новые авторы) | `partials/home/new_authors.html` | `test_home.HomeMobileThirdFold` |
| FR-HOME-10 (CTA) | `partials/home/become_author.html` | `test_home.GuestAuthorCta` |
| FR-HOME-11 (рейл) | `partials/right_rail/home.html` | `test_desktop_layout.RailContentHasMobileEquivalent` |
| FR-HOME-12 (состояния) | скелетоны в `pages/home.html` | `test_states.HomeStates` |

**Инвариант дублей.** Всё, что показывает рейл, обязано быть доступно и без него: рейл виден только с `xl`. Дубли в потоке помечены `xl:hidden` (FR-HOME-04, FR-HOME-08). Ломается это тихо — блок либо пропадает на планшете, либо показывается дважды на десктопе, — поэтому оба направления закрыты тестами `RailContentHasMobileEquivalent` и `ProfileStatsNotDuplicated`.

## 14.4 CAT · Каталог, поиск, теги

**Один движок на четыре режима** (DEC-27). Это главное архитектурное решение раздела: `_render_catalog(request, *, mode, genre_slug='', tag_slug='')` в `core/views.py`, поверх него четыре тонкие обёртки.

| URL | View-обёртка | `mode` | Hero-партиал |
|-----|--------------|--------|--------------|
| `/catalog/` | `catalog` | `catalog` | `partials/catalog/_hero_catalog.html` |
| `/search/?q=` | `search_results` | `search` | `partials/catalog/_hero_search.html` |
| `/genres/<slug>/` | `genre_detail` | `genre` | `partials/catalog/_hero_genre.html` |
| `/tag/<slug>/` | `tag_detail` | `tag` | `partials/catalog/_hero_tag.html` |

Все четыре рендерят **один** шаблон `pages/catalog/catalog.html`. Прежние `search_results.html` и `genre_detail.html` удалены — если понадобится пятый режим, добавляется hero-партиал и обёртка, но не копия страницы.

| Требование | Реализация | Тест |
|-----------|-----------|------|
| FR-CAT-01, 02 | `filter_catalog(query=, genre=)` | `test_catalog.SearchResults*`, `SearchByAuthorName` |
| FR-CAT-03 | `genre_index` → `pages/catalog/genre_index.html` | `test_catalog.GenreIndex` |
| FR-CAT-04 | `collections`, `collection_detail` | `test_catalog.CollectionsList`, `CollectionDetail*` |
| FR-CAT-05 | фильтр `page_range` | `test_filters.PageRange` |
| FR-CAT-06 | `search_index_json` → `/api/search-index.json` | `test_catalog.SearchIndexHasTags` |
| FR-CAT-07 | `partials/catalog/_filter_panel.html` + `_filter_sheet.html` | `test_catalog.CatalogFilterHelper`, `TagsInFilterPanel` |
| Комбинации фильтров | `/genres/triller/?tag=mektep` | `test_catalog.CatalogFilterCombination` |

**Коллекции сознательно не входят в движок** — это editorial curation, отдельный content type. Они переиспользуют только `partials/catalog/_book_list.html` (DEC-27).

Теги (модуль [11](11-tags.md)): `components/tag_chip.html`, `tag_list.html`, `tag_input.html`. Правило BR-TAG-07 (pending скрыты от публики) реализовано в `tag_list.html` через параметр `viewer_is_author`, закрыто `test_catalog.TagDetailPendingBlocked` и `test_story.StoryDetailTags`.

## 14.5 STORY · Произведение и чтение

**Одна страница на всё** (DEC-30): `story_detail` → `pages/story/story_detail.html`. Отдельного маршрута чтения нет, глава открывается через `?chapter=N`.

| Требование | Реализация | Тест |
|-----------|-----------|------|
| FR-STORY-01, 02 | шапка + секции страницы | `test_story.StoryDetailValidSlug` |
| FR-STORY-03 | sticky scrollspy (IntersectionObserver) | `test_story.StoryDetailValidSlug` |
| FR-STORY-04 | оглавление глав + прогресс | `test_story.StoryDetailReadingProgress` |
| FR-STORY-05 | `components/comment.html`, `CommentLoginGate` | `test_story.StoryDetailGuestVsAuth`, `test_home.StoryDetailHasGate` |
| FR-STORY-06 | `?chapter=N`, prev/next через `?chapter=N±1` | `test_story.StoryDetailChapterParam` |
| FR-STORY-07, 08 | Alpine: `readerSize` / `readerWidth` / `readerTheme` | — |
| FR-STORY-09 | `components/report_modal.html`, событие `open-report` | `test_story.StoryDetailGuestVsAuth` |
| FR-STORY-10 | `components/share_button.html` | — |
| FR-STORY-11 | `related_stories(slug, limit=6)` | `test_stub_data.StoryRelations` |
| FR-STORY-12 | `components/chapter_like.html` | — |
| DEC-28 (`single` vs `serial`) | `story.is_single` / `is_serial` | `test_story.StoryDetailSingleWork` |
| Комментарии к главе | `comments_of_chapter(slug, n)` | `test_story.StoryDetailPerChapterComments` |

> **Пробел в покрытии.** FR-STORY-07/08 (настройки чтения), FR-STORY-10 (share) и FR-STORY-12 (лайк главы) тестами не закрыты — это чистый Alpine-клиент, серверный рендер про него ничего не знает. Изменение классов `reader-*` или разметки лайка сейчас не поймается. Кандидат на добавление проверок разметки.

## 14.6 WRITE · Авторский кабинет

| Требование | View | Шаблон | Тест |
|-----------|------|--------|------|
| FR-WRITE-01 | `new_story` | `pages/write/new_story.html` | `test_write.NewStoryForm`, `TagInputOnNewStory` |
| FR-WRITE-02 | `my_stories` | `pages/write/my_stories.html` | `test_write.MyStoriesAuthedHasItems`, `MyStoriesAuthedEmpty` |
| FR-WRITE-03 | `manage_story` | `pages/write/manage_story.html` | `test_write.ManageStoryKnown`, `ManageStoryEmptyChapters` |
| FR-WRITE-04 | `story_settings` | `pages/write/story_settings.html` | `test_write.StorySettingsForm`, `TagInputOnStorySettings` |
| FR-WRITE-05 | `chapter_editor` | `pages/write/chapter_editor.html` | `test_write.ChapterEditorNew`, `ChapterEditorEdit` |
| FR-WRITE-06 | `components/delete_confirm_modal.html` | — | — |
| FR-WRITE-07 / BR-10, BR-11 | `Story.status` | `components/status_badge.html` | `test_write.MyStoriesAuthedHasItems` |

Все страницы раздела требуют авторизации и для гостя отдают gate — закрыто `MyStoriesGuest`, `NewStoryGuestSeesGate`.

## 14.7 PROF / LIB / NOTIF

| Требование | View | Тест |
|-----------|------|------|
| FR-PROF-01, 03 | `profile_me` (+ `_resolve_prof_tab`, `_prof_items`) | `test_prof_lib_notif.ProfileMeAuthed` |
| FR-PROF-02, 04 | `profile_other` | `ProfileOtherKnown`, `FollowGraph` |
| FR-PROF-05 | `profile_me_edit` → `/me/edit/` | `ProfileMeAuthed` |
| FR-LIB-01…03 / BR-60, BR-61 | `library` + `segmented_control` | `LibraryAuthed`, `LibraryEmpty`, `LibraryHelpers` |
| FR-NOTIF-01…04 / BR-70…72 | `notifications` | `NotificationsAuthed`, `NotificationsEmpty` |
| FR-NOTIF-02 (бейдж) | `auth_state.unread_notifications` | `HeaderUnreadBadge` |

Переключение вкладок — реальный `?tab=` через `components/segmented_control.html`, не псевдо-табы (DEC-15).

## 14.8 CONT · Конкурсы

| Требование | View | Тест |
|-----------|------|------|
| FR-CONT-01, 02 / BR-40 | `contest_list` | `test_contests.ContestList`, `ContestModel` |
| FR-CONT-03 / BR-42, BR-43 | `contest_detail` | `ContestDetailKnown`, `ContestDetailFinished` |
| FR-CONT-04 / BR-22 | `contest_submit` + `submission_checklist` | `ChecklistHelpers`, `ContestSubmitForm` |
| FR-CONT-05 / BR-23, BR-25 | `has_submission`, `eligible_for_contest` | `ContestSubmitAlreadyDone`, `ContestSubmitGuest` |
| FR-CONT-06 / BR-41 | `my_submissions` | `MySubmissionsAuthed`, `MySubmissionsEmpty` |
| FR-CONT-07 / BR-24 | порог объёма 5 000–15 000 знаков | `EligibleForContest` |
| DEC-21 (AI-декларация) | радио + `<details>` в `contest_submit.html` | `ContestSubmitForm` |
| DEC-24 (возраст) | чекбокс `confirm_age` | `ContestSubmitForm` |
| BR-42 (₸) | фильтр `spaced` | `test_desktop_layout.MoneyFormatting` |

## 14.9 LINKS, LEGAL, SYS

| Требование | Реализация | Тест |
|-----------|-----------|------|
| FR-LINKS-01…06 / BR-55…58 | `components/school_links.html` (3 layout), context processor `site_links` | `test_auth_links.SchoolLinks*` (4 класса) |
| FR-LEGAL-01…04 | `_legal(key)` + 5 обёрток → `pages/legal.html` | `test_urls_smoke` |
| FR-SYS-01 | `components/toast_host.html` | `test_urls_smoke` |
| FR-SYS-02 | `components/delete_confirm_modal.html` | — |
| FR-SYS-03 | единые `avatar`, `status_badge`, пагинация | `test_filters` |
| FR-SYS-04 / NFR-60 | `templates/404.html`, `500.html` | — |
| FR-SYS-05 / NFR-61 | favicon + theme-color в `base.html` | — |
| FR-SYS-06 | `search_index_json` | `test_catalog.SearchIndexHasTags` |
| DEC-17 | `skeleton_*`, `error_state`, `empty_state`, `?state=` | `test_states` (7 классов) |

`500.html` — **standalone**, без `extends base.html` и без context processors: иначе ошибка в процессоре роняет и саму страницу ошибки.

Showcase-маршруты `/_design/tokens/`, `/_design/components/`, `/_design/states/` доступны **только при `DEBUG=True`** — это закрыто `test_urls_smoke.DebugOnlyEnforcement`.

---

## 14.10 Обратная карта: что трогать, меняя код

Читается в обратную сторону — от файла к документам, которые придётся обновить.

| Меняешь | Обнови |
|---------|--------|
| `static_src/input.css` → `@theme` | [02](02-design-system.md) (имена и значения токенов) |
| OKLCH-значение в шаблоне | [03 §3.3](03-genre-color-system.md) — реестр ролей; новые пары `L C` без внесения запрещены |
| `partials/mobile_nav.html` | [07 §7.6](07-layout-navigation.md) — единственный авторитет; в [04 §4.7](04-component-library.md) только ссылка |
| `partials/header.html`, `footer.html` | [07 §7.2 / §7.5](07-layout-navigation.md) |
| Ширина контейнера, колонки контента или рейла в `base.html` | [07 §7.1](07-layout-navigation.md), [02 «Размеры каркаса»](02-design-system.md), константы в `test_desktop_layout.py` |
| Состав/порядок секций `pages/home.html` | [05 §5.2](05-functional-spec.md) FR-HOME-*, эта карта §14.3 |
| `_render_catalog`, `filter_catalog` | [05](05-functional-spec.md) FR-CAT-07 (таблица параметров), [12 §12.3](12-domain-model-contract.md) |
| Сигнатура хелпера в `stub_data.py` | [12 §12.3](12-domain-model-contract.md) |
| Поле/property на `Story` | [12 §12.4](12-domain-model-contract.md) |
| Новый маршрут в `core/urls.py` | [05 §5.13](05-functional-spec.md) (карта переходов), эта карта, `PUBLIC_URLS` в `test_urls_smoke.py` |
| Новый компонент в `templates/components/` | [04](04-component-library.md), счётчик в `CLAUDE.md` |
| Новый тест-файл | [15](15-testing-contract.md), счётчики в `README.md` и `CLAUDE.md` |
| Строка интерфейса | [16](16-content-voice.md) — тон, обращение на «сен» |
| `config/settings.py` | [17](17-deployment.md), [09 §9.7](09-nonfunctional.md) |
| Отмена/пересмотр решения | [10](10-resolved-decisions.md) — **новым DEC**, не правкой старого |

---

## 14.11 Незакрытые места

Честный список того, что реализовано, но не защищено, или описано, но не реализовано. Обновлять вместе с картой.

| Что | Статус |
|-----|--------|
| Настройки чтения, share-кнопка, лайк главы | Реализованы, тестами не закрыты (§14.5) |
| sRGB-fallback для OKLCH (DEC-12, NFR-41) | Не реализован; варианты решения в [03 §3.5](03-genre-color-system.md) |
| Вынос строк в локализацию (NFR-30) | Не реализовано, отложено осознанно |
| Гарнитура Serif в чтении (`--font-serif`) | Токен есть, применения нет — [02 §2.2](02-design-system.md) |
| Модерация тегов (Фаза 4 модуля 11) | После Ф14 — нужны модели |
| OG-метаданные, sitemap.xml, robots.txt (NFR-62, NFR-63) | Не сделано, обязательно к запуску |
| «Апта челленджі» из [13 §13.9](13-product-culture.md) | Запланировано, не реализовано |
