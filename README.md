# Recruiter

Django project for job posts aimed at Uganda and at roles that can be done from Uganda, plus a candidate coach. This repository root is the project folder: `manage.py` lives here.

`apps/ingestion` parses fixture postings. `apps/coaching` is the candidate coach: CV notes, a mock interview, and a seven-day plan. The recruiter module is not in this repository. LinkedIn, Indeed, ZipRecruiter, and Google Custom Search are not scraped.

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

`python manage.py test` mocks Gemini. The tests do not call the network.

## Ingestion

`ingest_fixtures` reads `apps/ingestion/fixtures/feed.json`, asks Flash to parse each posting (`JOB_PARSER`, temperature 0), then applies serializer checks the response schema cannot express:

- legitimacy is `high` when the applicant is charged or the employer is hidden, otherwise `review` when the only contact is a personal inbox, otherwise `clear`
- compensation is null when the posting states no pay
- discriminatory criteria are removed from stated skills
- a procurement tender is saved apart from an employment post

A normal fixture must save an employment row, and the fixture that charges the applicant must save legitimacy `high`.

Celery beat calls `apps.ingestion.tasks.ingest_fixture_feed` at 05:00 Africa/Kampala. That task runs the fixture path until a real feed exists.

```bash
celery -A config worker --loglevel=info
celery -A config beat --loglevel=info
```

The broker defaults to `redis://localhost:6379/0` (`CELERY_BROKER_URL`).

## Candidate coach

`apps.coaching` uses the Gemini wrapper in `apps/ingestion/gemini.py`. Closing untrusted tags are stripped, the system instruction is the shared policy plus one mode prompt, and the service reads `response.parsed` before its serializer. The interview call is synchronous `generate_content`. It is not queued on Celery.

- `CV_OPTIMIZER` and `CANDIDATE_REPORT` use Gemini 2.5 Flash at temperature 0. Thinking stays down.
- `MOCK_INTERVIEW` uses Gemini 2.5 Pro at temperature 0.2. The call carries this turn plus the questions Django has already stored. Thinking stays available.
- Django issues the session id, the turn number, and the question id. Those values are columns on the session. They are not model output fields.
- A CV bullet edit is dropped when `cv_excerpt` is not a substring of the source CV.
- Stored gaps feed the seven-day plan. An action is dropped unless `cites_gap_id` is one of those gap ids. A gap whose label is a discriminatory criterion is not usable.
- `coaching_quality` is an integer from 1 to 10 on mock-interview turns after turn 1, and null on turn 1. It is coaching quality, not a hiring score. The row stores the model id.

The coaching tests cover those three checks with a mocked client. A live call needs `GEMINI_API_KEY`. From a Django shell after `migrate`:

```python
from apps.coaching.services import (
    answer_interview,
    optimize_cv,
    record_stored_gap,
    start_interview,
    write_progress_report,
)
```
