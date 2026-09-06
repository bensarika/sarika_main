# Protocol Studio — Decisions (ADRs) and Open Questions

## Architecture decision records

| ADR | Decision | Reasoning | Alternatives rejected |
|---|---|---|---|
| ADR-001 | Model-first; document is a rendered view | Cross-section consistency and honest completion are impossible otherwise (see 01 §2) | Prose-first with LLM checker |
| ADR-002 | Adopt toolkit `protocol_model.schema.json` as persisted model | Already expresses estimands/rescue/paths/provenance; spec-validated on AD corpus | Bespoke schema; CDISC USDM as primary (kept as export target) |
| ADR-003 | 14 M11 sections + Section 0 as title/document control | Matches both the brief ("14") and the outline (0–14); M11 says front matter is not a numbered section | 15 numbered sections |
| ADR-004 | Python/FastAPI backend + worker; React/TS frontend | Scientific + PDF + LaTeX stack lives in Python; UI needs a rich editor | Full TypeScript stack |
| ADR-005 | PostgreSQL with JSONB model + materialised link tables | Spec: relational is sufficient; JSONB tolerates schema evolution | Graph DB; fully normalised 30-table schema |
| ADR-006 | Yjs CRDT collaboration with server persistence; autosave snapshots to S3 | Conflict-free multi-author editing; update log doubles as history | Lock-based editing; OT |
| ADR-007 | Render AST → LaTeX (Tectonic) for PDF and python-docx for DOCX | User requires LaTeX; identical content in both outputs | Pandoc conversion; HTML→PDF |
| ADR-008 | LLM pipeline tasks only via structured outputs; outputs are `proposed`; all calls logged | Regulatory auditability; cost attribution | Free-text prompting; auto-accept |
| ADR-013 | Provider-agnostic model gateway; providers/models/API keys managed in Admin (encrypted at rest); per-task default routing; on-demand streaming "Ask" threads saved with the work | User requirement (OpenAI, Grok, Muse, others); avoids lock-in; keeps reasoning auditable | Single hard-coded vendor; keys in env only; unlogged chat sidebar |
| ADR-009 | `gpt-6-astra` as coding/reasoning agent through a repo script (`tools/astra_review.py`) that reviews docs/PRs with logged prompts | User requirement; makes Astra's contribution reproducible rather than ad hoc | Manual copy-paste into ChatGPT |
| ADR-010 | Single EC2 + Docker Compose + S3, Caddy TLS, GitHub Actions deploy | Smallest footprint that meets "EC2 + S3"; upgrade path to RDS/ECS is code-free | ECS/Fargate day one; serverless |
| ADR-011 | OCR (Tesseract) as mandatory ingestion fallback with per-page confidence | Half the supplied corpus is image-only | Reject image PDFs |
| ADR-012 | Code lives in a `protocol-studio/` folder of `bensarika/sarika_main` for Phase 0; recommend a dedicated repo before Phase 1 | Only repo Devin can access today; a dedicated repo gives clean CI/deploy and secrets scope | — (see Q1) |
| ADR-014 | **Decided (Q1):** code stays in `sarika_main/protocol-studio` | Ben's call; one repo to watch | Dedicated repo |
| ADR-015 | **Decided (Q2):** deploy with a scoped IAM user `devin-deployer` (policy `DevinProtocolStudioDeploy`: S3 `protocol-studio-*`, EC2/SSM, KMS, logs, ACM/Route53); credentials are org secrets `AWS_DEPLOYER_ACCESS_KEY_ID` / `AWS_DEPLOYER_SECRET_ACCESS_KEY`. Root access keys must not be used | Least privilege; rotation without touching the root account | Root key; bootstrap script run by Ben |
| ADR-016 | **Decided (Q3+Q4):** hostname `studio.sarika.com`; Google Sign-In via GCP project `protocol-studio` (org `sarika.com`), Auth Platform audience **Internal** (only `@sarika.com` Workspace accounts can complete sign-in; the app's own allowlist decides *authorisation*). Web client `Protocol Studio web (studio.sarika.com)`: origins `https://studio.sarika.com`, `http://localhost:8080`; redirect URIs `https://studio.sarika.com/auth/google/callback`, `http://localhost:8080/auth/google/callback`. Client id/secret are org secrets `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET`; never in source. The console is operated by the service account `devin@sarika.com` (password + authenticator seed held as Devin secrets) | Internal audience removes the consent-screen verification step and blocks personal Gmail accounts outright; the backend route `/auth/google/callback` is now a contract | External audience + test users; per-email-only allowlist with no domain gate |

## Open questions for Ben (answers unblock Phase 1)

| # | Question | Why it matters | Default if no answer |
|---|---|---|---|
| ~~Q1~~ | *Answered → ADR-014.* **Repository:** keep `protocol-studio/` inside `sarika_main`, or create `bensarika/protocol-studio` and grant Devin access? | CI/CD, secrets and deploy workflows are per-repo | Stay in `sarika_main` |
| ~~Q2~~ | *Answered → ADR-015.* **AWS access:** an IAM user/role for Devin scoped to EC2, S3, SSM, ECR (I'll send the exact policy), or you run the bootstrap commands I provide? | Needed only for deployment (Phase 4), not for pilots | Pilots run locally with preview links; deploy later |
| ~~Q3~~ | *Answered → ADR-016.* **Domain:** which hostname (e.g. `protocol.sarika.com`)? DNS managed where? | Google OAuth redirect URI and TLS both need it | Temporary EC2 public DNS; OAuth restricted to it |
| ~~Q4~~ | *Answered → ADR-016.* **Google OAuth client:** you create it in Google Cloud Console (5 min, instructions provided) and store client id/secret as Devin secrets, or I do it with access to your Google Cloud project? | SSO cannot work without it | Dev-only local login stub behind a flag; SSO wired when credentials arrive |
| Q5 | **Corpus location:** do the FDA reviews / protocols / SAPs already sit in a Dropbox folder or S3 bucket? Link(s)? | Library pilot should ingest your real corpus, not just the 4 attached protocols | Start with the attached protocols + public FDA reviews for AD drugs |
| Q6 | **Indications:** AD first (per toolkit). Any second indication to keep the model honest (e.g. psoriasis, asthma)? | Avoids AD-specific assumptions leaking into the general model | AD only in Phase 1 |
| Q7 | **Historical outcomes:** do you already have an Excel of trial results (EASI-75, EASI-90, NRS etc. by drug/timepoint)? | Seeds the calculator immediately; otherwise extracted from PDFs first | Extract from attached + public sources |
| Q8 | **Users at launch:** roughly how many, and are they all on Google Workspace (`@sarika.com`) or mixed personal Google accounts? | Allowlist policy: domain-wide vs per-email | Per-email allowlist |
| Q9 | **Model-provider data handling:** which providers may receive which data classes (public library docs / your confidential protocols, IBs, SAPs / restricted)? OpenAI API data is not used for training by default, but zero-data-retention needs an enterprise agreement. | Compliance | **Fail closed**: only `public` data goes to any provider until you approve a provider for `confidential` in Admin |
| Q11 | **Model vendors at launch:** OpenAI is seeded. Which others should be wired in Phase 1 (Grok/xAI, Anthropic, Google Gemini, Muse — please share Muse's API docs/base URL)? Keys can be added later in Admin. | Each vendor is one adapter; Muse is unknown to me and needs its API reference | OpenAI + generic OpenAI-compatible adapter (covers many vendors incl. xAI) |
| Q10 | **SAP scope in Phase 1:** shared trial definition with the SAP as a separately versioned artifact (recommended) — do you need SAP authoring in Phase 1 or only the protocol? | Effort | Protocol first; SAP artifact in Phase 3 |
| Q12 | **Regulated use:** is this a drafting aid (approval happens in your existing document system) or the authoritative system of record for approved protocols/SAPs (implies validation, e-signature, retention requirements)? | Shapes approval workflow, audit and retention design | Drafting aid with full audit trail; e-signature deferred |
| Q13 | **Who approves what:** must clinical, statistical, safety and operational decisions have designated reviewers? May an author approve their own change? | Role model and approval records | Roles: author, statistician, medical, admin; self-approval allowed but flagged |
| Q14 | **Template inheritance:** is starter reuse mostly within a program, within a molecule, or across mechanisms? Which decision packages must always be reconfirmed? | Controls what a template may pre-fill silently | Study-specific packages always re-asked (pre-filled) |
| Q15 | **"Best endpoint/timepoint" definition:** lowest N, clinically meaningful effect, regulatory-claim suitability, operational burden, or a weighting? Who approves historical comparability/pooling? | Endpoint explorer semantics | Show N + precedent + relevance side by side; statistician approves pooling |
| Q16 | **Benchmark for acceptance:** nominate 2–3 protocols/SAPs with known inconsistencies, acceptable false-positive rate for findings, and who adjudicates | Defines the Phase-1 acceptance gate | The 4 attached protocols; Ben adjudicates |
| Q17 | **Concurrent amendments:** do regional/site amendments run concurrently in your programs? | Overlay/version model | Single global version + regional overlays |
| Q18 | **After DOCX export:** do authors edit in Word and need changes brought back, or does export end the app's guarantee? | Round-trip scope | Export is terminal; decisions re-entered as model commands |

## Review log

| Date | Reviewer | Output | Disposition |
|---|---|---|---|
| 2026-09-06 | GPT-6 Astra (`tools/astra_review.py`, prompt `review-v1`) | `docs/reviews/20260906-astra-phase0-docs.md` | B1 edit/commit contract → 01 §6.3a; B2 decision register + no silent inheritance → 01 §6.6; B3 evidence lifecycle + reconciliation gate → 01 §6.1, 03 §6; B4 historical analysis records, comparability, exploratory label → 01 §6.7, 04 S6; B5 four state dimensions + readiness predicates → 01 §6.2/§6.5, 02 §2, 03 §4; B6 fail-closed data routing, SSRF, sandboxing → 01 §7/§9a, Q9; gaps: schema governance, SAP artifact, claim states, rule classification, security-from-start → 01 §6.2/§6.3/§6.4, 03 §1; simplifications: 2 adapters first, single-writer pilot, one grouping pass, explorer deferred to 4b, "guarantee" wording removed → 01, 06; customer questions → Q12–Q18 |

## Recommendations (not blocking)

- Create the dedicated repo now; moving later costs a `git subtree split`.
- Use a Google Workspace domain-wide allowlist (`@sarika.com`) plus per-email
  exceptions — least admin work, still explicit.
- Budget one EC2 `t3.large` (~$60/mo) + S3 (< $5/mo) + OpenAI usage
  (structured passes over a 200-page protocol ≈ 300–500k input tokens per
  full Split+Adapt run; the template cache makes repeat runs near-zero).
