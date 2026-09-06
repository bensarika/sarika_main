# Protocol Studio

Browser-based authoring tool for clinical-trial protocols and statistical
analysis plans (SAPs), structured to ICH M11, with a source-traceable trial
model, evidence library, starter-protocol conversion, trial calculator,
deterministic + model-assisted checks, and LaTeX/DOCX export.

**Status: Phase 0 — architecture, visual language and clickable mock.**
No executable application code yet; see `docs/06_delivery_plan.md`.

## Layout

| Path | Contents |
| --- | --- |
| `docs/01_architecture.md` | System architecture and the reasoning behind it |
| `docs/02_visual_language.md` | "Clinical Slate" visual system (tokens, components, screens) |
| `docs/03_domain_model.md` | Trial model, claims, evidence lifecycle, states |
| `docs/04_workflows.md` | Usage scenarios S1–S11 the design is checked against |
| `docs/05_decisions.md` | ADRs, open questions for the customer, review log |
| `docs/06_delivery_plan.md` | Pilots, acceptance gates, testing strategy |
| `docs/reviews/` | Recorded GPT-6 Astra critiques of the design |
| `mock/` | Static clickable mock (`mock/README.md` explains routes and findings) |
| `reference/` | Customer-supplied toolkit: outline, schema, validation rules, spec |
| `tools/astra_review.py` | Reproducible design review with GPT-6 Astra (`OPENAI_API_KEY`) |

## Working conventions

- Design changes go through the docs first; the mock follows the docs.
- Every Astra review is saved under `docs/reviews/` with model, prompt version
  and token usage so critiques are auditable.
- Each future package (`apps/web`, `apps/api`, `packages/*`) gets its own
  README kept current with its behaviour and tests.
