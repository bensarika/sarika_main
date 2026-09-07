# Protocol Studio

Browser-based authoring tool for clinical-trial protocols and statistical
analysis plans (SAPs), structured to ICH M11, with a source-traceable trial
model, evidence library, starter-protocol conversion, trial calculator,
deterministic + model-assisted checks, and LaTeX/DOCX export.

**Status: Pilot 1 in progress** — model, rules, renderer and API are executable
and tested; the production web client is being scaffolded. The Phase 0 docs and
clickable mock remain the design reference. See `docs/06_delivery_plan.md`.

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
| `packages/model/` | `ps_model` — schema validation, 15-entry outline, slots, completion, stable-ID paths, entity index ([README](packages/model/README.md)) |
| `packages/rules/` | `ps_rules` — R01–R22 catalogue, deterministic + completeness rules, claim checks ([README](packages/rules/README.md)) |
| `packages/render/` | `ps_render` — render AST → LaTeX/Tectonic PDF and DOCX ([README](packages/render/README.md)) |
| `apps/api/` | `protocol_studio` — FastAPI: works, commands/revisions, findings, versions, export, auth, admin ([README](apps/api/README.md)) |
| `apps/web/` | React + TypeScript + Vite client ([README](apps/web/README.md)) |
| `tools/astra_review.py` | Reproducible design review with GPT-6 Astra (`OPENAI_API_KEY`) |

## Develop

Python 3.12+, [uv](https://docs.astral.sh/uv/), Node 20+, optional
[Tectonic](https://tectonic-typesetting.github.io/) for PDF.

```
cd protocol-studio
uv sync --all-packages                                # one venv for the workspace
uv run pytest                                         # all packages + API
uv run ruff check . && uv run ruff format --check .   # lint / format
uv run mypy                                           # strict types
uv run uvicorn protocol_studio.main:app --reload --port 8080 --app-dir apps/api
cd apps/web && npm install && npm run dev             # http://localhost:5173 (proxies /api, /auth to 8080)
```

CI (`.github/workflows/protocol-studio.yml`) runs the same commands on every PR
touching `protocol-studio/`.

## Working conventions

- The trial model is authoritative; the document is derived where it can be and
  annotated where it cannot (docs/01_architecture.md §3).
- Every semantic change is a command at a `base_revision`; stale commands are
  rejected with 409 rather than merged.
- Design changes go through the docs first; code follows the docs.
- Every Astra review is saved under `docs/reviews/` with model, prompt version
  and token usage so critiques are auditable.
- Each package keeps its own README current with its behaviour and tests.
- Secrets (OpenAI, Google OAuth, AWS) live in Devin org secrets / the deployment
  environment, never in source.
