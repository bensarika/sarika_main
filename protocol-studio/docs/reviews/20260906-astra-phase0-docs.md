# Astra review

- date: 2026-09-06T22:10:08+00:00
- model: gpt-6-astra
- prompt_version: review-v1
- inputs: docs/01_architecture.md, docs/02_visual_language.md, docs/03_domain_model.md, docs/04_workflows.md, docs/05_decisions.md, docs/06_delivery_plan.md
- spec context: reference/AD_protocol_builder_spec.md
- usage: {"input_tokens": 24344, "input_tokens_details": {"cache_write_tokens": 24341, "cached_tokens": 0}, "output_tokens": 3612, "output_tokens_details": {"reasoning_tokens": 288}, "total_tokens": 27956}

---

The model-first direction fits the brief. The main risk is that the design promises a single authoritative trial model but has not specified the synchronization, evidence adjudication, and release controls needed to make that promise true. I would approve a bounded prototype, **not implementation for regulated authoring as currently specified**.

Only the supplied Markdown was reviewed; the referenced schemas, rule catalog, M11 outline JSON, and mock were not available to verify.

## 1. Blocking issues

### B1. Two writable representations, with no consistency transaction
**`docs/01_architecture.md` §§6.2–6.3, 8**

> “Draft = Yjs document…”  
> “The trial model…persisted as JSONB per draft and per version”

These are two independently editable representations of clinical truth. The design does not say what happens when one author edits “Week 16” in prose while another changes the bound endpoint to Week 24. CRDT convergence resolves document-edit conflicts; it does not resolve contradictory clinical decisions.

Nor is it clear which revision an asynchronous finding or accepted proposal applies to. A delayed extraction could overwrite newer values, or a version could freeze text, model, and findings from different revisions.

**Required before building:** define authoritative edit commands, a shared revision identifier, optimistic concurrency for semantic edits, stale-result rejection, and an atomic version-freeze process. Generated fields should be edited through model commands; unrestricted narrative edits should create claims requiring reconciliation, not silently change accepted model values.

### B2. Template reuse and question minimisation can erase necessary decisions
**`docs/01_architecture.md` §6.6; `docs/03_domain_model.md` §7**

> “the second user who picks the same starter skips steps 1–5”  
> “asks only the drug-specific questions”

Population, jurisdiction, background therapy, rescue, estimands, follow-up, analysis framework, and oversight are **study-specific**, not necessarily drug-specific. A second trial of the same drug may legitimately need different answers to all of them.

> “merge questions with shared information content, drop those derivable from accepted inputs”

An LLM’s assertion that something is derivable is not a derivation. For example, choosing composite handling of rescue does not determine the operational rescue policy or whether follow-up observations continue.

**Required:** every applicable decision must remain traceable to an explicit answer, reviewed inherited value, or executable derivation. Minimisation may simplify presentation, but must not remove decision coverage. Reusing a template must reevaluate applicability and invalidate decisions affected by changed inputs or source-module versions.

### B3. The canonical library record collapses evidence and authority too early
**`docs/01_architecture.md` §6.1**

> “Purpose: parse any source once, reuse forever.”  
> “Re-opening a study never re-parses.”

A checksum identifies source bytes, not the correctness of their interpretation. Parser upgrades, corrected OCR, new amendments, and adjudicated conflicts require new extraction runs without destroying the original evidence.

The pipeline goes directly from extraction and normalization to a “canonical study record,” without an explicit reconciliation gate. That is unsafe for a package containing an original protocol, amendments, a later SAP, and results. A later SAP must not automatically overwrite the protocol; actual enrollment must not replace planned N.

**Required:** separate immutable source documents, versioned extraction runs, competing assertions, and accepted scoped study definitions. Retain source-native wording, physical-page evidence, normalization rationale, review decisions, and unavailable dependencies. Explicitly distinguish extraction failure from source omission or redaction.

### B4. Historical endpoint ranking is statistically under-specified and potentially misleading
**`docs/01_architecture.md` §6.7; `docs/03_domain_model.md` §6**

> “rank…N required for superiority vs the pooled placebo history”  
> “show uncertainty from the spread of historical placebo rates”

AD placebo response depends materially on background topical treatment, rescue definitions, population, instrument, endpoint algorithm, estimand, analysis set, and missing-data handling. Page provenance does not establish comparability.

The proposed outcome row lacks enough dimensions to prevent pooling clinically different results. “Spread” also conflates sampling uncertainty with between-study heterogeneity. A small calculated N is not evidence that an endpoint is the best regulatory or clinical choice.

The calculator additionally defaults to conventional testing inputs while the specified scope includes Bayesian estimation and explicit non-testing sample-size rationales.

**Required:** introduce reviewed historical-analysis records and explicit comparability criteria. Make pooling an approved statistical choice, not the default. Label ranking as exploratory scenario analysis, distinguish clinical/claim suitability from sample-size efficiency, and represent unsupported statistical frameworks explicitly rather than forcing alpha/power fields.

### B5. Readiness and acceptance states can give false assurance
**`docs/04_workflows.md` S3; `docs/01_architecture.md` §6.5**

> “‘Ready for formal review’ label is blocked until errors = 0.”  
> “required_slots_filled / required_slots…minus blocking findings”

Zero detected errors does not establish readiness. Checks may be unrun, stale, unsupported, or awaiting adjudication; an IB or operations manual may be unavailable; an extracted value may remain unreviewed. The completion formula also mixes a ratio with an unspecified finding penalty.

**`docs/02_visual_language.md` §2**

> “Accepted, checks pass”

Acceptance, validation status, provenance, and applicability are independent dimensions. A previously accepted value can fail a new check. An LLM proposal remains LLM-originated after approval.

**Required:** separate these states and define milestone predicates. Formal-review readiness should require current checks, resolved required dependencies, reviewed applicability, and an explicit disposition of unresolved decisions—not just an error count.

### B6. External data handling defaults to disclosure before authorization
**`docs/05_decisions.md` Q9**

> “Default if no answer: Proceed with API defaults; flag in admin”

This is not a defensible default for confidential protocols, IBs, or SAPs. The customer’s approval of one vendor does not authorize every user-selected provider or fallback.

**`docs/04_workflows.md` S11**

> “off restricts a vendor to library/public tasks”

The library accepts customer uploads and therefore is not synonymous with public information.

**Required:** fail closed until the customer approves each provider and data class. Enforce routing restrictions on the server, including fallback calls, source snippets, Ask context, and logs. Add document-level classification and permissions. Arbitrary source URLs and provider base URLs also require SSRF protection; document parsing and LaTeX compilation require sandboxing, resource limits, and controlled network access.

## 2. Gaps versus the requirements and supplied specification

### The schema scaffold is treated as a validated implementation contract
**`docs/05_decisions.md` ADR-002**

> “spec-validated on AD corpus”

The supplied specification explicitly describes an application scaffold and partial extractions, not a proven universal schema.

**`docs/01_architecture.md` §6.3**

> “so the API cannot store an invalid model”

Pydantic/JSON Schema can establish structural validity, not clinical correctness or complete cross-object semantics. Strict complete-object invariants also conflict with incremental authoring: an author needs to save an endpoint before all its fields and relationships are resolved.

The design needs application-owned schema versions, migrations, draft-tolerant validation, and explicit semantic constraints. It also needs a pinned USDM mapping and M11 technical-specification mapping—not only heading styles.

### SAP is promised but not designed as a controlled document
**`docs/03_domain_model.md` §1**

> “a second view, not a second model”

Sharing trial definitions is appropriate. Treating the SAP as merely another rendering leaves unspecified its independent versioning, approval, dependency on a particular protocol version, and detailed statistical content. E9/E9(R1) supplies principles, not a mandatory SAP outline.

There is also an architectural contradiction: `works` stores a protocol **or** SAP with its own model, but the design asserts that both share one model. Define a shared trial definition with separately versioned protocol and SAP artifacts and controlled extensions.

### Sentence-level checking lacks coverage and ambiguity semantics
**`docs/01_architecture.md` §6.3**

> “Deterministic extractors handle numbers, units, weeks/days, ratios, thresholds…”

Recognizing “16” and “weeks” is not equivalent to identifying the correct temporal anchor, population, exception, or modality. The claim structure omits explicit scope, condition, exceptions, and interpretation rationale. Sentence offsets will also become stale during collaborative editing.

The brief’s sentence-level checking requires visible distinctions between **checked**, **unbound**, **ambiguous**, **unsupported**, and **stale** claims. Otherwise unextracted prose can appear to have passed.

### Delivery defers foundations needed to evaluate the pilots
**`docs/06_delivery_plan.md` Phases 5 and 7**

> “Auth + Collaboration + Admin”  
> “Hardening: regression fixtures…amendment diff…”

Authentication can follow a local synthetic-data prototype, but authorization boundaries and audit events must shape persistence and job execution from the outset. Real-document adjudicated fixtures are how the extraction and model design are tested, not late-stage polish.

There is also a rule-planning inconsistency: architecture §6.4 classifies checks by execution type, while Phase 3 labels R13–R22 collectively as “semantic candidates.” Change impact and declared numerical/temporal constraints should not become LLM-only merely because of their rule numbers.

## 3. Simplifications

- **Defer automatic endpoint ranking and “JAK-like” inference.** First deliver a validated calculator using explicit, reviewed assumptions and a provenance-backed historical comparison table. This preserves substantial customer value without premature pooling.
- **Support one verified provider plus a capability-tested compatible adapter initially.** The promise that adding a vendor is “one adapter file + a price table entry” understates differences in structured outputs, streaming, refusal handling, retention, and model identification.
- **Defer live CRDT collaboration, not concurrency controls.** A short single-writer pilot can test the semantic edit contract. Add collaboration once text/model transactions and stale proposal handling are proven.
- **Do not build iterative minimisation as a five-pass subsystem initially.** Start with a decision inventory and one LLM-assisted grouping pass. Measure retained coverage and answer burden before adding iterative optimization.
- **Remove guarantee language.** “One AST…guarantees…identical content” should become a tested objective. Separate emitters can lose footnotes, table headers, symbols, or conditional text despite a common AST.

## 4. Specific suggestions

1. **`docs/01_architecture.md` §§6.2–6.4, 8 — Add an edit/commit contract.**  
   Document narrative edit, model edit, proposal acceptance, concurrent update, failed extraction, and version creation. Every command, claim, finding, and rendered artifact should identify its input revision. Add a test where a Week-16 proposal arrives after the endpoint has changed to Week 24.

2. **`docs/03_domain_model.md` §§2–5 — Separate semantic identity from storage location.**  
   The example `/endpoints/EP-01/time_reference/week` is not a valid JSON Pointer if `endpoints` is an array. Use stable entity-ID references plus field paths; resolve them to storage paths. Preserve claim anchors through text edits and mark interpretation stale when the relevant text changes.

3. **`docs/01_architecture.md` §§6.1, 8; `docs/03_domain_model.md` §§4, 6 — Specify the evidence lifecycle.**  
   Add extraction-run identifiers, parser/prompt versions, source assertions, scoped acceptance decisions, and supersession links. Test conflicting protocol/SAP rescue rules and an amendment correcting an omitted ECG. Neither case should silently replace prior evidence.

4. **`docs/01_architecture.md` §6.6; `docs/04_workflows.md` S1 — Make question coverage testable.**  
   Record `decision_id → applicable scope → question/answer/inherited value/derivation → reviewer`. Require every minimisation run to preserve this coverage. A dropped source block must become “not carried over—review required,” not automatically “Not applicable.”

5. **`docs/01_architecture.md` §§6.5, 6.9; `docs/02_visual_language.md` §§2, 5; `docs/04_workflows.md` S10 — Define one state machine.**  
   Distinguish “Insert proposal” from “Approve value”; currently “Accept inserts it as a proposed block” is contradictory. Keep provenance immutable, approval attributable, and validation revision-specific. Show completion denominators and milestone criteria independently.

6. **`docs/03_domain_model.md` §§1, 5; `docs/01_architecture.md` rendering — Define controlled releases.**  
   Freeze protocol/SAP dependencies, regional overlay, accepted model revision, unresolved-item disposition, source/module versions, render-engine version, and artifact hashes. A different overlay should produce a separately identifiable artifact. Pin the Tectonic bundle rather than fetching changing dependencies during release compilation.

7. **`docs/01_architecture.md` §§6.7, 8; `docs/06_delivery_plan.md` stats tests — Add a statistical analysis-record contract.**  
   Include population, background/rescue policy, instrument/version, endpoint algorithm, estimand/event handling, estimator, denominator definition, uncertainty measure, and provenance. Specify calculator formulas and unsupported cases; verify independently against adjudicated reference calculations.

8. **`docs/05_decisions.md` Q9; `docs/01_architecture.md` §§7–9 — Replace compliance flags with enforced controls.**  
   Add provider/data-class approval, source ACL inheritance, restricted egress, audit-log access controls, revocation behavior, and retention rules. Define backup RPO/RTO and test restoration; snapshots and nightly dumps alone are not a recovery design.

9. **`docs/06_delivery_plan.md` — Replace session estimates with acceptance gates.**  
   Before expanding the product, demonstrate an adjudicated end-to-end case: source assertion → accepted model → conditional SoA/estimand → exported document → semantic amendment. Measure threshold/negation preservation, branch correctness, evidence-location accuracy, and conflict precision/recall on held-out sponsor/version families.

## 5. Questions the team should ask the customer

1. **What is the intended regulated use?** Is this a drafting aid with approval elsewhere, or the authoritative system for approved protocols/SAPs? Which validation, retention, audit, and electronic-signature requirements apply?
2. **Who may approve what?** Must clinical, statistical, safety, and operational decisions have designated reviewers? Can the same author propose and approve a change?
3. **How are protocol and SAP versions governed today?** What constitutes an authorized deviation or clarification, and which regional/site amendments may operate concurrently?
4. **Which data may leave the customer environment, to which providers, under which agreements?** Are IBs, unpublished results, personal data, and confidential library documents subject to different restrictions?
5. **What may templates legitimately inherit?** Is reuse primarily within a study program, within a molecule, or across mechanisms? Which decision packages must always be reconfirmed?
6. **What does “best endpoint/timepoint” mean?** Lowest N, clinically meaningful effect, regulatory claim suitability, operational burden, or a weighted decision? Who approves historical comparability and pooling?
7. **What is the approval workflow after DOCX export?** If authors edit in Word, must those changes return to the model, or does exporting explicitly end the application’s consistency guarantee?
8. **What evidence will make the pilot acceptable?** Ask the customer to nominate representative protocols/SAPs, known inconsistencies, acceptable false-positive rates, and reviewers who can adjudicate the benchmark.