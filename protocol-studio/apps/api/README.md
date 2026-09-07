# protocol_studio (API)

FastAPI service that owns works, the edit/commit engine, findings, versions,
export, authentication and the admin surface. It is the only writer to the
database; `packages/*` are pure libraries it composes.

```
uv run uvicorn protocol_studio.main:app --reload --port 8080   # from protocol-studio/
open http://localhost:8080/docs
```

Default dev mode signs you in as `PS_DEV_USER_EMAIL` (ben@sarika.com) on
`POST /auth/dev-login`; set `PS_AUTH_MODE=google` plus the Google client
env vars for real Google Sign-In (Internal audience, `@sarika.com` only).

## Layout

| Path | Purpose |
| --- | --- |
| `main.py` | App factory: lifespan (DB init), session + CORS middleware, routers, `/healthz`, optional static serving of `apps/web/dist`. |
| `settings.py` | `Settings` (pydantic-settings, `PS_` prefix). DB URL, data dir, secret key, auth mode, admin allowlist, Google client, CORS. |
| `db.py` | SQLAlchemy 2 ORM: `User`, `Work`, `Permission`, `Draft` (one mutable head per work), `Revision` (append-only command log), `Version` (immutable freeze), `Adjudication`, `AuditEvent`. SQLite by default with FK enforcement; Postgres by URL. |
| `library.py` | Starters: `blank` and `example:<id>` (from `reference/protocol_examples.json`, converted to an authored draft). |
| `engine/state.py` | `DraftState` = model + narrative `Block`s (+ `Claim`s) + not-applicable declarations + revision. |
| `engine/commands.py` | Typed commands (`set_field`, `add_entity`, `remove_entity`, `upsert_block`, `delete_block`, `set_block_approval`, `set_claim`, `resolve_claim`, `set_not_applicable`) and `apply_command()`. |
| `engine/evaluation.py` | `evaluate(state, adjudications)` → findings (revision-stamped), completion per section/overall, readiness + blockers. |
| `engine/export.py` | `render_all()` → `.tex`, `.docx`, `.pdf` (if Tectonic) with SHA-256s; draft exports under `data/exports/<work>/rev-N/`, frozen under `data/versions/<work>/<label>/`. |
| `auth/session.py` | Signed session cookie, `current_user`, `require_admin`, per-work ACL (`view` < `edit` < `admin`), `audit()`. |
| `auth/routes.py` | `/auth/me`, `/auth/config`, `/auth/dev-login`, `/auth/google/login|callback`, `/auth/logout`. |
| `api/works.py` | Works CRUD, draft read, **commands**, evaluation, adjudications, history, outline, permissions. |
| `api/versions.py` | List/freeze/read versions, download frozen artifacts, draft export. |
| `api/admin.py` | Users (invite/activate/role), audit log, usage counts. The primary admin cannot be demoted. |
| `api/library.py` | Starters, outline, rule catalogue (with implemented/planned status), JSON schema. |

## Edit/commit contract

Every semantic change is a command posted to `POST /api/works/{id}/commands`
with the client's `base_revision`.

| Situation | Response |
| --- | --- |
| `base_revision == head` and command valid | `200` — new `revision`, full `state`, fresh `evaluation` |
| `base_revision != head` | `409` — client must reload and re-apply (optimistic concurrency) |
| model would violate the schema (draft mode) or command refers to a missing entity/block/claim | `422` |

Rules of the engine (docs/01_architecture.md §5):

- Narrative edits never silently change approved model values. A claim whose
  text disagrees with the model becomes a **CL01 mismatch**; the author resolves
  it explicitly with `resolve_claim` → `update_model` or `revert_text`.
- Editing an approved block's text demotes it to `unreviewed`; completion
  counts narrative only when approved.
- Findings, completion and claim states are recomputed on every accepted
  command and carry the revision they were computed at.
- Adjudications are keyed by the finding's stable key and must quote the
  revision the finding was computed at; if the head has moved the request is
  rejected with `409 stale` and the client re-evaluates first.

## Versions and export

`POST /api/works/{id}/versions {label, note}` freezes the current draft:
snapshot, evaluation (with `ready` and `blockers`), artifacts and hashes. A
freeze of an incomplete draft is allowed for internal review but is never
marked ready. `GET /api/works/{id}/export/{tex|docx|pdf}` renders the live draft.

## Tests

`apps/api/tests/test_api.py` (temp SQLite per test, dev auth):
auth/ACL, stale-command 409, schema 422, starters, entities, claim mismatch and
both resolutions, approval-driven completion, not-applicable + adjudication
staleness, freeze, DOCX/LaTeX export, admin usage/audit.

```
uv run pytest apps/api
```

## Environment

| Variable | Default | Notes |
| --- | --- | --- |
| `PS_DATABASE_URL` | `sqlite:///./data/protocol_studio.db` | Postgres URL in production |
| `PS_DATA_DIR` | `./data` | exports and versions |
| `PS_SECRET_KEY` | dev-only | **must** be set in production |
| `PS_AUTH_MODE` | `dev` | `google` in production |
| `PS_ADMIN_EMAILS` | `["ben@sarika.com"]` | always active admins |
| `PS_ALLOWED_DOMAIN` | `sarika.com` | Google accounts must match |
| `PS_GOOGLE_CLIENT_ID/SECRET` | — | from the `GOOGLE_OAUTH_*` org secrets; never commit |
| `PS_PUBLIC_BASE_URL` | `http://localhost:8080` | OAuth redirect base |
| `PS_WEB_DIST` | `../web/dist` | serve the built SPA if present |
