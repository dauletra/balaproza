# 04 · Библиотека компонентов

Спецификация переиспользуемых UI-компонентов: назначение, входные параметры (props), состояния и поведение. Компоненты обязаны использовать токены из модуля 02.

## 4.1 Бренд

### `Logo`
| Prop | Тип | По умолч. | Описание |
|------|-----|-----------|----------|
| `subtitle` | boolean | `true` | Показывать ли подпись «Балалар әдеби порталы» |

Логотип-картинка 36×36 + «Balaproza» (Montserrat 700, 24px). Кликабелен → ведёт на главную.

## 4.2 Кнопки

### `PrimaryButton`
Заливка `--teal`, белый текст, высота 37px, radius 8. Props: `children`, `icon?`, `width?`, `color?` (по умолч. `--teal`), `textColor?`.
Состояния: hover → `--teal-dark`; focus-visible → обводка; disabled → opacity 0.5.

### `SecondaryButton`
Белый фон, рамка и текст `--teal`. Те же props и состояния.

### `TelegramLoginPill`
Пилюля 999px, иконка Telegram + текст «Сайтқа кіру». Единственная точка входа в систему (см. модуль AUTH). Prop `width?`.

## 4.3 Карточки произведений

| Компонент | Обложка | Контекст | Доп. поля |
|-----------|---------|----------|-----------|
| `BookCardSmall` | 100×150 верт. | Карусели главной | title, author |
| `BookCardWide` | 80×120 гор. | Списки (mobile) | + genre, stats, description (clamp 4 строки) |
| `DeskBookCardWide` | 120×180 гор. | Списки (desktop) | расширенная Wide |

Все клики по карточке → страница произведения. `stats` = `{ likes, views, comments }` через `StatPill`.

### `CoverPlaceholder`
Двухрежимная «обложка» произведения. Если у `story.cover` задано имя файла — рендерит `<img src="/media/{cover}">` с `object-cover`. Иначе — типографическая плашка: цветная OKLCH-плашка + первая буква названия в display-фонте + тонкий цветной «корешок» слева. Hue берётся из `story.primary_genre.hue`, что одновременно работает как **визуальный маркер жанра** в карточке (фэнтези — фиолетовый, драма — бирюзовый и т.д.). Параметры: `story`, `cls` (внешние размеры/радиусы), `letter_cls` (размер буквы для letter-режима), `href` (опц.).

Все карточки произведений (`BookCardSmall`, `BookCardWide`, `DeskBookCardWide`, `LibraryRow`, `MyStoryRow`), а также шапки `story_detail`, `book_of_week`, `manage_story`, `story_settings`, hero `hero_returning` (continue-reading mode), мини-обложка в правом рейле — используют `CoverPlaceholder` (никогда не `{% static story.cover %}` напрямую). На MVP в `media/` лежат placeholder-обложки; пустой `cover` корректно деградирует до типографической плашки.

### `StatPill`
Иконка + значение. Иконки: `ThumbsUp` (лайки), `Eye` (просмотры), `MessageCaption` (комментарии). Цвет `--slate-600`, 12px.

## 4.4 Бейджи и статусы

### `Badge`
Базовая пилюля. Props: `children`, `bg`, `color`, `icon?`. Высота 22px, radius 999.

### `StatusBadges` — справочник статусов произведения
Централизованный набор (запрещено собирать статусы вручную):

| Ключ | Текст (kk) | Семантика |
|------|-----------|-----------|
| `Published` | Жарияланған | success + ✓ |
| `NotPublished` | Жарияланбаған | error |
| `OnProcess` | Жазылып жатыр | warning |
| `Completed` | Аяқталды | info + ✓ |
| `OnModeration` | Тексеруде | attention |

Статусная модель — BR-10/BR-11.

## 4.5 Формы

### `InputField`
Props: `label?`, `placeholder`, `value?`, `showSearch?`. Высота 36, фон `--slate-50`, рамка `--slate-300`, radius 8.

### `InputValidated`
Расширение `InputField` с состоянием валидации. Prop `state`: `default | success | error`. При `error` — красная рамка + текст ошибки; при `success` — зелёная отметка.

### `TextArea`
Props: `label?`, `placeholder`, `value?`, `count` (счётчик символов вида `0/250`), `h` (высота). Счётчик обязателен для полей с лимитом (аннотация, био).

### `Toggle`
Переключатель 40×20. Prop `on`. Включённое состояние — фон `--teal`, кружок справа. Анимация 150ms.

### `RadioOption`
Радио-кнопка с подписью. Props: `checked`, `label`. Выбранное — 5px бирюзовая рамка.

> ✅ **Решение DEC-13.** Все поля форм поддерживают три визуальных состояния валидации (default/success/error) через единый `InputValidated`/`TextAreaValidated`. Сообщение об ошибке выводится под полем, привязано через `aria-describedby`.

## 4.6 Контент и социальное

### `Comment`
Блок комментария. Props: `name`, `date`, `text`, `likes`, `badge?` (напр. «Автор»). Содержит аватар, лайк (`Heart`), меню (`DotsHorizontal`), ссылку «жауап беру». Поддерживает один уровень ответов (BR-30).

### `CommentLoginGate`
Заглушка вместо поля комментария для гостя: «Пікір қалдыру үшін кіріңіз» + кнопка входа. Показывается, когда роль = Гость.

### `Avatar`
Заглушка: **буквенные инициалы** (первая буква отображаемого имени) на OKLCH-фоне. Hue стабильно выводится из длины seed (`username + name`) — один и тот же автор всегда получает один и тот же цвет. Размер шрифта пропорционален `size`. Параметры: `size` (px, default 36), `name` (для инициалов и aria-label), `username` (опц., для стабильного цвета). В продакшене заменится на фото пользователя.

## 4.7 Навигация и служебные

| Компонент | Платформа | Назначение |
|-----------|-----------|-----------|
| `MobileHeader` | mobile | Шапка 375×64: лого + поиск |
| `MobileBottomNav` | mobile | 5 пунктов: home / saved / **plus (FAB)** / bell / profile |
| `DesktopHeader` | desktop | Лого, поиск (520px), ссылка «Байқаулар» (с активной подсветкой), CTA «Шығарма жазу» (с иконкой pen), bell+счётчик, аватар-dropdown с иконками (Профиль / Менің шығармаларым / Кітапхана / Менің заявкаларым / Шығу) либо «Кіру» для гостя |
| `DesktopFooter` | desktop | Карта сайта (4 колонки): Байланыс · Контент · Сайт · Құжаттар + Авторлар мектебі. См. 7.5 |
| `SectionHeader` | оба | Заголовок секции + стрелка |
| `Pagination` | оба | ‹ 1 2 3 … › активная в синей заливке |
| `GenreChip` | оба | Цветной чип жанра (OKLCH, модуль 03) |
| `Countdown` / `ContestStatus` | оба | Отсчёт дней и статус конкурса |

> ✅ **Решение DEC-25.** `DesktopSidebar` исключён. Контентная навигация — секции главной + колонка footer; единственная нав-ссылка в хедере — `Байқаулар` (без альтернативного входа с главной); личные разделы — через аватар-dropdown. Bottom nav на mobile без изменений.

> ✅ **Решение DEC-14.** В прототипе сосуществовали `GenrePill` (плоский текст) и `GenreChip` (цветной). В продакшене остаётся **только `GenreChip`** — единый компонент жанра на базе OKLCH. `GenrePill` исключается.

## 4.8 Модальные окна и оверлеи

| Компонент | Назначение |
|-----------|-----------|
| `LoginModal` | Вход через Telegram |
| `ReportModal` | Жалоба на контент: выбор причины + комментарий |
| `DeleteConfirm` | Подтверждение удаления произведения (деструктивное действие) |
| `ReaderSettingsPopover` | Настройки чтения: шрифт (Sans/Serif), размер, тема (светлая/тёмная) |
| `ToastShowcase` → `Toast` | Системные уведомления: success/info/error, автоскрытие |

Все модалки: затемнённый бэкдроп, закрытие по `Esc` и клику вне, кнопка `X` с `aria-label="Жабу"`, фокус-trap внутри (NFR-доступность).

## 4.9 Иконки (`templates/components/icons/_sprite.html`)

Один SVG-спрайт, подключённый один раз в `base.html` сразу после `<body>`. Каждая иконка — `<symbol id="icon-…">`, вызывается через `components/icon.html with name="…"`. Базовый стиль — `currentColor` (цвет берётся из CSS `text-*`), `viewBox=24`.

Состав:

- **Навигация:** Search, ArrowRight/Left, AngleLeft/Right, ChevronLeft/Right, X
- **Действия:** Home, Bookmark/-filled, Bell, UserCircle, Plus, Pen, Cog, Trash, Upload, PaperPlane, List, Check, Adjustments, Book, ArrowRightToBracket
- **Метрики:** ThumbsUp/-filled, Eye, MessageCaption, Heart/-filled
- **Меню:** DotsHorizontal, DotsVertical
- **«Настроения» для коллекций (DEC-25 ассеты):** Drop, Backpack, Planet, Cityscape, Feather, Fir, Skull, Smile. Каждой коллекции в `stub_data.Collection.icon` соответствует один из них (например, «Көзжасты түн» — `drop`, «Мектеп күнделігі» — `backpack`).
- **Бренд:** Telegram (с градиентом), Instagram, TikTok, YouTube

> ✅ **Решение DEC-09b.** Набор смешивает залитые (`fill`) и контурные (`stroke`) иконки. Фиксируется единый стиль — **контурный (outline) 2px** для всех иконок интерфейса; залитые остаются только там, где это семантически оправдано (заполненный `Heart`/`Bookmark` = активное состояние «лайкнуто»/«сохранено»).

> ✅ **Правило (no-emoji).** Стандартные эмодзи (☀️ 📖 🇰🇿 🕯️ 😢 🎒 👽 🌆 ✍️ 🎄 🧟 😄 и т.п.) в шаблонах, stub_data и любом контенте проекта **запрещены** — они выглядят дёшево и роняют уровень дизайна. Если нужна «иконка настроения» (как в коллекциях) — добавляем SVG-symbol в спрайт. Если нужна разметка для пользовательского контента (комментарии) — оставляем как есть, пользователи могут писать эмодзи в своих текстах.

## 4.10 Состояния и инфраструктура (DEC-17 implementations)

Эти компоненты не были описаны в прототипе явно, но реализованы как обязательные элементы дизайн-системы (на основе DEC-17 и UX-практик).

### `skeleton_book_card_small` / `skeleton_book_card_wide`
Скелетон-плейсхолдер карточки произведения. Используется в loading-состоянии. Параметров нет — повторяет геометрию реальной карточки с пульсирующими блоками `bg-slate-200 animate-pulse`.

### `skeleton_text` / `skeleton_comment`
Универсальные скелетоны для блоков текста и комментариев. `skeleton_text` принимает `lines` (default 3).

### `error_state`
Блок ошибки загрузки данных. Параметры: `title` (text), `text` (description), `retry_href` (опционально — ссылка повтора). Иконка `x` в круге, кнопка «Қайталау».

### `empty_state`
Блок пустого состояния (нет данных). Параметры: `icon` (имя иконки), `title`, `text`, `action_label` (опц), `action_href` (опц).

### `segmented_control`
Реальный переключатель табов через `?tab=` (DEC-15: не псевдо-табы). Параметры:
- `items` — список `{slug, label, count}` (count опц)
- `current` — текущий ключ
- `base_url` — URL без `?tab=` (для href)
- `param` — имя GET-параметра (default: `tab`)

Используется на `library.html` (3 вкладки saved/reading/done) и `profile.html`.

### `delete_confirm_modal`
Модал подтверждения деструктивного действия. Параметры: `title`, `body`, `confirm_label` (default «Жою»), `cancel_label` (default «Болдырмау»), `action_url` (form POST), `dispatch` (custom Alpine event для открытия).

### `toast_host` + событие `toast`
Глобальный приёмник тостов. Подключён один раз в `base.html`. Любая страница диспатчит:
```js
$dispatch('toast', { kind: 'success'|'info'|'warning'|'error', text: '...' })
```
Тост появляется снизу, исчезает через 3.5с.

### `share_button`
Кнопка «Бөлісу» с двумя режимами: на мобайле — `navigator.share()` (Web Share API), на десктопе — dropdown с Telegram/WhatsApp/Copy link (через clipboard API). Параметры: `url` (обязательно), `title`, `label`.

### `search_popup`
Глобальный quick-search модал. Открытие: хоткей **⌘K / Ctrl+K** или событие window `open-search`. Содержит до 5 произведений и 5 авторов по substring-совпадению. Enter → полноценная страница `/search/?q=`. Данные приходят как JSON-индекс через context_processor `search_index`. Подключён один раз в `base.html`.

### `catalog_controls` removed (DEC-27)
Старая sort+status панель удалена. После унификации каталога её заменяет секция Сұрыптау/Мәртебесі внутри `partials/catalog/_filter_panel.html`.

### `school_links`
Блок внешних ссылок «Авторлар мектебі» (DEC-22). Параметры: `links` (итерируемый), `layout` (`"list"` | `"grid"` | `"inline"`).

## 4.11 Унифицированный каталог (DEC-27)

После DEC-27 search/genre/tag/catalog рендерятся одним шаблоном `pages/catalog/catalog.html` через тонкие view-обёртки над `_render_catalog()`. Каркас собирается из переиспользуемых партиалов:

| Партиал | Назначение |
|---------|-----------|
| `partials/catalog/_hero_search.html` | Search-режим: поле ввода + echo запроса |
| `partials/catalog/_hero_genre.html` | Genre-режим: hue-tinted блок, имя жанра, счётчик |
| `partials/catalog/_hero_tag.html` | Tag-режим: slate-блок + `#`-префикс, usage_count |
| `partials/catalog/_hero_catalog.html` | Нейтральный hero для `/catalog/` |
| `partials/catalog/_book_list.html` | Список `book_card_wide` + empty-state (переиспользуется И коллекциями) |
| `partials/catalog/_filter_panel.html` | Sort + status + q (refining) + genre chip-cloud + popular tags chip-cloud. В рейле всегда, в форме `@change="$el.requestSubmit()"` |
| `partials/catalog/_filter_sheet.html` | Mobile bottom-sheet с тем же `_filter_panel`. Триггер: `$dispatch('open-catalog-filters')` |
| `partials/right_rail/catalog.html` | Wrapper рейла: оборачивает `_filter_panel` в card |

Комбинация фильтров — через query string: `/genres/triller/?tag=mektep&status=Published`. Тонкая обёртка — `_render_catalog(request, mode='...', genre_slug=..., tag_slug=...)`.

## 4.12 Теги (UGC, docs/11)

### `tag_chip`
Нейтральный slate-чип для UGC-тега. Параметры: `tag` (объект `Tag` с `.slug`, `.name`, `.status`), `href` (опц., default `/tag/<slug>/` для accepted; `'#'` для pending), `size` (`sm` | `md`).

Pending-теги автоматически с пунктирной рамкой + бейдж «проверкада» (BR-TAG-07 — видны только автору, в публичной выдаче скрыты через `tag_list`).

### `tag_list`
Ряд `tag_chip` для произведения. Параметры: `tags` (resolved Tag-список через `stub_data.tags_of(story)`), `viewer_is_author` (bool, default `False`), `size`. Скрывает pending-теги для не-автора.

### `tag_input`
Alpine-компонент для формы (`new_story`, `story_settings`). Включает: input с автокомплитом по `accepted_tags`, чипы выбранных с ×, счётчик `N/10` (BR-TAG-01), inline-валидация (длина 2-30, blocklist, дубль). Hidden input `name="tags"` отправляет names через запятую (backend сам резолвит slug и создаёт `Tag(status=pending)` для новых).

Контекст view обязательно даёт: `accepted_tags` (через `stub_data.accepted_tags_json()`), `blocked_patterns` (через `stub_data.blocked_tag_patterns_list()`). Initial — список существующих `Tag` для edit-режима.
