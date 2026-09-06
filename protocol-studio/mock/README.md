# Phase-0 clickable mock

Static, dependency-free mock of the key Protocol Studio screens. It exists to
exercise the architecture (`../docs/01_architecture.md`) and the visual
language (`../docs/02_visual_language.md`) against the usage scenarios in
`../docs/04_workflows.md` **before** executable application code is written.
Every number, page reference and study value is illustrative.

## Run

```bash
cd protocol-studio/mock && python3 -m http.server 8765
# open http://localhost:8765/index.html
```

Opening `index.html` directly from disk also works (hash routing, no fetches).

## Files

| File | Purpose |
| --- | --- |
| `index.html` | Shell; loads fonts, `styles.css`, `data.js`, `app.js` |
| `styles.css` | Clinical Slate tokens and components (single source for the mock's look) |
| `data.js` | Illustrative outline, works, studies, historical records, findings, questions, providers |
| `app.js` | Hash router + one render function per screen; small in-place interactions |

## Routes ↔ scenarios

| Route | Screen | Scenario (04_workflows) |
| --- | --- | --- |
| `#/login`, `#/login/denied` | Google SSO entry; non-allowlisted account | S9 |
| `#/library` | Works with % complete, blocking count, presence | S1, S3 |
| `#/library/studies` | Study library with source/extraction/OCR state | S5 |
| `#/library/master` | Indication master sheet (reviewed records, evidence pages) | S5, S7 |
| `#/library/templates` | Saved conversion templates | S2 |
| `#/new/1…5` | New-from-starter wizard: choose → split/map → bind/adapt → key inputs → create | S2 |
| `#/editor/W-102` | Three-pane editor; Inspect / Findings / Ask / Compare / History | S1, S3, S4, S6, S8, S10 |
| `#/calculator` | Sample size, comparability filter, pooling, sensitivity heat-map, historical strip | S7 |
| `#/admin/*` | Users, per-work permissions, usage, models & providers, audit | S9, S11 |

## Walkthrough notes (what the mock taught us)

Exercising the routes in the order login → library → new-from-starter →
editor → calculator → admin confirmed or adjusted these design points (all
reflected in the docs):

1. **Four state dimensions must be visible at once on a block** (provenance,
   approval, validation, applicability). If approval is merged into the green
   validation chip, a `proposed` block that passes checks looks "done". The
   Inspector shows four separate chips.
2. **Block hover actions cannot sit on top of the text.** The Ask/Comment
   menu now floats above the block's top-right edge.
3. **Findings need a "Go to §n" affordance** because the outline rail already
   shows per-section dots but the finding list is the natural work queue.
4. **Ask threads need the data class in the context line** and disabled
   models must say *why* ("not approved for confidential") — otherwise the
   fail-closed routing feels like a bug.
5. **Insert ≠ Approve** reads naturally in the Proposal card when the button
   is literally labelled "Insert as proposal" and the block then shows
   `unapproved`.
6. **Calculator comparability must be explicit**: excluded historical
   records are shown greyed with the exclusion reason and the pooled value
   is opt-in, with the between-study range next to it.
7. **The wizard's "drop" column needed relabelling** to *Not carried over —
   review required*; "dropped" implied silent loss of source content.
8. **Section 0 is visually distinct** in the outline (front matter, not a
   numbered M11 section) so the 15-entry internal outline does not read as
   "15 sections".

## Not in the mock

Real editing, collaboration cursors, exports, ingestion progress, the
endpoint explorer (Pilot 4b) and the SAP editor. These are deliberately
deferred to the pilots described in `../docs/06_delivery_plan.md`.
