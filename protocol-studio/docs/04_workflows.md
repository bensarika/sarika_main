# Protocol Studio — Usage Walkthroughs (against the Phase-0 mock)

Each scenario was "played" against `mock/index.html` before any executable code
was written, as the brief requires. For each: the path a user takes, what the
mock showed, and what it exposed (design changes made as a result). Scenarios
marked ✱ changed the design.

## S1 — New protocol from a starter (the headline flow)

**Persona:** medical writer starting a Phase 2b protocol for a new OX40L
antagonist in adult AD, using the temtokibart P2b protocol as starter.

1. Workspace → *New work* → *From starter* → pick "Temtokibart P2b (already
   parsed)" from Library. Enter drug profile: name, class/MoA, route, planned
   regimens, IB facts (upload IB PDF optional).
2. **Split** view: left = source outline (bookmarks), right = 0–14 outline
   with proposed mapping; unmapped source headings are listed at the bottom
   and must be placed or marked "Not carried over".
3. **Adapt** view: per section, blocks in three columns *Keep / Adapt / Drop*,
   plus an *Add* tray of proposals (e.g. mechanism-specific safety monitoring
   for the new class). Each card shows its bindings and a one-line rationale.
   Nothing is accepted yet.
4. **Ask** view: raw question list (e.g. 37) → after 3 minimisation rounds, 11
   questions; each shows "merged from 4" and "depends on 6 blocks".
5. Answer the 11. Draft is created; outline shows completion per section;
   findings inspector shows the first deterministic findings (e.g. R04:
   week-16 EASI required by EP-01 has no scheduled activity because the source
   SoA was image-only and was OCR'd with low confidence).
6. *Save as template* → "Temtokibart P2b → anti-OX40L class" reusable.

✱ Exposed: users need to see *why* a question exists. Added "depends on N
blocks" and a hover list of the blocks to each question card.
✱ Exposed: "Drop" is dangerous if the block held a regulatory-required
heading. Dropping a block under a fixed M11 heading now inserts a placeholder
"Not applicable — <reason>" block rather than deleting the heading.

## S2 — Editing and checking (daily use)

1. Open draft → Section 3 → edit the primary estimand's intercurrent-event
   strategy from "treatment policy" to "composite (rescue = non-response)".
2. Model changes → R22 marks 6 dependent blocks `needs_review` (SoA footnote,
   §6.9.2 rescue therapy, §10.4.1.2 handling of data, synopsis, endpoint
   table, §7.1). Outline shows amber dots on 5 sections.
3. Inspector *Findings* lists the impact; "Go to" jumps; each block offers
   "Regenerate from model" (derived text) or "Keep, mark reviewed".

✱ Exposed: without a global "impact list" users lost track across sections.
Added a *Review queue* pane (top bar chip "6 to review") that persists until
empty.

## S3 — Collaboration and versions

1. Two authors in §5 simultaneously; presence avatars; block-level cursors.
2. Statistician adds a comment on §10.11; author resolves.
3. *Create version v0.2* → dialog shows semantic diff vs v0.1 and open blocking
   findings (2). Versioning is allowed with open findings but the version is
   labelled "draft quality"; *Ready for formal review* is a predicate (all
   checks run at this revision, errors resolved, candidates adjudicated,
   dependencies present or waived, unresolved items dispositioned,
   applicability reviewed) — the dialog lists which predicate fails.
4. Autosave status "Saved 8 s ago"; *History* tab lists snapshots; restore
   creates a new draft branch, never overwrites.

## S4 — Export

1. *Export* → PDF (LaTeX/Tectonic) or DOCX; options: include validation
   report appendix, watermark "DRAFT", region overlay (e.g. EU).
2. Job runs in worker; progress toast; download via presigned S3 URL.
3. PDF shows M11 heading structure exactly; conditional headings not applicable
   render "Not applicable" (M11 rule: retain L1/L2 headings).

✱ Exposed: M11 requires Section 0 (foreword) to be deleted at finalisation
and the title page to carry identity; our Section 0 therefore renders as title
page + document history, never as a numbered section.

## S5 — Library: add a study and view the master sheet

1. Library → *Add study* → paste Dropbox link to an FDA review PDF (or upload
   PDF/MD/XLSX). Job: fetch → sha256 → classify (FDA review) → structure →
   extract → canonical JSON/MD to S3.
2. Study page: parsed sections, arms, endpoints, outcomes table with page
   links; "text layer: none → OCR (confidence 0.83)" badge.
3. Master sheet (Atopic dermatitis): rows per study × arm × endpoint ×
   timepoint; filters; export XLSX.

✱ Exposed: three of the supplied PDFs are image-only. OCR quality must be
visible per page and low-confidence values must be `needs_review`, otherwise
the calculator silently inherits bad numbers.

## S6 — Trial calculator

1. Endpoint EASI-75 @ week 16; comparator = placebo records from the master
   sheet filtered by comparability criteria (moderate-to-severe adults, TCS
   background allowed, NRI handling) — the included/excluded records are
   listed, and *Pool* is an explicit toggle that shows between-study spread
   separately from within-study CI; anticipated active
   rate 60%; α 0.05 two-sided; power 90%; ratio 1:1; dropout 10%.
2. Result: N per arm and total; sensitivity grid ratio {1:1, 2:1, 3:1} ×
   effect {±5 pts}; every historical point links to its study/page.
3. *Endpoint explorer* (labelled exploratory): profile "JAK-like" (derived
   from upadacitinib and abrocitinib records) → table of endpoints ×
   timepoints with N for superiority at 90% power **alongside** regulatory
   precedent (used as primary in which pivotal trials) and clinical-relevance
   notes, so smallest N is not read as "best".

✱ Exposed: "JAK-like" must be an editable, saved *profile object* (expected
effect per endpoint×timepoint with its sources), not a hidden constant.

## S7 — Inclusion/exclusion comparator

1. §5.2 → click criterion "EASI ≥ 16 at screening and baseline".
2. Inspector shows 6 similar criteria across AD studies; token diffs highlight
   `≥ 16` vs `≥ 12`, "screening and baseline" vs "baseline", added "IGA ≥ 3".
3. *Adopt wording* copies as a `proposed` block with source provenance.

## S8 — Admin

1. Admin → Users: allowlist emails (add/remove, role), pending sign-ins.
2. Works & permissions: matrix of works × users × level.
3. Usage: DAU, edits, exports, jobs, LLM tokens/cost by user/work/day.
4. Audit: filterable log.

## S10 — Ask the model (on-demand reasoning)

1. In §10.4.1.2, select the paragraph on handling rescue → *Ask* → model
   picker shows "GPT-6 Astra (default) · Grok 4 · …" (only admin-enabled).
2. Chip "Explain this finding" (R14 sensitivity vs supplementary) → streamed
   answer with citations to the bound estimand and the E9(R1) concept.
3. Follow-up: "Rewrite this paragraph for a composite strategy" → response
   arrives as a *Proposal* card; *Insert* places it as a `proposed` block that
   still needs *Approve* by a role-holder (two distinct actions, two audit
   records); thread saved in the work's *Ask* history and logged with
   tokens/cost/revision.

✱ Exposed: the context pack must be visible — users asked "what did it see?".
Added a collapsible "Context sent" list (objects, pages, findings) to each
thread turn.

## S11 — Admin: add a model provider

1. Admin → Models → *Add provider* → vendor "xAI (Grok)" → paste API key →
   *Test connection* (lists models) → enable `grok-4` → set as default for
   "Ask" only; keep Astra for structured pipeline tasks.
2. Key is stored encrypted, shown masked (`sk-…9f2a`), rotatable. Provider
   starts with **no approved data classes**: the admin ticks `public` and/or
   `confidential` explicitly; until then the server refuses to route any
   customer text (uploads included) to it.
3. Usage tab now breaks down tokens and cost by provider.

## S9 — Access denied path

Non-allowlisted Google account signs in → "Your account is not authorised.
Request access" → admin sees the request in *Pending*.

---

## Cross-cutting findings from the walkthroughs

1. Every LLM output surface needs the same three affordances: **Accept /
   Edit / Reject** + rationale + "Why". Standardised as the *Proposal* component.
2. Completion must link to a *remaining items* list (already in principles;
   the mock made the click target explicit on the bar).
3. Section 1 (Protocol Summary) is generated; users tried to type in it.
   Canvas shows it read-only with "Edit the model in §3/§4/§8 to change this".
4. The calculator's historical data quality drives trust — provenance badges
   on every number were added to the results pane, not just the library.
