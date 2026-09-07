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
| `#/editor/W-102` | Docs-style editor: title/menu/toolbar header, wide sidebar (Outline / Workflow / Analysis), paper canvas, Inspector (Inspect / Findings / Ask / Compare / History) | S1, S3, S4, S6, S8, S10 |
| `#/calculator` | Sample size in three numbered steps, working comparability checkboxes + pooling, sensitivity table with reading guide, historical SVG chart: dumbbell (by study) / Δ forest (treatment effect) / placebo lollipop | S7 |
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

Second round (user walkthrough feedback):

9. **Calculator controls must be real controls.** Checkboxes now hold
   per-study inclusion state (`state.calc.include`); excluded-by-filter rows
   can still be deliberately included and are then flagged *included
   despite*. Sliders re-render only the output panel (`calcSet`) so the thumb
   never loses the drag, have 22px thumbs, and each has a numeric twin.
10. **Headline before table.** "Result" became a sentence: *Enrol N to have
    X% power to show … if the true rates are p1 vs p0*. The sensitivity
    table has a "How to read" strip (rows = ratio, columns = effect ±5 pts,
    outlined cell = current inputs). Panels are numbered 1-2-3 to give the
    eye a path: endpoint → placebo evidence → assumptions → headline → fragility.
11. **Historical performance as a dumbbell chart, three views.** The first
    round's vertical dot strip was too abstract (no n, no arm names, study
    labels truncated); horizontal grouped bars (round 2) were better but
    still made the eye compare bar lengths instead of the treatment effect.
    A Devin data-analysis child session iterated six alternatives on the
    illustrative CSV (`docs/07_chart_recommendation.md`) and recommended the
    current design: one row per trial, grey placebo dot → coloured active
    dot, Δ + 95% CI (Newcombe) written on the connector, the user's own
    assumption pinned on top in amber and drawn the same way, a pooled-placebo
    band, dot area ∝ n, JAK-like arms as diamonds, and excluded records faded
    + dashed below a labelled divider with the exclusion reason. Secondary
    tabs: a *treatment effect* forest (Δ with CI, numeric column right of
    the plot) and a *placebo only* lollipop with Wilson CIs on a 0–50 % scale.
    The chart re-renders live as the sliders move. Placebo grey is `#9CA3AF`
    for deuteranopia separation from teal.
12. **Uppercase, letter-spaced headers and tabs** everywhere (page titles,
    panel headers, top nav, sidebar/inspector tabs, wizard steps).
13. **Editor is document-first.** A persistent horizontal app bar sits over
    every screen; the editor adds a Google-Docs-style header (title, save
    state, presence, Share / Create version / Export), a menu bar with
    real dropdowns (File … Model … Help) and a formatting toolbar. The
    sidebar grew from a 260px outline rail to 340px with three tabs:
    **Outline** (sections with completion bars and blocking dots),
    **Workflow** (stages, personal queue, readiness predicates) and
    **Analysis** (per-section completion vs blocking findings, provenance
    mix, findings by check type, claims coverage, cross-section
    dependencies, model usage). Blocks are `contenteditable` so typing feels
    like a document (edits are not persisted in the mock).
14. **The lower-left avatar opens an account menu** (my works, permissions,
    administration, preferences, shortcuts, sign out); the same menu is
    reachable from the top bar.
15. **No icon-only navigation.** The 56px icon rail was rejected ("I don't
    like the image only"). Every screen now has a 232px labelled sidebar:
    brand, four primary destinations as icon + label, and the active one
    expanded into its second-level pages in words (Workspace lists open
    works with status dot and %). It collapses to icons only on an explicit
    « Collapse click. The account block at the bottom shows name, email and
    role. Editor panes were rebalanced to 300 / canvas / 380 to make room.

## Not in the mock

Real editing, collaboration cursors, exports, ingestion progress, the
endpoint explorer (Pilot 4b) and the SAP editor. These are deliberately
deferred to the pilots described in `../docs/06_delivery_plan.md`.
