# Protocol Studio — Domain Model, Outline and Provenance

## 1. The "14 sections" question — resolved

The brief asked for "14 different sections corresponding to the sections in
your proposed universal outline". The supplied outline
(`reference/canonical_outline.json`) has **15** entries numbered **0–14**, and
the official ICH M11 template (final, 19 Nov 2025; `reference/ich_m11_outline.json`)
has **14 numbered sections (1–14)** plus a title page/document-control front
matter. The two line up one-to-one:

| # | Universal outline (toolkit) | ICH M11 (Nov 2025) |
|---|---|---|
| 0 | Identity and document control | Title page, sponsor/ids, version & amendment history, signatures (front matter — not a numbered M11 section) |
| 1 | Study summary *(generated view)* | 1 Protocol Summary (1.1 Synopsis, 1.2 Trial Schema, 1.3 Schedule of Activities) |
| 2 | Scientific justification | 2 Introduction |
| 3 | Questions and outcomes | 3 Trial Objectives and Associated Estimands |
| 4 | Design and participant paths | 4 Trial Design |
| 5 | Participant selection | 5 Trial Population |
| 6 | Treatments and concomitant care | 6 Trial Intervention and Concomitant Therapy |
| 7 | Discontinuation and continued observation | 7 Participant Discontinuation of Trial Intervention and Discontinuation or Withdrawal from Trial |
| 8 | Assessments and procedures | 8 Trial Assessments and Procedures |
| 9 | Safety events and reporting | 9 Adverse Events, SAEs, Product Complaints, Pregnancy and Postpartum Information, and Special Safety Situations |
| 10 | Statistical specification | 10 Statistical Considerations |
| 11 | Oversight and conduct | 11 Trial Oversight and Other General Considerations |
| 12 | Supporting material | 12 Appendix: Supporting Details |
| 13 | Terminology | 13 Appendix: Glossary of Terms and Abbreviations |
| 14 | References | 14 Appendix: References |

**Decision:** the editor shows the **14 M11 sections** as the user's "14
sections", with **Section 0** as a distinct *Title & document control* panel
above them (it renders as the title page + document history + signature page,
never as "Section 0" in the export). The M11 L2/L3 headings are the
sub-structure of each section; the toolkit's subsection list is used as the
*semantic checklist* (what must be present) mapped onto the M11 headings.
`packages/model/outline.py` holds this mapping; both source files stay in
`reference/` unmodified.

For **SAPs**: protocol and SAP share one *trial definition* (the model) but
are **separately versioned, approved artifacts**; an SAP version records the
protocol version it depends on. The SAP outline follows ICH E9/E9(R1)
principles (analysis sets, estimands, estimators, sensitivity/supplementary,
multiplicity, interim, sample size) plus SAP-only content (derivations,
table shells, programming conventions) stored as SAP extensions of the
definition — E9 provides principles, not a mandated outline, so the SAP
outline is our own and labelled as such.

## 2. The trial model

We adopt `reference/protocol_model.schema.json` (toolkit v0.1.0) as the
*starting point* for the persisted model. The toolkit itself calls it an
application scaffold, not a proven universal schema, so the application owns
its `schema_version`, migrations and any extensions (SAP content, historical
analysis records, data classes). Top-level collections and what they answer:

| Collection | Answers | Central to |
|---|---|---|
| `protocol` | identity, version, amendment, sponsor, phase, regions | §0 |
| `sources`, `assertions`, `collection_status` | where each value came from and its evidence state | provenance everywhere |
| `populations`, `criteria` | who is eligible, cohorts | §5, comparator |
| `products`, `regimens`, `anchors` | what is given, how, when | §6, adaptation |
| `periods`, `paths`, `allocations`, `transitions` | design, arms, branches, rerandomisation, escape | §4, §7, schema figure |
| `assessments`, `encounters`, `scheduled_activities` | SoA | §1.3, §8 |
| `objectives`, `endpoints`, `estimands` | questions and how they are answered | §3, §10 |
| `events` | intercurrent events, rescue events, safety triggers | §3, §6, §7, §9, §10 |
| `analysis_sets`, `analyses`, `testing_families` | statistics | §10, SAP |
| `rules`, `roles`, `governance`, `dependencies` | operational and oversight rules | §6, §7, §9, §11 |
| `unresolved` | explicit open decisions | completion, Ask step |

Invariants enforced by `packages/model` (Pydantic + `jsonschema`):
- IDs are stable, prefixed (`EP-`, `EST-`, `AN-`, `RG-`, `CR-`, `EV-`, `RL-`,
  `SA-` …) and never reused within a work.
- Every endpoint links ≥1 objective; every primary/secondary estimand links an
  endpoint, population, treatment conditions, ≥1 event strategy (or an
  explicit `no_relevant_intercurrent_events: true`) and a population summary.
- Rescue is modelled three times, deliberately (spec): `rules[type=rescue]`
  (operational policy) → `events[type=rescue]` (the qualifying event) →
  `estimands[].event_strategies[]` (per-estimand handling) → `analyses[]`
  (data handling). R11 checks the chain.

## 3. Blocks, bindings and claims (document ↔ model)

```
Draft
 └─ Section (0–14, M11 L1)                 completion, findings roll-up
     └─ Heading (M11 L2/L3/L4 or added)   fixed | conditional {…} | optional | added
         └─ Block                          narrative | list | definition | table | figure | rule | reference | generated
             ├─ provenance                 author | inherited | derived | proposed | source
             ├─ approval                   unreviewed | approved(by, at, revision) | rejected
             ├─ validation                 pass | findings | unrun | stale        (per revision)
             ├─ applicability              applies | not_applicable(reason) | not_carried_over
             ├─ bindings[]                 model object ids this block asserts about
             ├─ claims[]                   sentence-level typed assertions extracted from the text
             └─ evidence[]                 source_id + page + bbox (for source/inherited blocks)
```

**Claim** = `{anchor, type, target: {entity_id, field}, value, unit?,
modality?, scope?, condition?, exceptions?, extraction, rationale, state,
revision}` where `type ∈ {quantity, threshold, time_reference, ratio,
identifier, modality_rule, reference, other}`. Targets use **stable entity
ids plus a field path** (e.g. `EP-01` / `time_reference.week`) and are
resolved to storage locations at check time — never raw array-index JSON
pointers. `anchor` is a Yjs relative position so it survives concurrent
edits; if the anchored text changes, the claim becomes `stale`.
R03/R07/R10/R13 compare claims to model values; mismatches are findings on the
exact span. Claim states: `checked | mismatch | unbound | ambiguous |
unsupported | stale`.

## 4. Provenance and evidence states

Authoring values: `author_supplied | inherited | derived | proposed`.
Analysis (library) values: `observed | redacted | not_reported | not_retrieved
| not_applicable | conflicting`.

Provenance is immutable (an LLM proposal stays `proposed` after approval).
**Approval** is a separate, attributable record (`approved_by, at, revision`,
role-checked). **Validation** is per revision (`pass | findings | unrun |
stale`). **Applicability** is reviewed per conditional heading (`applies |
not_applicable(reason) | not_carried_over`). A value counts toward completion
only when approved and applicable; a previously approved value can still fail
a new check.

## 5. Versions, drafts, autosave

- `Draft` = live CRDT state + current model; edited collaboratively.
- `Autosave snapshot` = opaque backup (every 30 s of activity / on idle / on
  disconnect); retained 30 days; restorable to a new draft branch.
- `Version` = user-created, labelled, immutable, frozen **atomically** at one
  revision: model + render AST + PDF/DOCX + validation report + regional
  overlay + accepted source/template/module versions + dependency versions
  (SAP → protocol) + disposition of every unresolved item + render engine
  version and artifact hashes. A different overlay yields a distinct,
  separately identifiable artifact. Amendments are versions with
  `amendment_of` and an auto-generated *semantic diff* (R22: values, scopes,
  conditions, formulas, paths that changed and the sections they affect).

## 6. Library study record and evidence lifecycle

```
Source (immutable bytes, sha256, data_class)
  └─ ExtractionRun (parser/prompt/OCR versions)  ── many per source, never overwritten
       └─ SourceAssertion (target, value, source_text, page/bbox, evidence_state, scope, rationale)
            └─ review: accepted(scope) | rejected | superseded_by  ── the RECONCILIATION GATE
Study (accepted record: document_kind "analysis", assembled from accepted assertions)
  ├─ arms[]: {id, label, product_ids, regimen_id, n_randomised}
  └─ historical_analysis_records[]: {arm_id, population, background_rescue_policy, instrument(+version),
        endpoint_algorithm{transform, threshold, timepoint, baseline_def}, estimand/event_handling,
        analysis_set, estimator, n_denominator, estimate, uncertainty{type, low, high}, unit,
        source_assertion_id, review_state}
```

Evidence states are kept distinct: `observed | redacted | not_reported |
not_retrieved | not_applicable | conflicting | extraction_failed`. An
extraction failure is never recorded as an omission.

The indication **master sheet** is a view: one row per study × arm × endpoint
× timepoint with design and comparability columns joined in. The calculator
reads only *reviewed* records and shows the comparability filter it applied.

## 7. Templates (conversion memory)

```
Template {
  starter_study_id, drug_class_profile (class, MoA, route, regimen shape, mechanism-risk package),
  section_mapping (source heading → outline heading, accepted),
  block_decisions[] (block_id → keep|adapt|drop|add, rationale, accepted_by),
  question_set (minimised, with merge lineage),
  created_by, created_at, version
}
```
Instantiating a Template for a new drug reuses mapping and decisions, and asks
only the drug-specific questions (those whose answers are bound to the
`DrugProfile` rather than the class profile).
