# 12. Domain model contract for F14

> `Обновлён: 2026-08-22` · `Сверен с кодом: 72aee26`

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
| **Contest** | `Contest` | Хранятся три даты (`opens_on` / `closes_on` / `results_on`); фаза, отсчёт, год и число заявок **выводятся** (DEC-45, BR-40a). Хранимого `status` нет и заводить его нельзя — это тот же класс поля, что `Author.works`. Повторяющийся конкурс — отдельный объект на каждый выпуск, связь через `series` (BR-47): у выпусков расходится всё, чем конкурс является. Separate from collections. Admin UI is Django admin for MVP (DEC-23) |
| **Submission** | `Submission` | One story per author per contest (BR-23). Eligibility is a query/service concern, never template logic (BR-22, BR-24). `submitted_on` is a date; the relative wording is derived (BR-41a) |
| **LibraryEntry** | `LibraryEntry` | `kind`: `saved` / `reading` / `done`, non-overlapping (BR-60/61). Continue-reading is a first-class reader workflow — it drives both the hero and the mobile nav |
| **Comment** | `StoryComment` | One reply level only (BR-30). Anchored to a chapter via `chapter_number`; `None` means the whole work. Reply form and comment-like persistence can wait |
| **Notification** | `Notification` | Secondary in MVP: header badge plus the notifications page are enough (BR-70…72). Stores when the event happened, not how long ago; every notification links to its subject (BR-70a, BR-72a) |

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
- `top_stories_of(username: str, limit: int = 3) -> list[Story]` — самые читаемые публичные работы автора, для рейла чужого профиля (FR-PROF-09). Сортировка по накопленному `views`, а не по `recent_views`: рейл отвечает «с чего начать», а не «что сейчас в моде». Не `related_stories` — тот, наоборот, исключает того же автора
- `writer_stats(username: str) -> dict`
- `library_of(username: str, kind: str = "") -> list[LibraryEntry]`
- `in_library(username: str, story_slug: str) -> bool`
- `public_stats(username: str) -> dict` — `works` / `reads` / `likes` / `followers` по публичным работам (FR-PROF-01). `works` совпадает с `Author.works` по построению
- `reader_stats(username: str) -> dict` — `public_stats` плюс приватное: `works_total` (с черновиками), `finished` (дочитано, из библиотеки). Ключ `read` переименован в `finished`, чтобы не путаться с `reads`
- `AWARDS` — реестр наград: `key` / `label` / `art` / `tier` / `hint` и предикат `earned`, принимающий username. **Условие лежит рядом с наградой**, а не в отдельном списке «как получить»: два описания одного правила однажды разошлись бы
- `award_catalog(username: str) -> list[dict]` — все награды с `earned` и `dim` (FR-PROF-08). Тот же реестр, что у публичного ряда, поэтому «что можно получить» не может разойтись с «что получено»
- `read_ladder(username: str) -> list[dict]` — ступени оқылым: `earned`, `is_next`, `left`
- `achievements_of(username: str) -> list[dict]` — награды автора (FR-PROF-06, BR-ACH-01): `key` / `label` / `art` / `tier`. `art` — слаг иллюстрации в `components/awards/_sprite.html`, `tier` — металл ступени (`AWARD_TIERS`). **Выводятся, не хранятся**; URL-ы слой данных не отдаёт
- `READ_TIER_ART` — ступень оқылым → (слаг рисунка, металл). Один рисунок-стела на четыре ступени: меняются число на табличке и металл
- `reads_total(username: str) -> int` — прочтения по публичным работам
- `tier_for(total: int) -> tuple | None`, `next_tier_for(total: int) -> tuple | None` — чистые функции над `READ_TIERS`, чтобы границы проверялись напрямую
- `read_tier(username: str)`, `next_read_tier(username: str)` — они же для автора
- `winning_stories_of(username: str) -> list[Story]` — работы автора, отмеченные наградой конкурса (по `AWARD_GRANTS`)
- `contest_awards_of(username: str) -> list[dict]` — награды конкурсов автора (DEC-46), свежие сверху: `key` / `title` / `image` / `contest` / `story` / `year` / `note`. Работа названа только пока публична (BR-73); сама награда остаётся — она принадлежит автору, а не видимости текста
- `is_following(me: str, them: str) -> bool`
- `following_of(username: str) -> list[Author]` — оба списка публичны (BR-75), страницу собирает `profile_people`
- `followers_of(username: str) -> list[Author]`
- `notifications_for_user(username: str) -> dict` — три бакета FR-NOTIF-01; событие старше недели не попадает ни в один (BR-70a)
- `unread_count_for_user(username: str) -> int` — считает то же, что показывается: скрытое старое уведомление в бейдж не идёт
- `kk_ago(days: int, hours: int | None = None) -> str` — «как давно» словами, одна формулировка на проект: её берут `Notification.when` и `Submission.submitted_label`

Contests:
- `submissions_of(username: str) -> list[Submission]`
- `has_submission(username: str, contest_slug: str) -> bool`
- `contest_history(username: str, *, is_self: bool = False) -> list[dict]` — конкурсная биография (FR-PROF-07). Правило видимости живёт здесь, а не в шаблоне (BR-74a): при `is_self=False` результат режется до победы/принятия, `note` приходит пустым, непубличная работа не называется. Второе место с тем же правилом однажды разошлось бы с первым
- `common_rules(contest: Contest) -> list[dict]` — правила, действующие на любом конкурсе: `{key, label, hint, per_work}`. Один источник для списка «Шарттар» на странице конкурса и для чек-листа подачи (BR-48a). `per_work=False` у правил про автора, а не про текст («Бір автор — бір өтінім»)
- `submission_checklist(story: Story, contest: Contest) -> list` — общая часть из `common_rules`, возрастной пункт только при непустом `eligibility_line` (BR-48). Пороги объёма берутся у конкурса, а не вписаны в подпись литералом (FR-CONT-07); числа проходят через `spaced_number`
- `spaced_number(value) -> str` — разряды через неразрывный пробел, канонический вид числа для автора. Живёт в слое данных, а не в фильтре `balaproza.spaced`: те же числа собираются и в подсказках чек-листа. Фильтр вызывает эту функцию — двух реализаций одной формы записи быть не должно
- `eligible_for_contest(username: str, contest_slug: str) -> list[dict]` — кандидаты на подачу: `{story, chars, eligible, reason, hint}`. Только публичные работы (BR-24); `reason` — ключ из `INELIGIBLE_REASONS` (`too_short` · `too_long` · `busy`), пустой у проходящей
- `busy_contest_of(username, story_slug, *, besides='') -> Contest | None` — незавершённый конкурс, который уже держит эту работу (BR-23a)
- `can_withdraw(username, contest_slug) -> bool` — можно ли отозвать заявку (BR-23b): идёт приём и статус `reviewing`

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

Contest — **хранятся три даты, остальное выводится** (DEC-45, BR-40a):
- `opens_on` / `closes_on` / `results_on: date` — открытие приёма, дедлайн, объявление итогов. Всё, что заводит админ по срокам. Инвариант: `opens_on <= closes_on < results_on`
- `phase` — производное: `upcoming` · `accepting` · `judging` · `finished`. Полей `status` нет
- `is_accepting` / `is_finished` — производные-предикаты. **Кнопку «Қатысу», баннер главной и доступ к форме подачи решает `is_accepting`**, бейдж работы «Байқауға қатысады» — `not is_finished`; смешивать их в одном «активен» нельзя
- `days_left` / `days_until_open` — производные, каждое не `None` ровно в своей фазе
- `year` — производное: год `results_on`. Нужен конкурсной биографии (FR-PROF-07): «1 жыл бұрын» из `Submission.submitted_relative` устаревает каждый день
- `submissions` — производное: число заявок по `SUBMISSIONS_BY_USER`. Было хранимым литералом и показывало «87» при одной настоящей заявке
- `opens_on_label` / `closes_on_label` / `results_on_label` — производные: дата в казахской короткой форме («9 қыр»). Своё форматирование, а не Django-фильтр `date`, который берёт месяцы из локали
- `timing_line` — производное: «что дальше и когда» одной строкой, у завершённого пусто. Спрашивают об этом из трёх мест (строка заявки, конкурсное уведомление, рейл), и собирать формулировку в шаблоне запрещено — первая версия стояла inline в `pages/contests/my_submissions.html`. Отсчёта в днях в строке нет: он протухает назавтра (BR-40a)
- `winners: tuple[str]` — слаги **произведений**-победителей, не имена авторов; автор выводится через `Story.author_username`. Второй литерал с именем разошёлся бы с первым ровно так же, как хранимый `Author.works` разошёлся с числом произведений. У незавершённого конкурса пусто
- `awards: tuple[ContestAward]` — номинации конкурса, произвольный набор (BR-44)
- `grants` — производное: присуждения этого конкурса в порядке номинаций
- `winners` — производное **от присуждений**, а не хранимый кортеж
- `winner_stories` — производное: `Story` по слагам, неизвестные молча отбрасываются
- `current_stage` / `next_stage` — производные: этап, идущий сейчас, и ближайший будущий. Нужны правому рейлу (FR-CONT-09) — «что идёт сейчас» единственное, чего нет в хиро
- `poster: str` — афиша, файл в `MEDIA_ROOT` (`contests/<slug>.<ext>`), грузит админ; пусто — типографическая афиша (BR-47a). Прежнее `cover` указывало в `static/img/bookN.jpg` — фотографию книжной обложки, к конкурсу отношения не имевшую
- `series: str` — слаг семейства повторяющегося конкурса (BR-47). Пусто — разовый
- `min_age` / `max_age: int | None` — возрастная вилка **этого конкурса** (BR-48). Любая граница может отсутствовать, обе — тоже. У платформы ценза нет и быть не может (DEC-47)
- `eligibility_line` — производное: «16-25 жас» · «18 жастан бастап» · «22 жасқа дейін» · пусто. Собирать её в шаблоне запрещено — её показывают три поверхности сразу
- `other_editions` — производное: другие выпуски того же семейства, свежие сверху. Связь по `series`, не по совпадению имён

ContestAward (BR-44, BR-46):
- `slug`, `title`, `image` (файл в `MEDIA_ROOT`, пусто — типографическая заглушка), `description`

AwardGrant (BR-45) — **хранится**, в отличие от системных знаков:
- `contest_slug`, `award_slug`, `story_slug`, `note`; автор выводится из работы

Submission (BR-41, BR-41a):
- `contest_slug`, `story_slug`, `submitted_on: date`, `status`, `note`
- `submitted_label` — производное: «5 күн бұрын» через `kk_ago()`. Хранимая строка `submitted_relative` не только устаревала, но и лгала проверяемо — «6 ай бұрын» у конкурса, закрывшегося в 2023-м
- инвариант: `contest.opens_on <= submitted_on <= contest.closes_on`

Notification (BR-70a, BR-72a) — **хранится «когда», выводится «как давно»**:
- stored: `kind`, `days_ago: int`, `hours_ago: int | None`, `actor_username`, `story_slug`, `contest_slug`, `text`, `read`
- `when` / `bucket` — производные. Полей с этими именами нет: `when="5 күн бұрын"` и `bucket="past_week"` устаревали назавтра
- `actor` / `story` / `contest` — резолвы ссылок. Уведомление обязано вести к своему предмету, и `contest_slug` заведён именно для этого
- `text` несёт только событие. Имя конкурса или работы в нём не повторяется — оно приходит из объекта (исключение: `comment`, где `text` — цитата читателя)

TimelineStage:
- `label`, `starts: date`, `ends: date` — однодневный этап задаётся равными датами
- `period` — производное: «1 қыр — 1 жел» либо «15 жел»
- `state` — производное от календаря: `done` · `active` · `upcoming`. Хранимое значение уже разошлось с данными — этап «Өтінім қабылдау» конкурса 2024 года стоял `active` в 2026-м

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
