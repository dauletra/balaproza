# 12. Domain model contract for F14

> `Обновлён: 2026-08-21` · `Сверен с кодом: f1f896b`

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

What the table carries instead is the part `stub_data.py` cannot state: what must survive the migration and why.

| Model | Stub source | Must survive F14 |
|-------|-------------|------------------|
| **User / Author** | `Author` | DEC-01 holds: no separate Reader role — any signed-in user reads, writes, comments, saves and submits. Follows stay a small relation and must not drive navigation |
| **Genre** | `Genre` | Closed reference of 12 (DEC-11). `/genres/` is an overview page, `/catalog/` the primary reading entry, `/genres/<slug>/` a catalog filter entry — **not** a separate engine (DEC-27) |
| **Tag** | `Tag`, `TAGS`, `BLOCKED_TAG_PATTERNS` | Up to 10 per story (BR-TAG-01). `status`: `pending` / `accepted` / `rejected`. Pending visible to the author, hidden from public catalog and story views (BR-TAG-07). Blocked patterns stay admin-managed |
| **Story** | `Story` | `OnProcess` is a continuation state, **not** a moderation state. Public catalog carries only `Published` and explicitly allowed public states. `format` is chosen by the author, never inferred from chapter count (DEC-28). Status labels — `components/status_badge.html`, see [16 §16.3](16-content-voice.md) |
| **Chapter** | `Chapter`, `CHAPTERS_BY_STORY` | One-based numbers. Bodies live **outside** `stub_data.py` in `core/story_texts/<slug>/<n>.txt`; `_chapter()` loads them and derives `char_count`. Keep long prose out of the data module. Read via `?chapter=N` — no separate route (DEC-30) |
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
- `filter_catalog(*, query="", genre="", tag="", status="", sort="popularity", audience="", length="", format="") -> list[Story]`
- `apply_catalog_filters(stories, sort="popularity", status="", ...) -> list[Story]`
- `stories_by_genre(genre_slug: str) -> list[Story]`
- `search_stories(query: str) -> list[Story]`
- `search_authors(query: str, limit=5) -> list[Author]`
- `related_stories(slug: str, limit=6) -> list[Story]`

Story and chapters:
- `chapters_of(story_slug: str) -> list[Chapter]`
- `chapter_of(story_slug: str, number: int) -> Chapter | None`
- `comments_of(story_slug: str) -> list[StoryComment]`
- `comments_of_chapter(story_slug: str, chapter_number: int) -> list[StoryComment]`
- `reactions_of(chapter: Chapter) -> list[dict]` — полный ряд из пяти реакций, включая нулевые (BR-REACT-01)
- `reaction_breakdown(story_slug: str) -> list[dict]` — «чем зацепила каждая глава», для авторского кабинета
- `poll_of(story_slug: str, chapter_number: int) -> ChapterPoll | None` — опрос необязателен (BR-POLL-01)

Author workspace, library, social:
- `my_stories_of(username: str) -> list[Story]`
- `writer_stats(username: str) -> dict`
- `library_of(username: str, kind: str = "") -> list[LibraryEntry]`
- `in_library(username: str, story_slug: str) -> bool`
- `reader_stats(username: str) -> dict`
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
- format (DEC-28): `format`, `format_label`, `format_badge_label`, `is_single`, `is_serial`
- reading effort: `total_chars`, `read_minutes`, `length_bucket`, `reading_meta_label`

Author:
- `username`, `name`, `bio`, `works`, `followers`

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
