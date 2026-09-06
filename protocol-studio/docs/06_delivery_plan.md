# Protocol Studio — Delivery Plan (pilots, previews, checkpoints)

Estimates are in Devin sessions (one session ≈ a focused multi-hour build with
tests and a PR). External waits (AWS access, OAuth client, corpus links) are
listed separately because they, not build time, drive the calendar.

| Phase | Deliverable | Preview for Ben | Sessions | External dependency |
|---|---|---|---|---|
| **0** | Architecture, visual language, domain model, walkthroughs, clickable mock (this PR) | Static mock in browser | this one | Answers to Q1–Q11 |
| **1** | **Pilot A — Model + Editor + Export (single writer).** Monorepo scaffold, CI, `packages/model` (Pydantic from schema, schema_version, outline), **edit/commit contract** (commands, revisions, stale rejection), roles + ACL + audit log from day one (dev-login stub), `packages/rules` deterministic set, editor with 0–14 outline, blocks with 4 state dimensions, claims with visible states, completion + readiness predicates, findings inspector, versions (atomic freeze) + autosave, Render AST → LaTeX PDF + DOCX with golden-file diffs | Local preview: create work, edit, see findings/completion, export PDF/DOCX | 2 | Tectonic (pinned bundle)/Tesseract in env (blueprint) |
| **2** | **Pilot B — Library + Evidence lifecycle.** Sources (upload/URL/Dropbox/S3 with host allow-list), PyMuPDF + OCR, structure recovery, extraction runs + source assertions with page anchors and evidence states, **reconciliation gate**, accepted study records, historical analysis records, master sheet, Excel import; adjudicated fixtures from the attached protocols (amendment-corrects-ECG, protocol-vs-SAP rescue conflict) | Ingest the 4 attached protocols + 2 public FDA reviews; adjudicate a conflict; browse master sheet | 2 | Corpus links (Q5), results Excel (Q7), benchmark docs (Q16) |
| **3** | **Pilot C — Starter→Template→Protocol + Ask.** Model gateway (OpenAI + capability-tested OpenAI-compatible adapter), fail-closed data-class routing, Split/Bind/Adapt pipeline, **decision register** with coverage check, one grouping pass, key-inputs form, Proposal (Insert ≠ Approve), template save/reuse with applicability re-evaluation, Ask threads with streaming + visible context pack, semantic candidate rules, SAP artifact if Q10 says yes | Convert temtokibart P2b to a new anti-OX40L drug end-to-end | 2 | Vendor list (Q11), data-class approval (Q9) |
| **4a** | **Pilot D — Calculator + Comparator.** `packages/stats` verified against published tables, comparability filter, explicit pooling with heterogeneity display, sensitivity grid, criteria predicates + similarity + diff | Power an EASI-75 trial; compare I/E criteria | 1 | Reviewed historical records (Phase 2) |
| **4b** | **Endpoint explorer** (exploratory): saved profile objects ("JAK-like"), endpoint×timepoint N alongside precedent + relevance columns | Explore endpoints for a JAK-like profile | 1 | Q15 answered |
| **5** | **SSO + Collaboration + Admin.** Google OIDC, allowlist, Yjs multi-user on top of the proven edit contract, presence, comments, admin portal (users, works, usage, models/keys/data classes, audit) | Two accounts editing together; admin adds a Grok key | 1–2 | Google OAuth client (Q4), domain (Q3) |
| **6** | **Deploy.** EC2 + S3 + Caddy + Compose, sandboxed worker, GitHub Actions deploy, SSM secrets, backups with rehearsed restore, runbook | Live URL | 1 | AWS access (Q2) |
| **7** | Hardening: validation report export, amendment diff, USDM export, second indication, e-signature if Q12 requires | — | ongoing | — |

Checkpoints: after every pilot a preview + a short list of decisions; Astra
review runs on every PR (`tools/astra_review.py`), its findings attached to the
PR as a comment for the human reviewer.

## Acceptance gates (what "done" means before the next phase starts)

Session counts above are effort; **gates** decide progression:

- **Gate A** (after Pilot A): the stale-proposal test passes (Week-16 proposal
  at rev 41 rejected after Week-24 change at rev 42); a narrative edit that
  contradicts the model yields a `mismatch` finding, never a silent model
  change; PDF and DOCX golden diffs match; readiness predicate lists its
  failing clauses.
- **Gate B** (after Pilot B): on the benchmark set (Q16) — evidence-location
  accuracy (page correct) ≥ 95 %; threshold/negation preserved in extracted
  criteria ≥ 95 %; the amendment and protocol-vs-SAP fixtures produce
  competing assertions, not overwrites; OCR confidence surfaced per page.
- **Gate C** (after Pilot C): end-to-end adjudicated case — source assertion →
  accepted model → conditional SoA/estimand → exported document → semantic
  amendment diff; decision coverage 100 % (every decision_id has an answer,
  reviewed inheritance or executable derivation); conflict-finding precision
  and recall measured against the adjudicated set with agreed acceptable
  false-positive rate; no confidential text reached an unapproved provider
  (audit query).
- **Gate D** (after 4a): sample sizes match published reference tables within
  tolerance; every displayed historical number resolves to a reviewed record
  and page.

## Definition of done (per package)

- README current (purpose, interface, invariants, how to test).
- Unit tests; rules have positive + negative fixtures.
- `ruff`, `mypy --strict`, `eslint`, `tsc` clean.
- No LLM output enters the model without `proposed` status.
- Every number rendered in UI has a provenance link.

## Testing strategy

| Layer | Tool | What |
|---|---|---|
| Model | pytest + jsonschema | schema validation, ID uniqueness, link integrity, fixtures from `reference/protocol_examples.json` |
| Rules | pytest | each rule: fixture that must trigger, fixture that must not; regression cases from the spec (EASI direction, amendment corrections, mixed IE strategies) |
| Render | pytest + Tectonic in CI | AST → LaTeX compiles; heading numbering equals M11 outline; DOCX heading styles; golden-file diffs |
| Stats | pytest | sample-size against published tables (e.g. Fleiss, PASS examples) within tolerance |
| Ingest | pytest | structure recovery on the text-layer PDFs; OCR path on an image page; page anchors round-trip |
| LLM | pytest with recorded responses (VCR) | schema conformance of outputs; minimisation converges; no acceptance without human action |
| API | pytest + httpx | auth, ACL denial, versioning, autosave |
| UI | Vitest + Playwright | outline navigation, block editing, findings jump, export flow, admin models CRUD |
