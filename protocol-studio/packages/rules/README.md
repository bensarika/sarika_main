# ps_rules — deterministic checks, completeness and claims

Turns a model (+ narrative claims) into a list of `Finding`s. Rules are pure
functions registered by ID; the API runs them on every commit and stamps each
finding with the draft revision so stale results are visible.

Deterministic findings and model-suggested findings are kept apart by design
(docs/01_architecture.md §6): everything in this package is deterministic and
reproducible. LLM-suggested findings (Pilot 3+) will live in `packages/llm` and
arrive as `Severity.CANDIDATE` for a human to accept or dismiss.

## Modules

| Module | Purpose |
| --- | --- |
| `catalogue.py` | Loads `reference/validation_rules.json` — the customer's R01–R22 catalogue (id, title, type, severity, inputs). The catalogue is the *specification*; `registry` holds the *implementations*. |
| `finding.py` | `Finding` (rule_id, severity, message, targets, section_id, explanation, suggested_fix, needs_adjudication, revision, data) and `Severity`. `Finding.key` is a stable hash so adjudications survive a recompute. |
| `registry.py` | `@rule("R01")` decorator, `RuleContext` (revision, entity index, claims, narrative states, not-applicable slots), `run_rules(model, revision=..., only=[...])`. |
| `rules_deterministic.py` | R01 reference integrity, R03 expression arithmetic, R07 dose calendar, R09 participant transitions (candidate), R10 time anchors/units/windows, R16 testing dependency graph (cycles, alpha, unknown analyses). |
| `rules_completeness.py` | R02, R12, R15, R17, R18 — conditional completeness rules emitted as `INCOMPLETE` (feeds completion, never blocks on its own). Reviewed not-applicable slots suppress the finding. |
| `rules_claims.py` | CL01 mismatch (error, needs adjudication: *Update model* / *Revert text*) and CL02 unbound/unsupported (warning). `claim_state()` is also used by the API to refresh claim states after each command. |

### Severity semantics

| Severity | Effect |
| --- | --- |
| `error` | blocks formal-review readiness and version freeze as "ready" |
| `candidate` | cross-view/semantic suspicion; a human must accept or dismiss (adjudication) |
| `warning` | shown, does not block |
| `incomplete` | a required slot is empty; drives completion %, not a defect |
| `info` | commentary |

### Coverage vs. catalogue

Implemented: R01, R02, R03, R07, R09, R10, R12, R15, R16, R17, R18, CL01, CL02.
Not yet implemented (listed in the catalogue, surfaced in the API as `status: "planned"`):
R04 schedule coverage, R05 scope/version conflict, R06 footnote loss, R08 blinding
calendar, R11 rescue linkage, R13 observed vs analysis value, R14 sensitivity vs
supplementary, R19 source availability, R20 provenance, R21 planning vs results,
R22 change impact. Most need the evidence/ingestion layer (Pilot 2).

## Usage

```python
from ps_rules import run_rules

findings = run_rules(model, revision=draft.revision, claims=claims, not_applicable=na)
errors = [f for f in findings if f.severity == "error"]
```

## Tests

`packages/rules/tests/test_rules.py` — catalogue load, clean examples produce
no errors, each implemented rule has a positive and negative fixture, claim
state transitions, stable keys and revision stamps.

## Adding a rule

1. Check the catalogue entry (inputs, type, severity) in `reference/validation_rules.json`.
2. Add `@rule("Rxx")` in the module matching its type; return `Finding`s with
   dotted-path `targets` so the UI can jump to the field.
3. Add a failing fixture and a clean fixture to the tests. Keep the rule pure:
   no I/O, no LLM calls.
