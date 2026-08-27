# 20 · План Ф15: запись

> `Обновлён: 2026-08-27` · `Сверен с кодом: 7218259`

Ф14 закрыта: портал отвечает из PostgreSQL на всех страницах. Формы записи (создание/редактирование произведения, комментарии, реакции, опрос, подача на конкурс, редактирование профиля) свёрстаны, но кнопки ничего не делают — submit гасится Alpine (`@submit.prevent`) и показывает демо-тост. Этот документ — план Ф15 по образцу [`19`](19-f14-migration-plan.md): границы, принятые решения и порядок этапов до того, как код начал меняться.

Источник фактов — три параллельных исследования кодовой базы (форма произведения; комментарии/реакции/опрос; подача на конкурс и профиль): ни один текущий тест не делает `client.post(...)` к письменным маршрутам, весь POST-слой пишется с нуля.

---

## 20.1 Границы

**Входит:** POST-обработка пяти форм (создание/редактирование произведения и главы, комментарии, реакции + опрос главы, подача на конкурс, редактирование профиля) и их прямые зависимости — новые модели голосов/через-модели там, где этого требует бизнес-правило. Toggle-семантика реакции или лайка требует знать, кто уже голосовал: счётчика без строки на пользователя недостаточно.

**Не входит:** Telegram Login Widget (NFR-25 ⛔, блокирован секретами деплоя — `login_view` продолжает подписывать в демо-аккаунт `views.DEMO_USERNAME`), автосохранение черновика по debounce (FR-WRITE-05 явно откладывает это на будущее — «Жоба ретінде сақтау» остаётся кнопкой, не таймером), объединение конкурсов в Collection (закрыто DEC-50, вне темы).

---

## 20.2 Принятые решения

- **`User.age`/`User.gender`** — новые поля модели. `age` без верификации документами (DEC-24 — самодекларация), `gender` — `choices=('boy','girl')` по уже свёрстанной форме. Ни одно бизнес-правило их пока не читает — возрастная вилка конкурса решается отдельным чекбоксом на форме подачи (CONT-8/9, `Contest.eligibility_line`), поля профиля собираются на будущее и возвращают Ф15 к уже закрытому [`Q-C3`](18-open-questions.md) («поле `age` при регистрации + чекбокс при подаче» — решено DEC-24/DEC-47, но не реализовано: у `User` не было поля).
- **`User.avatar`** — `FileField` с `RASTER_ONLY` (тот же валидатор, что у `Story.cover`/`Contest.poster`), `upload_to` по аналогии с `story_cover_path`. `components/avatar.html` становится двухрежимным, как `cover_placeholder.html`: `<img>`, если `avatar` задан, иначе инициалы на OKLCH-фоне.
- **AI-декларация конкурса сохраняется.** `Submission.ai_declaration` (choices `no`/`partial`/`yes`, DEC-21), `age_confirmed`, `rules_confirmed` (bool) — пишутся один раз при создании заявки, дальше read-only: видны жюри/модератору, автор их повторно не редактирует.
- **Тег получает дату связи с работой (DEC-31 долг).** Голое M2M `Story.tags` не может нести `created_at`. Заменяется на `ManyToManyField(Tag, through='StoryTag')`, `StoryTag(story, tag, created_at=auto_now_add)`. Это часть Этапа 1: как только теги становятся редактируемыми через `story_settings`, голому M2M негде хранить момент добавления, а `weekly_count`/`usage_count` без него не смогут действовать корректно.
- **`Story.likes` становится агрегатом (BR-14a долг).** Хранимая колонка остаётся — имя используется в шаблонах, есть индекс — но перестаёт устанавливаться вручную. Обновляется транзакционно (`F()`-инкремент/декремент) при создании/смене/удалении `ChapterReactionVote`, тем же способом, каким уже поддерживаются `ChapterReaction.count`/`PollOption.votes`/`User.followers`: денормализованный счётчик, не агрегатный запрос на каждый рендер.
- **Смена статуса «черновик → модерация» — не через `apply_moderation`.** `apply_moderation` требует `status == 'OnModeration'` — это решение модератора, а не автора. Новый метод `Story.submit_for_review()`: guard `status == 'NotPublished' and can_submit_for_review(self)`, иначе `ValueError` — тот же паттерн валидации перехода на модели, что у `apply_moderation`.
- **PRG + toast без нового транспорта.** Все четыре формы записи сейчас гасят submit через Alpine `@submit.prevent`. Реальный путь: обычный `POST` → редирект (Post/Redirect/Get) → `django.contrib.messages` → мост в `base.html`, превращающий поставленные messages в уже существующее глобальное событие `toast`. UX (текст тостов) не меняется, меняется источник — сервер вместо Alpine-заглушки.
- **IDOR-дыра чинится в Этапе 1, не отдельно.** `manage_story`/`story_settings`/`chapter_editor` (`core/views/write.py`) не проверяют `story.author == request.user` — сейчас не эксплуатируется, потому что нет записи, но с появлением POST это открытая дыра. Все три view переходят на `get_object_or_404(Story, slug=slug, author__username=username)`.
- **Опрос — одна ставка на весь опрос, не на вариант**, голос не меняется после отправки. BR-POLL не оговаривает смену голоса — выбран самый простой вариант, зафиксирован здесь явно, чтобы его можно было пересмотреть на ревью конкретного этапа.

---

## 20.3 Новые модели и поля

| Модель/поле | Назначение | Ограничение |
|---|---|---|
| `User.age`, `User.gender`, `User.avatar` | профиль (FR-PROF-05 / FR-AUTH-04) | `avatar`: `RASTER_ONLY` |
| `StoryTag(story, tag, created_at)` | through-модель вместо голого M2M `Story.tags` | `unique_together(story, tag)`; нужна `weekly_count`/`usage_count` (DEC-31) |
| `ChapterReactionVote(user, chapter, kind, created_at)` | кто поставил какую реакцию — сейчас есть только `ChapterReaction.count` | `UniqueConstraint(user, chapter)` — BR-REACT-03, одна активная реакция |
| `CommentLike(user, comment, created_at)` | toggle-лайк комментария — BR-31 требует «повторный клик снимает», чистый счётчик этого не может | `UniqueConstraint(user, comment)` |
| `PollVote(user, poll, option, created_at)` | кто как проголосовал — сейчас есть только `PollOption.votes` | `UniqueConstraint(user, poll)` — одна ставка на опрос |
| `Submission.ai_declaration` / `age_confirmed` / `rules_confirmed` | ответы формы подачи (DEC-21/DEC-24) | пишутся один раз при создании |

Готово и трогать не нужно: `Story`/`Chapter` (поля, `RASTER_ONLY`, `char_count` авто-пересчёт при `save()`), `Story.apply_moderation()`, весь чек-лист (`PUBLISH_CHECKLIST` / `publish_checklist` / `can_submit_for_review` / `missing_for_review`), `Submission.UniqueConstraint(contest, author)`, `Chapter.number` unique-констрейнт, все URL-маршруты кроме удаления/отзыва.

---

## 20.4 Этапы

### Этап 0 — инфраструктура записи ✅

PRG + `messages`→`toast` мост в `base.html` (`core/tests/test_toast_bridge.py`, 5 тестов). Владение решено не отдельным хелпером, а сменой сигнатуры самого читающего запроса — см. Этап 1.

### Этап 1 — Произведение и глава ✅

`core/views/write.py`, `core/urls.py`, `core/queries/write.py` (новый), `core/queries/tags.py`, `core/domain/slugs.py` (новый), миграция `0010_story_tags` (модель `StoryTag`).

- `new_story`: POST создаёт `Story(author=request.user, status='NotPublished', ...)` через `data.create_story`, редирект на `chapter_new`. Slug — транслитерация заголовка (`domain/slugs.py::slugify_kz`, кириллица → ASCII: `<slug:slug>` кириллицу не матчит), с суффиксом при коллизии.
- `story_settings`: POST сохраняет метаданные, обложку (`enctype="multipart/form-data"` — без него `request.FILES` был бы пуст), жанры (`data.genre_by_slug`), теги (`data.resolve_story_tags` — переиспользует существующий тег по имени без учёта регистра, новый заводит `pending`, лимит 10 и блок-лист проверяются и на сервере), `audience` (BR-10b), `status`-радио только когда применимо (BR-10a — иначе присланное значение отбрасывается). Доп. guard: нельзя переключить в `single` работу с более чем одной написанной главой.
- `chapter_editor`: POST с двумя действиями по `name="action"` (`draft`/`submit_review`) на одной форме — «Жоба ретінде сақтау» всегда сохраняет `Chapter` (`data.save_chapter`); «Модерацияға жіберу» сохраняет и затем зовёт `data.submit_story_for_review(story)`. Опрос главы создаётся тут же (`data.save_chapter_poll`), если заполнен `poll_question` и указано ≥2 вариантов (BR-POLL-02).
- `Story.submit_for_review()` из плана реализован не методом модели, а функцией `core/queries/write.py::submit_story_for_review` — иначе модель импортировала бы `core/queries/author.py` (цикл: `queries` уже импортирует `models`). Модель осталась чистой, правило (`can_submit_for_review`/`missing_for_review`) не задвоено.
- Удаление произведения: `core:delete_story` (POST-only, GET безопасен), `delete_confirm_modal.html` теперь смонтирован глобально в `base.html` (раньше был только на `manage_story.html` — на `my_stories.html` его меню тихо никуда не вело) и шлёт настоящий POST с CSRF вместо фейкового тоста.
- **IDOR закрыт сменой сигнатуры**, не отдельным хелпером: `story_by_slug_for_author(slug, username)` теперь фильтрует по автору сама, и чужой/несуществующий slug неотличимы снаружи — оба дают `None` и карточку «не найдено» (не 403, чтобы не подтверждать существование чужого slug).
- Тесты: `core/tests/test_write.py` — 6 новых классов, 28 тестов (создание, транслитерация/уникальность slug, гостевой POST, сохранение настроек, guard на смену формата, резолв тегов, черновик/опрос главы, отправка на модерацию — полная и неполная, удаление, IDOR по всем четырём POST-маршрутам).

**Не закрыто в этом этапе:** `Tag.usage_count`/`weekly_count` остаются денормализованными полями, которые больше никто не обновляет при обычном использовании — `StoryTag.created_at` появился (связка с датой готова), но витрины (`popular_tags`, `trending_tags`) ещё не пересчитывают эти два числа по нему. Пока это ничем не хуже, чем было (значения статичны, как в демо-корпусе), но и не лучше — полноценный агрегат по `StoryTag` в `core/queries/tags.py` остаётся отдельной задачей, а не побочным продуктом этого этапа.

### Этап 2 — Комментарии ✅

`core/views/story.py` (три новых view: `comment_create`/`comment_delete`/`comment_like` — отдельный модуль не понадобился), `core/urls.py`, `core/queries/story.py`, миграция `0011_comment_likes` (модель `CommentLike`).

- POST создания топ-уровневого комментария и ответа (`comment_create`) — сервер сам проверяет вложенность через `data.top_level_comment_of(slug, parent_id)` (BR-30): чужой id, id ответа или id из другой работы — молча не создают ничего, до этого правило держал только шаблон.
- Удаление — `comment_delete`, владение решает существующий `StoryComment.belongs_to()` (BR-33), тот же метод, что уже выбирал «Жою» или «Шағым» в меню. Удаление каскадное (ответы уходят с родителем, BR-30 — вложенность одна) и синхронизирует `Story.comments`.
- `CommentLike` — новая модель (user, comment, unique), `comment_like` — toggle (BR-31). `StoryComment.likes` пересчитывается заново от `like_set.count()` при каждом toggle, а не инкрементируется: у сид-комментария «87 ұнату» не было ни одной настоящей строки голоса, и первый реальный лайк отвечает правде, а не сумме с выдуманной историей демо-корпуса.
- `.liked` для шаблона (`cm.liked`, раньше — несуществующий атрибут, тихо резолвился в `''`) проставляется в `queries/story.py::_attach_liked` одним запросом на всю страницу (не на комментарий).
- Побочный, но обязательный фикс: `StoryComment.replies` был `@property`, вызывающим `.select_related('author')` — это рвало кэш `prefetch_related('reply_set__author')` из `_comments()` и превращало один запрос на все ответы страницы в один на каждый комментарий (N+1, никем не пойманный, потому что `.replies` читался один раз в шаблоне). `.liked` требовал того же самого объекта при повторном чтении, что и вскрыло проблему: стал `cached_property` на `list(self.reply_set.all())`. Бюджет `test_query_budget.py` от этого упал: `test_story_page` 21→19, `test_story_chapter_with_comments_and_poll` 34→31.
- Тесты: `core/tests/test_story.py` — `CommentCreatePersists` и `CommentDeleteRemovesIt` (12 новых тестов: верхний уровень, ответ, ответ на ответ отклонён, ответ на чужую работу отклонён, пустой текст, гость, каскадное удаление с пересчётом счётчика, чужой комментарий не удаляется, GET не удаляет), `CommentLike` дополнен POST-тестами на toggle. Плюс два обновлённых бюджета запросов и одна поправка совместимости с дизайн-шоукейсом (`templates/pages/_design/components.html`): лайк/ответ деградируют в инертную разметку без `story_slug`/`comment_id` — иначе `{% url %}` падал бы на пустых kwargs.

### Этап 3 — Реакции на главу ✅

`core/models.py` (модель `ChapterReactionVote`), миграция `0012_chapter_reaction_votes`, `core/queries/story.py`, `core/views/story.py` (новый view `chapter_react`), `core/urls.py`, `templates/components/reaction_bar.html`.

- POST `core:chapter_react` (`/story/<slug>/chapter/<N>/react/`): `data.toggle_chapter_reaction(chapter, user, kind)` — повтор того же `kind` снимает (BR-REACT-02), другой `kind` заменяет; `kind` валидируется во view по `data.REACTIONS_BY_SLUG` (закрытый список, BR-REACT-01). Одна активная реакция на пользователя и главу — `ChapterReactionVote.UniqueConstraint(user, chapter)` (BR-REACT-03), а не только правило формы.
- `ChapterReaction.count` остаётся денормализованным счётчиком, но теперь агрегат по `ChapterReactionVote`: строка заводится первым голосом (`_bump_reaction_count`), а не заранее пятью нулями на каждую главу.
- `Story.likes` — агрегат **по числу голосов**, не по сумме реакций (BR-14a): смена вида реакции его не трогает, только появление/снятие голоса. Обновляется `F()`-инкрементом/декрементом в той же транзакции, что и голос (`transaction.atomic()` + `select_for_update()` на строке голоса — гонка двух кликов подряд не даёт двойного счёта).
- `reactions_of(chapter, viewer='')` (`core/queries/story.py`) получает `viewer` — `mine` перестаёт быть жёстким `False`. `chapter_of(story_slug, number, viewer='')` с `viewer` аннотирует `chapter._my_reaction`, и `reactions_of` переиспользует уже проставленную аннотацию, если она есть, — второго запроса на странице произведения нет.
- `Chapter.my_reaction` — свойство, читает аннотацию `_my_reaction` (тот же контракт, что у `has_chapters`/`total_chars`: без аннотации — пустая строка, а не поход в базу). Шаблон уже ссылался на `current.my_reaction` (FR-STORY-12) — заработало без правки include, кроме двух новых параметров.
- `templates/components/reaction_bar.html` потерял Alpine-заглушку (`@submit.prevent`, локальный `counts`/`picked`, burst-анимация клика) — теперь настоящая `<form>` с пятью `<button type="submit" name="kind" value="...">` и PRG-редиректом, тем же путём, что комментарии и их лайк (Этап 2). Гость видит те же пять карточек как `<a href="…/auth/login/?next=…">` (BR-REACT-05).
- Тесты: `test_story.py::ChapterReactionVoting` — 7 тестов (первый голос + `Story.likes`, повтор снимает голос, другой вид заменяет без изменения `Story.likes`, гостевой POST не голосует, невалидный `kind` отклоняется, `reactions_of`/`Chapter.my_reaction` отражают голос, HTML показывает «Автор сенің реакцияңды көреді» после голосования).

### Этап 4 — Опрос главы ✅

`core/models.py` (модель `PollVote`), миграция `0013_poll_votes`, `core/queries/story.py`, `core/views/story.py` (новый view `poll_vote`), `core/urls.py`, `templates/components/chapter_poll.html`.

- POST `core:poll_vote` (`/story/<slug>/chapter/<N>/poll/vote/`): `data.cast_poll_vote(poll, user, option_slug)` — голос принимается только пока `not poll.closed` (BR-POLL-05, закрытие уже вычисляется публикацией следующей главы). Одна ставка на пользователя и опрос — `PollVote.UniqueConstraint(user, poll)`, не на вариант: второй POST с другим `option` — no-op, голос не меняется (docs/20 §20.2). Невалидный `option_slug` (не из `poll.option_set`) — тоже no-op.
- `PollOption.votes` остаётся денормализованным счётчиком, теперь агрегат по `PollVote`: `F()`-инкремент в той же транзакции, что и создание голоса.
- `poll_of(story_slug, chapter_number, viewer='')` с `viewer` аннотирует `poll._my_vote` (`_attach_my_vote`, тот же приём, что `_attach_my_reaction` в Этапе 3).
- `ChapterPoll.my_vote` — свойство, читает аннотацию; `ChapterPoll.results` больше не жёстко ставит `mine=False` — сравнивает `o.slug == self.my_vote`.
- `templates/components/chapter_poll.html` потерял Alpine-заглушку (`x-data`, локальные `voted`/`counts`, live-проценты без перезагрузки) — теперь четыре серверные ветки вместо трёх: закрыт / гость / **проголосовал** (результаты, без ссылки на ответ) / не голосовал (настоящая `<form>` с кнопками `name="option"`, PRG-редирект).
- Тесты: `test_story.py::ChapterPollVoting` — 6 тестов (первый голос + счётчик варианта, второй голос не меняет первый, гостевой POST не голосует, закрытый опрос отклоняет голос, невалидный вариант отклоняется, HTML показывает результаты вместо бюллетеня после голоса). `ChapterPollStates` (Ф14) не тронут — по-прежнему зелёный.

### Этап 5 — Подача на конкурс ✅

`core/models.py` (три новых поля `Submission`), миграция `0014_submission_declarations`, `core/domain/contests.py` (`AI_DECLARATIONS`), `core/queries/contests.py`, `core/views/contests.py`, `core/urls.py`, `core/admin.py`, `templates/pages/contests/contest_submit.html`, `templates/components/withdraw_confirm_modal.html`, `templates/pages/contests/my_submissions.html`.

- `Submission` получил три поля, которых не хватало для мутации (§20.3): `ai_declaration` (choices `no`/`partial`/`yes`, DEC-21), `age_confirmed`, `rules_confirmed` (bool). Пишутся один раз при создании заявки; в админке — `readonly_fields` (видны жюри/модератору, автор их не редактирует).
- `data.create_submission` / `data.withdraw_submission` (`core/queries/contests.py`, не `core/queries/write.py` — тот же приём, что у мутаций Этапов 2-4: новые функции легли рядом с уже существующими запросами конкурса, а не в отдельный файл). `create_submission` — `get_or_create` по (`contest`, `author`): гонка двух кликов подряд не даёт второй строке упасть 500-й — тихо возвращает уже существующую заявку (`created=False`), и `contest_submit` превращает это в понятное сообщение, не в исключение.
- `contest_submit`: POST-ветка перед GET-логикой (`request.method == 'POST' and username and contest`). Кандидат — только из `submission_candidates` (публичные работы автора, BR-10/DEC-23): чужой или непубличный `story_slug` просто не находится, отдельной проверки владения не нужно. Валидация во view (фаза `is_accepting`, `ai_used` — один из `data.AI_DECLARATIONS`, `confirm_rules` всегда, `confirm_age` — только если `contest.eligibility_line` непуст, BR-48) — тот же водораздел, что у Этапа 1: домен решает, что допустимо, view знает контекст запроса. PRG на саму себя: успех показывает уже свёрстанный блок «өтінім бергенсің», ошибка — форму заново.
- `contest_withdraw` (новый view + `core:contest_withdraw`, `/contests/<slug>/withdraw/`): POST-only, GET безопасен и просто возвращает в «Менің өтінімдерім». Условие (приём идёт, `status=='reviewing'`) проверяет `data.withdraw_submission` заново — `can_withdraw` на странице решает только, показывать ли кнопку, а не охраняет сам POST. `withdraw_confirm_modal.html` получил `withdraw_url` в событии `open-withdraw-confirm` и настоящую `<form method="post">` с csrf — тот же приём, что у `delete_confirm_modal.html` (Этап 1).
- `contest_submit.html` потерял `@submit.prevent` — Alpine (`x-data` с `picked`/`vols`) остался только для пересчёта чек-листа объёма при смене выбранной работы (FR-CONT-04), саму отправку формы больше не перехватывает.
- Тесты: `core/tests/test_contest_submit.py` — 20 новых тестов (создание заявки с посланными полями, редирект, обязательность `ai_used`/`confirm_rules`/`confirm_age` — последний только когда конкурс ставит вилку, работа не из кандидатов отклоняется, отправка вне фазы приёма ничего не создаёт, повторная подача не плодит вторую строку, гостевой POST ничего не создаёт, отзыв удаляет заявку и не трогает чужую, GET отзыва безопасен, отзыв вне окна и без заявки — no-op). `AcceptedIsTheJuryWord.test_submit_form_does_not_promise_acceptance` переведён с чтения Alpine-атрибута на настоящий POST + `follow=True` — раньше строка «Өтінім жіберілді» бралась из мёртвой JS-заглушки, а не из ответа сервера.

### Этап 6 — Профиль ✅

`core/models.py` (`User.age`/`gender`/`avatar`), миграция `0015_user_profile_fields`, `core/domain/profile.py` (новый — `GENDERS`/`GENDER_LABELS`), `core/queries/profile.py`, `core/views/profile.py`, `core/admin.py`, `templates/pages/profile/profile_me_edit.html`, `templates/components/avatar.html` + 6 call sites.

- `User` получил три поля: `age`/`gender` — самодекларация (DEC-24), `avatar` — `FileField` с тем же `RASTER_ONLY`, что у `Story.cover`/`Contest.poster`, путь `avatars/<username>.<ext>` (`user_avatar_path`, по аналогии с `story_cover_path`). `gender` — закрытый список `GENDERS` (`core/domain/profile.py`, новый файл — тот же приём, что `AI_DECLARATIONS` у конкурса), а не голая строка.
- `data.update_profile` (`core/queries/profile.py`, рядом с `author_by_username` — не отдельный файл, тот же приём, что у мутаций Этапов 2-5): пишет пять полей на уже проверенных значениях; `avatar` — пусто значит «не меняем» (как `cover` у `update_story_settings`).
- `profile_me_edit`: POST-ветка валидирует обязательность `pen_name`/`name`, длины полей (пределы формы раньше расходились с `max_length` модели: `pen_name` — 80 в шаблоне против 60 в модели, значение длиннее 60 уронило бы `save()` ошибкой Postgres, а не мягкой формой), `gender` — только из `data.GENDERS`, `age` — целое 1-120, `avatar` — валидируется тем же `RASTER_ONLY`, что у `Story.cover`/наград (вызван явно: прямое присваивание `FileField` в обход `ModelForm` валидаторы не запускает — см. ниже, тот же пробел найден и закрыт у `story_settings.cover`). Успех — редирект на `core:profile_me` (как показывал старый Alpine-таймаут), ошибка — обратно на форму.
- **Найденный при реализации баг**: `value=profile_user.public_name` в поле «Авторлық атың» показывало производное (`pen_name or '@username'`), а не сырое `pen_name`. У автора без псевдонима форма отрисовала бы `@username`, и первый же сохранённый POST записал бы эту строку в `pen_name` буквально — молчаливая порча пустого поля. Исправлено на `value=profile_user.pen_name`; закрыто `ProfileEditPrefillsRawPenName`.
- `components/avatar.html` — двухрежимный, как `cover_placeholder.html`: новый опциональный параметр `avatar` (значение `User.avatar`), `<img>` если задан, иначе прежняя OKLCH-заглушка с инициалами. Обратно совместим — вызов без `avatar` не меняется. Реально передан там, где объект автора уже под рукой без лишнего запроса: `partials/profile/_header.html`, `components/author_row.html`, `partials/story/author_card.html`, `partials/home/new_authors.html`, `pages/story/story_detail.html` (шапка работы и своя реплика в форме комментария — там `avatar=user.avatar`, `user` уже глобален в контексте шаблона через `django.contrib.auth.context_processors.auth`), `components/comment.html` (`author_avatar` — новый параметр, и аватар в форме ответа — тоже `user.avatar`). Не тронуты жюри конкурса (`ContestDetail` — не `User`, аватара не бывает) и `templates/pages/_design/components.html` (витрина без объекта).
- Тесты: `core/tests/test_profile.py` — 20 новых тестов (сохранение всех полей, пустые `age`/`gender`/`bio` допустимы, обязательность `pen_name`/`name`, лимиты длины, невалидный `gender`/`age` откатывают весь POST, PNG-аватар принимается и ложится под `avatars/<username>`, SVG отклоняется и не даёт сохраниться остальным полям формы, гостевой POST ничего не сохраняет, редирект после ошибки — на саму форму, после успеха — в профиль, сырой `pen_name` в форме не подменяется публичным именем).

**Пробел, найденный здесь, закрыт и у `Story.cover`.** Этап 6 обнаружил: прямое присваивание `FileField` (`obj.cover = f; obj.save()`) не запускает `validators=[RASTER_ONLY]` — он срабатывает только внутри `ModelForm.full_clean()`, а мутации этого проекта идут в обход форм. Для `avatar` пробел закрыт сразу, здесь же; следом тем же приёмом закрыт и у `story_settings.cover` (Этап 1, `core/views/write.py`) — задним числом, отдельным проходом после Этапа 6, не расширяя его файловый список. Тесты — `StorySettingsCoverUpload` в `core/tests/test_write.py` (SVG отклоняется и блокирует весь POST, PNG принимается и ложится под `covers/<slug>`).

---

## 20.5 Риски и тесты

- Ни один текущий тест не делает `client.post(...)` к письменным маршрутам — весь POST-слой тестов пишется с нуля по каждому этапу, существующие GET-тесты не модифицируются.
- `core/tests/test_query_budget.py` не тронется на чтении (POST — новые пути), но стоит добавить бюджет на сами POST-запросы, если они начнут делать лишние SELECT — не обязательно в первом проходе.
- `core/tests/test_docs_sync.py` проверяет синхронность docs/CLAUDE.md — после добавления этого файла прогнать эту проверку.
- Миграции этой фазы (`StoryTag`, `ChapterReactionVote`, `CommentLike`, `PollVote`, `User.age/gender/avatar`, `Submission.ai_declaration/age_confirmed/rules_confirmed`) не трогают данные существующих таблиц — `seed_demo` может понадобиться дополнить (голоса/реакции демо-пользователей), но это не блокирует план.
