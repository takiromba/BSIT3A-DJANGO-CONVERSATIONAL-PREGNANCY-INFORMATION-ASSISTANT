# PregnaBot

PregnaBot is a Django application for general pregnancy education. It includes a pregnancy information and FAQ library, a ranked keyword-search chatbot, private chat histories, a pregnancy planning toolkit, and superuser account management.

PregnaBot is not a diagnostic or treatment service. Urgent-symptom replies advise users to contact their maternity-care team or local emergency services; the app does not publish location-specific hotline numbers.

## Requirements

- Python 3.14
- SQLite for local development, or MySQL 8.0.11+ / MariaDB 10.5+ when configured

## Local setup (Windows PowerShell)

From the project directory:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

Generate and set a fresh local secret key:

```powershell
$secret = (python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())").Trim()
$envText = Get-Content .env -Raw
$envText = $envText -replace '(?m)^DJANGO_SECRET_KEY=.*$', "DJANGO_SECRET_KEY=$secret"
Set-Content -Path .env -Value $envText
```

The default local database is `db.sqlite3`. To use MySQL or MariaDB, uncomment and set `DB_ENGINE`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, and `DB_PORT` in `.env`.

Initialize and run the app:

```powershell
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open `http://127.0.0.1:8000/`. Create a Django administrator login with `createsuperuser`; there is no default admin password.

## Tests and quality checks

The default test settings use in-memory SQLite so tests do not need a database server:

```powershell
python manage.py test --settings=mysite.test_settings
python manage.py check --settings=mysite.test_settings
ruff check apps mysite manage.py
black --check apps mysite manage.py
```

The CI workflow runs the tests against MySQL 8.0. Production database backends must be MySQL 8.0.11+ or MariaDB 10.5+.

## Configuration and production

- `mysite.settings` is the local/development configuration. `DJANGO_SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, and DB connection values are read from `.env` or environment variables.
- `mysite.production_settings` requires a non-SQLite database, uses the database cache for cross-process login throttling, forces secure cookies and HTTPS by default, enables HSTS, and uses WhiteNoise for collected static assets.
- Generate a new secret for each environment. Never commit `.env`, actual credentials, production database files, or backup data. `DJANGO_SECRET_KEY` is mandatory.
- If TLS terminates at a reverse proxy, only set `TRUST_X_FORWARDED_PROTO=True` when the application can trust that proxy to set the forwarded protocol header. Keep `SECURE_SSL_REDIRECT=True` in production.
- Sentry is opt-in using `SENTRY_DSN`; default PII collection is disabled.
- The `/healthz/` endpoint checks database connectivity and returns a 503 when the database is unavailable.
- Production login throttling uses Django's database cache. Create its table once with `python manage.py createcachetable`.

### Docker Compose

Set a fresh `DJANGO_SECRET_KEY` and a strong `MYSQL_ROOT_PASSWORD` in `.env`, then run:

```powershell
docker compose up --build
```

The Compose file runs MySQL 8, migrations, cache-table creation, static collection, and Gunicorn. Its `SECURE_SSL_REDIRECT=False` is only for local HTTP testing at `http://127.0.0.1:8000/`; do not expose that configuration to the public internet. For a deployment, set `SECURE_SSL_REDIRECT=True` and terminate TLS at a trusted reverse proxy.

For a non-container Linux deployment, install `requirements-prod.txt`, set `DJANGO_SETTINGS_MODULE=mysite.production_settings`, configure the environment, migrate, run `createcachetable` and `collectstatic`, then start `gunicorn mysite.wsgi:application` behind a TLS-enabled reverse proxy.

## Pregnancy information, sources, and privacy

Content editors can manage topics and FAQs in Django admin. Add a reviewed source name and URL to each item before presenting it as sourced; existing seed entries intentionally have no invented per-answer citations. Chat feedback analytics show aggregate ratings to superusers, and do not expose individual users' names.

Conception dates, blood type, appointments, and saved topics are optional account-linked information. Access is restricted to the signed-in owner; deleting an account removes the related records. Appointment reminders are shown in the toolkit only—no email, SMS, or push reminders are sent. Do not use the app for urgent care.

The due-date tool estimates the due date as 266 days after the estimated conception date and calculates an approximate gestational week/trimester. It is not clinical dating; confirm timing with a qualified care professional.

The Filipino interface is selectable from the language menu. Pregnancy content remains the approved source-language copy unless editors provide a medically reviewed translation.

The PWA service worker caches same-origin static assets only. It deliberately does not cache authenticated pages or personal/health information for offline use.

## Content seeding

Pregnancy information and FAQ seed content is applied by the initial Django migration. To safely re-add any missing built-in entries:

```powershell
python manage.py seed_content
```

The command is idempotent and does not overwrite content already edited by administrators.

## Database backup and restore

For MySQL/MariaDB, store backups outside the repository and protect them as sensitive health/user data:

```powershell
New-Item -ItemType Directory -Force backups
mysqldump --single-transaction --routines --triggers -h localhost -u root -p bsitcrud > "backups\bsitcrud-$(Get-Date -Format yyyyMMdd-HHmmss).sql"
```

Restore to the intended database only after verifying the target and backup:

```powershell
cmd.exe /c "mysql -h localhost -u root -p bsitcrud < backups\bsitcrud-YYYYMMDD-HHMMSS.sql"
```

For local SQLite development, stop the server and copy `db.sqlite3` to a protected backup location. Periodically test restore procedures; never commit database backups.
