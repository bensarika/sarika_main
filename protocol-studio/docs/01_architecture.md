# Protocol Studio — Architecture and Reasoning

Status: Phase 0 (design). Nothing in this document is implemented yet. Every
decision below is open to challenge; the *why* is recorded so a later agent can
revisit it with full context.

Companion documents: `02_visual_language.md` (graphic grammar),
`03_domain_model.md` (the trial model, outline, provenance), `04_workflows.md`
(usage scenarios walked through against the mock), `05_decisions.md` (ADRs and
open questions), `06_delivery_plan.md` (pilots and phases).

---

## 1. What the product is (one paragraph)

Protocol Studio is a browser-based workspace for writing and analysing clinical
trial protocols and statistical analysis plans (SAPs). It is **model-first**:
the unit of truth is a versioned, source-traceable *trial model* (populations,
products, regimens, paths, endpoints, estimands, analyses, rules, schedules).
The 14-section ICH M11 document is one *rendered view* of that model; the
synopsis, treatment diagram, schedule of activities (SoA) and endpoint tables
are other views of the same model. Because they share one source, the
application can check them against each other. LLMs (OpenAI `gpt-6-astra` by
default; Grok, Muse or others added by the admin) help parse, adapt, question
and reason on demand, but only deterministic code and human adjudication can
mark something *accepted*.

---

## 2. Why model-first (the core reasoning)

The supplied specification (`reference/AD_protocol_builder_spec.md`) makes the
argument in detail; the short version:

1. **Regulatory documents fail on consistency, not prose.** A protocol whose
   SoA omits the week-16 EASI visit that the primary endpoint needs, or whose
   rescue rule is treated as "treatment policy" in section 3 and "composite
   failure" in section 10, is defective regardless of how well it reads. Only
   a shared model lets software detect this.
2. **"Intelligent drug replacement" needs typed objects, not text.** To decide
   whether a sentence about "loading dose at Week 0 and Week 2" still applies to
   a new molecule, the system must know that the sentence is a `regimen`
   assertion bound to `product:lebrikizumab`, not just that it contains the
   string "lebrikizumab". Find-and-replace is what you get without a model.
3. **Provenance is a first-class regulatory requirement.** Every value must be
   attributable to a source page, an author, an inherited library module, a
   derivation, or an LLM proposal — and its review state must be visible.
4. **Completion percentages must be honest.** "% complete" is computed from
   required model slots and unresolved decisions per section, never from word
   count. The UI must always be able to show *what* is missing.

Consequence: the editor is a *structured document editor* whose paragraphs are
blocks bound to model objects, not a free-text word processor with a checker
bolted on. Free narrative is allowed (rationale, background) but numeric and
operational claims inside narrative are extracted as `claims` and checked
against the model (see §6.3).

---

## 3. System overview

```
┌────────────────────────────────────────────────────────────────────────────┐
│  Browser (React + TypeScript)                                              │
│  Library · Workspace · Editor (outline | canvas | inspector | Ask thread)  │
│  Calculator · Comparator · Admin (users, works, usage, models)  Yjs client │
└───────────────▲────────────────────────────▲───────────────────────────────┘
                │ HTTPS/JSON (REST)          │ WebSocket (collab + presence)
┌───────────────┴────────────────────────────┴───────────────────────────────┐
│  API  (Python 3.12 · FastAPI)                                              │
│  auth (Google OIDC, allowlist) · permissions · works/versions · model ops  │
│  validation engine · render AST · calculator · comparator · admin/usage    │
│  collab gateway (y-py / pycrdt) · autosave snapshots                       │
└──────┬──────────────────────┬──────────────────────┬───────────────────────┘
       │                      │                      │
┌──────▼───────┐   ┌──────────▼──────────┐   ┌───────▼────────────────────────┐
│ PostgreSQL   │   │ Worker (same code)  │   │ Object store (S3)              │
│ relational + │   │ ingestion · LLM     │   │ source PDFs · parsed cache     │
│ JSONB model  │   │ passes · LaTeX/DOCX │   │ (canonical JSON/MD) · exports  │
│ versions,    │   │ compile · question  │   │ · autosave snapshots · assets  │
│ perms, usage │   │ minimisation        │   └────────────────────────────────┘
└──────────────┘   └──────────┬──────────┘
                              │ HTTPS
                   ┌──────────▼──────────┐   ┌────────────────────────────────┐
                   │ Model gateway →     │   │ External sources               │
                   │ OpenAI gpt-6-astra  │   │ Dropbox links · S3 links ·     │
                   │ · Grok · Muse · …   │   │ user uploads (PDF/MD/XLSX/URL) │
                   │ (admin-managed keys)│   └────────────────────────────────┘
                   └─────────────────────┘
```

Deployment target (user requirement): the customer's **Amazon EC2 + S3**.
Phase 1 runs everything except S3 on one EC2 host via Docker Compose
(Caddy for TLS → web static + API + worker + Postgres). Postgres can move to
RDS later without code change. See §9.

---

## 4. Technology choices and why

| Layer | Choice | Why (and what we rejected) |
|---|---|---|
| Frontend | React 18 + TypeScript + Vite; TanStack Router/Query; Tailwind with design tokens from `02_visual_language.md` | Mature ecosystem for a dense three-pane editor. Next.js rejected: no SSR/SEO need; a static bundle behind Caddy/S3 is simpler to host on EC2/S3. |
| Editor | ProseMirror via TipTap, with **custom block nodes bound to model IDs**; Yjs for real-time collaboration | Block-level schema control is the whole point (§2). TipTap gives Yjs binding for free. Plain contenteditable/Slate rejected (weaker schema enforcement). |
| API | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 | Python owns the hard parts: PDF parsing (PyMuPDF), statistics (SciPy/statsmodels), JSON-Schema (`jsonschema`), LaTeX/DOCX generation, OpenAI SDK. One language for API + worker keeps the audit surface small. Node/Nest rejected for weaker scientific stack. |
| Database | PostgreSQL 16. Relational tables for identity/permissions/versions/usage; JSONB for model documents (validated against `protocol_model.schema.json`) | Spec: "a relational DB with stable IDs and link tables is sufficient; no graph DB". JSONB avoids a 30-table ORM for a schema still evolving; link tables (`model_refs`) are materialised from the JSON for cross-reference checks. |
| Background jobs | `procrastinate` (Postgres-backed queue) | Ingestion, LLM passes and LaTeX compiles are seconds-to-minutes. A Postgres queue avoids Redis as another moving part on one EC2 box. Swap to SQS/Celery later if needed. |
| Collaboration | Yjs CRDT; server-side `pycrdt` gateway persists updates; periodic snapshots to S3 = autosaved backups | CRDTs give conflict-free multi-cursor editing and an update log that doubles as fine-grained history. Google-Docs-style OT rejected (harder to self-host). |
| Versioning | Immutable `versions` (semantic: v0.1, v1.0, Amendment 1) = frozen model + rendered artifacts; continuous autosave snapshots every 30 s / on idle | Regulatory versions are deliberate acts; autosave is safety. Both kept, clearly separated in UI. |
| Rendering | Model → **Render AST** (section tree of typed blocks) → (a) LaTeX → PDF via **Tectonic**; (b) DOCX via `python-docx` with M11 heading styles | User requires LaTeX. One AST feeding two emitters keeps PDF and DOCX content aligned (tested with golden-file diffs of both outputs; not assumed). Pandoc LaTeX→DOCX rejected (loses tables/styles). Tectonic chosen over full TeX Live: reproducible, self-contained, fetches packages on demand into a cached bundle. |
| LLM | **Provider-agnostic model gateway** (`packages/llm`): adapters for OpenAI (default `gpt-6-astra`), xAI Grok, Anthropic, Muse and any OpenAI-compatible endpoint; providers, models and API keys are **added in the Admin panel** (keys encrypted at rest, never returned to the browser); **structured outputs (JSON Schema)** for pipeline tasks, streaming for on-demand reasoning; prompts versioned in repo; every call logged (`llm_calls`) with provider, model, prompt id, tokens, cost, latency, caller | User requirement (multi-vendor, admin-managed keys). Auditable, cost-attributable, reproducible. Vendor lock-in and hard-coded keys rejected. Free-text prompting rejected for pipeline tasks — outputs must be typed to enter the model as *proposed* values. |
| PDF ingestion | PyMuPDF (text, bookmarks, tables, bboxes) + OCR fallback (Tesseract) for image-only PDFs; page-anchored `source_assertions` | Three of the six supplied PDFs (M11 template copy, E9 framework copy, lebrikizumab P2b) have **no text layer** — OCR is not optional. |
| Auth | Google OpenID Connect (Authlib), server session cookie (HttpOnly, SameSite=Lax); allowlist table; `ben@sarika.com` bootstrapped as admin | Requirement. No password store. Works for Google Workspace and personal Google accounts. |
| Infra | Docker Compose on EC2; Caddy (auto-TLS); S3 for objects; GitHub Actions builds images and deploys via SSM/SSH | Requirement (EC2 + S3). Smallest reliable footprint. |
| Tests | `pytest` (API, engine, rules with fixtures from `reference/protocol_examples.json`); Vitest + Playwright (UI) | Rules engine must be regression-tested against the toolkit's synthetic fixtures and the real-document cases the spec lists. |

---

## 5. Repository layout (monorepo)

```
protocol-studio/
  docs/                 design docs (this folder) — kept current, one README per subcomponent
  reference/            supplied toolkit (schema, outline, rules) + ICH M11 outline JSON — read-only inputs
  mock/                 Phase-0 static clickable mock (no build step)
  apps/
    web/                React app            (README.md)
    api/                FastAPI app + worker  (README.md)
  packages/
    model/              Pydantic models generated from protocol_model.schema.json; outline; provenance types
    rules/              validation rule plugins R01–R22 (+ later), each a file with tests
    render/             Render AST → LaTeX / DOCX emitters, M11 style sheet
    ingest/             source classification, structure recovery, OCR, assertion extraction
    llm/                model gateway: vendor adapters (openai, xai, anthropic, muse, openai-compatible),
                        prompt registry, structured outputs, streaming, logging, cost accounting
    stats/              sample size, power, sensitivity, endpoint/timepoint ranking
    compare/            criteria normalisation + similarity + diff highlighting
  infra/
    compose/            docker-compose.yml, Caddyfile, env templates
    aws/                EC2 bootstrap, S3 bucket policy, IAM policy (least privilege)
  .github/workflows/    ci.yml (lint, typecheck, tests), deploy.yml
```

Each `apps/*` and `packages/*` directory carries its own `README.md` describing
purpose, public interface, invariants and how to test it. Agents editing a
package update its README in the same PR (enforced by a CI check that the
README changed whenever the package's public surface changed — see
`06_delivery_plan.md`).

---

## 6. Core subsystems

### 6.1 Library (study corpus)

*Purpose:* parse any source once, reuse without re-parsing — while keeping
evidence, interpretation and acceptance as separate, versioned layers.

- `sources` — an immutable document (protocol, amendment, SAP, FDA review,
  publication, registry record) with origin (`upload`, `dropbox_link`,
  `s3_link`, `url`), sha256, page count, text-layer status, OCR status, and a
  **document classification** (public / confidential) that controls which
  model providers may see its text (§7).
- `extraction_runs` — one per (source, parser version, prompt version, OCR
  version). Produces `source_assertions` (typed claims with page/bbox, source
  wording, evidence state: observed / redacted / not_reported / extraction
  failed). Re-running a newer parser creates a new run; nothing is
  overwritten.
- **Reconciliation gate** — competing assertions across a package (protocol +
  amendments + SAP + results) are shown side by side; a reviewer accepts a
  scoped value (region/cohort/version). A later SAP never auto-overwrites the
  protocol; actual enrolment never replaces planned N (R21).
- `studies` — a trial (NCT id / sponsor id), indication, phase, sponsor, and
  the **accepted study record**: a `protocol_model.schema.json` document with
  `document_kind: "analysis"` assembled from accepted assertions, plus
  `historical_analysis_records` (§6.7) for results.
- Parsing pipeline (worker): fetch → classify → recover structure → extract
  → normalise → **write run outputs (canonical JSON + Markdown) to S3**, index
  in Postgres. Opening a study reads the accepted record; it never re-parses
  unless a reviewer requests a new run.
- **Indication master sheet** = a materialised view over `studies` ×
  `endpoints` × `outcomes` for one indication (e.g. Atopic dermatitis):
  trials, arms, N, endpoints measured, timepoints, key results, source links.
  Exportable to XLSX.
- Upload tool accepts URL, PDF, Markdown, or **Excel** (a results sheet mapped
  to the outcomes schema via a column-mapping step; the LLM proposes the
  mapping, the user confirms).

### 6.2 Workspace and editor

- `trial_definitions` (the shared model) → `works` (a **protocol** or **SAP**
  artifact over that definition, each with its own versions, approvals and a
  `depends_on_version` link — an SAP v1.0 is bound to protocol v2.0) →
  `versions` (immutable) → one `draft` (live) per work.
- Draft = Yjs document whose top-level structure is the 15-node outline
  (Section 0 title/identity + M11 sections 1–14) and whose paragraphs are
  typed blocks: `narrative`, `list`, `definition`, `table`, `figure`, `rule`,
  `reference`, `generated` (synopsis, schema, SoA — read-only views).
- Every block carries four **independent** state dimensions (they are not
  collapsed into one badge): `provenance` (`author | inherited | derived |
  proposed | source` — immutable, records origin), `approval` (`unreviewed |
  approved(by, at, revision) | rejected`), `validation` (per-revision result of
  the checks that touched it: `pass | findings | unrun | stale`), and
  `applicability` (`applies | not_applicable(reason) | not_carried_over`).
  Plus `bindings` (model entity ids) and `claims` (see 6.3).
- Inspector pane shows, for the selected block: bound objects, source
  evidence (page thumbnails), validation findings, comments, history.
- Section header shows completion (see 6.5) and blocking findings count.

### 6.3 Model and claims

- The trial model is the toolkit schema (`protocol_model.schema.json`),
  persisted as JSONB per draft and per version; `packages/model` generates
  Pydantic classes from it so the API rejects *structurally* invalid models
  (structure only — clinical correctness is the job of rules and reviewers).
- **Claims** are sentence-level metadata anchored to text by Yjs relative
  positions (so they survive concurrent edits): `{block_id, anchor,
  claim_type, target: {entity_id, field}, value, unit, modality, scope,
  condition?, exceptions?, extraction: deterministic|llm, rationale,
  state}`. Deterministic extractors handle numbers, units, weeks/days, ratios,
  thresholds, identifiers; the LLM proposes typed claims (with the anchor,
  scope and interpretation rationale) for the rest. The rule engine compares
  claims to model values — this is the "meta-data that checks every sentence".
- Claim `state` is always visible: `checked` (matches model), `mismatch`
  (finding), `unbound` (no target yet), `ambiguous` (extractor could not
  decide; needs a human), `unsupported` (claim type not checkable), `stale`
  (text changed since interpretation). Prose that has not been interpreted is
  shown as *unbound*, never as passing.
- Changing a model value marks all dependent blocks/claims `needs_review`
  (R22 change impact) and highlights them in the outline rail.
- Schema governance: the application owns a `schema_version`; migrations are
  code; **draft-tolerant validation** allows incomplete entities to be saved
  (missing fields become `incomplete` findings), while *approval* and
  *version freeze* require full validity.

### 6.3a Edit and commit contract (single authoritative model)

The **model is authoritative**; the document is derived where it can be and
annotated where it cannot. Rules:

1. Every change is a **command** (`set_field`, `add_entity`, `link`,
   `edit_narrative`, `insert_proposal`, `approve`, `mark_na`, `freeze_version`
   …) applied to a `revision` (monotonic per work). Findings, proposals,
   claims and rendered artifacts record the revision they were computed
   against; results for an older revision are rejected/marked stale, never
   applied.
2. Generated/derived text (synopsis, SoA, endpoint tables, numeric spans bound
   to the model) is edited **through the model**, not the prose.
3. Free narrative edits never silently change an approved model value. If a
   narrative edit introduces a claim that conflicts with the model, the result
   is a `mismatch` finding with two actions: *Update model* (a command, with
   R22 impact) or *Revert text*.
4. Semantic edits use optimistic concurrency (`expected_revision`); two
   authors changing the same entity field get a conflict card, not a silent
   last-writer-wins.
5. **Insert proposal** ≠ **Approve**. Accepting an LLM suggestion inserts a
   `proposed` block/value that still needs approval by a user with the right
   role. Provenance remains `proposed` forever; approval is recorded on top.
6. `freeze_version` is atomic: text, model, claims, findings, overlay, source
   and template versions, render engine version and artifact hashes are
   captured together (see 03 §5).

Test that must pass before Pilot A ships: a Week-16 proposal computed at
revision 41 arrives after the endpoint moved to Week 24 at revision 42 → the
proposal is shown stale and cannot be applied.

### 6.4 Validation engine

- Rule plugins implement `check(model, draft, context) -> Finding[]` with
  `severity ∈ {error, warning, incomplete, info}`, `scope`, `targets`,
  `explanation`, `suggested_fix?`, `needs_adjudication`.
- Catalogue = `reference/validation_rules.json` (R01–R22). Deterministic rules
  (arithmetic, IDs, chronology, schedule coverage, dose calendar,
  dependency graph) run on every model change (<1 s budget, incremental).
  Classification is by *check type in the catalogue*, not by rule number:
  deterministic and conditional-completeness checks (most of R01–R12, R16,
  R21's planned-vs-actual guard, R22 change impact) run inline; semantic
  checks (R13 observed-vs-analysis interpretation, R14 sensitivity vs
  supplementary intent, R20 provenance adoption, and any LLM-suggested
  conflict) run in the worker and produce **candidate** findings that a human
  accepts or dismisses. Every finding records the revision it was computed
  at; findings from older revisions display as *stale* until re-run.
- Grammar checks: each block type has an authoring grammar (spec §"Grammar").
  A `rule` block must have scope, modality, trigger, action, owner; an
  `endpoint` needs measurement, transform, time reference, aggregation. Missing
  slots → `incomplete` findings, which feed completion.
- Findings are stored, diffed between versions, and exported as a
  **validation report** appended to exports (optional).

### 6.5 Completion and readiness

Per section: `% = filled_required_slots / applicable_required_slots`, where
conditional headings/slots marked "Not applicable — reason" leave the
denominator and `proposed`/`unreviewed` values do not count as filled. The
denominator (what counts) is shown next to the number. Findings are **not**
blended into the percentage; they are shown beside it ("64% · 9 items · 2
blocking").

The three milestones from the spec are **predicates**, evaluated at the
current revision, not error counts:

- *Design-ready*: objectives, populations, paths, endpoints and estimands
  present and approved; R01/R02/R12 pass.
- *Operationally specified*: schedules, interventions, rescue, safety and
  follow-up rules approved; R04–R11, R17, R18 pass; no `ambiguous` claims in
  §6–§9.
- *Ready for formal review*: all checks **run at this revision** (none unrun
  or stale); all `error` findings resolved; all candidate findings
  adjudicated; required external dependencies (IB, manuals, SAP version)
  present or explicitly waived by a named reviewer; every `unresolved`
  decision has a disposition (answered / deferred-with-owner); applicability
  reviewed for every conditional heading.

The UI always links a percentage to the list of what remains. Never a bare
number.

### 6.6 Starter → Template → Protocol pipeline (the "intelligent replacement")

```
Starter (library study or uploaded protocol)
  │  1. SPLIT      structure recovery → map source headings to outline 0–14 (LLM proposes, deterministic
  │                 heuristics from bookmarks/numbering; user confirms unmapped sections)
  │  2. BIND       extract assertions → model objects; every block gets bindings + source pages
  │  3. ADAPT      for a target DrugProfile (molecule, class, MoA, route, regimen, known risks, IB facts):
  │                 per block, LLM (structured) classifies KEEP / ADAPT / DROP / ADD-CANDIDATE with rationale,
  │                 constrained by bindings (a block bound to product:X and mechanism-specific safety
  │                 cannot be "kept" for a drug of another class). Output = proposed blocks, never accepted.
  │  4. ASK        build the DECISION REGISTER: every applicable decision (from the spec's 12 decision
  │                 packages + block-level unresolved items) gets a decision_id, scope and status
  │                 (answered / inherited(reviewed) / derived(by rule) / open). Open decisions → typed
  │                 questions (choice / value / free / upload).
  │  5. GROUP      one LLM-assisted pass groups questions that share an information source into
  │                 fewer prompts and orders them by dependency. Grouping changes PRESENTATION only:
  │                 every decision_id must still map to an answer, a reviewed inherited value or an
  │                 executable derivation (coverage check is deterministic and blocks if violated).
  │                 Further iterative minimisation is added only after measuring answer burden vs
  │                 coverage on real conversions.
  │  6. ANSWER     user answers the grouped set (the "key inputs" form); answers become
  │                 author-supplied model values; ADAPT re-runs only on affected blocks
  ▼
Template (starter_id + class profile + accepted mapping + block decisions + decision register
          + source/module versions) — saved, reusable
  ▼
New Work (draft) — instantiated from Template; applicability RE-EVALUATED for the new study
```

Templates are shared library objects, so the second user who picks the same
starter skips SPLIT/BIND and reuses the accepted mapping and block decisions.
But **study-specific decisions are never inherited silently**: population,
jurisdictions, background/rescue policy, estimands, follow-up, analysis
framework and oversight are re-asked (pre-filled with the template's answer
and marked `inherited — confirm`), and any decision whose inputs or source
module versions changed is invalidated. Dropped source blocks under a fixed
M11 heading become *"Not carried over — review required"* until a reviewer
marks them not applicable with a reason.

### 6.7 Trial calculator and endpoint explorer

- **Historical analysis record** (what the library stores per result, so
  results are comparable before they are compared): study, arm, population,
  background therapy / rescue policy, instrument + version, endpoint algorithm
  (transform, threshold, timepoint, baseline definition), estimand / event
  handling, analysis set, estimator, denominator, estimate + uncertainty
  measure, source page, review state.
- Inputs: endpoint (binary responder e.g. EASI-75 / continuous e.g. EASI CFB,
  %CFB / NRS ≥4-point), timepoint, comparator assumption — chosen from
  reviewed historical records that match explicit **comparability criteria**
  (the user sees which records were included/excluded and why), anticipated
  effect, α (1- or 2-sided), power, allocation ratio, dropout, multiplicity.
  Pooling across studies is an explicit, recorded choice with a
  heterogeneity display (between-study spread shown separately from
  within-study CI), never a silent default.
- Methods (`packages/stats`, SciPy): two-proportion (normal approx. with
  continuity correction, and exact), two-sample t (pooled / unequal),
  non-inferiority margins later; each formula documented with a reference and
  verified against published tables. Frameworks not supported (Bayesian
  decision rules, precision-based estimation) are stated as unsupported rather
  than forced into α/power fields. Sensitivity grid over ratio, effect,
  dropout.
- **Endpoint explorer** (labelled *exploratory scenario analysis*): given a
  saved, editable *profile* object (e.g. "JAK-like": expected effect per
  endpoint × timepoint with the records it was derived from), compute for
  every endpoint × timepoint the N required for superiority against the
  selected comparator records; present N alongside clinical relevance and
  regulatory-precedent columns (which pivotal trials used it as primary), so
  "smallest N" is not read as "best". Ships after the calculator itself is
  validated (Phase 4b).
- Every number links back to the records, studies and pages that produced it.

### 6.8 Inclusion/exclusion comparator

- Criteria are stored as typed predicates (`criterion` grammar in the spec:
  predicate / all_of / any_of / not / temporally_qualified) with source text.
- Clicking a criterion: find similar criteria across the indication's studies
  (structured match on concept + embedding similarity on text), show them side
  by side with **token-level diff highlighting** of thresholds, time windows,
  instruments, negation and modality.

### 6.9 On-demand reasoning ("Ask")

- Any selection (block, section, finding, criterion, calculator result) has an
  **Ask** action opening a side thread. The user picks a model (from those the
  admin enabled; default per task type), and the request is sent with a typed
  context pack: the selected objects, their bindings, source evidence, the
  relevant model slice and current findings — never the whole document unless
  asked.
- Responses stream in real time. Anything the model proposes as a change is
  rendered as a *Proposal* (Accept / Edit / Reject); plain answers stay in the
  thread. Threads are saved with the work (they are part of the audit trail).
- Built-in prompts ("Explain this finding", "Draft rationale for this choice",
  "Compare with study X", "Rewrite in M11 register") are versioned in
  `packages/llm/prompts/` and appear as chips.
- Same gateway, same logging, budgets and data-class routing rules as
  pipeline tasks (§7).

### 6.10 Auth, permissions, admin

- Google OIDC → session. Access requires an allowlist row (admin-managed).
- Roles: `admin`, `member`. Per-work ACL: `owner | editor | commenter | viewer`;
  works are private to their ACL by default; library is org-wide.
- Admin portal: users and roles, pending access requests, per-work ACL view,
  usage (active users, edits, exports, ingestion jobs, LLM tokens/cost by
  user/work/day/provider), **Models** (add provider → paste API key → test
  connection → enable models → set defaults per task type and per-user
  budgets), audit log (who changed what, when — needed for regulatory work
  anyway).

---

## 7. LLM integration policy

1. **Gateway, not vendor.** `packages/llm` exposes `complete(task, context,
   schema?) ` and `stream(thread, message)`; adapters implement a small
   interface (`chat`, `structured`, `stream`, `count_tokens`, `price`).
   Adapters in Phase 1: OpenAI (Responses API; default `gpt-6-astra`, verified
   on the org key), xAI Grok, Anthropic, Muse, and a generic
   OpenAI-compatible adapter (covers most others). Adding a vendor = one
   adapter file + a price table entry.
2. **Admin-managed providers.** `model_providers(id, vendor, label, base_url,
   encrypted_api_key, enabled, approved_data_classes)` and `models(id,
   provider_id, model_id, label, caps: {structured, streaming, context},
   price_in, price_out, enabled)`. Keys are encrypted with a server-side key
   (KMS-backed on AWS), shown once, testable ("Test connection") and
   rotatable. Adapters are **capability-tested** on connection (structured
   output, streaming, refusal shape) rather than assumed. The `OPENAI_API_KEY`
   env var seeds the first provider on first boot so the pipeline works before
   anyone opens Admin. Phase 1 ships OpenAI + a generic OpenAI-compatible
   adapter; further vendors are added once the customer approves them.
3. **Fail-closed data routing.** Every source, work and library document has
   a data class (`public`, `confidential`, `restricted`). A provider may
   receive text of a class only if the admin has explicitly approved that
   provider for that class. The check runs **server-side** on every call —
   including fallbacks, Ask context packs, source snippets and log payloads —
   and denies by default. Provider base URLs are allow-listed by the admin
   (SSRF protection), as are ingestion URLs (Dropbox/S3/https only, no
   private ranges).
4. **Routing.** Each task type (split, adapt, group, claims, review,
   ask-default) has an admin-set default model and an optional fallback.
   Structured pipeline tasks may only route to models with `caps.structured`.
5. Every task has a versioned prompt file and a JSON Schema for the output.
   Outputs enter the system only as `proposed` values or `candidate` findings.
   Every call logs: task, prompt version, provider, model, input/output
   tokens, cost, latency, work id, user id, revision. Surfaces in the admin
   usage view.
6. Cost guardrails: per-user and per-provider daily budgets
   (admin-configurable); long-document tasks are chunked by section with a
   map-reduce summary.
7. Source text sent to a vendor is the customer's own corpus; no third-party
   copyrighted full text is retained by us beyond the parsed cache. (Flag for
   the user: confirm data-handling terms per vendor for regulated content;
   the admin can restrict which providers may receive protocol text.)
8. Development use: Astra is also used as a **reviewer** of these design docs
   and of code (see `05_decisions.md` ADR-009) via `tools/astra_review.py`,
   so its critiques are reproducible and logged. The first such review
   (`docs/reviews/20260906-astra-phase0-docs.md`) shaped §6.1, §6.3a, §6.5,
   §6.6, §6.7 and §7 of this document.

---

## 8. Data model (relational skeleton)

```
users(id, email, name, picture, role, created_at, last_seen_at)
allowlist(email, added_by, added_at, note)
trial_definitions(id, indication, title, data_class, schema_version, created_at)
works(id, trial_definition_id, kind: protocol|sap, title, owner_id, template_id?, depends_on_version_id?, created_at)
work_acl(work_id, user_id, level)
revisions(work_id, revision, command_jsonb, actor_id, created_at)          -- append-only command log
versions(id, work_id, label, revision, model_jsonb, render_ast_jsonb, overlay, source_versions_jsonb,
         render_engine, artifact_hashes_jsonb, unresolved_dispositions_jsonb, created_by, created_at, notes)
drafts(work_id PK, yjs_state bytea, model_jsonb, revision, updated_at)
decisions(id, work_id, decision_id, scope_jsonb, status: answered|inherited|derived|open, answer_jsonb, reviewer_id, revision)
autosave_snapshots(id, work_id, s3_key, created_at)
blocks(id, work_id, section_id, order, type, provenance, approval_jsonb, applicability_jsonb)  -- materialised from Yjs for queries
bindings(block_id, entity_type, entity_id)
claims(id, block_id, anchor_jsonb, type, target_entity_id, target_field, value_jsonb, unit, modality, scope_jsonb, state, extraction, rationale, revision)
findings(id, work_id, revision, rule_id, severity, targets_jsonb, message, state, adjudicated_by)
sources(id, origin, uri, s3_key, sha256, kind, pages, text_layer, ocr_status, data_class, status)
extraction_runs(id, source_id, parser_version, prompt_version, ocr_version, outputs_s3_key, created_at)
source_assertions(id, run_id, target_entity, field, value_jsonb, source_text, page, bbox, evidence_state, scope_jsonb, normalisation_rationale, review_state, accepted_by?)
studies(id, indication, registry_id, sponsor, phase, title, accepted_record_s3_key, model_jsonb)
historical_analysis_records(id, study_id, arm, population_jsonb, background_rescue_jsonb, instrument, instrument_version,
         endpoint_algorithm_jsonb, timepoint, estimand_jsonb, analysis_set, estimator, n_denominator, estimate,
         uncertainty_jsonb, unit, source_assertion_id, review_state)
criteria(id, study_id, kind: inclusion|exclusion, text, predicate_jsonb, concept_tags, embedding vector)
templates(id, starter_study_id, drug_class_profile_jsonb, mapping_jsonb, questions_jsonb, created_by)
model_providers(id, vendor, label, base_url, encrypted_api_key, enabled, allow_protocol_text, created_by)
models(id, provider_id, model_id, label, caps_jsonb, price_in, price_out, enabled, is_default_for jsonb)
ask_threads(id, work_id, user_id, context_jsonb, model_id, created_at) ; ask_messages(id, thread_id, role, content, proposal_jsonb?)
llm_calls(id, task, prompt_version, provider_id, model_id, in_tokens, out_tokens, cost_usd, ms, user_id, work_id, created_at)
audit_log(id, actor_id, action, entity, entity_id, diff_jsonb, created_at)
jobs (procrastinate tables)
```

---

## 9. Deployment (EC2 + S3)

- One EC2 instance (start: t3.large / 8 GB — Tectonic and OCR need memory),
  Ubuntu 24.04, Docker Compose: `caddy`, `web` (static), `api`, `worker`,
  `postgres` (EBS volume), nightly `pg_dump` to S3.
- S3 bucket (private, SSE-S3, versioning on): `sources/`, `parsed/`,
  `exports/`, `snapshots/`, `backups/`. Presigned URLs for downloads.
- IAM: instance role limited to that bucket; no long-lived keys on the box.
- GitHub Actions: `ci.yml` on PR (ruff, mypy, pytest, eslint, tsc, vitest,
  Playwright smoke); `deploy.yml` on main → build images → push to ECR →
  SSM `docker compose pull && up -d`.
- Secrets on the host via SSM Parameter Store: `OPENAI_API_KEY` (seed only),
  `GOOGLE_CLIENT_ID/SECRET`, `SESSION_SECRET`, `DATABASE_URL`,
  `PROVIDER_KEY_ENCRYPTION_KEY` (KMS-wrapped; encrypts admin-entered vendor
  keys at rest).
- Requires from the user: AWS account access (or an IAM user scoped to
  EC2/S3/SSM/ECR), a domain (for Google OAuth redirect and TLS), and a Google
  OAuth client. Listed in `05_decisions.md`.

---

## 9a. Security and operations controls (added after Astra review)

- Authorization boundaries and audit events are built into persistence and
  job execution from the first pilot (dev-login stub, real roles) — not
  retrofitted with SSO.
- Ingestion and rendering run in the worker container with no inbound
  network, CPU/memory/time limits, and outbound egress restricted to the
  allow-listed fetch hosts and approved model providers. Tectonic uses a
  **pinned bundle** baked into the image; release compilation never fetches.
- Backups: nightly `pg_dump` + S3 object versioning; **RPO 24 h, RTO 4 h**
  targets; restore is rehearsed in CI monthly against a scratch instance.
- Audit log is append-only, readable by admins only, retained 7 years
  (configurable); revocation of a user invalidates sessions immediately.
- Exporting to DOCX is a boundary: the export carries a manifest (revision,
  hashes). Edits made in Word are outside the consistency guarantee; the
  intended workflow is to re-import decisions as model commands, not to
  round-trip prose (asked as Q18).

## 10. Non-goals for Phase 1 (explicit)

- Not claiming ICH M11 *conformance*; we pin to the Nov-2025 template
  structure (`reference/ich_m11_outline.json`) and label it as such.
- No crossover / platform / adaptive design modules; no non-AD therapeutic
  modules (extensions later, per spec).
- No automated acceptance of LLM output; no "auto-fix" of clinical content.
- No offline mode; no mobile layout beyond read-only.
