# AO3 API Proxy -- Formal Specification

## 1. Overview

The AO3 API proxy is a local FastAPI server that decouples the autonovel agent
code from direct AO3 web scraping. AO3 has no official API; all data comes from
HTML scraping. The proxy provides a clean JSON REST interface that the agent and
other pipeline tools consume, hiding scraping details, caching, and rate
limiting behind stable endpoints.

### Role in the System

```
Agent code  --->  Local proxy (localhost:8000)  --->  AO3 (scraping)
                         |
                   publish_queue/  (filesystem)
```

The proxy serves four endpoint categories:

1. **Browse and Search** -- list and search works by fandom, tag, query, or user.
2. **Metrics** -- per-work and per-user aggregate statistics.
3. **Comments** -- retrieve comments on works and chapters.
4. **Publish Queue** -- stage work drafts for human-reviewed posting to AO3.

### Dependencies

| Dependency | Role |
|------------|------|
| `fastapi` | HTTP framework |
| `uvicorn` | ASGI server |
| `httpx` | HTTP client for AO3 requests |
| `beautifulsoup4` | HTML parsing of AO3 pages |
| `pydantic` v2 | Request/response schema validation |

### Modes

- **Real mode** (default): Proxies requests to AO3 via `ao3_client.py` with
  rate limiting and disk caching.
- **Mock mode** (`--mock` flag or `MOCK_MODE=true`): Returns deterministic seed
  data from `mock.py`. No network requests are made.

---

## 2. Current State

The following modules exist in `api/`:

| File | Purpose | Status |
|------|---------|--------|
| `__init__.py` | Package docstring | Complete |
| `models.py` | Pydantic v2 models: `WorkStats`, `WorkSummary`, `ChapterDetail`, `WorkDetail`, `Comment`, `PublishRequest`, `QueueItem`, `QueuePatchRequest`, `UserStats`, `SearchParams`, enums (`Rating`, `SortField`, `QueueStatus`) | Complete |
| `server.py` | FastAPI app with 12 endpoints across browse, metrics, comments, and publish queue categories | Complete |
| `ao3_client.py` | Real AO3 scraper with rate limiting (1 req / 3 s), disk-based caching, and BeautifulSoup parsing | Complete |
| `queue.py` | Filesystem-based publish queue (`publish_queue/` directory, JSON files) | Complete |
| `mock.py` | Deterministic seed data (3 works, 5 comments, 2 authors) for testing | Complete |

All modules are implemented and functional. No endpoints are stubbed.

---

## 3. Changes and Decisions

### Design Rationale

**Why a local proxy instead of direct scraping in agent code?**

1. **Separation of concerns.** Agent logic reasons about stories, not HTML
   selectors. If AO3's markup changes, only `ao3_client.py` needs updating.
2. **Rate limiting in one place.** A single 3-second throttle in `ao3_client.py`
   prevents all callers from accidentally hammering AO3.
3. **Caching without caller complexity.** Callers get fast JSON; the proxy
   handles disk cache transparently.
4. **Testability.** Mock mode lets the entire agent loop run without network
   access, returning consistent data for deterministic tests.
5. **Human-in-the-loop publishing.** The publish queue pattern ensures no
   automated posting to AO3 (AO3 TOS compliance). The agent stages; a human
   reviews and posts.

### Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Filesystem queue (not database) | Zero-dependency persistence; human can inspect/edit JSON files directly |
| Disk-based cache (not Redis) | Single-user local tool; no need for distributed cache |
| `_MIN_INTERVAL = 3.0` seconds | Respectful scraping; AO3 rate limits are strict |
| Work text cached indefinitely (`_TTL_WORK_TEXT = 0`) | Published text does not change; saves requests |
| Metadata/stats/comments cached 24 hours | Balances freshness with request economy |
| Mock mode uses in-memory seed data | Fast, deterministic, no filesystem side effects for reads |
| Queue uses filesystem even in mock mode | Queue is a write concern, not AO3-dependent |

---

## 4. Formal Specification

### 4.1 Browse and Search Endpoints

#### GET /fandoms/{fandom_name}/works

List works in a fandom, sorted and optionally filtered by tags.

**Path parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `fandom_name` | `str` | Fandom name (URL-encoded) |

**Query parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `sort` | `str` | `"kudos"` | Sort field. One of: `kudos`, `hits`, `date_posted`, `date_updated`, `bookmarks` |
| `tags` | `list[str]` | `[]` | Filter by additional tags (repeated query param) |
| `page` | `int` | `1` | Pagination page number |

**Response:** `200 OK` -- `list[WorkSummary]`

```json
[
  {
    "id": 10001,
    "title": "The Stars Between Us",
    "authors": ["nightowl_writes"],
    "fandoms": ["Harry Potter - J. K. Rowling"],
    "tags": ["Slow Burn", "Enemies to Lovers"],
    "rating": "Teen And Up Audiences",
    "summary": "After the war...",
    "word_count": 48320,
    "chapter_count": 12,
    "date_posted": "2025-06-15",
    "date_updated": "2025-11-03",
    "stats": {
      "kudos": 1842,
      "hits": 23400,
      "bookmarks": 312,
      "subscriptions": 189,
      "comment_count": 97,
      "by_date": null
    }
  }
]
```

**Error responses:**

| Status | Condition |
|--------|-----------|
| `422` | Invalid query parameters (FastAPI validation) |
| `502` | AO3 unreachable or returned error (real mode only) |

**Caching:** Results cached under `fandom_works` namespace. TTL: 86400 seconds (24 hours). Cache key includes fandom, sort, tags, and page.

**Rate limiting:** In real mode, each AO3 request is throttled to 1 request per 3 seconds. Requests to the local proxy itself are not rate-limited.

**Mock mode:** Filters `_WORKS` seed data by fandom name (case-insensitive substring match). Ignores `tags` filter parameter.

---

#### GET /tags/{tag_name}/works

List works with a specific tag.

**Path parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `tag_name` | `str` | Tag name (URL-encoded) |

**Query parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `sort` | `str` | `"kudos"` | Sort field |
| `page` | `int` | `1` | Page number |

**Response:** `200 OK` -- `list[WorkSummary]`

Same schema as `/fandoms/{fandom_name}/works`.

**Error responses:** Same as fandom works endpoint.

**Caching:** Shares the `fandom_works` cache namespace (delegates to `list_works_by_fandom` internally).

**Mock mode:** Filters `_WORKS` seed data by tag name (case-insensitive substring match).

---

#### GET /works/{work_id}

Get a single work's full metadata and chapter text.

**Path parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `work_id` | `int` | AO3 work ID |

**Response:** `200 OK` -- `WorkDetail`

`WorkDetail` extends `WorkSummary` with:

```json
{
  "chapters": [
    {
      "id": 50001,
      "number": 1,
      "title": "September Again",
      "body": "The platform was quieter...",
      "word_count": 4200
    }
  ],
  "body": "The platform was quieter..."
}
```

**Error responses:**

| Status | Condition |
|--------|-----------|
| `404` | Work ID not found (real mode: AO3 returned 404; mock mode: not in seed data) |
| `422` | `work_id` not a valid integer |
| `502` | AO3 unreachable (real mode only) |

**Caching:** Cached under `work_detail` namespace. TTL: 0 (indefinite -- published text does not change).

**Mock mode:** Returns matching `WorkDetail` from `_WORKS` list or `None` (triggering 404).

---

#### GET /search

Search works by query string, fandom, tags, and sort order.

**Query parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `query` | `str` | `""` | Free-text search query |
| `fandom` | `str` | `""` | Filter by fandom |
| `tags` | `list[str]` | `[]` | Filter by tags (repeated query param) |
| `sort` | `str` | `"kudos"` | Sort field |
| `page` | `int` | `1` | Page number |

**Response:** `200 OK` -- `list[WorkSummary]`

**Error responses:**

| Status | Condition |
|--------|-----------|
| `422` | Invalid query parameters |
| `502` | AO3 unreachable (real mode only) |

**Caching:** Cached under `search` namespace. TTL: 86400 seconds. Cache key includes all parameters.

**Mock mode:** Filters seed data by query (title/summary substring), fandom, and first tag. Only the first element of `tags` is used in mock mode.

---

### 4.2 Metrics Endpoints

#### GET /works/{work_id}/stats

Get engagement statistics for a single work.

**Path parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `work_id` | `int` | AO3 work ID |

**Response:** `200 OK` -- `WorkStats`

```json
{
  "kudos": 1842,
  "hits": 23400,
  "bookmarks": 312,
  "subscriptions": 189,
  "comment_count": 97,
  "by_date": null
}
```

**Error responses:**

| Status | Condition |
|--------|-----------|
| `404` | Work not found |
| `422` | Invalid `work_id` |

**Caching:** Cached under `work_stats` namespace. TTL: 86400 seconds. In real mode, fetches the full work detail to extract stats (which itself is cached indefinitely), then caches stats separately.

**Mock mode:** Returns `stats` field from matching `WorkDetail` in seed data.

---

#### GET /users/{username}/stats

Aggregate statistics across all of a user's works.

**Path parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `username` | `str` | AO3 username |

**Response:** `200 OK` -- `UserStats`

```json
{
  "username": "nightowl_writes",
  "total_works": 2,
  "total_kudos": 2366,
  "total_hits": 27700,
  "total_bookmarks": 400,
  "total_subscriptions": 201,
  "total_comments": 128,
  "total_word_count": 54520
}
```

**Error responses:**

| Status | Condition |
|--------|-----------|
| `404` | User not found or user has no works |

**Caching:** Computed from `get_user_works`, which is cached under `user_works` namespace (TTL: 86400 seconds).

**Mock mode:** Aggregates from seed works matching the author name (case-insensitive exact match).

---

#### GET /users/{username}/works

List all works by a user.

**Path parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `username` | `str` | AO3 username |

**Response:** `200 OK` -- `list[WorkSummary]`

**Error responses:**

| Status | Condition |
|--------|-----------|
| `502` | AO3 unreachable (real mode; returns empty list on HTTP errors) |

**Caching:** Cached under `user_works` namespace. TTL: 86400 seconds.

**Mock mode:** Filters seed data by exact author match (case-insensitive).

---

### 4.3 Comment Endpoints

#### GET /works/{work_id}/comments

Get all comments on a work.

**Path parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `work_id` | `int` | AO3 work ID |

**Response:** `200 OK` -- `list[Comment]`

```json
[
  {
    "id": 90001,
    "author": "fanfic_lover42",
    "date": "2025-11-04T14:30:00Z",
    "chapter_id": 50001,
    "body": "This is SO good...",
    "is_reply": false,
    "parent_id": null
  }
]
```

**Error responses:**

| Status | Condition |
|--------|-----------|
| `502` | AO3 unreachable (real mode; returns empty list on HTTP errors) |

**Caching:** Cached under `comments` namespace. TTL: 86400 seconds. Cache key includes `work_id` and `chapter_id` (which is `None` for this endpoint).

**Mock mode:** Returns comments whose `chapter_id` matches any chapter in the work's seed data.

---

#### GET /works/{work_id}/chapters/{chapter_id}/comments

Get comments on a specific chapter.

**Path parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `work_id` | `int` | AO3 work ID |
| `chapter_id` | `int` | Chapter ID |

**Response:** `200 OK` -- `list[Comment]`

Same schema as work comments.

**Error responses:** Same as work comments endpoint.

**Caching:** Same namespace as work comments. Cache key includes the specific `chapter_id`.

**Mock mode:** Filters seed comments to those matching both the work's chapters and the specified `chapter_id`.

---

### 4.4 Publish Queue Endpoints

The publish queue implements a human-in-the-loop pattern: the agent creates
draft publications, a human reviews them, and the human either confirms
(marking as published with an AO3 work ID) or rejects (deleting from the
queue).

#### Queue Lifecycle

```
Agent calls POST /works
       |
       v
  [PENDING] --- queue_id returned
       |
   Human reviews JSON file in publish_queue/
       |
       +--- Approve ---> PATCH /queue/{id} with ao3_work_id ---> [PUBLISHED]
       |
       +--- Reject  ---> DELETE /queue/{id} ---> (removed)
```

#### POST /works

Create a new publish queue item.

**Request body:** `PublishRequest`

```json
{
  "title": "The Stars Between Us",
  "fandom": "Harry Potter - J. K. Rowling",
  "rating": "Teen And Up Audiences",
  "tags": ["Slow Burn", "Enemies to Lovers"],
  "summary": "After the war...",
  "body": "Chapter 1 text...",
  "author_notes": "First fic in this fandom!"
}
```

**PublishRequest fields:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `title` | `str` | yes | -- | Work title |
| `fandom` | `str` | yes | -- | Primary fandom |
| `rating` | `Rating` | no | `"Not Rated"` | AO3 rating enum |
| `tags` | `list[str]` | no | `[]` | Freeform and relationship tags |
| `summary` | `str` | no | `""` | Work summary |
| `body` | `str` | yes | -- | Full work text |
| `author_notes` | `str` | no | `""` | Author's notes |

**Response:** `201 Created` -- `QueueItem`

```json
{
  "queue_id": "a1b2c3d4e5f6",
  "publish_request": { "..." },
  "status": "pending",
  "created_at": "2026-03-26T12:00:00Z",
  "published_at": null,
  "ao3_work_id": null
}
```

**Error responses:**

| Status | Condition |
|--------|-----------|
| `422` | Missing required fields (`title`, `fandom`, `body`) or invalid `rating` enum value |

**Side effects:** Creates a JSON file at `publish_queue/{queue_id}.json`.

**Mock mode:** Behaves identically (queue is filesystem-based, not AO3-dependent).

---

#### GET /queue

List all queued publications, sorted by `created_at` descending.

**Response:** `200 OK` -- `list[QueueItem]`

**Mock mode:** Behaves identically.

---

#### GET /queue/{queue_id}

Get a specific queued publication.

**Path parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `queue_id` | `str` | 12-character hex queue ID |

**Response:** `200 OK` -- `QueueItem`

**Error responses:**

| Status | Condition |
|--------|-----------|
| `404` | Queue item not found |

**Mock mode:** Behaves identically.

---

#### DELETE /queue/{queue_id}

Remove a publication from the queue (reject it).

**Path parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `queue_id` | `str` | 12-character hex queue ID |

**Response:** `204 No Content`

**Error responses:**

| Status | Condition |
|--------|-----------|
| `404` | Queue item not found |

**Side effects:** Deletes the JSON file from `publish_queue/`.

**Mock mode:** Behaves identically.

---

#### PATCH /queue/{queue_id}

Mark a queued publication as published with its real AO3 work ID.

**Path parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `queue_id` | `str` | 12-character hex queue ID |

**Request body:** `QueuePatchRequest`

```json
{
  "ao3_work_id": 54321
}
```

**Response:** `200 OK` -- `QueueItem` (with `status: "published"`, `published_at` set, `ao3_work_id` set)

**Error responses:**

| Status | Condition |
|--------|-----------|
| `404` | Queue item not found |
| `422` | Missing or invalid `ao3_work_id` |

**Side effects:** Updates the JSON file in `publish_queue/` with new status, timestamp, and AO3 work ID.

**Mock mode:** Behaves identically.

---

### 4.5 Rate Limiting

Rate limiting applies only to outbound requests from the proxy to AO3 (real
mode). The local proxy itself imposes no rate limits on its callers.

| Parameter | Value |
|-----------|-------|
| Minimum interval | 3.0 seconds between AO3 requests |
| Implementation | Module-level `_last_request_time` with `time.sleep()` |
| Scope | Global -- all proxy endpoints share one throttle |
| Cache bypass | Cached responses are served immediately, no rate limit delay |

### 4.6 Caching

All caching is disk-based, stored under `api/cache/`. Each namespace has its own
subdirectory. Cache keys are SHA-256 hashes (first 16 hex chars) of
`{namespace}:{identifier}`.

| Namespace | TTL | Invalidation |
|-----------|-----|--------------|
| `work_detail` | 0 (indefinite) | Manual deletion of cache file |
| `work_stats` | 86400 s (24 h) | Automatic expiry |
| `fandom_works` | 86400 s (24 h) | Automatic expiry |
| `search` | 86400 s (24 h) | Automatic expiry |
| `user_works` | 86400 s (24 h) | Automatic expiry |
| `comments` | 86400 s (24 h) | Automatic expiry |

Cache file format:

```json
{
  "_cached_at": 1711411200.0,
  "payload": { "..." }
}
```

**TTL = 0 means indefinite.** The `_cache_get` function skips expiry checks when
`ttl > 0` is false.

**No programmatic cache invalidation API exists.** To force a refresh, delete
files under `api/cache/{namespace}/`.

---

## 5. Test Cases

All test cases assume the FastAPI `TestClient` is used with the proxy app. Queue
tests require a temporary `publish_queue/` directory that is cleaned up after
each test.

### TC-01: Browse -- list fandom works (happy path)

**INPUT:** `GET /fandoms/Harry%20Potter/works?sort=kudos&page=1` (mock mode)

**EXPECTED:** `200 OK`. Response is `list[WorkSummary]`. Contains work ID 10001
("The Stars Between Us") with `stats.kudos == 1842`. List is sorted by kudos
descending.

**RATIONALE:** Verifies the primary browse endpoint returns filtered, sorted
results from mock data.

---

### TC-02: Browse -- list tag works (happy path)

**INPUT:** `GET /tags/Slow%20Burn/works?sort=kudos` (mock mode)

**EXPECTED:** `200 OK`. Response contains work 10001 (tagged "Slow Burn").
Does not contain work 10002 (not tagged "Slow Burn").

**RATIONALE:** Confirms tag filtering works correctly in the mock backend.

---

### TC-03: Browse -- get work detail (happy path)

**INPUT:** `GET /works/10001` (mock mode)

**EXPECTED:** `200 OK`. Response is `WorkDetail` with `id == 10001`,
`chapters` list of length >= 2, `body` field is non-empty string,
`chapter_count == 12`.

**RATIONALE:** Validates the full work detail endpoint including chapters.

---

### TC-04: Browse -- work not found

**INPUT:** `GET /works/99999` (mock mode)

**EXPECTED:** `404 Not Found` with body `{"detail": "Work not found"}`.

**RATIONALE:** Confirms 404 handling when a work ID does not exist.

---

### TC-05: Search -- query match (happy path)

**INPUT:** `GET /search?query=stars&sort=kudos` (mock mode)

**EXPECTED:** `200 OK`. Response contains work 10001 ("The Stars Between Us")
because "stars" appears in the title.

**RATIONALE:** Validates free-text search against title and summary.

---

### TC-06: Search -- no results

**INPUT:** `GET /search?query=xyznonexistent&fandom=Nonexistent` (mock mode)

**EXPECTED:** `200 OK`. Response is an empty list `[]`.

**RATIONALE:** Verifies that a search with no matches returns an empty list, not
an error.

---

### TC-07: Metrics -- work stats (happy path)

**INPUT:** `GET /works/10001/stats` (mock mode)

**EXPECTED:** `200 OK`. Response is `WorkStats` with `kudos == 1842`,
`hits == 23400`, `bookmarks == 312`, `subscriptions == 189`,
`comment_count == 97`.

**RATIONALE:** Confirms per-work stats endpoint returns correct values.

---

### TC-08: Metrics -- user stats (happy path)

**INPUT:** `GET /users/nightowl_writes/stats` (mock mode)

**EXPECTED:** `200 OK`. Response is `UserStats` with `username == "nightowl_writes"`,
`total_works == 2`, `total_kudos == 2366` (1842 + 524),
`total_word_count == 54520` (48320 + 6200).

**RATIONALE:** Verifies cross-work aggregation for a user with multiple works.

---

### TC-09: Metrics -- user not found

**INPUT:** `GET /users/nonexistent_user/stats` (mock mode)

**EXPECTED:** `404 Not Found` with body `{"detail": "User not found"}`.

**RATIONALE:** Confirms 404 when the username does not match any author in the
data.

---

### TC-10: Comments -- work comments (happy path)

**INPUT:** `GET /works/10001/comments` (mock mode)

**EXPECTED:** `200 OK`. Response is `list[Comment]` containing comments 90001,
90002, and 90003 (all associated with chapters 50001 and 50002 of work 10001).
Each comment has `id`, `author`, `body`, `is_reply`, and `chapter_id` fields.

**RATIONALE:** Validates comment retrieval for a multi-chapter work.

---

### TC-11: Comments -- chapter-level filtering

**INPUT:** `GET /works/10001/chapters/50001/comments` (mock mode)

**EXPECTED:** `200 OK`. Response contains comments 90001 and 90002 (both on
chapter 50001). Does not contain comment 90003 (on chapter 50002).

**RATIONALE:** Confirms chapter-level comment filtering works.

---

### TC-12: Publish queue -- create, retrieve, confirm lifecycle

**INPUT:**
1. `POST /works` with body:
   ```json
   {"title": "Test Work", "fandom": "Test Fandom", "body": "Chapter text", "rating": "Not Rated"}
   ```
2. Capture `queue_id` from response.
3. `GET /queue/{queue_id}`
4. `PATCH /queue/{queue_id}` with body: `{"ao3_work_id": 12345}`

**EXPECTED:**
1. `201 Created`. Response has `status == "pending"`, `ao3_work_id == null`.
2. `queue_id` is a 12-character hex string.
3. `200 OK`. Response matches the created item.
4. `200 OK`. Response has `status == "published"`, `ao3_work_id == 12345`,
   `published_at` is not null.

**RATIONALE:** Tests the full happy-path lifecycle: create, read, confirm.

---

### TC-13: Publish queue -- list and delete (reject)

**INPUT:**
1. `POST /works` with valid body (create item A).
2. `POST /works` with valid body (create item B).
3. `GET /queue`
4. `DELETE /queue/{queue_id_A}`
5. `GET /queue`

**EXPECTED:**
1-2. Both return `201 Created`.
3. `200 OK`. List contains both items, sorted by `created_at` descending.
4. `204 No Content`.
5. `200 OK`. List contains only item B.

**RATIONALE:** Validates queue listing order and deletion (rejection workflow).

---

### TC-14: Publish queue -- item not found

**INPUT:** `GET /queue/nonexistent123`

**EXPECTED:** `404 Not Found` with body `{"detail": "Queue item not found"}`.

**RATIONALE:** Confirms 404 for invalid queue IDs.

---

### TC-15: Publish queue -- delete nonexistent item

**INPUT:** `DELETE /queue/nonexistent123`

**EXPECTED:** `404 Not Found` with body `{"detail": "Queue item not found"}`.

**RATIONALE:** Confirms DELETE returns 404 for missing items, not silent success.

---

### TC-16: Publish queue -- PATCH nonexistent item

**INPUT:** `PATCH /queue/nonexistent123` with body `{"ao3_work_id": 99999}`

**EXPECTED:** `404 Not Found` with body `{"detail": "Queue item not found"}`.

**RATIONALE:** Confirms PATCH returns 404 for missing items.

---

### TC-17: Validation -- malformed publish request

**INPUT:** `POST /works` with body `{"title": "Missing body and fandom"}`

**EXPECTED:** `422 Unprocessable Entity`. Response body contains validation
errors for missing `fandom` and `body` fields.

**RATIONALE:** Confirms Pydantic validation catches missing required fields.

---

### TC-18: Validation -- invalid rating enum

**INPUT:** `POST /works` with body including `"rating": "Super Explicit"`

**EXPECTED:** `422 Unprocessable Entity`. Validation error on `rating` field.

**RATIONALE:** Confirms the `Rating` enum rejects invalid values.

---

### TC-19: Mock mode -- consistent data across calls

**INPUT:** Call `GET /works/10001` twice in mock mode.

**EXPECTED:** Both responses are byte-identical JSON. Same `id`, `title`,
`authors`, `stats.kudos`, `chapters` length.

**RATIONALE:** Mock mode must be deterministic for reproducible agent testing.

---

### TC-20: Caching -- second request hits cache (real mode)

**INPUT:** (Real mode with a test AO3 page or a mocked httpx transport.)
1. `GET /works/{id}/stats` -- first call.
2. `GET /works/{id}/stats` -- second call within 24 hours.

**EXPECTED:** Both return identical data. The second call does NOT trigger an
outbound HTTP request to AO3 (verify by checking `_last_request_time` or
mocking `_get`).

**RATIONALE:** Validates that the disk cache prevents redundant AO3 requests.

---

### TC-21: Caching -- cache expiry triggers refresh

**INPUT:** (Real mode with mocked time.)
1. `GET /works/{id}/stats` -- populates cache.
2. Advance time by 86401 seconds (past 24-hour TTL).
3. `GET /works/{id}/stats` -- should re-fetch.

**EXPECTED:** The third step triggers a new AO3 request. The `_cached_at`
timestamp in the cache file is updated.

**RATIONALE:** Validates TTL-based cache expiry.

---

### TC-22: Rate limiting -- requests are throttled

**INPUT:** (Real mode with mocked httpx.)
1. Issue two `_get()` calls in rapid succession.
2. Measure elapsed wall time.

**EXPECTED:** Total elapsed time is >= 3.0 seconds (the `_MIN_INTERVAL`). The
second call sleeps until the minimum interval has passed.

**RATIONALE:** Validates the rate limiter prevents rapid-fire AO3 requests.

---

### TC-23: Error handling -- AO3 unreachable

**INPUT:** (Real mode with httpx mocked to raise `httpx.ConnectError`.)
`GET /works/10001`

**EXPECTED:** `404 Not Found` (because `ao3_client.get_work` returns `None` when
`httpx.HTTPStatusError` is raised) or `502 Bad Gateway` if the connection error
propagates.

**RATIONALE:** Validates graceful degradation when AO3 is down.

---

### TC-24: User works -- empty list for unknown user

**INPUT:** `GET /users/nonexistent_user/works` (mock mode)

**EXPECTED:** `200 OK`. Response is an empty list `[]`.

**RATIONALE:** The user works endpoint returns an empty list (not 404) when no
works are found. This differs from user stats, which returns 404.

---

### TC-25: Browse -- pagination

**INPUT:** `GET /fandoms/Harry%20Potter/works?page=999` (mock mode)

**EXPECTED:** `200 OK`. Response is an empty list `[]` (page beyond available
results).

**RATIONALE:** Validates that out-of-range pagination returns empty results
rather than an error.

---

## 6. Implementation Notes

### Module Structure

The current module layout is well-organized:

```
api/
  __init__.py          # Package marker
  models.py            # All Pydantic schemas (single source of truth)
  server.py            # FastAPI routes (thin -- delegates to client/queue)
  ao3_client.py        # Real AO3 scraper (rate limiting, caching, parsing)
  mock.py              # Deterministic test data
  queue.py             # Filesystem publish queue
  cache/               # Disk cache (gitignored)
```

### Dependency Choices

| Package | Why this one |
|---------|-------------|
| FastAPI | Automatic OpenAPI docs, Pydantic integration, async-ready |
| httpx | Modern HTTP client, sync and async, good timeout handling |
| BeautifulSoup4 | Battle-tested HTML parser, handles malformed AO3 markup |
| Pydantic v2 | Fast validation, `model_dump`/`model_validate` for cache serialization |
| uvicorn | Standard ASGI server for FastAPI |

### Suggested Improvements (Not in Current Code)

1. **Structured error responses.** Currently, AO3 HTTP errors can surface as
   unhandled 500s. Wrap `ao3_client` calls in try/except and return proper
   502 responses.
2. **Cache management endpoint.** `DELETE /cache/{namespace}` to clear cached
   data without filesystem access.
3. **Health check endpoint.** `GET /health` returning mode (mock/real) and cache
   stats.
4. **Async support.** `ao3_client.py` uses synchronous httpx. Converting to
   `httpx.AsyncClient` with `async def` endpoints would improve throughput
   under concurrent requests.
5. **Pagination metadata.** Return total count and page info in response headers
   or a wrapper object.

---

## 7. Open Questions

1. **Should the proxy support authentication for AO3?** Currently, all requests
   are unauthenticated. Some AO3 content (locked works, private bookmarks)
   requires a logged-in session. If the agent needs to read its own unpublished
   drafts or restricted works, cookie-based auth would be needed.

2. **How should the proxy handle AO3 rate limit responses (HTTP 429)?** The
   current `_MIN_INTERVAL` is proactive, but AO3 may still return 429 under
   load. Should the proxy retry with exponential backoff, or surface the error?

3. **Should the queue support a "rejected" status?** Currently, rejection is
   implemented as deletion (`DELETE /queue/{id}`). A `REJECTED` status exists
   in the `QueueStatus` enum but is never set by any endpoint. Should `DELETE`
   set status to `REJECTED` instead of removing the file?

4. **Should cache TTLs be configurable?** Currently hardcoded. Environment
   variables or a config file would allow tuning without code changes.

5. **Should `GET /users/{username}/works` return 404 for nonexistent users?**
   Currently it returns an empty list, while `GET /users/{username}/stats`
   returns 404. This inconsistency may confuse callers.

6. **Should the `tags` query parameter on `/fandoms/{fandom_name}/works` be
   used in mock mode?** Currently, mock mode ignores the `tags` filter on this
   endpoint (it only passes `fandom`, `sort`, and `page` to `list_works`).

---

## 8. Future Considerations

1. **Webhook for publish confirmation.** Instead of polling `GET /queue/{id}`,
   the proxy could fire a webhook when a human marks a work as published. This
   would let the agent react immediately to publication events.

2. **Real-time metrics streaming.** A WebSocket endpoint
   (`ws://localhost:8000/ws/metrics/{work_id}`) that periodically fetches stats
   and pushes updates. Useful for the agent's learning loop to detect engagement
   spikes.

3. **Comment sentiment analysis.** Pre-process comments through a sentiment
   classifier before returning them, adding a `sentiment` field to the `Comment`
   model. This would save the agent from doing its own NLP on every comment
   fetch.

4. **Multi-work publish batches.** Support publishing a series (multiple works/
   chapters) as a single queue item with ordering guarantees.

5. **AO3 session management.** A `/auth` endpoint that accepts AO3 credentials,
   maintains a session cookie, and enables access to restricted content and the
   agent's own profile/dashboard data.

6. **Rate limit dashboard.** Expose rate limit state (`GET /rate-limit/status`)
   showing last request time, queue depth, and estimated wait time. Useful for
   the agent to decide whether to batch requests or wait.

7. **Cache warming.** A background task that pre-fetches works the agent is
   likely to need (e.g., all works in a target fandom, the agent's own
   published works) to minimize latency during active writing sessions.

8. **Async migration.** Convert `ao3_client.py` to use `httpx.AsyncClient` and
   make all FastAPI endpoints `async def`. This is a prerequisite for WebSocket
   support and improves behavior under concurrent requests.
