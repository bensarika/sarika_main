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
| `db.py` | SQLAlchemy 2 ORM: `User`, `Work` (+ study code, phase, drugs, status, data class), `Permission`, `Draft` (one mutable head per work), `Revision` (append-only command log), `Version` (immutable freeze), `Adjudication`, `AuditEvent`, `Comment`, `Presence`, `AccessRequest`, `ProviderConfig` (encrypted key), `ProviderPolicy`, `AiCall` (usage, no prompt text), `SourceRecord`, `StudyRecordRow` (user-added canonical study JSON), `SourceConnection` (S3/Dropbox folders). SQLite by default with FK enforcement; Postgres by URL. |
| `library.py` | Starters: `blank`, `template:ad-antibody-p2b` (rich synthetic AD antibody protocol, see `starters/`) and `example:<id>` (from `reference/protocol_examples.json`). Claims are bound on creation. |
| `starters/ad_antibody.py` | The synthetic starter: full model + narrative blocks with claims across all 14 sections. Explicitly illustrative, never a real protocol. |
| `engine/state.py` | `DraftState` = model + narrative `Block`s (+ `Claim`s, pending `Proposal`) + not-applicable declarations + `Adaptation` + typed `key_inputs` + revision; `refresh_claims()`. |
| `engine/commands.py` | Typed commands (`set_field`, `add_entity`, `remove_entity`, `upsert_block`, `delete_block`, `set_block_approval`, `set_claim`, `resolve_claim`, `set_not_applicable`, `start_adaptation`, `decide_adaptation_change`, `set_evidence_requirement`, `answer_key_input`, `propose_text`, `resolve_proposal`), `apply_command()` and `apply_restore()`. |
| `engine/adaptation.py` | Starter → new drug(s): classifies every block/model value as retain / rewrite / remove / add / evidence with a clinical question and the evidence needed. Never find-and-replace; nothing applies until accepted. |
| `engine/key_inputs.py` | Grouped key-input questionnaire derived from unresolved adaptation changes; typed answers write to model paths and re-propose narrative. |
| `engine/textcheck.py` | Deterministic factual-change detection between a block and a proposed rewrite (numbers/units, negation, modals, actors, dropped claim phrases). |
| `engine/diff.py` | Pure diff between two `DraftState`s: dotted-path model changes + word-level tracked changes per block. |
| `engine/evaluation.py` | `evaluate(state, adjudications)` → findings (revision-stamped), completion per section/overall, readiness + blockers. |
| `engine/export.py` | `render_all()` → `.tex`, `.docx`, `.pdf` (if Tectonic) with SHA-256s; draft exports under `data/exports/<work>/rev-N/`, frozen under `data/versions/<work>/<label>/`. |
| `auth/session.py` | Signed session cookie, `current_user`, `require_admin`, per-work ACL (`view` < `edit` < `admin`), `audit()`. |
| `auth/routes.py` | `/auth/me`, `/auth/config`, `/auth/dev-login`, `/auth/google/login|callback`, `/auth/logout`. |
| `api/works.py` | Works CRUD (+ metadata patch), draft read, **commands**, evaluation, adjudications, history, outline, permissions, adaptation summary, key-input questionnaire, pending proposals. |
| `api/versions.py` | List/freeze/read versions, download frozen artifacts, draft export, `GET …/versions/{label}/diff?against=head|<label>`, `POST …/versions/{label}/restore` (new revision; approvals reset). |
| `api/collab.py` | Comment threads and suggestions (view access), `…/comments/{id}/apply` → pending `propose_text`, presence heartbeat, access requests (request / decide / mine). |
| `api/trial_lab.py` | `/api/trial-lab/sample-size`, `/profiles`, `/explore` over `packages/stats`. |
| `api/admin.py` | Users (invite/activate/role), audit log, usage per period (`/usage`, `/usage.csv`), pending access requests across works. The primary admin cannot be demoted. |
| `api/library.py` | Starters, outline, rule catalogue (with implemented/planned status), JSON schema. |
| `api/ai.py` | `GET …/ai/status`, `POST …/ai/revise` (→ pending `propose_text`, origin `ai`), `POST …/ai/ask` (advisory answer). |
| `api/providers.py` | Admin › Models: provider list (never returns keys), put config/key, per-data-class policy, connectivity test, `/ai-usage`. |
| `llm/keys.py` | Fernet encryption of provider keys at rest, derived from `PS_SECRET_KEY`; 4-char hint only. |
| `llm/providers.py` | `ProviderSpec` registry (OpenAI `gpt-6-astra` via the Responses API today; Grok/Muse/… are one adapter each) and the `Provider` protocol. |
| `llm/gateway.py` | The single door to any model: resolve config → **fail-closed data-class policy** → call → `AiCall` record. |
| `llm/prompts.py` | Deterministic prompt builders; a revise prompt carries only the selected block + its claim-bound facts. |
| `evidence/schema.py` | Canonical study JSON (`StudyRecord`: arms, endpoints with `transformation`, criteria, results, documents). Every fact carries a `Provenance` (document, page, section, quote, `quoted|registry|synthetic|unverified`). |
| `evidence/master.py` | Evidence Master: seeded records in `reference/evidence/<indication>/*.json` + user-added rows + the 17-protocol `reference/source_inventory.json` (registered, not yet parsed) merged into one sheet; endpoint matrix; per-indication summary. |
| `evidence/extract.py` | Deterministic first pass over PDF (`pypdf`), Markdown/text and `.xlsx` (`openpyxl`): SHA-256, pages, text layer, NCT/EudraCT/version ids, primary-endpoint and age-eligibility candidates. Produces a **draft** record, never a canonical one. |
| `evidence/compare.py` | Pure comparisons: primary endpoints (absolute vs percent change, responder, timepoint, instrument), eligibility (upper age, regional exceptions), results at one endpoint/timepoint (active vs placebo) with a Trial Lab hand-off. |
| `evidence/connections.py` | S3 (boto3, read-only listing of the corpus prefix) and Dropbox link status; credentials never appear in messages. |
| `api/evidence.py` | `/api/evidence/*`: studies, matrix, sources (upload / link / extract / draft / confirm), connections (add / check / sync), compare endpoints / eligibility / results. |

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

History is append-only: **restore** replays a frozen snapshot as a *new* head
revision (block approvals reset to `unreviewed`, pending proposals dropped) and
requires the caller's `base_revision` like any command. **Diff** compares a
version to the head or another version: model changes by dotted path
(`endpoints[easi75].time.offset.value`), narrative as word-level
insert/delete ops per block.

## Collaboration

Comments are review metadata, not document content — they never enter
exports, versions or the revision counter. A *suggestion* carries
`suggested_text` for a block; an editor can **apply** it, which creates a
pending `propose_text` (with deterministic factual-change checks) that still
needs accept/reject. Viewers may comment and suggest; resolving needs edit
access or authorship. Access requests bypass the work ACL by design and are
decided by a work admin, which writes the `Permission` row.

## Model reasoning (LLM gateway)

On-demand only, at the user's request, and always as a proposal: `POST
/api/works/{id}/ai/revise {block_id, instruction, base_revision}` sends one
block and its bound facts to the configured provider, then records the reply
as a pending `propose_text` (origin `ai`, `proposed_by` = `provider:model`)
with the same deterministic factual-change checks a human suggestion gets. The
live text does not change until an editor accepts. `…/ai/ask` answers a
question about a section and is marked `advisory`.

Policy is fail-closed per work `data_class`: only `public` is allowed by
default; an administrator approves a provider for `internal`, `confidential`
or `restricted` in Admin › Models (`PUT /api/admin/providers/{id}/policy`).
A blocked request returns `403` before anything leaves the server and is
still counted (`status=blocked`) in `/api/admin/ai-usage`. Provider keys are
entered in Admin, stored Fernet-encrypted, and never returned by any route;
the `OPENAI_API_KEY` environment variable is a fallback when no key is stored.
A provider must be **enabled** by an admin even if a key exists.

## Evidence and comparison

The Evidence Master is one sheet per indication: **parsed** records (seeded
JSON with page-level provenance — temtokibart 2a/2b, GSK1070806 2b,
lebrikizumab 2b), **user** records confirmed from uploads, and **registered**
entries from the source inventory that have a document but no parsed facts yet.
A record flagged `synthetic` (the planning fixture) is always labelled as such
in rows, comparisons and Trial Lab hand-offs; it is never counted as evidence.

Upload flow (`POST /api/evidence/sources`, multipart; or `/sources/link` for a
URL): the file is stored under `data/uploads/`, hashed (same SHA-256 → the
existing source is returned, not duplicated), then `POST …/extract` runs the
deterministic pass and `GET …/draft` renders a draft `StudyRecord` whose every
fact is `unverified`. A reviewer edits the draft and `POST …/study` stores it
with status `review`; an admin `PATCH /studies/{id} {"status": "approved"}`.
Nothing extracted becomes canonical without that step. PDFs without a text
layer are flagged (`needs OCR or manual entry`) rather than guessed at.

Sources are `workspace` (visible to any active user) or study-scoped
(`work_id`, view access on the work required; upload needs edit access).
Connections: `POST /api/evidence/connections {kind: s3|dropbox, uri}` (admin
for workspace scope), `…/check` lists the prefix (`ok | error |
not_configured`), `…/sync` registers each listed object as a `SourceRecord`
once (idempotent by URI). The default corpus is `PS_CORPUS_S3_URI`
(`s3://sarika-main-fs/protocol-corpus/`, region `PS_AWS_REGION`).

Comparisons are read-only and cite provenance on every row:
`GET /compare/endpoints?studies=<id,id,…>&role=primary` (flags absolute vs
percent change, responder vs continuous, timepoint and instrument
differences, non-quoted sources), `GET /compare/eligibility?indication=&category=age&text=&min_age=&max_age=`
(criteria of one category across the indication, ours on top; upper-age and
regional-exception flags), `GET /compare/results?indication=&instrument=EASI&transformation=responder&threshold=75%&week=16`
(active/placebo rows with source status and context, plus a ready-to-post
`/api/trial-lab/sample-size` body when both arms are present).

## Tests

Temp SQLite per test, dev auth. `test_api.py`: auth/ACL, stale-command 409,
schema 422, starters, entities, claim mismatch and both resolutions,
approval-driven completion, not-applicable + adjudication staleness, freeze,
DOCX/LaTeX export, admin usage/audit. `test_authoring.py`: synthetic starter,
adaptation classification, key inputs, factual-change detection, text
proposals, Trial Lab. `test_collab.py`: comment threads, suggestion → proposal,
presence, access-request flow, version diff/restore, usage periods + CSV.
`test_ai.py`: key encryption, Responses parsing, provider admin surface (no key
leakage), fail-closed policy, revise → pending proposal with factual checks,
ask, provider errors, viewer denial. The upstream call is faked.
`test_evidence.py`: seeded records + master rows, matrix, Markdown/PDF/Excel
extraction (blank PDF flagged; real temtokibart protocol when the attachment
is present), upload dedupe by SHA-256, draft → review → approve, unsupported
and empty uploads, link-only sources, source ACL, S3/Dropbox connections
(boto3 faked) + idempotent sync, endpoint/eligibility/result comparisons,
synthetic labelling, Trial Lab hand-off.

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
| `PS_AWS_REGION` | `us-east-2` | corpus bucket region |
| `PS_CORPUS_S3_URI` | `s3://sarika-main-fs/protocol-corpus/` | default read-only corpus prefix (boto3 default credential chain) |
| `PS_UPLOAD_MAX_BYTES` | `62914560` | 60 MiB upload cap |
