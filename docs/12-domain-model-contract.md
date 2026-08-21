# 12. Domain model contract for F14

> `Обновлён: 2026-08-21` · `Сверен с кодом: 855d37c`

This document is the implementation contract for replacing `core/stub_data.py` with real Django models. It does not introduce models yet; it fixes the fields, relationships, computed values, and query helpers that the current templates already depend on.

## 12.1 Product boundary

F14 replaces stub data with persisted data while preserving the current UX contract.

Primary scenarios:
- read and continue reading;
- search/filter the catalog;
- write and manage stories;
- submit a story to a contest.

Secondary scenarios stay minimal until real usage exists:
- followers/following;
- notifications;
- comment replies and comment likes;
- popularity-based tag ranking.

## 12.2 Core models

Fields are **not listed here.** Every stub dataclass is in `core/stub_data.py`, twenty lines above the data it holds — a prose copy of those field lists would be a second source that silently rots, which is exactly what happened to §12.3 before this revision.

**`Story.recent_views` и `Story.updated_days_ago` в Ф14 не переносятся как есть.** Второе — дельта в днях от «сегодня», в бою это `updated_at` с `auto_now`: хранить дельту нельзя, она устаревает каждые сутки. В стабе она числом потому, что фиксированная дата «сегодня» ломала бы тесты через день. Заполнена только у произведений демо-автора — кабинет показывает своё, а `None` значит «не задано» и уходит в конец сортировки.

**`Story.recent_views` — про окно, а не про давность.** Это просмотры за 14 дней (DEC-36), в стабе — литерал, в бою — агрегат по логу просмотров с окном. Считать его от `views` нельзя: смысл оси в том, что она расходится с накопленным счётчиком. Инвариант `recent_views <= views` закрыт тестом `test_stub_data.RecentViewsAreConsistent`.

**`NEW_AUTHOR_FOLLOWERS = 150` — стаб-условная константа, не правило.** Авторов в стабе шесть, и любая граница между ними произвольна. В Ф14 «новое имя» должно определяться перцентилем по подписчикам или возрастом аккаунта, а не абсолютным числом: 150 подписчиков на портале из двухсот авторов и из двадцати тысяч означают разное. Число не наследовать.

What the table carries instead is the part `stub_data.py` cannot state: what must survive the migration and why.

| Model | Stub source | Must survive F14 |
|-------|-------------|------------------|
| **User / Author** | `Author` | DEC-01 holds: no separate Reader role — any signed-in user reads, writes, comments, saves and submits. Follows stay a small relation and must not drive navigation |
| **Genre** | `Genre` | Closed reference of 12 (DEC-11). `/genres/` is an overview page, `/catalog/` the primary reading entry, `/genres/<slug>/` a catalog filter entry — **not** a separate engine (DEC-27) |
| **Tag** | `Tag`, `TAGS`, `BLOCKED_TAG_PATTERNS` | Up to 10 per story (BR-TAG-01). `status`: `pending` / `accepted` / `rejected`. Pending visible to the author, hidden from public catalog and story views (BR-TAG-07). Blocked patterns stay admin-managed |
| **Story** | `Story` | `OnProcess` is a continuation state, **not** a moderation state. Public catalog carries only `Published` and explicitly allowed public states. `format` is chosen by the author, never inferred from chapter count (DEC-28). Status labels — `components/status_badge.html`, see [16 §16.3](16-content-voice.md) |
| **Chapter** | `Chapter`, `CHAPTERS_BY_STORY` | One-based numbers. Bodies live **outside** `stub_data.py` in `core/story_texts/<slug>/<n>.txt`; `_chapter()` loads them and derives `char_count`. Keep long prose out of the data module. Read via `?chapter=N` — no separate route (DEC-30). **`Story.chapters` не может обещать больше, чем есть записей**: запись главы обязана нести текст, поэтому произведение без текста несёт `chapters=0`, а не пустые главы. Закрыто `test_stub_data.DeclaredChapterCountMatchesLoadedChapters`, там же заморожен список каталожных сериалов, которым текст ещё не написан |
| **Collection** | `Collection` | Ordered many-to-many with `Story`. Editorial curation by a moderator, not a smart auto-filter, and separate from contests (DEC-27). **Admin-authored only** — there is no user-created collection (DEC-31); `count` and `covers` are derived from `story_slugs`, never stored alongside it |
| **Contest** | `Contest` | `status`: `active` / `finished`. Separate from collections. Admin UI is Django admin for MVP (DEC-23) |
| **Submission** | `Submission` | One story per author per contest (BR-23). Eligibility is a query/service concern, never template logic (BR-22, BR-24) |
| **LibraryEntry** | `LibraryEntry` | `kind`: `saved` / `reading` / `done`, non-overlapping (BR-60/61). Continue-reading is a first-class reader workflow — it drives both the hero and the mobile nav |
| **Comment** | `StoryComment` | One reply level only (BR-30). Anchored to a chapter via `chapter_number`; `None` means the whole work. Reply form and comment-like persistence can wait |
| **Notification** | `Notification` | Secondary in MVP: header badge plus the notifications page are enough (BR-70…72) |

## 12.3 Query/service helpers to preserve

Current views rely on these helpers from `stub_data.py`. In F14 they should move to query/service functions, not into templates.

**Signatures below are the actual ones in the code.** Note that every helper takes a **string key** (`username`, `story_slug`, `genre_slug`, `contest_slug`), not a model object — stub dataclasses are frozen and unlinked. F14 may switch these to objects, but that is a deliberate signature change touching every call site, not a free refactor.

Catalog and search:
- `filter_catalog(*, query="", genre="", tag="", status="", sort="trending", audience="", length="", format="", badge="", author_tier="", kind="") -> list[Story]`
- `apply_catalog_filters(stories, sort="trending", status="", ..., badge="", author_tier="", kind="") -> list[Story]`
- `stories_by_genre(genre_slug: str) -> list[Story]`
- `PUBLIC_STATUSES` — статусы, видимые публике (DEC-23). `filter_catalog` режет по ним на входе
- `is_new_author(username) -> bool`, `NEW_AUTHOR_FOLLOWERS`, `CATALOG_AUTHOR_FILTERS` — ось «Автор» (FR-CAT-13)
- `AUDIENCE_ORDER` — отметки от младшей к старшей; ось «Жасың» сравнивает по индексу, не по равенству (DEC-38)
- `CATALOG_KIND_FILTERS`, `KIND_PREDICATES` — ось «Түрі» (DEC-37). Правило «у публичного сериала не бывает `Published`» — BR-10a; `writer_stats` считает `published` как `Published` + `Completed`, ключ `ongoing` (бывший `drafts`) считает `OnProcess`
- `CATALOG_PRESETS`, `STORY_BADGES` / `BADGE_LABELS`, `CATALOG_BADGE_FILTERS`, `CATALOG_DEFAULT_SORT` — справочники осей каталога
- `search_stories(query: str) -> list[Story]`
- `search_authors(query: str, limit=5) -> list[Author]`
- `related_stories(slug: str, limit=6) -> list[Story]`

Story and chapters:
- `chapters_of(story_slug: str) -> list[Chapter]`
- `chapter_of(story_slug: str, number: int) -> Chapter | None`
- `Story.is_public -> bool` — видна ли работа читателю. По `PUBLIC_STATUSES`, а не по литералу `'Published'` (DEC-37)
- `Story.updated_label -> str` — «кеше», «3 күн бұрын»; пусто, когда `updated_days_ago` не задан
- `writer_attention(username: str) -> list[dict]` — сигналы кабинета (FR-WRITE-08): `kind` / `count` / `slug`. Только данные; ссылку строит view (`_attention_links`), как и в каталоге
- `Story.text_chapter -> int | None` — номер главы с текстом одночастного произведения; None у сериала и у `single` без текста. Кнопка «Мәтін» / «Мәтінді өңдеу» обязана вести туда, а не в `chapter_new`: у `single` глава ровно одна, и пустой редактор давал автору сохранить вторую
- `comments_of(story_slug: str) -> list[StoryComment]`
- `comments_of_chapter(story_slug: str, chapter_number: int) -> list[StoryComment]`
- `reactions_of(chapter: Chapter) -> list[dict]` — полный ряд из пяти реакций, включая нулевые (BR-REACT-01)
- `reaction_breakdown(story_slug: str) -> list[dict]` — «чем зацепила каждая глава», для авторского кабинета
- `poll_of(story_slug: str, chapter_number: int) -> ChapterPoll | None` — опрос необязателен (BR-POLL-01)

Author workspace, library, social:
- `my_stories_of(username: str) -> list[Story]` — **любой** статус: выдача авторского кабинета, не публичная
- `public_stories_of(username: str) -> list[Story]` — только `is_public` (BR-73). Публичный профиль строится на ней; на `my_stories_of` он показывал посторонним черновики
- `writer_stats(username: str) -> dict`
- `library_of(username: str, kind: str = "") -> list[LibraryEntry]`
- `in_library(username: str, story_slug: str) -> bool`
- `public_stats(username: str) -> dict` — `works` / `reads` / `likes` / `followers` по публичным работам (FR-PROF-01). `works` совпадает с `Author.works` по построению
- `reader_stats(username: str) -> dict` — `public_stats` плюс приватное: `works_total` (с черновиками), `finished` (дочитано, из библиотеки). Ключ `read` переименован в `finished`, чтобы не путаться с `reads`
- `is_following(me: str, them: str) -> bool`
- `following_of(username: str) -> list[Author]`
- `followers_of(username: str) -> list[Author]`
- `notifications_for_user(username: str) -> dict`
- `unread_count_for_user(username: str) -> int`

Contests:
- `submissions_of(username: str) -> list[Submission]`
- `has_submission(username: str, contest_slug: str) -> bool`
- `submission_checklist(story: Story, contest: Contest) -> list`
- `eligible_for_contest(username: str, contest_slug: str) -> list[Story]`

Tags (module 11):
- `tag_by_slug(slug: str) -> Tag | None`
- `tags_of(story: Story) -> list[Tag]`
- `popular_tags(limit=10) -> list[Tag]` — all-time, by `usage_count`
- `trending_tags(limit=6) -> list[Tag]` — last 7 days, by `weekly_count`; skips tags with no weekly activity (DEC-31)
- `is_blocked(name: str) -> bool`
- `accepted_tags_json() -> list`
- `blocked_tag_patterns_list() -> list`

Collections (DEC-31):
- `collections_of(story: Story) -> list[Collection]` — reverse entry from the story page, in editorial order

Home page:
- `portal_stats() -> dict` — counters in the guest hero (FR-HOME-01)
- `new_authors(limit=4) -> list[Author]`

## 12.4 Template contract

Templates should continue receiving objects with these attributes:

Story — stored fields plus computed properties. In the stubs the computed ones are `@property` on the dataclass; after F14 they may become model properties, annotations, or denormalised columns, but the template-facing names must not change.

- stored: `slug`, `title`, `cover`, `annotation`, `status`, `audience`, `badges`, `chapters`, `views`, `likes`, `comments`
- resolved relations: `author`, `primary_genre`, `genres_resolved`, `tags_resolved`
- format (DEC-28): `format`, `format_label`, `format_badge_label`, `is_single`, `is_serial`, `text_chapter`
- статус и время: `is_public`, `updated_days_ago`, `updated_label`
- reading effort: `total_chars`, `read_minutes`, `length_bucket`, `reading_meta_label`

Author:
- `username`, `name`, `bio`, `followers`
- `joined_year` — год прихода на платформу («2024 жылдан бері»). Единственный факт профиля, который нельзя вывести из данных. Год, а не полная дата: подростку важно «давно или недавно», а точная дата — лишние персональные данные
- `works` — **производное**, как `Collection.count`: число публичных работ автора. Было хранимым литералом и врало у всех шести авторов сразу, а рендерится в шести местах, включая карточку автора на странице произведения. Черновики в него не входят (BR-10: публично не видны)

Contest:
- `winners: tuple[str]` — слаги **произведений**-победителей, не имена авторов; автор выводится через `Story.author_username`. Второй литерал с именем разошёлся бы с первым ровно так же, как хранимый `Author.works` разошёлся с числом произведений. У active-конкурса пусто
- `winner_stories` — производное: `Story` по слагам, неизвестные молча отбрасываются

Genre:
- `slug`, `name`, `hue`, `icon`, `count`

Tag:
- `slug`, `name`, `status`, `usage_count`

## 12.5 Migration order

1. Create read-only models and seed data equivalent to stubs.
2. Replace catalog queries first.
3. Replace story detail and chapters.
4. Replace library/progress.
5. Replace write dashboard with real user-owned stories.
6. Replace contests/submissions.
7. Replace comments and notifications.
8. Remove `stub_data.py` only after all tests pass against models.

## 12.6 Test contract

Existing tests are the behavior contract. During F14:

- keep route smoke tests passing;
- keep catalog/search/genre/tag behavior stable;
- keep story detail `?chapter=N` behavior stable;
- preserve pending tag visibility rules;
- preserve guest vs signed-in navigation surfaces;
- add model tests before deleting the corresponding stub helper.
