# Contributing

Bug reports, fixes and new integrations are welcome. PolSales is a sales and marketing panel: a
FastAPI backend on PostgreSQL with Alembic migrations, a worker, a React and TypeScript frontend
built with Vite, and an AI assistant whose tools read the data through a read-only role, with
personal data masked by polanon first.

## Setup

PostgreSQL 16, Python 3.10 or newer, Node.js 24 LTS. The README's *Getting started* has every step,
Docker Compose included; in short:

```bash
cd backend
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[dev]"                               # pytest, ruff, mypy and polanon
export DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:5432/polsales
alembic upgrade head
python -m app.scripts.seed_demo                       # a fictional sports shop

cd ../frontend
npm ci
npm run dev                                           # http://localhost:5173
```

On Windows without Docker, `deploy\run-local.ps1` sets up a portable PostgreSQL. For the assistant
without an API key, `python tools/mock_llm.py --port 8765` and `AI_BASE_URL=http://127.0.0.1:8765`.

## Quality bar

- Backend, in `backend/`: `ruff check . ../tools ../evals`, `ruff format --check . ../tools ../evals`,
  `mypy` and `pytest -q -W error --cov` pass, with warnings treated as errors. Frontend: `npm test`,
  `npm run typecheck` and `npm run build`. CI runs both on Linux and Windows, with the migrations
  applied to an empty PostgreSQL.
- Coverage stays at or above the floor in `backend/pyproject.toml` (68%, a little under where the
  suite is). The floor is there to stop it sliding back: raise it when the suite has grown past it.
- A change to the schema comes with an Alembic migration in `backend/alembic/versions/`, and
  `alembic upgrade head` runs on an empty database.
- Tests for every behaviour change, and no network or paid API in them: the model is replaced with
  a fake or with `tools/mock_llm.py`, which prints what it receives.
- Anything that sends text to a model keeps the guarantees in `SECURITY.md`: the assistant's tools
  only read `analytics.*` through the `assistant_ro` role, the model never writes SQL, e-mail
  content and tool results reach it between data tags, and with masking on nothing leaves without
  it. A change there comes with a test in `tests/test_privacy.py`, `tests/test_prompt_injection.py`
  or `tests/test_security.py`.
- A change to the assistant is measured, not asserted: `python ../evals/run.py --mock` in
  `backend/` checks the harness, and `evals/README.md` explains a real run and its cost.
- A new `# noqa` for a security rule (`S`) says on its line why the code is safe.
- Conventional Commits in the imperative mood, one logical change each:
  `feat(evals): measure the assistant on demo data against plain SQL`, `fix(chat): ...`,
  `docs: ...`, `test: ...`, `chore: ...`.
- `README.md` is Polish and `README.en.md` is its English translation: a change to one is made to
  the other in the same commit.

## Test data

Invented data only, in tests, fixtures, the demo seed, screenshots and issues alike. Customer
e-mails and orders are personal data: no real customer, company, order, mailbox export, database
dump or log belongs in the repository.

- E-mail addresses and websites use `example.com` or a `.example` domain
  (`anna.testowa@orlik.example`).
- A PESEL has a valid checksum and a birth date before 1860 or after 2100, so it can never belong
  to a living person: `50810112354` is 1 January 1850.
- Companies, NIPs, products and campaigns are made up; `app/scripts/seed_demo.py` and
  `backend/tests/dane/` show the shape.

## Changes written with AI tools

Welcome, on the same terms as any other change. Say in the pull request that an AI tool wrote or
helped write it, and which one, so the review knows where to look. You answer for the change as if
you had typed it yourself: you have read every line, run the quality bar above, and can answer
questions about it. A pull request that nobody answers for after a review is closed.

## Masking and security

Masking of personal data before an AI call is done by
[polanon](https://github.com/boromat/polanon). A value it did not recognise is a detection gap in
polanon: report it there, with invented text of the same shape. A way into the panel without
logging in, past the read-only role, around the data tags, or for personal data to reach the
model while masking is on is a security report: see `SECURITY.md`, never a public issue.

## Releases

The version is written in `backend/pyproject.toml`, `backend/app/main.py` (the number the API
reports), `frontend/package.json` and `frontend/package-lock.json`. To release, change all four and
rename `## [Unreleased]` in `CHANGELOG.md` to `## [X.Y.Z] - YYYY-MM-DD` in one commit
(`chore(release): X.Y.Z`), then push the tag `vX.Y.Z`. `.github/workflows/release.yml` checks that
they agree with the tag and that the section is dated, and creates the release *PolSales X.Y.Z*
with that section as its notes.
