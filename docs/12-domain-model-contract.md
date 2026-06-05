# 12. Domain model contract for F14

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

### User / Author profile

Source stub: `Author`.

Persisted fields:
- `username`
- `name`
- `bio`
- `gender`
- `age`
- profile/avatar seed or uploaded avatar later

Computed/query values:
- `works_count`
- `followers_count`
- `following_count`
- reader/writer stats

Notes:
- DEC-01 stays: there is no separate Reader role. Any signed-in user can read, write, comment, save, and submit.
- Follows can remain a small relation and should not drive MVP navigation.

### Genre

Source stub: `Genre`.

Persisted fields:
- `slug`
- `name`
- `hue`
- `icon`
- optional ordering

Computed/query values:
- published story count

Notes:
- `/genres/` is an overview page.
- `/catalog/` is the primary reading entry.
- `/genres/<slug>/` is a catalog filter entry, not a separate engine.

### Tag

Source stub: `Tag`, `TAGS`, `BLOCKED_TAG_PATTERNS`.

Persisted fields:
- `slug`
- `name`
- `status`: `pending`, `accepted`, `rejected`
- `usage_count` can be cached or computed

Relationships:
- many-to-many with `Story`

Business rules:
- story can have up to 10 tags.
- pending tags are visible to the author, hidden from public catalog and public story views.
- blocked patterns stay admin-managed after F14.

### Story

Source stub: `Story`.

Persisted fields:
- `slug`
- `title`
- `author`
- `cover`
- `annotation`
- `status`
- `audience`
- `primary_genre`
- `secondary_genre`
- timestamps: created, updated, published

Relationships:
- author: user/profile
- genres: primary and optional secondary
- tags: many-to-many

Status UX labels:
- `NotPublished` -> `Жоба`
- `OnModeration` -> `Модерацияда`
- `Published` -> `Жарияланды`
- `Completed` -> `Аяқталды`
- `OnProcess` -> `Жазылып жатыр`

Notes:
- `OnProcess` is a continuation state, not a moderation state.
- Public catalog should only include `Published` and any explicitly allowed public states.
- Current templates expect `primary_genre`, `genres_resolved`, `tags_resolved`, and `author`-like accessors.

### Chapter

Source stub: `Chapter`, `CHAPTERS_BY_STORY`.

Persisted fields:
- `story`
- `number`
- `title`
- `body`
- `char_count`
- `likes_count` can be cached or computed

Business rules:
- one-based chapter numbers.
- story detail reads one chapter via `?chapter=N`.
- right rail uses chapters as the chapter index.

### Collection

Source stub: `Collection`.

Persisted fields:
- `slug`
- `name`
- `description`
- `curator`
- `icon`
- ordering

Relationships:
- ordered many-to-many with `Story`

Notes:
- Collections remain separate from contests.
- Collections are editorial curation, not smart auto-filters in MVP.

### Contest

Source stub: `Contest`.

Persisted fields:
- `slug`
- `name`
- `subtitle`
- `description`
- `status`: `active`, `finished`
- `deadline`
- `prize_kzt`
- rules/checklist fields

Relationships:
- submissions

Notes:
- Contests remain separate from collections.
- Moderation/admin UI is Django admin for MVP.

### Submission

Source stub: `Submission`.

Persisted fields:
- `contest`
- `story`
- `author`
- `status`: `reviewing`, `accepted`, `rejected`
- `submitted_at`
- AI declaration fields
- age self-declaration field

Business rules:
- one story can be submitted once per contest by the author.
- eligibility is a query/service concern, not template logic.

### LibraryEntry

Source stub: `LibraryEntry`.

Persisted fields:
- `user`
- `story`
- `kind`: `saved`, `reading`, `done`
- `current_chapter`
- `updated_at`

Computed/query values:
- minutes left
- progress percent

Notes:
- Mobile nav prioritizes library for signed-in users.
- Continue reading should be a first-class reader workflow.

### Comment

Source stub: `StoryComment`.

Persisted fields:
- `story`
- `chapter` nullable
- `author`
- `text`
- `created_at`
- `parent` nullable
- `likes_count` can be cached or computed

Business rules:
- one reply level only in MVP.
- reply form and comment-like persistence can wait until after the core model migration.

### Notification

Source stub: `Notification`.

Persisted fields:
- `user`
- `kind`
- `actor`
- `story`
- `contest`
- `text`
- `created_at`
- `read_at`

Notes:
- Notifications should stay secondary in MVP.
- Header badge and notifications page are enough.

## 12.3 Query/service helpers to preserve

Current views rely on these helper shapes from `stub_data.py`. In F14 they should move to query/service functions, not into templates:

- `my_stories_of(user)`
- `chapters_of(story)`
- `comments_of_chapter(story, chapter_number)`
- `stories_by_genre(slug)`
- `search_stories(query)`
- `search_authors(query)`
- `related_stories(story, limit=6)`
- `filter_catalog(query="", genre="", tag="", status="", sort="popularity")`
- `library_of(user, kind=None)`
- `reader_stats(user)`
- `writer_stats(user)`
- `is_following(me, them)`
- `following_of(user)`
- `followers_of(user)`
- `notifications_for_user(user)`
- `unread_count_for_user(user)`
- `submissions_of(user)`
- `has_submission(user, contest)`
- `submission_checklist(story, contest)`
- `eligible_for_contest(user, contest)`
- `tag_by_slug(slug)`
- `tags_of(story)`
- `popular_tags(limit=8)`

## 12.4 Template contract

Templates should continue receiving objects with these attributes:

Story:
- `slug`, `title`, `cover`, `annotation`, `status`, `audience`
- `views`, `likes`, `comments`, `chapters`
- `author`
- `primary_genre`
- `genres_resolved`
- `tags_resolved`
- `badges`

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
