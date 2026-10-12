# Recruiter

Django project for ingesting job posts aimed at Uganda and at roles that can be done from Uganda. This repository root is the project folder: `manage.py` lives here.

Slice 1 is the parser path only. `apps/coaching` and `apps/recruiting` are later modules and are not created yet. This module does not coach a candidate or score an application.

A fixture feed is parsed with Gemini 2.5 Flash (`JOB_PARSER`, temperature 0). Employment posts and procurement tenders are stored in separate models. LinkedIn, Indeed, ZipRecruiter, and Google Custom Search are not scraped.

## Run locally

Python 3.12.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Put a Gemini API key in `.env` as `GEMINI_API_KEY`. The key stays on the machine. It is not committed.

Vertex AI is unused unless both `VERTEX_AI_PROJECT` and `VERTEX_AI_LOCATION` are set. Local runs use the API key.

```bash
python manage.py migrate
python manage.py ingest_fixtures
python manage.py test
```

`ingest_fixtures` reads `apps/ingestion/fixtures/feed.json`, asks Flash to parse each posting, then applies serializer checks the response schema cannot express:

- legitimacy is `high` when the applicant is charged or the employer is hidden, otherwise `review` when the only contact is a personal inbox, otherwise `clear`
- compensation is null when the posting states no pay
- discriminatory criteria are removed from stated skills
- a procurement tender is saved apart from an employment post

The tests mock Gemini. They do not call the network. A normal fixture must save an employment row, and the fixture that charges the applicant must save legitimacy `high`.

## Daily run

Celery beat calls `apps.ingestion.tasks.ingest_fixture_feed` at 05:00 Africa/Kampala. That task runs the fixture path until a real feed exists.

```bash
celery -A config worker --loglevel=info
celery -A config beat --loglevel=info
```

The broker defaults to `redis://localhost:6379/0` (`CELERY_BROKER_URL`).
