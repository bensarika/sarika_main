# Protocol Studio — Visual Language ("Clinical Slate")

The interface must make a regulatory author *trust* it. Trust comes from
restraint: one accent colour, a strict semantic palette reserved for meaning
(provenance and validation), a document canvas that looks like the document
that will be submitted, and dense-but-calm information layout. Every visual
element below has a job; nothing is decorative.

Implementation: these tokens are the single source of truth for
`apps/web` (Tailwind theme) and for `mock/` (CSS custom properties). Change
them here first.

---

## 1. Principles

1. **The document is the hero.** The canvas is paper-like (warm white,
   serif body); everything else (rails, inspector, chrome) recedes into cool
   slate greys.
2. **Colour means something.** The accent (teal) is *only* for interactive
   affordances. Every other hue is a semantic state (provenance, validation,
   completion) and is never used decoratively.
3. **Show the seams.** Where a value came from, whether it was reviewed, and
   what depends on it are always one glance away (chips, underlines, rail
   markers) — never hidden behind a menu.
4. **Numbers are links.** Any number, threshold, week or N shown in prose,
   tables or the calculator is a link to its model object or source page.
5. **Calm density.** 8-px grid, generous line-height, tight vertical rhythm.
   Panels, not cards; hairlines, not shadows; no gradients.

---

## 2. Colour tokens

### Neutrals (chrome)
| Token | Hex | Use |
|---|---|---|
| `--slate-950` | `#0F1720` | Primary text on light, sidebar text on dark |
| `--slate-800` | `#26323F` | Secondary headings |
| `--slate-600` | `#4B5A6B` | Body text in chrome, icons |
| `--slate-400` | `#8A97A6` | Placeholders, tertiary |
| `--slate-300` | `#C3CBD4` | Hairline borders |
| `--slate-200` | `#DEE3E9` | Dividers, table rules |
| `--slate-100` | `#EEF1F4` | Rail / inspector background |
| `--slate-50`  | `#F6F8FA` | App background |

### Canvas (document)
| Token | Hex | Use |
|---|---|---|
| `--paper` | `#FCFBF8` | Document canvas background (warm) |
| `--ink`   | `#1B1B1B` | Document body text |
| `--ink-soft` | `#5A5A5A` | Instructional / placeholder text in canvas |

### Accent (interaction only)
| Token | Hex | Use |
|---|---|---|
| `--accent-700` | `#0E5E63` | Primary button, active nav, focus ring, links |
| `--accent-500` | `#177E85` | Hover |
| `--accent-100` | `#DDF0F1` | Selected row / block highlight |

### Semantic — provenance (who/what asserted a value)
| Token | Hex | Meaning | Where |
|---|---|---|---|
| `--prov-source`   | `#2F63C9` (blue)   | Observed in a source document (page-anchored) | left border of block, chip |
| `--prov-author`   | `#1B1B1B` (ink)    | Author-supplied | no marker (default) |
| `--prov-inherited`| `#6E4BC4` (violet) | Inherited from library module / template | chip |
| `--prov-derived`  | `#0E7C6B` (green-teal) | Derived by deterministic computation | chip, dotted underline |
| `--prov-proposed` | `#B7791F` (amber)  | Proposed by LLM, not yet accepted | chip + hatched left border |

### Semantic — validation / review
| Token | Hex | Meaning |
|---|---|---|
| `--state-error`      | `#C2361C` | Blocking finding (deterministic) |
| `--state-warning`    | `#D98A0B` | Warning / candidate conflict needing adjudication |
| `--state-incomplete` | `#E06A17` | Required slot empty / unresolved decision |
| `--state-ok`         | `#2E8B57` | Checks pass at the current revision (validation only — approval and provenance are shown as separate chips, never merged into this colour) |
| `--state-na`         | `#8A97A6` | Not applicable (with reason) |
| `--state-info`       | `#4B5A6B` | Informational |

### Semantic — completion
Progress bars use a single hue ramp: `--slate-200` track, `--accent-700`
fill; milestone ticks at design-ready / operationally specified / ready for
review are `--slate-600`. Completion never uses red/green — completion is not
a judgement, findings are.

Contrast: all text pairs meet WCAG AA (≥ 4.5:1) on their intended background.
Amber and orange are always paired with an icon/label, never colour-alone.

---

## 3. Typography

| Role | Family | Size / line | Notes |
|---|---|---|---|
| UI text | **Inter** (variable) | 13 / 20 body, 12 / 16 dense, 15 / 22 panel titles | tabular numerals on (`font-variant-numeric: tabular-nums`) for tables |
| Document canvas | **Source Serif 4** | 15.5 / 26 body; headings: L1 20 bold caps-tracked, L2 17 bold, L3 15.5 bold, L4 15.5 bold italic | mirrors M11's Times-based hierarchy in a screen-friendly serif; exports use Times New Roman/TeX Gyre Termes |
| Identifiers, numbers in chips, code | **JetBrains Mono** | 12 / 16 | IDs like `EP-01`, `R07`, `p.42` |

Heading numbering in the canvas is *generated* from the outline; it is not
typed by the author (M11 forbids editing L1/L2 headings).

---

## 4. Layout

**App frame:** 56-px left icon rail (Library, Workspace, Calculator, Compare,
Admin) → content. Top bar (48 px) shows breadcrumb, version chip, presence
avatars, autosave status, primary action.

**Editor (three panes, resizable):**
```
┌──────┬────────────────────────┬────────────────────────────────┬──────────────┐
│ rail │ OUTLINE (260)          │ CANVAS (flex, max 820 text)    │ INSPECTOR    │
│      │ 0 Title & control  92% │  3 TRIAL OBJECTIVES AND …      │ (360)        │
│      │ 1 Protocol summary  ◔  │  3.1 Primary Objective(s) …    │ Bindings     │
│      │ 2 Introduction     71% │  ┃ To evaluate the efficacy of │ Evidence     │
│      │ 3 Objectives ●2    64% │  ┃ <DRUG> vs placebo …         │ Findings (2) │
│      │ …                      │                                │ Comments     │
│      │ ───────────────────    │                                │ History      │
│      │ Overall 58% ▮▮▮▮▮░░░░  │                                │              │
└──────┴────────────────────────┴────────────────────────────────┴──────────────┘
```
- Outline rows: number, title, completion %, finding dots (● error, ◐ warning,
  ○ incomplete). Generated sections (1.1–1.3) show a "generated" glyph.
- Canvas: blocks have a 3-px left border coloured by provenance (none for
  author). Selected block gets `--accent-100` wash. Findings underline the
  offending span (wavy, coloured by severity). Placeholders `<…>` render in
  `--ink-soft` with grey shading exactly as M11 does.
- Inspector: tabs; empty states explain what would appear.

**Library / master sheet:** data-grid with sticky first column, row density
32 px, filter chips, column groups (Trial · Design · Endpoints · Results).

**Calculator:** two columns — inputs (form, left 380) and results (right):
headline N per arm, total, assumptions list, sensitivity heat-grid, historical
strip chart of the endpoint by drug.

**Comparator:** selected criterion on top, similar criteria list below as
two-column diffs; differences highlighted `--accent-100` background with
`--state-warning` underline for threshold/time/negation changes.

**Admin:** tabs Users · Works & permissions · Usage · Audit.

---

## 5. Components (kit)

| Component | Spec |
|---|---|
| Button | 32 px, radius 6, primary = accent fill/white text; secondary = hairline; destructive = `--state-error` outline; icon-only 32×32 |
| Chip | 20 px, radius 4, mono 11 for IDs; semantic chips carry a 6-px dot + label ("Proposed", "Source p.42", "Derived") |
| Finding row | severity icon · rule id (mono) · message · targets as chips · actions (Go to / Accept / Dismiss with reason) |
| Progress | 6 px bar; label "58% · 12 items remaining" always adjacent, clickable |
| Table | hairline rules, header `--slate-100`, numeric right-aligned tabular |
| Block (canvas) | left border by provenance; hover reveals ⋮ menu (Bind, View source, Mark N/A, History); drag handle |
| Question card (Ask/Minimise) | question · type control · "why we ask" (which blocks depend) · "merged from N" count |
| Diff | inline token diff; inserted = `--accent-100`, removed = strike `--slate-400`, changed threshold = `--state-warning` underline |
| Toast / status | bottom-left, `--slate-950` on dark; autosave "Saved 12 s ago · v0.3 draft" lives in top bar, not a toast |

Icons: Lucide, 16 px, 1.5 stroke. Motion: 120 ms ease-out for panels, none for
text; reduced-motion respected. Radius: 6 (controls), 8 (panels). Shadows:
none except popovers (`0 4px 16px rgba(15,23,32,.12)`).

---

## 6. Voice and microcopy

- Regulatory register, no exclamation marks, no "awesome".
- Never say "complete" for a percentage; say "58% · 12 items remaining".
- LLM output is always labelled "Proposed" with a one-line rationale and a
  "Why" link to the prompt/task record.
- Empty states tell the user the next action ("No findings yet — run checks
  or edit a block to trigger them.").

---

## 7. Accessibility

Keyboard-first editor (⌘/Ctrl-K command palette, `[`/`]` for previous/next
finding, `⌘/Ctrl-Shift-O` outline), focus rings in accent, ARIA landmarks per
pane, live region for autosave/validation status, colour never the only signal.
