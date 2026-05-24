# 11 · Теги (Tags) — UGC-таксономия

## 11.1 Назначение

Жанры (модуль 03) — закрытый справочник 12 категорий, заданный редакцией. Теги — открытая UGC-таксономия: авторы сами придумывают ключевые слова, описывающие детали произведения («мектеп», «достық», «саяхат», «сиқыр-академиясы»). Теги дополняют жанры, а не заменяют их.

Зачем: жанровая сетка слишком грубая для дискавери — два «фэнтези» могут быть совершенно разными произведениями. Теги дают читателю second-order навигацию («хочу фэнтези **про школу магии**»), а автору — способ донести оттенки темы без новых жанров.

## 11.2 Бизнес-правила

| ID | Правило |
|----|---------|
| **BR-TAG-01** | Произведение может иметь до **10 тегов** одновременно. Жанры считаются отдельно (1 основной + до 1 доп.). |
| **BR-TAG-02** | Автор вводит тег в свободной форме. Длина 2-30 знаков, разрешены kk/ru/lat буквы + цифры + дефис. |
| **BR-TAG-03** | Каждый созданный тег попадает в статус `pending`. Модератор пост-фактум переводит в `accepted` или `rejected`. |
| **BR-TAG-04** | Только `accepted`-теги показываются в автокомплите следующим авторам. |
| **BR-TAG-05** | Часть тегов в блок-листе — их создать нельзя (мат, бренды, политика, спам). UI отклоняет inline до отправки формы. |
| **BR-TAG-06** | Если введённый тег точно (case-insensitive) совпадает с существующим `accepted` — переиспользуется (не создаётся дубль). |
| **BR-TAG-07** | Pending-теги отображаются автору в его произведении с индикатором «проверкада». В публичном каталоге/поиске фильтр работает только по `accepted`. |
| **BR-TAG-08** | Rejected-тег удаляется из произведения; автор получает уведомление с причиной. |
| **BR-TAG-09** | Языки контента: kk и ru разрешены. В MVP — экзактный match. Алиасы (`школа` = `мектеп`) — вне MVP (см. 11.9). |

## 11.3 Жизненный цикл тега

```
[author types tag in form]
       │
       ▼
[blocklist check]  ──fail──> inline error, prompt to remove
       │ pass
       ▼
[exact match accepted?]  ──yes──> reuse existing (no new Tag)
       │ no
       ▼
[create Tag status=pending]  ──> linked to story
       │
       ▼
[moderator review in Django admin]
       ├── accept                     → enters autocomplete; public filter works
       ├── reject (+note)             → removed from story; author gets notification
       └── block (+add to blocklist)  → also prevents future creation
```

## 11.4 Модель данных (для Ф14)

```python
@dataclass
class Tag:
    slug: str                # auto: lower + transliterate (мектеп → mektep)
    name: str                # оригинал (отображается)
    status: str              # 'pending' | 'accepted' | 'rejected'
    created_by: str          # username
    created_at: datetime
    usage_count: int         # денормализовано, для сортировки автокомплита
    moderator_note: str = '' # причина rejected

class Story:
    # ...existing fields...
    tags: tuple[str, ...] = ()   # slug-список, max 10 (BR-TAG-01)

# Блок-лист — отдельная таблица, чтобы модератор мог редактировать без релиза
class TagBlock:
    pattern: str        # exact или regex
    reason: str         # коммент для модератора
    added_by: str
    added_at: datetime
```

## 11.5 UI-поверхности

| Раздел | Где появляется | Что показывает |
|--------|----------------|----------------|
| **WRITE · new_story** | Поле «Тегтер» под жанрами | input с автокомплитом (`accepted`), чипы выбранных, счётчик `N/10` |
| **WRITE · story_settings** | То же поле | редактирование уже существующих тегов |
| **STORY · детальная** | Ряд под genre-chips | `accepted` — нейтральные slate-чипы (отличается от цветного `genre_chip`); `pending` — только автору с бейджем «проверкада» |
| **CAT · /tag/<slug>/** | Новый маршрут | каталог-страница, отфильтрованная по тегу |
| **CAT · controls** | Catalog filter section | секция «Тегтер» (V2-кандидат) |
| **CAT · search popup (Cmd+K)** | Группа результатов | раздел «Тегтер» наряду со Story/Author (V2) |
| **HOME · сайдбар** | Виджет «Танымал тегтер» | топ-10 `accepted` по `usage_count` (V2-кандидат) |
| **MOD · Django admin** | Tag-список + фильтр по status | bulk accept/reject/block; редактор блок-листа (DEC-23) |

## 11.6 Новые компоненты

| Компонент | Назначение |
|-----------|------------|
| `tag_chip.html` | Визуальный чип. Нейтральный slate-стиль (vs цветной `genre_chip`). Опц. `href` → tag-каталог. Опц. `pending=True` → серый бейдж |
| `tag_list.html` | Ряд тегов с overflow «+N more» при количестве > k |
| `tag_input.html` | Alpine-компонент: input + dropdown автокомплита (из `accepted_tags`), валидация blocklist, чипы добавленных с ×, счётчик |

## 11.7 Стаб-данные (фаза 1)

Расширение `stub_data.py`:

```python
@dataclass(frozen=True)
class Tag:
    slug: str
    name: str
    status: str               # 'pending' | 'accepted'
    usage_count: int

TAGS = [
    Tag('mektep',           'мектеп',           'accepted', 42),
    Tag('dostyk',           'достық',           'accepted', 38),
    Tag('sayahat',          'саяхат',           'accepted', 24),
    Tag('jasospirim',       'жасөспірім',       'accepted', 56),
    Tag('gashyqtyq',        'ғашықтық',         'accepted', 31),
    Tag('mistika',          'мистика',          'accepted', 18),
    Tag('syikyr-akademiya', 'сиқыр-академиясы', 'accepted', 12),
    Tag('arman',            'арман',            'accepted', 27),
    Tag('detektiv-jas',     'жас детектив',     'accepted',  9),
    Tag('aua-ralighi',      'ауыл-қала',        'accepted', 14),
    # pending — для иллюстрации модерации
    Tag('basqa-alem',       'басқа әлем',       'pending',   3),
    Tag('experimental',     'эксперимент',      'pending',   1),
]

BLOCKED_TAG_PATTERNS = {
    # MVP-минимум, пополняется через Django admin
    'spam', 'реклама', 'политика',
}

# Story.tags хранит slug-list, поле добавляется в Ф14:
#   Story("dalney-berega", ..., tags=("mektep", "dostyk", "syikyr-akademiya"))
```

Helpers:
- `accepted_tags() -> list[Tag]`
- `popular_tags(limit=10) -> list[Tag]` — sort by `usage_count` desc
- `tag_by_slug(slug) -> Optional[Tag]`
- `is_blocked(name) -> bool`
- `suggest_tags(prefix, limit=5) -> list[Tag]` — для автокомплита
- `tags_of(story) -> list[Tag]` — resolved из `story.tags`
- `stories_by_tag(slug, status='accepted') -> list[Story]`

## 11.8 План внедрения (поэтапно)

### Фаза 1 — Стаб и компоненты (дизайн-итерация) ✓ ГОТОВО
- [x] `Tag` dataclass + `TAGS` seed + helpers в `stub_data.py`
- [x] `Story.tags` поле (с дефолтом `()`) + теги назначены 8 стори
- [x] `components/tag_chip.html`
- [x] `components/tag_list.html`
- [x] Показ тегов на `story_detail.html` (ряд под genre-chips)
- [x] Smoke-тесты: `tag_chip` рендерится; pending-бейдж — только автору (BR-TAG-07)

### Фаза 2 — Write-форма ✓ ГОТОВО
- [x] `components/tag_input.html` (Alpine: автокомплит, чипы, счётчик)
- [x] Интеграция в `pages/write/new_story.html` и `story_settings.html`
- [x] Inline-ошибка при попадании в blocklist + длина + дубль + лимит
- [x] Showcase состояний в `_design/components.html` (секция «Теги»)

### Фаза 2.5 — Унификация каталог-движка (предусловие к Фазе 3, см. DEC-27)
Цель: убрать дубликат между `search_results` и `genre_detail` (90% одинаковые) и подготовить базу под `/tag/<slug>/`, чтобы Фаза 3 не плодила третий клон шаблона.

- [ ] Извлечь `partials/catalog/_book_list.html` — список карточек + empty-state
      (переиспользуется каталогом И коллекциями)
- [ ] Извлечь `partials/catalog/_filter_bar.html` — активные фильтры как чипы с ×
      (genre / tag / search query) + сортировка/статус
- [ ] Извлечь hero-партиалы:
      `partials/catalog/_hero_search.html`, `_hero_genre.html`
- [ ] Создать общий `pages/catalog/catalog.html` — собирает hero + filter_bar + book_list
- [ ] View-функция `catalog(request, *, genre=None, tag=None, query=None)`
      — единый pipeline через `apply_catalog_filters` с поддержкой комбинаций
- [ ] Тонкие обёртки-view: `search_results`, `genre_detail` делегируют в `catalog`
- [ ] Поддержка комбинаций через query-string: `/genres/triller/?tag=mektep`
- [ ] Тесты: проверить что старые URL по-прежнему работают и рендерят те же маркеры

**Что НЕ меняется в этой фазе:** коллекции (`collections.html`, `collection_detail.html`)
остаются отдельным типом — они переиспользуют только `_book_list.html`,
не каталог-движок (DEC-27).

### Фаза 3 — Теги в унифицированном каталоге ✓ ГОТОВО
- [x] Маршрут `/tag/<slug>/` → тонкая view-обёртка `tag_detail` → `_render_catalog(mode='tag')`
- [x] `partials/catalog/_hero_tag.html` (slate + `#`-стиль, отличается от genre-hue)
- [x] Tag показывается как chip в правом рейле (`_filter_panel`) с ×-снятием на активном
- [x] Pending/unknown теги → error-блок «Тег табылмады» (BR-TAG-07)
- [x] Multi-tag в UI пока один за раз; `filter_catalog(tag=slug)` поддерживает combinations
- [x] `tag_chip.html` дефолтный href = `/tag/<slug>/` для accepted, `#` для pending
- [x] Search popup (Cmd+K): группа результатов «Тегтер»; `search_index_json` отдаёт только accepted
- [ ] Правый рейл главной: виджет «Танымал тегтер» (V2-кандидат, опц. — не делали)

### Фаза 4 — Модерация (после Ф14, когда модели в БД)
- [ ] Django admin: `Tag`-список с фильтром по `status`
- [ ] Custom actions: Accept selected / Reject (with note) / Block
- [ ] `TagBlock`-модель + admin для блок-листа
- [ ] Notification flow: автор получает уведомление при rejected/blocked
- [ ] SLA: модерация тегов в течение N дней (open question)

## 11.9 Открытые вопросы

1. **Видимость pending-тегов в публичном каталоге** — скрывать полностью или показывать с бейджем «проверкада»? *Предложение: скрывать в публике, видны только автору.*
2. **Multi-tag фильтр** — AND или OR при выборе двух тегов? *Предложение: AND в V1.*
3. **Alias/synonyms** — модератор объединяет «школа» = «мектеп»? *Предложение: вне MVP, V2.*
4. **Auto-suggest из текста главы** — извлекать ключевые слова автоматически и предлагать? *Предложение: вне MVP, V3.*
5. **SLA модерации тегов** — сколько часов/дней? *Open.*
6. **Кто может блокировать паттерн** — любой модератор или только суперюзер? *Open.*
7. **Тег в book_card_small** — показывать ли 1-2 топ-тега под названием в каточках главной/каталога? *Предложение: нет, только на детальной (карточка перегружается).*

## 11.10 Связи с другими модулями

- **03 Genres** — теги дополняют жанры, не заменяют. Жанры остаются 12 закрытых.
- **05 Functional spec** — добавятся: FR-WRITE-* (поле тегов), FR-STORY-* (отображение), FR-CAT-* (фильтр по тегу), FR-MOD-* (модерация в admin).
- **08 Business rules** — добавятся BR-TAG-01…09 (выше в 11.2).
- **10 Resolved decisions** — DEC-26 (тегирование как UGC-таксономия параллельно жанрам); DEC-27 (унификация catalog-движка для search/genre/tag; collections остаются отдельным типом — editorial curation).
- **CLAUDE.md** — упоминание `tag_chip`, `tag_input`, `tag_list` в списке компонентов после реализации фазы 1.
