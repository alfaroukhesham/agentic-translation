# FastAPI translation service contract

**Status:** Canonical for translation automation (updated 2026-05-27)  
**WordPress consumer:** `prod-dev-scripts/lib/bta-http-client.php`, `translation-job-worker.php`  
**Design spec:** `docs/superpowers/specs/2026-05-21-blog-translation-automation-design.md`

---

## Authentication

All WordPress → FastAPI requests include:

```http
X-Translation-Api-Key: <BLOG_TRANSLATION_API_KEY>
Authorization: Bearer <BLOG_TRANSLATION_API_KEY>
Content-Type: application/json
```

`BLOG_TRANSLATION_API_KEY` may be omitted in wp-config when it is the same value as `BLOG_TRANSLATION_WEBHOOK_SECRET` (WordPress falls back to the webhook secret).

The VisaTop translation sidecar does **not** use `X-Translation-Secret` on inbound API calls — that header is only for FastAPI → WordPress webhooks.

Timeout: **120 seconds** on the WordPress side (`wp_remote_request`).

The same secret is sent to FastAPI on translate submit as `callback_secret` so FastAPI can call the WordPress webhook with the same header value.

---

## Job types (`job_type`)

WordPress sends a **`job_type`** on every translate submit. FastAPI must branch translation logic and S3 layout on this field.

| `job_type`   | WordPress trigger              | What to translate                         | Import on WP                          |
|-------------|--------------------------------|-------------------------------------------|----------------------------------------|
| `blog`      | EN `post` publish/update       | title, content, excerpt, Yoast, optional ACF | `import-translations.php` + fix-urls |
| `news`      | EN `news` publish/update       | **`title` only**                          | `import-news-translations.php` (shared EN slug) |
| `page_acf`  | EN `page` publish/update (ACF) | **`english.acf_fields` tree only**        | `apply-page-acf-translations.php`      |

Default when omitted (legacy clients): `blog`.

**Rules by type:**

- **`news`:** Never translate `english.content`. Result must include `translations.{lang}.title` only. Preserve `english.slug` on import (WP copies EN slug to all langs). URLs in any optional fields stay identical to EN.
- **`page_acf`:** Never translate post title, slug, or `post_content`. Only string values inside `items[0].english.acf_fields` (and mirror structure under `translations.{lang}.acf_fields`). Preserve attachment IDs, URLs, HTML attributes, repeater row counts (same rules as homepage ACF prompt).
- **`blog`:** Existing behavior (see export shape below).

---

## Endpoints

Base URL: `BLOG_TRANSLATION_FASTAPI_URL` (no trailing slash).

Presigned upload/download paths are **scoped by job type** (see [Object layout](#object-layout-convention)).

### `POST /v1/jobs/{wp_job_id}/export-upload`

Request body (optional):

```json
{
  "job_type": "blog"
}
```

Response (200):

```json
{
  "upload_url": "https://...",
  "export_key": "blog-translations/exports/42/export.json",
  "expires_in": 900
}
```

`export_key` must use the prefix for the job’s `job_type` (e.g. `news-translations/exports/42/export.json`).

WordPress uploads export JSON with `PUT` to `upload_url`, `Content-Type: application/json`.

---

### `POST /v1/translate`

Start translation. WordPress sends:

```json
{
  "wp_job_id": "42",
  "en_post_id": 12345,
  "job_type": "news",
  "callback_url": "https://example.com/wp-json/blog-translation/v1/webhook",
  "callback_secret": "<BLOG_TRANSLATION_WEBHOOK_SECRET>",
  "target_langs": ["ar", "fr", "tl"],
  "source": {
    "inline": { "generated_at": "...", "job_type": "news", "items": [ ] }
  }
}
```

Or large export via S3 reference:

```json
{
  "wp_job_id": "42",
  "en_post_id": 12345,
  "job_type": "page_acf",
  "callback_url": "https://example.com/wp-json/blog-translation/v1/webhook",
  "callback_secret": "<BLOG_TRANSLATION_WEBHOOK_SECRET>",
  "target_langs": ["ar", "fr"],
  "source": {
    "s3": {
      "bucket": "optional-if-api-default",
      "key": "page-acf-translations/exports/42/export.json"
    }
  }
}
```

Response (200):

```json
{
  "fastapi_job_id": "uuid-or-correlation-id",
  "s3_result_key": "news-translations/results/42/result.json",
  "job_type": "news"
}
```

`job_type` in the response should echo the request (optional but recommended).

**FastAPI rules (all types):**

- Preserve JSON structure; translate string values only per job type rules; preserve URLs and markup where applicable.
- Write completed result JSON to `s3_result_key` **before** calling the webhook.
- If translation aborts or job fails, **do not** call the WordPress webhook with `status: completed`. Failed/aborted jobs may use a non-completed status or no callback; WordPress must not transition to `ready_import` on failure.
- `callback_secret` must be echoed on webhook as `X-Translation-Secret` (same value as submit).

**Inline threshold:** WordPress uses inline when `filesize(export.json) <= BLOG_TRANSLATION_INLINE_MAX_BYTES` (default 262144). FastAPI may still persist a copy server-side.

---

### Export / result JSON shapes

#### `blog` (unchanged)

Same as `export-recent-en-posts-for-translation.php`:

```json
{
  "generated_at": "2026-05-27T12:00:00+00:00",
  "job_type": "blog",
  "en_slug": "en",
  "items": [
    {
      "original_post_id": 12345,
      "missing_languages": ["fr"],
      "english": {
        "id": 12345,
        "title": "...",
        "slug": "...",
        "content": "...",
        "excerpt": "",
        "yoast_title": "",
        "yoast_desc": "",
        "acf_fields": {},
        "categories": []
      },
      "translations": {
        "fr": {
          "title": "",
          "content": "",
          "yoast_title": "",
          "yoast_desc": "",
          "acf_fields": {}
        }
      }
    }
  ]
}
```

FastAPI fills `translations.{lang}.*` string fields. Worker reads `items[0]` only in single-post mode.

#### `news` (title only)

```json
{
  "generated_at": "2026-05-27T12:00:00+00:00",
  "job_type": "news",
  "en_slug": "en",
  "post_id": 7189,
  "items": [
    {
      "original_post_id": 7189,
      "missing_languages": ["fr", "de"],
      "english": {
        "id": 7189,
        "title": "UAE family visa guide 2026...",
        "slug": "uae-family-visa-guide-2026-...",
        "content": "<p>...</p>",
        "excerpt": "",
        "parse_url": "https://...",
        "thumbnail_id": 123
      },
      "translations": {
        "fr": { "title": "" },
        "de": { "title": "" }
      }
    }
  ]
}
```

**FastAPI must:**

- Translate only `translations.{lang}.title`.
- Leave `english.content`, `english.slug`, and all non-title fields unchanged in the result (WordPress copies EN body/meta on import).
- Not require or produce `content`, `yoast_*`, or `acf_fields` under translations.

**Result example (completed):**

```json
{
  "job_type": "news",
  "items": [
    {
      "original_post_id": 7189,
      "translations": {
        "fr": { "title": "Guide du visa familial..." },
        "de": { "title": "Leitfaden zum Familienvisum..." }
      }
    }
  ]
}
```

#### `page_acf`

```json
{
  "generated_at": "2026-05-27T12:00:00+00:00",
  "job_type": "page_acf",
  "en_slug": "en",
  "post_id": 12,
  "items": [
    {
      "original_post_id": 12,
      "missing_languages": ["fr"],
      "english": {
        "id": 12,
        "title": "VisaTop",
        "slug": "visatop-2",
        "acf_fields": {
          "b1_title": "Are you looking for a <span>Visa</span>...",
          "button_link": "https://visatop.com/ai-faq/"
        }
      },
      "translations": {
        "fr": { "acf_fields": {} }
      }
    }
  ]
}
```

**FastAPI must:**

- Fill `translations.{lang}.acf_fields` with the same keys as `english.acf_fields`.
- Translate human-readable strings only; preserve URLs, attachment IDs (`_attachment_id`, `logo`, `icon`), HTML structure, repeater length/order.
- Do not translate `english.title` / `slug` in the result (not used by importer).

Reference prompt: `prod-dev-scripts/homepage-acf-translation-external-ai-prompt.md` (homepage is one page; same field rules apply to all pages).

---

### `GET /v1/jobs/{fastapi_job_id}`

Fallback status poll (webhook miss). Response (200):

```json
{
  "status": "pending",
  "job_type": "news",
  "s3_result_key": "news-translations/results/42/result.json"
}
```

`status` values: `pending`, `processing`, `completed`, `failed`.

When `status === completed`, WordPress sets job `ready_import` and stores `s3_result_key` if present.

---

### `POST /v1/jobs/{wp_job_id}/result-download`

Request body (optional):

```json
{
  "job_type": "page_acf"
}
```

Response (200):

```json
{
  "download_url": "https://...",
  "expires_in": 900
}
```

WordPress `GET`s `download_url` and saves to `wp-content/uploads/bta-jobs/{wp_job_id}/translated.json`.

---

## Webhook (FastAPI → WordPress)

**Route:** `POST /wp-json/blog-translation/v1/webhook`

**Auth:** `X-Translation-Secret: <BLOG_TRANSLATION_WEBHOOK_SECRET>` — mismatch → **401**, no database writes.

**Body:**

```json
{
  "wp_job_id": "42",
  "fastapi_job_id": "uuid",
  "status": "completed",
  "job_type": "news",
  "s3_result_key": "news-translations/results/42/result.json"
}
```

`job_type` is optional on webhook; WordPress resolves the job from `wp_job_id` and stored row.

**Handler (`BTA_Webhook`):**

1. Validate secret and `wp_job_id`.
2. If job status is already `completed` or `failed` → **200** `{ "ignored": true }` (idempotent).
3. If `status !== completed` → **200** ignored (no `ready_import`).
4. Happy path: set `status = ready_import`, store `s3_result_key`, bump `updated_at` (UTC). No CLI, no S3 download in the HTTP request.

---

## Object layout (convention)

Prefixes by `job_type`:

```text
blog-translations/exports/{wp_job_id}/export.json
blog-translations/results/{wp_job_id}/result.json

news-translations/exports/{wp_job_id}/export.json
news-translations/results/{wp_job_id}/result.json

page-acf-translations/exports/{wp_job_id}/export.json
page-acf-translations/results/{wp_job_id}/result.json
```

`POST /v1/jobs/{wp_job_id}/export-upload` and `result-download` must return keys under the matching prefix when `job_type` is supplied (or infer from stored FastAPI job metadata).

---

## WordPress configuration (new)

| Constant | Default | Purpose |
|----------|---------|---------|
| `BLOG_TRANSLATION_NEWS_AUTO` | `true` | Auto-queue EN `news` on publish/update |
| `BLOG_TRANSLATION_PAGE_ACF_AUTO` | `true` | Auto-queue EN `page` with ACF on publish/update |

Existing: `BLOG_TRANSLATION_FASTAPI_URL`, `BLOG_TRANSLATION_WEBHOOK_SECRET`, `BLOG_TRANSLATION_LANGS`, CPU/debounce constants.

---

## WordPress fallback timing

| Constant | Default | Behavior |
|----------|---------|----------|
| `BLOG_TRANSLATION_WEBHOOK_GRACE_MINUTES` | 20 | Do not poll until job age ≥ grace |
| `2 × grace` | 40 | `submitted` → `failed`, `last_error = webhook timeout` |
| `BLOG_TRANSLATION_SUBMITTED_POLL_LIMIT` | 5 | Max status polls per worker cron tick |

Stale sweep does **not** modify `submitted` rows.

---

## Error responses

FastAPI should return JSON errors with HTTP 4xx/5xx. WordPress maps failures to job `pending` (retry with exponential debounce) or `failed` after 3 attempts.

---

## FastAPI implementation checklist

1. Accept `job_type` on `POST /v1/translate` and persist on internal job record.
2. Route to one of three translation pipelines (`blog` | `news` | `page_acf`).
3. Scope S3 keys to `{prefix}/exports|results/{wp_job_id}/...`.
4. Pass `job_type` into export-upload / result-download OR look up from `wp_job_id`.
5. Validate result JSON shape before webhook `completed` (e.g. news must have non-empty titles for requested langs).
6. Echo `job_type` on status poll response (recommended).
7. Keep webhook contract backward-compatible (`job_type` optional).
