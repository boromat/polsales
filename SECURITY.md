# Security policy

## Reporting a vulnerability

Please report security issues privately by e-mail: **kontaktboromat@gmail.com**.
Do not open a public GitHub issue for a vulnerability.

Include, if you can: what is affected, steps to reproduce, and the impact you expect.
You will get an answer within 7 days. Fixes are released as a new version and noted in
[CHANGELOG.md](CHANGELOG.md).

## Supported versions

| Version | Supported |
|---|---|
| 1.0.x | yes |

## Security model in short

- Secrets live only in `.env` files; the panel shows whether an integration is configured,
  never the value of a secret.
- In production (`APP_DOMAIN` other than `localhost`) the app refuses to start with default
  secrets, and the session cookie is `Secure` and `HttpOnly`; session tokens are stored hashed.
- Login is rate-limited per (address, username), per address (IPv6 counted per /64) and per
  existing account; unknown usernames cost the same argon2 time as real ones. Changing a password
  with `create_user` revokes all sessions.
- State-changing API requests from another origin are rejected (Origin / Sec-Fetch-Site check)
  on top of the `SameSite=Lax` session cookie. Request bodies are capped at 8 MB at the edge
  (Caddy) and while streaming (ASGI), also without a `Content-Length` header.
- Optional Cloudflare Access login verifies the signed JWT (RS256, audience and issuer), never
  creates accounts on its own, and throttles key refreshes. With `CF_ACCESS_ONLY=true` password
  login is off, so Access cannot be bypassed through the server's direct address.
- The AI assistant is read-only: its tools run as a separate database role (`assistant_ro`)
  that can only `SELECT` from `analytics.*` views, with a statement timeout. If that role cannot
  be used, the tools are off and return an error; they never fall back to the application's
  full-privilege session (fail closed). The model never writes SQL;
  row limits and argument types are enforced on the server.
- Prompt injection: e-mail content and every assistant tool result reach the model between data
  tags (`<dane_maila>`, `<wynik_narzedzia>`) that the system prompts mark as data, not
  instructions; the same tag inside the text is defused. An e-mail can only produce a draft for
  manual review, never an order. Tags reduce the risk, they do not remove it.
- Containers: the API and worker run as a non-root user; the database and API ports are not
  published, only Caddy is.
- Secrets that can appear in error messages (API tokens, the GA4 service account key) are
  scrubbed before they are logged or stored.
- With PII masking on (the default), personal data detected by polanon and every client value
  known to the database (company names, NIPs, draft and contact names) is replaced with tokens
  before any text is sent to a model; if masking cannot run, nothing is sent (fail closed).
  Detection is rule-based, so treat it as risk reduction, not a guarantee.
- The body, HTML and headers of handled e-mails are cleared after `RAW_EMAIL_RETENTION_DAYS` (GDPR).
