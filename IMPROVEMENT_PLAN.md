# PregnaBot — Project Analysis & Improvement Plan

Baseline analysis of the Django pregnancy information system ("PregnaBot") + legacy CRUD module

## Implementation status

The main implementation work is in place. The baseline findings below are retained as historical context; use this status section for the current state and the remaining caveats.

- **Phase 0 — verification:** Django is pinned to 5.2.18. The current full Django suite passes **90/90 tests** with the in-memory SQLite test settings. Local MariaDB 10.4 is below Django 5.2's supported minimum, so MySQL CI uses MySQL 8.
- **Phase 1 — configuration/security:** settings read the secret, hosts, debug flag, and DB connection from the environment; production settings add HTTPS/security defaults, database-backed cache, WhiteNoise, structured logs, and opt-in Sentry. The previously committed key was removed and a fresh local key is stored only in ignored `.env`. Login throttling is cache-backed and keyed by username/IP.
- **Phase 2 — architecture:** core views are split into account, dashboard, content, chatbot, prenatal, and chatbot-service modules. Forms, shared user-list querying, category choices, and the unified Pregnancy templates are wired in. The unused legacy theme and its unreferenced Tabler/vendor bundles were removed.
- **Phase 3 — tests/CI:** user-management, lockout, registration, chat, toolkit, and content tests are present; Ruff/Black configuration and a MySQL 8 GitHub Actions workflow are in place.
- **Phase 4 — product:** ranked top-three library answers, suggested prompts, conversation management/pagination, feedback analytics, optional owner-scoped pregnancy profile/appointments/bookmarks, source fields, Filipino translations for primary app surfaces and safety responses, and a static-only PWA are implemented. Search currently uses portable ranked database substring queries, not a dedicated full-text index or stemming. The new pregnancy profile supplements the legacy generic `Info` records; those records are retained to avoid discarding user data. Per the user's preference, urgent replies direct people to local emergency services without listing a number. Medical source fields are available, but no WHO/DOH citations are fabricated; content editors must add reviewed references. Medical-library text remains in its approved source language unless medically reviewed translations are supplied.
- **Phase 5 — deployment:** production settings, Docker Compose, health check, seed command, backup/restore instructions, and production dependencies are included.

**Validation:** the full test suite passed (90 tests), Django checks and migration consistency passed, Ruff passed, and production `collectstatic` copied 133 files and post-processed 399. The production deployment check reports only W021 because HSTS preload is deliberately disabled until the deployment domain and preload eligibility are confirmed. Docker Compose could not be validated locally because Docker is not installed.

---

## 1. What the project was at baseline

| App | Purpose |
|---|---|
| `apps/core` | Pregnancy topics, FAQs, chat conversations/messages, custom auth (login/lockout/register), dashboard, profile, keyword-based "PregnaBot" chatbot |
| `apps/users` | Superuser-only AJAX user management (list/get/save/delete) |
| `apps/info` | Legacy per-user CRUD records (`tblinfo`), owner-scoped via `apps/scoping.py` |
| `mysite` | Settings/URLs (MySQL via XAMPP, Tabler theme static assets) |

**Real strengths worth keeping:**
- Owner-scoping done right in `info` (`scoped_info()` → 404 for foreign records); tested.
- Login lockout after 5 failed attempts; CSRF on all POST forms; `login_required` everywhere.
- Urgent-symptom detection in the chatbot with a safe "seek emergency care" response.
- 29 tests exist (core + info) covering authz, search, CRUD validation, chatbot safety.
- Dashboard uses `prefetch_related` / `select_related` — query awareness is good.

## 2. Problems found (with evidence)

### 🔴 Critical — the project does not currently verify

- **The test suite was not fully green under the original environment, and the original cause was not confirmed.** At analysis time, `requirements.txt` pinned **Django 5.0.14** while the venv ran **Python 3.14.7**; that Django/Python combination is unsupported and was a plausible cause of the observed template-rendering errors. `settings.py`'s generated-file comment mentioned Django 6.0.5, but that alone did not establish a project requirement.
  The original `manage.py test` run reported **16 of 29 tests ERROR**, including `'super' object has no attribute 'dicts'` in template rendering. That cause was not confirmed. After upgrading to Django 5.2.18, the current SQLite-backed test run passes **90/90 tests**. The default MySQL test database cannot start against local **MariaDB 10.4.32**, below Django 5.2's MariaDB 10.5 minimum. The original template errors should not be attributed solely to the Django/Python mismatch without a reproduction on a supported database.
- **Secrets committed to git:** `SECRET_KEY` and MySQL credentials (`root`, empty password) are hardcoded in `mysite/settings.py`. The key is treated as compromised; the committed value has been removed from settings, which now requires `DJANGO_SECRET_KEY` to be set. Provision a fresh secret in the runtime environment immediately; do not reuse the exposed value.

### 🟠 Security & configuration

- `DEBUG = True`, `ALLOWED_HOSTS = []` — fine for dev, but there is **no production settings path at all**; these values and DB credentials remain hardcoded, with no `SECURE_*` settings or logging config.
- Login lockout state lives **in the session cookie** (`request.session['failed_attempts']`) — clearing cookies or opening a new session bypasses it entirely. Throttling must be keyed by username/IP in cache or DB.
- `apps/users/views.py` imports `django.contrib.auth.models.User` **directly** instead of `get_user_model()` — breaks the moment a custom user model is introduced.
- MariaDB Strict Mode warning (data-truncation risk on inserts).

### 🟡 Code architecture

- **`apps/core/views.py` is a ~600-line god module**: login, register, logout, dashboard, topic browsing, FAQ search, the entire chatbot engine (`_pregnabot_reply`, `URGENT_PHRASES`, `STOP_WORDS`), and profile — all in one file.
- **Duplicate presentation data:** `CATEGORY_META` in views duplicates `PregnancyTopic.Category` choices (titles/icons/colors live in two places and can drift).
- **Manual hand-rolled validation** in register/profile views; `apps/users/forms.py::UserForm` exists but is **never used** anywhere.
- **Dead code:** `mysite/views.py::home` renders `templates/index.html`, which **does not exist** and the view is not wired into any URLconf.
- **Two parallel UIs:** legacy `theme/base.html` + `info.html` + `users/list.html` vs the newer `pregnancy/*` templates. Two stylesheets worlds, inconsistent navigation.
- `user_list_ajax` **ignores the search `q` param** while the HTML page supports it — the AJAX endpoint is a second, subtly different copy of the list logic.
- `static/libs/` ships full vendor bundles including `.map` files, coverage reports and upstream test suites — repo bloat.

### 🟡 Testing gaps

- `apps/users/tests.py` is **empty** — the most privileged endpoints in the app (superuser CRUD over every account, password setting, deletion) have **zero tests**.
- No tests for: login lockout behavior, registration validation, `users` app authz (non-superuser must be rejected).

### 🔵 Product

- Chatbot is exact-substring keyword matching — no ranking beyond term counts, no stemming, no full-text index.
- Conversations cannot be renamed, deleted, or exported; no message pagination.
- No feedback loop ("was this helpful?"), no admin analytics.
- `Info` model is a generic CRUD leftover ("name/age/address") — not pregnancy-specific.

## 3. The plan

### Phase 0 — Make the project verifiable again (do first, ~half a day)

1. **Align versions:** pin the latest compatible **Django 5.2 LTS** patch release; `requirements.txt` now selects Django 5.2.18, installed and validated under Python 3.14. The generated-settings comment is not a reason to choose Django 6.0.
2. Use Django's built-in `manage.py test` runner; remove the unused `pytest.ini` rather than adding a second runner. `mysite.test_settings` provides an in-memory SQLite database for tests.
3. The full suite currently runs **90 tests OK** with `python manage.py test --settings=mysite.test_settings --noinput`. Use MariaDB 10.5+ or MySQL 8.0.11+ if running tests against the default MySQL backend.
4. **Fix the README** — resolved the leftover `<<<<<<< HEAD` merge conflict and added setup and test instructions.

### Phase 1 — Configuration & security hardening (~1 day)

1. Complete environment-based configuration for `DEBUG`, `ALLOWED_HOSTS`, and DB credentials; commit only `.env.example`. **Immediate: generate a fresh `DJANGO_SECRET_KEY` in the ignored local `.env` or runtime environment** (settings load it with `python-decouple`); never commit the value.
2. Add `mysite/settings` split: `base.py` / `dev.py` / `prod.py` (or env-switched), with prod security settings (`SECURE_SSL_REDIRECT`, HSTS, secure cookies, proxy headers).
4. Move login throttling to **cache/DB keyed by username + IP** (Django's cache framework), so clearing cookies no longer resets it. Consider `django-axes` if you'd rather not hand-roll it.
5. Replace direct `User` import with `get_user_model()` in `apps/users`.
6. Enable MariaDB strict mode (or set `sql_mode` explicitly) to kill the W002 warning.

### Phase 2 — Architecture cleanup (~1–2 days)

1. **Split `apps/core/views.py`** into focused modules (keep URLs stable):
   `accounts.py` (login/register/logout/profile), `dashboard.py`, `content.py` (topics/FAQ), `chatbot.py`; move the reply engine into `apps/core/services/pregnabot.py` so it is unit-testable without HTTP.
2. Derive `CATEGORY_META` from the model (e.g. `PregnancyCategory` model or a `classmethod` on `PregnancyTopic`) — single source of truth.
3. **Rewrite register/profile with Django forms** (`AuthenticationForm`-style login, `UserCreationForm`-based register, a `ProfileForm`); delete or actually use `UserForm`.
4. Delete dead code: `mysite/views.py::home` (+ unused `templates/home.html` if truly unreferenced).
5. Unify on the `pregnancy/` template family; port the user-admin page into it and **reuse one list/queryset builder** for both the HTML page and the AJAX endpoint (fixing the missing search).
6. Trim `static/libs/` to only the files actually referenced; drop `.map`/coverage/test artifacts.

### Phase 3 — Tests & CI (~1–2 days)

1. **Write `apps/users` test suite**: authz matrix (anonymous → redirect, non-superuser → rejected, superuser → OK), create/update/delete/password-reset flows, duplicate username/email conflicts, self-deletion blocked.
2. Add tests for login lockout (5 failures → locked; success resets) and registration validation.
3. Add **ruff** (lint) + **black** (format) config; optionally `coverage` with a floor (aim ≥ 80% on `apps/`).
4. **GitHub Actions CI**: matrix on Python 3.14 + MySQL 8 service container; run lint + tests on every push/PR.

### Phase 4 — Product upgrades (pick by value, ~1 week)

1. **Chatbot quality:** MySQL full-text index (`django-mysql` / native `FULLTEXT`) or SQLite FTS5 for ranked search; stem/lemmatize terms; return "best 3 answers" instead of one blob; suggested-questions chips.
2. **Conversation management:** rename, delete, export-as-text; paginate long threads.
3. **Feedback loop:** 👍/👎 on each bot answer stored on `ChatMessage` → admin analytics page (top questions, unanswered questions, satisfaction) → content gaps become visible.
4. **Pregnancy toolkit** (high user value, reuses the DB):
   - **Due-date / pregnancy-week calculator** (estimated date of conception + trimester-aware topic highlighting).
   - Replace generic `Info` with a **prenatal profile**: due date, week, blood type, appointments log with reminders.
   - **Bookmarks** for saved topics.
5. **Medical credibility:** add `source` field to `FAQ`/`PregnancyTopic` (WHO/DOH references), show a disclaimer, and surface **local emergency hotline numbers** in the urgent-symptom response.
6. **i18n:** English/Filipino (`django-i18n`) — meaningful for the audience.
7. **PWA:** manifest + service worker so the app works on low connectivity; mobile-first pass over the templates.

### Phase 5 — Production readiness (~1–2 days)

1. `gunicorn`/`uvicorn` + `whitenoise` (or nginx), `docker-compose` with MySQL for one-command setup.
2. Structured logging + error tracking (Sentry), health-check endpoint.
3. DB backup/restore procedure documented in the README; seed-data management command (`manage.py seed_content`) instead of hand-loaded SQL.

## 4. Suggested order & effort

```
Phase 0 (tests green)  → Phase 1 (security) → Phase 2 (architecture)   [≈ 3–4 days total, highest ROI]
Phase 3 (users tests + CI)  → runs in parallel once Phase 0 is done
Phase 4 (features)     → pick 4.1–4.4 first; they build directly on existing models
Phase 5 (deploy)       → when you're ready to put it in front of real users
```

Rule of thumb for every phase: **a green test suite before and after each change** — that guarantee is exactly what Phase 0 restores.
