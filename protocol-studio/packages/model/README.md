# ps_model — the authoritative trial model

Pure-Python, dependency-light package that owns the *shape* of a protocol/SAP
document. Everything else (rules, renderer, API, web) consumes it.

Design rule (docs/01_architecture.md §3): **the model is authoritative; the
document is derived where it can be and annotated where it cannot.** Nothing in
this package knows about narrative text, users or storage.

## Modules

| Module | Purpose |
| --- | --- |
| `schema.py` | Loads `reference/protocol_model.schema.json`; `validate_model(model, strict=)`; `empty_model()` for a blank authored draft. `strict=False` ignores *missing required* errors so incomplete drafts can be saved; `strict=True` is used for frozen versions and fixtures. |
| `outline.py` | `OUTLINE`: the 15-entry canonical outline (Section 0 identity/document control + ICH M11 sections 1–14), each with subsections and the model collections it is fed by. |
| `slots.py` | Required-slot map: for each section, which model fields/collections must be present ("slot"), with `conditional` slots whose applicability depends on other fields. |
| `completion.py` | `% complete = filled_required_slots / applicable_required_slots`, per section and overall. Reviewed not-applicable slots leave the denominator; narrative slots count only when **approved**; drafted progress is tracked separately. Section 1 is generated from 3/4/8 and is not a denominator. |
| `paths.py` | Dotted paths with stable-ID selectors — `endpoints[easi75].time.offset.value` — `get_path` / `set_path` / `PathError`. Never index by position; IDs survive reordering. |
| `refs.py` | `index_entities(model)` → `EntityIndex`; `iter_references` finds every `*_id` / `*_ids` foreign key so R01 can check dangling references generically. |

## Usage

```python
from ps_model import empty_model, validate_model, completion_for_model, overall_completion

m = empty_model(protocol_id="W-1", name="SRK-201 Ph2b", indication="Atopic dermatitis")
assert validate_model(m, strict=False) == []  # a blank draft is saveable
issues = validate_model(m, strict=True)  # ... but not freezable as complete
sections = completion_for_model(m)
print(overall_completion(sections))  # {'filled': 0, 'applicable': N, 'pct': 0}
```

## Tests

`packages/model/tests/test_model.py` — schema strictness, outline count, path
semantics, entity index, completion arithmetic (approval, not-applicable).

```
uv run pytest packages/model
```

## Extending

- New model field → add to the JSON schema first (it is the contract), then to
  `slots.py` if the field is required for a section to count as complete.
- Do not add classes that mirror the schema; keep the model a plain `dict` until
  the schema stabilises (0.1.0 today).
