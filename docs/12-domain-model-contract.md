# 12. Domain model contract for F14

> `Обновлён: 2026-08-26` · `Сверен с кодом: be979e3`

> ✅ **Контракт исполнен.** Ф14 завершена: стаба нет, читает база, порядок работ и разбор каждого этапа — [`19`](19-f14-migration-plan.md). Документ остаётся **не описанием таблиц** (для них есть `core/models.py`, где у каждого поля стоит причина), а списком того, что миграция была обязана сохранить, и почему. Читается он теперь в обратную сторону: не «что сделать», а «что нельзя сломать потом».

Читающая сторона обращается к фасаду `core.data`, а не к моделям напрямую: имена ниже — его поверхность, и она не меняется от того, кто за ней отвечает. Словарь предметной области (оси каталога, реакции, ступени наград, подписи статусов, формулировки времени) живёт в `core/domain/`: это правила, а не записи, и замена хранилища их не коснулась — ни один файл домена в Ф14 не изменился по существу.

Колонка «Stub source» сохранена намеренно: по ней видно, что чем стало, и она же объясняет, почему у некоторых моделей поля выглядят странно (`Story.likes` — счётчик без строк под ним, потому что в демо-корпусе их некому создать). **`User.followers` из этого списка вышел**: колонка осталась (её читают сортировка «Жаңа авторлар» и ось каталога — это `ORDER BY` и `WHERE`), но пересчитывается по строкам `Follow` — и в `toggle_follow`, и в сиде. Раньше сид клал туда число из корпуса, и профиль объявлял 8 420 оқырман при трёх записях.

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

Fields are **not listed here.** Они в `core/models.py`, у каждого — причина рядом; прозаическая копия тех же списков была бы вторым источником, который тихо гниёт, — ровно это и случилось с §12.3 до одной из ревизий.

**`Story.updated_days_ago` не перенесён как есть** — это была дельта в днях от «сегодня», и в базе ей соответствует `updated_at` с `auto_now`: хранить дельту нельзя, она устаревает каждые сутки. Состояния «не задано» вместе со стабом не стало: у строки времени изменения не может не быть. Postgres при `DESC` ставит `NULL` первыми — сортировка кабинета поэтому явно просит `nulls_last`.

**`Story.recent_views` — про окно, а не про давность.** Это просмотры за 14 дней (DEC-36); пока колонка, дальше — агрегат по логу просмотров с окном. **Оба счётчика растут с заходов читателей** (`record_story_view`, один оқылым на работу за сессию, свой заход автору не засчитывается) — до этого их клал только сид, и дефолтная сортировка каталога навсегда показывала порядок демо-данных. **Убыли у `recent_views` пока нет** ⛔: журнала просмотров с датами не существует, и окно в четырнадцать дней остаётся обещанием — со временем ось сойдётся с накопленной. Лог и пересчёт — отдельная задача. Считать его от `views` нельзя: смысл оси в том, что она расходится с накопленным счётчиком. Инвариант `recent_views <= views` закрыт тестом `test_corpus.RecentViewsAreConsistent`.

**`NEW_AUTHOR_FOLLOWERS = 150` — условная константа, не правило.** Авторов в демо-корпусе шесть, и любая граница между ними произвольна. В Ф14 «новое имя» должно определяться перцентилем по подписчикам или возрастом аккаунта, а не абсолютным числом: 150 подписчиков на портале из двухсот авторов и из двадцати тысяч означают разное. Число не наследовать.

What the table carries instead is the part a field list cannot state: what had to survive the migration, and what must keep surviving.

| Model | Stub source | Must survive F14 |
|-------|-------------|------------------|
| **User / Author** | `Author` | DEC-01 holds: no separate Reader role — any signed-in user reads, writes, comments, saves and submits. Follows stay a small relation and must not drive navigation |
| **Genre** | `Genre` | Closed reference of 12 (DEC-11). `/genres/` is an overview page, `/catalog/` the primary reading entry, `/genres/<slug>/` a catalog filter entry — **not** a separate engine (DEC-27) |
| **Tag** | `Tag`, `TAGS`, `BLOCKED_TAG_PATTERNS` | Up to 10 per story (BR-TAG-01). `status`: `pending` / `accepted` / `rejected`. Pending visible to the author, hidden from public catalog and story views (BR-TAG-07). Blocked patterns stay admin-managed |
| **Story** | `Story` | `OnProcess` is a continuation state, **not** a moderation state. Public catalog carries only `Published` and explicitly allowed public states. `format` is chosen by the author, never inferred from chapter count (DEC-28). Status labels — `components/status_badge.html`, see [16 §16.3](16-content-voice.md). **`audience` has no default** — blank means «not chosen yet», and anything past `NotPublished` must carry a mark (BR-10b); after F14 the column stays nullable/blank rather than defaulting, or the choice silently reverts to being made by the schema |
| **Chapter** | `Chapter`, `CHAPTERS_BY_STORY` | One-based numbers. Bodies live **outside** the data module in `core/story_texts/<slug>/<n>.txt`; сид читает их в `Chapter.body`, `char_count` считается при сохранении. Keep long prose out of the data module. Read via `?chapter=N` — no separate route (DEC-30). **`Story.chapters` — производное, а не колонка** (DEC-51): число частей считается по записям глав — аннотацией `chapter_count` в выдаче, `chapter_set.count()` у одиночного объекта. Обещать бөлім, которых никто не написал, портал больше не может. Закрыто `test_corpus.ChapterCountIsDerived` |
| **Collection** | `Collection` | Ordered many-to-many with `Story`. Editorial curation by a moderator, not a smart auto-filter, and separate from contests (DEC-27). **Admin-authored only** — there is no user-created collection (DEC-31); `count` and `covers` are derived from `story_slugs`, never stored alongside it |
| **Contest** | `Contest` | Хранятся три даты (`opens_on` / `closes_on` / `results_on`); фаза, отсчёт, год и число заявок **выводятся** (DEC-45, BR-40a). Хранимого `status` нет и заводить его нельзя — это тот же класс поля, что `Author.works`. Повторяющийся конкурс — отдельный объект на каждый выпуск, связь через `series` (BR-47): у выпусков расходится всё, чем конкурс является. Separate from collections. Admin UI is Django admin for MVP (DEC-23) |
| **Submission** | `Submission` | One story per author per contest (BR-23). Eligibility is a query/service concern, never template logic (BR-22, BR-24). `submitted_on` is a date; the relative wording is derived (BR-41a) |
| **LibraryEntry** | `LibraryEntry` | `kind`: `saved` / `reading` / `done`, non-overlapping (BR-60/61). Continue-reading is a first-class reader workflow — it drives both the hero and the mobile nav. **Номера главы здесь нет** (DEC-52): закладку держит `ReadingProgress`, полка получает её аннотацией `progress_chapter`; две колонки об одном и том же в корпусе уже разошлись |
| **Comment** | `StoryComment` | One reply level only (BR-30). Anchored to a chapter via `chapter_number`; `None` means the whole work. Reply form and comment-like persistence can wait |
| **Notification** | `Notification` | Secondary in MVP: header badge plus the notifications page are enough (BR-70…72). Stores when the event happened, not how long ago; every notification links to its subject (BR-70a, BR-72a) |

## 12.3 Query/service helpers to preserve

Views полагаются на эти хелперы; после Ф14 они живут в `core/queries/*` и отдаются через фасад `core.data`. В шаблоны эта логика не спускается.

**Список — поверхность фасада, а не архив.** Хелпер, которого не зовёт ни один view и ни один шаблон, снимается отсюда вместе с кодом: контракт, называющий то, чем никто не пользуется, читается как обещание. Так ушли восемь имён — отдельные `stories_by_genre` и `search_stories` (после DEC-27 на оба вопроса отвечает `filter_catalog`), `search_authors`, `is_new_author`, `next_read_tier`, `winning_stories_of`, `reaction_breakdown` и `KIND_PREDICATES`; `apply_catalog_filters` и `catalog_base` остались в модуле, но с фасада сняты — их зовёт только `filter_catalog`.

**Signatures below are the actual ones in the code.** Хелпер принимает **строковый ключ** (`username`, `story_slug`, `genre_slug`, `contest_slug`), а не объект модели. Так было в стабе, и так осталось намеренно: перевод на объекты — отдельное решение и отдельный проход по всем вызовам, а смешанный с миграцией он лишил бы возможности понять, что сломалось — модель или вызов.

Исключение одно и заведено по цене, а не по вкусу: `can_withdraw` и `submission_candidates` принимают **и слаг, и готовый конкурс**. Через слаг ответ стоил полной выборки конкурса со всем составом, и список заявок платил её на каждой строке. Слаг остаётся ради вызовов, у которых объекта на руках нет.

Catalog and search:
- `filter_catalog(*, query="", genre="", tag="", status="", sort="trending", audience="", length="", format="", badge="", author_tier="", kind="") -> QuerySet[Story]` — **queryset, а не список**: чипы пресетов спрашивают у него `.count()`, и `len` вместо этого выполняет выдачу целиком, материализуя список ORM-объектов со всеми тегами (шесть раз за страницу каталога)
- `PUBLIC_STATUSES` — статусы, видимые публике (DEC-23). `filter_catalog` режет по ним на входе
- `NEW_AUTHOR_FOLLOWERS`, `CATALOG_AUTHOR_FILTERS` — ось «Автор» (FR-CAT-13). Порог применяется в `WHERE`; отдельного `is_new_author` нет — предикат над одним автором отвечал на вопрос, которого никто не задавал
- `AUDIENCE_ORDER` — отметки от младшей к старшей; ось «Жасың» сравнивает по индексу, не по равенству (DEC-38)
- `STORY_AUDIENCES` — те же ключи для формы автора: `(key, mark, hint)`. Отдельная константа от `CATALOG_AUDIENCE_FILTERS` потому, что подписи там про **читателя** (вилка «10-13», ось накопительная), а в форме автор ставит отметку **работе**. Дефолта у `Story.audience` нет — пустая строка значит «не выбрана» (BR-10b)
- `CATALOG_KIND_FILTERS` — ось «Түрі» (DEC-37); предикатов рядом нет, оси выражены в SQL, и вторая их копия лямбдами разошлась бы с выдачей. Правило «у публичного сериала не бывает `Published`» — BR-10a; `writer_stats` считает `published` как `Published` + `Completed`, ключ `ongoing` (бывший `drafts`) считает `OnProcess`
- `CATALOG_PRESETS`, `STORY_BADGES` / `BADGE_LABELS`, `CATALOG_BADGE_FILTERS`, `CATALOG_DEFAULT_SORT` — справочники осей каталога
- `related_stories(slug: str, limit=6) -> list[Story]`

Story and chapters:
- `chapters_of(story_slug: str) -> list[Chapter]`
- `chapter_of(story_slug: str, number: int, viewer: str = '') -> Chapter | None` — с `viewer` аннотирует `Chapter.my_reaction` (BR-REACT-02/03, Ф15 Этап 3)
- `Story.is_public -> bool` — видна ли работа читателю. По `PUBLIC_STATUSES`, а не по литералу `'Published'` (DEC-37)
- `Story.chapters -> int` — число написанных частей: аннотация `chapter_count` в выдаче, `chapter_set.count()` у одиночного объекта (DEC-51)
- `record_story_view(story) -> None` — засчитать оқылым: `views` и `recent_views` растут вместе, одним UPDATE по queryset'у (гонки складываются в базе, `updated_at` не двигается — чтение не есть правка). «Один раз на работу за сессию» и «свой заход не в счёт» решает view (`_count_view`), а не слой данных: это правило про запрос, а не про запись
- `Story.updated_label -> str` — «кеше», «3 күн бұрын»; пусто, когда `updated_days_ago` не задан
- `writer_attention(username: str, *, facts=None) -> list[dict]` — сигналы кабинета (FR-WRITE-08): `kind` / `count` / `slug`. Только данные; ссылку строит view (`_attention_links`), как и в каталоге
- `publish_checklist(story) -> list[dict]` — готовность работы к модерации (FR-WRITE-09): `key` / `ok` / `required` / `target`. Порядок — порядок работы автора, задан `PUBLISH_CHECKLIST`. Ссылку строит view (`_checklist_links`), тексты — шаблон
- `missing_for_review(story) -> list[str]` — незакрытые **обязательные** пункты
- `can_submit_for_review(story) -> bool` — «готова» **и** «ещё не отправлена» (BR-11). Два разных вопроса: у работы на модерации кнопка означала бы повторную заявку, у публичной — откат в непубличное
- `Story.text_chapter -> int | None` — номер главы с текстом одночастного произведения; None у сериала и у `single` без текста. Кнопка «Мәтін» / «Мәтінді өңдеу» обязана вести туда, а не в `chapter_new`: у `single` глава ровно одна, и пустой редактор давал автору сохранить вторую
- `comments_of(story_slug: str) -> list[StoryComment]`
- `comments_of_chapter(story_slug: str, chapter_number: int) -> list[StoryComment]`
- `reactions_of(chapter: Chapter, viewer: str = '') -> list[dict]` — полный ряд из пяти реакций, включая нулевые (BR-REACT-01); `mine` отвечает на голос `viewer`
- `toggle_chapter_reaction(chapter, user, kind: str) -> str` — ставит/снимает/меняет реакцию (BR-REACT-02/03, Ф15 Этап 3); возвращает новый slug, `''` — если снята. `Story.likes` — агрегат по числу голосов, не по сумме реакций (BR-14a): смена вида его не трогает
- `poll_of(story_slug: str, chapter_number: int, viewer: str = '') -> ChapterPoll | None` — опрос необязателен (BR-POLL-01); с `viewer` аннотирует `ChapterPoll.my_vote` (Ф15 Этап 4)
- `cast_poll_vote(poll, user, option_slug: str) -> bool` — голос: одна ставка на опрос, не на вариант, не меняется (docs/20 §20.2); закрытый опрос (BR-POLL-05) и невалидный/повторный вариант — no-op, возвращает `False`

Author workspace, library, social:

**`AuthorFacts` — снимок автора на один запрос.** Хелперы этого слоя
возвращают `list`, а не `QuerySet`: у списка нет кэша, и каждый вызов идёт
в базу заново. Вызывающая сторона об этом не знала и звала их столько раз,
сколько было удобно читать, — свой профиль спрашивал `my_stories_of`
**шестнадцать раз** за один рендер, и из этого складывались 59 запросов на
страницу. Поэтому view собирает снимок один раз и раздаёт его дальше.

- `author_facts(username: str) -> AuthorFacts` — снимок. Поля ленивые
  (`cached_property`): объект создаётся заранее, а платит только за то,
  что странице понадобилось — заявки на конкурс нужны профилю и не нужны
  кабинету
- Поля: `stories` (все, любого статуса), `public_stories` (режется из
  `stories` по тому же правилу публичности — второй запрос с тем же
  `WHERE` это просто второй запрос), `submissions`, `library`,
  `user`, `reads`; метод `facts.shelf(kind)` — одна полка из общей выборки
- **Живёт ровно один запрос.** Это снимок, а не кэш: между запросами его
  не переиспользуют, иначе страница показывала бы вчерашние работы
- Хелперы ниже принимают его именованным `facts=` и, если не дан, строят
  свой. Сигнатура с `username` первым аргументом сохранена везде

<!-- -->

- `my_stories_of(username: str) -> list[Story]` — **любой** статус: выдача авторского кабинета, не публичная
- `public_stories_of(username: str) -> list[Story]` — только `is_public` (BR-73). Публичный профиль строится на ней; на `my_stories_of` он показывал посторонним черновики
- `top_stories_of(username: str, limit: int = 3, *, facts=None) -> list[Story]` — самые читаемые публичные работы автора, для рейла чужого профиля (FR-PROF-09). Сортировка по накопленному `views`, а не по `recent_views`: рейл отвечает «с чего начать», а не «что сейчас в моде». Не `related_stories` — тот, наоборот, исключает того же автора
- `writer_stats(username: str, *, facts=None) -> dict`
- `record_reading_progress(user, story, chapter_number: int, chapters) -> None` — запомнить, где читатель остановился (FR-HOME-02). `minutes_left` — сумма глав **после** текущей: позиции внутри главы читалка не сообщает, и прикидывать её долю значило бы выдумывать число. `quote` не сочиняется, только сохраняется, если уже есть. Сначала UPDATE, вставка — только на ноль задетых строк: это самое частое действие портала
- `library_of(username: str, kind: str = "") -> list[LibraryEntry]` — со снимком полка берётся как `facts.shelf(kind)`: три вкладки библиотеки стоили трёх выборок ради трёх счётчиков
- `in_library(username: str, story_slug: str) -> bool`
- `toggle_library_entry(user, story) -> bool` — кнопка «Сақтау»: положить на полку `saved` или снять с любой. Возвращает новое состояние
- `move_to_shelf(user, story, *, finished: bool) -> None` — автопереход по факту чтения (BR-61). Запись создаётся, если её не было: на полку попадают по чтению, а не только по кнопке
- `public_stats(username: str, *, facts=None) -> dict` — `works` / `reads` / `likes` / `followers` по публичным работам (FR-PROF-01). `works` совпадает с `Author.works` по построению
- `reader_stats(username: str, *, facts=None) -> dict` — `public_stats` плюс приватное: `works_total` (с черновиками), `finished` (дочитано, из библиотеки). Ключ `read` переименован в `finished`, чтобы не путаться с `reads`
- `AWARDS` — реестр наград: `key` / `label` / `art` / `tier` / `hint` и предикат `earned`, принимающий **`AuthorFacts`**. **Условие лежит рядом с наградой**, а не в отдельном списке «как получить»: два описания одного правила однажды разошлись бы. Предикат читает снимок, а не ник: пока он принимал ник, каждая из пяти наград шла в базу за работами автора сама
- `award_catalog(username: str, *, facts=None) -> list[dict]` — все награды с `earned` и `dim` (FR-PROF-08). Тот же реестр, что у публичного ряда, поэтому «что можно получить» не может разойтись с «что получено». `earned` вычисляется **один раз** на награду: `dim` это его отрицание, а не второй расчёт
- `read_ladder(username: str, *, facts=None) -> list[dict]` — ступени оқылым: `earned`, `is_next`, `left`
- `achievements_of(username: str, *, facts=None) -> list[dict]` — награды автора (FR-PROF-06, BR-ACH-01): `key` / `label` / `art` / `tier`. `art` — слаг иллюстрации в `components/awards/_sprite.html`, `tier` — металл ступени (`AWARD_TIERS`). **Выводятся, не хранятся**; URL-ы слой данных не отдаёт
- `READ_TIER_ART` — ступень оқылым → (слаг рисунка, металл). Один рисунок-стела на четыре ступени: меняются число на табличке и металл
- `reads_total(username: str, *, facts=None) -> int` — прочтения по публичным работам. Со снимком считается из уже загруженных работ; без него остаётся агрегатом — сам по себе он дешевле выборки всех работ ради суммы
- `tier_for(total: int) -> tuple | None`, `next_tier_for(total: int) -> tuple | None` — чистые функции над `READ_TIERS`, чтобы границы проверялись напрямую
- `read_tier(username: str, *, facts=None)` — высшая взятая ступень; «что дальше» отдаёт `read_ladder` флагом `is_next`
- `contest_awards_of(username: str) -> list[dict]` — награды конкурсов автора (DEC-46), свежие сверху: `key` / `title` / `image` / `contest` / `story` / `year` / `note`. Работа названа только пока публична (BR-73); сама награда остаётся — она принадлежит автору, а не видимости текста
- `is_following(me: str, them: str) -> bool`
- `toggle_follow(follower, following) -> bool` — подписаться/отписаться (FR-PROF-04). `User.followers` пересчитывается по строкам, а не сдвигается на единицу: колонка остаётся самоисправляющейся
- `following_of(username: str) -> list[Author]` — оба списка публичны (BR-75), страницу собирает `profile_people`
- `followers_of(username: str) -> list[Author]`
- `following_count_of(username: str) -> int` / `followers_count_of(username: str) -> int` — только число. Страница показывает два сегмента, а открывает один: соседнему нужен счётчик, а не выборка имён со счётчиком работ у каждого
- `notifications_for_user(username: str) -> dict` — три бакета FR-NOTIF-01; событие старше недели не попадает ни в один (BR-70a)
- `unread_count_for_user(username: str) -> int`
- `mark_notification_read(user, pk) -> Notification | None` — снять «непрочитано» с одного (BR-71). Только со своего: `user` в фильтре
- `mark_all_notifications_read(user) -> int` — со всех в пределах недельного окна ленты — считает то же, что показывается: скрытое старое уведомление в бейдж не идёт. Считает **база**: окно ленты в семь дней (`FEED_DAYS`) выражено условием по `created_at`, а не отбором по свойству `bucket` в Python. Число зовёт контекст-процессор на каждой странице, и у автора с двухлетней историей прежний вариант вёз всю историю ради семи дней
- `kk_ago(days: int, hours: int | None = None) -> str` — «как давно» словами, одна формулировка на проект: её берут `Notification.when` и `Submission.submitted_label`

Contests:
- `submissions_of(username: str) -> list[Submission]`
- `has_submission(username: str, contest_slug: str) -> bool`
- `contest_history(username: str, *, is_self: bool = False, facts=None) -> list[dict]` — конкурсная биография (FR-PROF-07). Правило видимости живёт здесь, а не в шаблоне (BR-74a): при `is_self=False` результат режется до победы/принятия, `note` приходит пустым, непубличная работа не называется. Второе место с тем же правилом однажды разошлось бы с первым
- `common_rules(contest: Contest) -> list[dict]` — правила, действующие на любом конкурсе: `{key, label, hint, per_work}`. Один источник для списка «Шарттар» на странице конкурса и для чек-листа подачи (BR-48a). `per_work=False` у правил про автора, а не про текст («Бір автор — бір өтінім»)
- `submission_checklist(story: Story, contest: Contest, *, chars: int = None) -> list` — объём берётся из аннотации выдачи (`written_chars`, не `effective_chars`: второй дорисовывает ненаписанные части по заявленному числу глав, а на конкурс идёт текст, который прочтёт жюри). `chars` это уже посчитанный объём: страница подачи считает его каждому кандидату в `submission_candidates`, и без него объём шёл в базу за главами по второму разу. — общая часть из `common_rules`, возрастной пункт только при непустом `eligibility_line` (BR-48). Пороги объёма берутся у конкурса, а не вписаны в подпись литералом (FR-CONT-07); числа проходят через `spaced_number`
- `spaced_number(value) -> str` — разряды через неразрывный пробел, канонический вид числа для автора. Живёт в слое данных, а не в фильтре `balaproza.spaced`: те же числа собираются и в подсказках чек-листа. Фильтр вызывает эту функцию — двух реализаций одной формы записи быть не должно
- `submission_candidates(username: str, contest, *, facts=None) -> list[dict]` — вторым аргументом принимает и готовый конкурс, и слаг: — работы автора как кандидаты и что о них стоит знать: `{story, chars, notes}`, где `notes` — `[{key, text}, …]`, ключи из `SUBMISSION_NOTES` (`too_short` · `too_long` · `busy`). **Заметки, не запреты** (BR-24): форма ничего не отклоняет, решение принимает человек. Заметок бывает несколько сразу — прежняя цепочка `elif` называла первую и молчала об остальных. Кандидатами остаются только публичные работы: черновик на конкурс не выставляется (BR-10, DEC-23)
- `busy_contest_of(username, story_slug, *, besides='') -> Contest | None` — незавершённый конкурс, который уже держит эту работу (BR-23a)
- `contest_history` добирает присуждения `prefetch_related_objects` сама: их читает только она, и `submissions_of` за чужой вопрос не платит
- `can_withdraw(username, contest) -> bool` — можно ли отозвать заявку (BR-23b): идёт приём и статус `reviewing`. Принимает и готовый конкурс, и слаг. Готовый — потому что список заявок спрашивает это по строке, а через слаг ответ стоил полной выборки конкурса **со всем составом**: номинации, этапы, жюри, условия и присуждения, шесть лишних запросов на каждую строку
- `contest_participants(contest: Contest) -> list[dict]` — список участников (FR-CONT-16, DEC-50): `{story, result, label}`, где `result` — `'accepted'` или `'winner'` (победа читается через `contest.grants`, не отдельный статус заявки), `label` — название номинации у победителя или подпись «Қабылданды». Видимость — BR-74a: только `status='accepted'` и публичная работа (`PUBLIC_STATUSES`). Принимает **готовый** конкурс, полученный через `contest_by_slug`, а не слаг — иначе `contest.grants` тянет присуждения отдельным запросом
- `home_contests(limit: int = 4) -> list[Contest]` — конкурсы для секции «Байқаулар» на главной (FR-HOME-14): открытые (`open_contests`, DEC-45) перед недавно завершёнными (`finished_contests`)

Tags (module 11):
- `tag_by_slug(slug: str) -> Tag | None`
- `tags_of(story: Story) -> list[Tag]`
- `popular_tags(limit=10) -> list[Tag]` — all-time, по аннотации `usage` (DEC-53: колонки нет)
- `trending_tags(limit=6) -> list[Tag]` — последние 7 дней, по аннотации `weekly` (считается по `StoryTag.created_at`); теги без недельной активности пропускаются (DEC-31)
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

- stored: `slug`, `title`, `cover`, `annotation`, `status`, `audience`, `badges`, `views`, `likes`, `comments`
- ⛔ `likes` — **сумма реакций по главам** (BR-14, DEC-32), и по общему правилу его следовало бы вычислять, как `Author.works`. Пока хранится: у четырёх работ главы не написаны вовсе (48 глав текста, `KNOWN_TEXTLESS`), и вычисление обнулило бы им метрику в каталоге. Инвариант условный — где главы несут реакции, итог обязан сходиться с их суммой (BR-14a, `test_corpus.StoryReactionsMatchTheirChapters`). **После Ф14 — агрегат запроса**, имя для шаблонов не меняется
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

Notification (BR-70a, BR-72a, BR-11) — **хранится «когда», выводится «как давно»**:
- stored: `kind`, `days_ago: int`, `hours_ago: int | None`, `actor_username`, `story_slug`, `contest_slug`, `outcome`, `text`, `read`
- `when` / `bucket` — производные. Полей с этими именами нет: `when="5 күн бұрын"` и `bucket="past_week"` устаревали назавтра
- `actor` / `story` / `contest` — резолвы ссылок. Уведомление обязано вести к своему предмету, и `contest_slug` заведён именно для этого
- `outcome` — **хранится**, только у `kind='moderation'`: `approved` · `needs_work` · `rejected` · `''` (решения ещё нет). Это акт модератора, а не состояние работы: вывести его из `Story.status` нельзя, потому что статус живёт дальше события — автор правит работу и отправляет снова, и вчерашний отказ начинает говорить «Модерацияда». Тот же довод, по которому `AwardGrant` хранит присуждение (DEC-46), а не вычисляет победу из данных
- отрицательных исхода два: `needs_work` (возврат с замечанием) и `rejected` (отказ по правилам) — BR-72b. Оба обязаны нести причину в `text`; инвариант данных — работа с таким исходом не может быть публичной
- `outcome_label` — производное: подпись из `MODERATION_OUTCOME_LABELS`. В шаблоне слово не собирается, как не собираются статусы работы (BR-10) и фазы конкурса (BR-40)
- `text` несёт только событие. Имя конкурса или работы в нём не повторяется — оно приходит из объекта. Исключений **два**, и оба про чужие слова, а не про пересказ данных: у `comment` в `text` цитата читателя, у отклонённой `moderation` — причина от модератора, которую требует BR-11

TimelineStage:
- `label`, `starts: date`, `ends: date` — однодневный этап задаётся равными датами
- `period` — производное: «1 қыр — 1 жел» либо «15 жел»
- `state` — производное от календаря: `done` · `active` · `upcoming`. Хранимое значение уже разошлось с данными — этап «Өтінім қабылдау» конкурса 2024 года стоял `active` в 2026-м

Genre:
- `slug`, `name`, `hue`, `icon`, `count`

Tag:
- `slug`, `name`, `status` (оба счётчика — производные, DEC-53)

## 12.5 Migration order

1. Create read-only models and seed data equivalent to stubs.
2. Replace catalog queries first.
3. Replace story detail and chapters.
4. Replace library/progress.
5. Replace write dashboard with real user-owned stories.
6. Replace contests/submissions.
7. Replace comments and notifications.
8. Remove `stub_data.py` only after all tests pass against models. ✅ — сделано на этапе 11: файла нет, демо-корпус лежит литералами рядом с `seed_demo` и читается только ею.

## 12.6 Test contract

Existing tests are the behavior contract. During F14:

- keep route smoke tests passing;
- keep catalog/search/genre/tag behavior stable;
- keep story detail `?chapter=N` behavior stable;
- preserve pending tag visibility rules;
- preserve guest vs signed-in navigation surfaces;
- add model tests before deleting the corresponding stub helper.
