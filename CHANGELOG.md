# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versions follow [SemVer](https://semver.org/).

## [Unreleased]

### Added
- Optional `google` extra (`google-analytics-data`, `google-auth`, `google-ads`) for the GA4 and
  Google Ads integrations, and a `BACKEND_EXTRAS` build arg for the Docker images. Without the
  packages a configured integration reports how to install them instead of an `ImportError`,
  on the dashboard and in Settings.

### Fixed
- `EMAIL_PARSER_ESCALATION_MODEL` was read by the e-mail parser but missing from the settings,
  so it could not be set; it is now a documented setting (empty = the chat model).

### Changed
- `docs/08-plan-etapow.md` is marked as an archived build plan; the README test counts
  match the current suite (288 backend, 17 frontend).
- The Polish number format used by the weekly summary and the recommendations lives in one
  helper, `app/services/text_format.num_pl` (it was duplicated in both services).

### Security
- `deploy/run-local.ps1` checks the SHA256 of the PostgreSQL ZIP it downloads (`Get-FileHash`
  against a pinned value) and stops, deleting the file, before unpacking anything that does not
  match. A failed download now stops the script too.
- Assistant conversations belong to the account that started them (migration `0020`; existing
  conversations go to the first account) and the chat API lists and opens only the caller's own.
  Before, every account saw every conversation.
- Assistant tools fail closed: when the read-only `assistant_ro` session cannot be used, or
  runs as another role, every tool returns an error that points to the README and a warning is
  logged. Before, the tools silently fell back to the application's full-privilege session.

## [1.0.0] - 2026-11-09

First public release.

### Added
- PII masking with [polanon](https://pypi.org/project/polanon/) for every LLM call: assistant
  chat (question, history, tool results), weekly summaries, recommendations and the AI e-mail
  parser. Tokens are restored locally in tool arguments, structured output and the streamed answer.
- Values known from the database are always masked (polanon `DenylistGuard`): client company
  names (also without the legal form), NIPs with and without dashes, draft and contact names,
  also when a name looks like a well-known brand.
- Fail closed: with masking on and polanon unavailable, nothing is sent to the model.
- Settings -> AI privacy: masking switch, optional spaCy NER mode, polanon install status.
  Stored in the new `ops.app_settings` table (migration `0019`).
- Chat badge with the number of masked values and the question exactly as the model saw it.
- `AI_BASE_URL` alone enables a custom Anthropic-compatible endpoint without an API key, and
  `tools/mock_llm.py`, a local mock model for demos and end-to-end tests.
- Tests: masking contract with a fake anonymizer, the same scenarios with the real polanon,
  an end-to-end test through the Anthropic SDK over HTTP, fail-closed tests, e-mail parser tests.
- CI on Linux and Windows (PostgreSQL, ruff, migrations, backend tests with warnings as errors,
  frontend tests, typecheck and build), on Node 24 LTS with actions v7.
- `frontend/Dockerfile`: the Caddy image now contains the built frontend.

### Fixed
- GDPR e-mail retention never ran: it updated a column that does not exist and rolled back the
  whole nightly job (expired sessions, sync log). It now clears the body, HTML, headers and
  attachment metadata of handled e-mails, and each clean-up step has its own transaction.
- Behind Caddy every login came from the proxy's IP, so 5 wrong passwords from anyone locked the
  owner out for 15 minutes; uvicorn now reads `X-Forwarded-For` (`--proxy-headers`).
- Docker Compose served an empty frontend: the `frontend_dist` volume was never filled.
- `get_company_profile` and `get_orders` did not find a company when the NIP was given with
  dashes or a `PL` prefix.
- Chat showed raw tool names for 4 of the 13 tools; the "assistant unavailable" hint named the
  wrong environment variable.
- A test assumed the Anthropic SDK always sends `x-api-key`; SDK 0.120+ sends a Bearer header.
- Vitest printed deprecation warnings from the React plugin; the Vite config did not typecheck.

### Security
- Dependency audit: `pip-audit` clean; frontend upgraded to Vite 8, `@vitejs/plugin-react` 6,
  React Router 7 and Vitest 4.1.12, so `npm audit` reports 0 vulnerabilities (was 13, incl. a
  React Router open redirect and Vite dev-server path traversal).
- Ruff security rules (flake8-bandit, `S`) run in CI; every f-string SQL was checked to interpolate
  only constant fragments chosen in code, with values always passed as bind parameters.
- Row limits from tool arguments are clamped on the server (the JSON schema is only a hint);
  chat input and login fields have length limits.
- Independent security review, all findings fixed:
  - login limits per address (IPv6 per /64) and per existing account, constant-time handling
    of unknown usernames, sessions revoked on password change;
  - CSRF protection (Origin / Sec-Fetch-Site check) for state-changing API requests;
  - request body capped while streaming (chunked bodies had no limit) and in Caddy;
  - `CF_ACCESS_ONLY` mode and throttled JWKS refresh for Cloudflare Access;
  - the GA4 service account JSON was treated as a file path, so its private key could end up in
    error messages; it is now parsed as JSON and scrubbed from errors;
  - notification subjects are flattened to one line; the production guard rejects short or
    placeholder `SESSION_SECRET` values; the backend image runs as a non-root user.

### Changed
- Session cookie `polsales_session` and `POLSALES_USERNAME` / `POLSALES_PASSWORD` / `POLSALES_EMAIL`
  for `create_user` (names left over from the internal project name).
- Demo data is a fictional sports shop; all sample e-mails, people, companies and NIPs are invented.
- Removed the unused `pytest-asyncio` dependency; added `pymupdf` to dev extras so the PDF
  layout tests run instead of being skipped.
