# apps/web — Protocol Studio web client

React 18 + TypeScript + Vite single-page app. It is a thin, typed client of
`apps/api`; all business rules (schema, completion, findings, versions) live
server-side so the UI can never disagree with the exporter.

## Layout

```
src/
  main.tsx               routes (BrowserRouter; the API serves index.html for unknown paths)
  styles.css             Clinical Slate tokens + primitives (docs/02_visual_language.md)
  lib/api.ts             one function per endpoint, exact response types, ApiError(status, body)
  lib/session.tsx        SessionProvider (/auth/me at boot), RequireAuth / RequireAdmin guards
  lib/useDraft.ts        per-work draft session: state + evaluation + outline, `send(cmd)` with
                         optimistic concurrency (409 → reload + "stale" notice, never silent retry)
  components/Frame.tsx   rail (232px, labelled) + persistent top nav + account menu; Chip, Progress
  components/BlockEditor.tsx   one narrative block: save-on-blur, approve, claims, mismatch resolution
  components/AnalysisPane.tsx  FINDINGS · MODEL (remaining slots, set field, not-applicable) · HISTORY
  pages/Login.tsx        dev one-click or Google redirect, depending on /auth/config
  pages/Library.tsx      works the user can see
  pages/NewWork.tsx      starter → identity → create
  pages/Editor.tsx       outline rail + Docs-like sheet + analysis pane; Section 1 is generated
  pages/Admin.tsx        users & roles · usage · audit
```

## Conventions

- **Commands, not PUTs.** Every semantic change goes through `useDraft().send({type, ...})`;
  the hook stamps `base_revision` and serialises calls so blur+click in one tick cannot race.
- **Model is authoritative.** Narrative blocks are saved as `upsert_block`; numbers that
  must agree with the model are bound as *claims* (`set_claim`) and surfaced as
  `checked / mismatch / unbound / unsupported`. Mismatches offer exactly two actions:
  *Update model* or *Revert text*.
- **Completion is server-computed** (`/outline`, `/evaluation`); the UI only draws it.
- **Provenance chips** (`imported`, `author`, `derived`, `proposed`) and **approval**
  (`unreviewed`, `approved`, `rejected`) are always visible on a block.
- Headers and tabs are uppercase (`.caps`). No icon-only navigation.

## Develop

```bash
npm install
npm run dev          # http://localhost:5173, proxies /api and /auth to :8080
npm run typecheck    # tsc, strict + noUncheckedIndexedAccess
npm run build        # dist/ — the API serves it when PS_WEB_DIST points here (default ../web/dist)
```

Start the API alongside: `uv run uvicorn protocol_studio.main:app --reload --port 8080 --app-dir apps/api`.

## Not in Pilot 1 (placeholders in the rail are greyed)

Calculator, source-study library, indication master sheet, conversion templates,
models & providers admin, per-work permission matrix UI, live multi-cursor collaboration.
