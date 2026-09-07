<!-- Produced by the Devin data-analysis child session https://app.devin.ai/sessions/59d898bfba664e018b4521fbb163a083 (pandas/matplotlib, illustrative CSV). The mock SVG port is histChartHtml() in mock/app.js. -->

# Trial calculator — historical EASI-75 chart: recommendation

Dataset: `historical_easi75.csv` (8 arm-level rows → 5 trials; 3 comparable, 2 excluded). Endpoint EASI-75 at Week 16.
User assumption under test: SRK-201, placebo 16.0 % → active 45.0 % (Δ +29.0 pts).
All figures rendered by `viz.py` (pandas + matplotlib/seaborn) at 1400×700 px unless noted.

## TL;DR

| Slot | Chart | File |
|---|---|---|
| **Default view** | Dumbbell (placebo → active per trial) with user-assumption row on top, pooled-placebo band, Δ + 95 % CI on the connector | `final_default_dumbbell.png` |
| Secondary: "Treatment effect" | Forest plot of Δ with Newcombe 95 % CI, n-scaled markers, user Δ as dashed amber line, numeric table on the right | `final_secondary_treatment_effect.png` |
| Secondary: "Placebo only" | Placebo lollipop/forest with Wilson 95 % CIs and the pooled estimate band (CI + observed range) | `final_secondary_placebo_pooled.png` |
| Optional wide layout (≥1400 px) | Dumbbell + Δ-forest side by side, sharing rows | `final_two_panel_dumbbell_plus_effect.png` |

Keep v2's three-tab structure (by study / treatment effect / placebo only) — the *information architecture* is right; the *encodings* are what change.

---

## 1. Candidates tried (what each makes easy / what it hides)

| # | File | Makes easy | Hides / costs |
|---|---|---|---|
| 1 | `cand1_grouped_bars_delta.png` — grouped horizontal bars (placebo bar over active bar) with Δ bracket | Absolute magnitude of each arm; familiar to anyone who has read a CSR. Closest to v2, so cheapest to port. | Two bars per trial doubles vertical space, so 5 trials already fill the panel; Δ is read as a bar-length difference, which is imprecise; the user's assumption has to become two more bars and competes visually with data. |
| **2** | `cand2_dumbbell.png` — one row per trial, grey placebo dot → coloured active dot | Placebo level, active level **and** Δ (connector length) in a single glyph per row; the user's row reads as "one more trial" so comparison is immediate; the pooled-placebo band lines up all placebo dots; half the vertical footprint of bars. | Uncertainty (CI) is only shown as text on the connector; placebo-only trials leave a "stub" that needs an explanatory note. |
| **3** | `cand3_forest_effect.png` — forest plot of Δ with 95 % CI, marker area ∝ total n | Direct answer to "is my Δ plausible?" — the user's dashed line either sits inside or outside each CI. Uncertainty is honest (JADE MONO-1 with n=231 has a much wider CI than Measure Up 1 with n=566). | Absolute placebo/active levels are only in the side table; placebo-only trials disappear (no Δ) and must be sign-posted to the placebo view. |
| **4** | `cand4_placebo_lollipop_pooled.png` — placebo rates with Wilson CIs and pooled band | The "what placebo did and how much it varied" question in one look: pooled 16.5 % (CI 13.7–19.6, n=601) vs every arm's own CI; excluded arms visibly *not* in the band's computation. | Says nothing about active arms or effect size. |
| 5 | `cand5_slope.png` — two columns (placebo, active), one sloped line per trial | Slope = effect size is intuitive; the fan-out of active arms is striking. | Placebo values cluster in 11.8–16.3 %, so left-hand labels collide and need leader lines; excluded/comparable status is hard to see in a line; poor fit for a wide, short panel (needs height). **Rejected.** |
| 6 | `cand6_small_multiples.png` — one mini bar panel per trial | Each trial is self-contained; exclusion reason lives in the title. | Cross-trial comparison forces the eye to jump between panels and re-read the y-axis; the user's assumption becomes 5 repeated lines; scales badly beyond ~6 trials. **Rejected.** |

## 2. Why the dumbbell is the default

It is the only form that answers all four questions on one screen without a table:

1. *Placebo level & spread* — all grey dots share the same x-axis; the teal band spans the comparable placebo range (14.7–21.0 %) with a dotted line at the pooled 16.5 %.
2. *Active level & Δ* — coloured dot + connector; Δ and 95 % CI printed on the connector.
3. *Comparable vs excluded* — excluded rows sit below a labelled dashed divider, are faded to 38 % opacity, hatched, dashed connectors, with the exclusion reason printed in red-orange under the trial name. They cannot be misread as peers.
4. *User vs history* — the user's assumption is the top row in amber, drawn with the same glyph; the eye compares its connector to those directly beneath. It also has to sit inside the pooled band (it does: 16.0 % vs 14.7–21.0 %).

The colour-vision-deficiency simulation (`final_default_dumbbell_cvd_check.png`; deuteranopia/protanopia/tritanopia) shows all four hues remain separable. Placebo grey was lightened to `#9CA3AF` for this reason: at `#6B7280` it collapsed onto teal under deuteranopia. Redundant encodings are also present (JAK-like = violet **and** diamond; excluded = faded **and** hatched **and** dashed **and** labelled; user = amber **and** open circle).

## 3. Ordering rules (apply in every view)

```
1. User assumption row first (pinned), then a slightly larger gap.
2. Comparable trials WITH an active arm, sorted by Δ descending.
3. Comparable placebo-only trials (no Δ yet), sorted by placebo % descending.
4. Divider: "EXCLUDED FROM POOLING — shown for context, not equivalent".
5. Excluded trials, same sort (Δ desc, then placebo % desc).
```

Placebo-only view: replace 2–3 with "comparable arms by placebo % descending".
Never interleave excluded and comparable rows, and never sort excluded rows above comparable ones even if their Δ is larger (JADE MONO-1's +50.9 would otherwise land second).

## 4. Labelling rules

- Row label, two lines: **Trial name** (bold) / `dose · MoA · Phase · timepoint` (muted). Excluded rows add a third line `excluded: <reason>` in red-orange italic.
- Every mark carries `xx.x%  n=NNN` (one decimal, explicit n). Placebo label sits left of the dot; active label right of the dot. If placebo < 13 % the label flips to right-above to avoid running off the axis.
- Δ label on the connector: `Δ +36.6 pts   (95% CI +28.2 to +44.2)`. Always signed, always "pts", never bare numbers.
- User row label: `Your assumption · SRK-201` / `placebo 16.0% → active 45.0%`. Never a bare "Result".
- Pooled caption above the band: `pooled placebo 16.5% · 3 comparable arms, n=601, range 14.7–21.0%`.
- Source page as a monospace `p.41` in a right gutter — in the web app make it the click target that opens the PDF at that page.
- Placebo-only rows: italic grey note `active arm not yet extracted` where the connector would be; in the Δ view: `no Δ (active arm not extracted)`.
- Axis titles spelled out: `Participants reaching EASI-75 (%)`, `Treatment effect: active − placebo (percentage points), 95% CI (Newcombe)`.
- Legend items spelled out: `placebo arm`, `active arm`, `active arm, JAK-like profile`, `your assumption`, `pooled placebo range`, `excluded from pooling`.

## 5. Encoding tokens (CSS variables)

```css
--placebo: #9CA3AF;        /* grey-400 dot fill  */
--placebo-text: #374151;   /* grey-700 labels    */
--active: #0F766E;         /* teal-700           */
--jak: #6D28D9;            /* violet-700, diamond marker */
--user: #B45309;           /* amber-700, open circle + dashed */
--pooled-band: #CCFBF1;    /* teal-100, 60% opacity */
--excluded-text: #C2410C;  /* orange-700 */
--excluded-opacity: 0.38;  /* plus 45° hatch, plus dashed connector */
--separator: #D1D5DB;
```

Marker size: **area ∝ n**, `area_pt2 = 30 + 0.55·n` → radius `r = sqrt(area/π)`; in SVG, `r_px ≈ 0.6 · sqrt(30 + 0.55·n)`. n=52 → 7.7 px, n=285 → 11.6 px. Area (not radius) is the perceptually honest choice; the explicit `n=` label carries the exact value.

## 6. What the current v2 does wrong

1. **Excluded rows look identical to included ones.** Abrocitinib (W12) and Lebrikizumab (TCS/OCR-unreviewed) get the same solid bars and only a small red caption; a hurried reader pools them mentally. Fix: divider + fade + hatch + dashed connector + reason line.
2. **No uncertainty.** A 62.7 % on n=154 is displayed like a 79.7 % on n=285. Fix: Wilson CIs on arms, Newcombe CI on Δ, marker area ∝ n.
3. **No placebo variability summary.** The question "how much did placebo vary?" has no answer on screen. Fix: pooled estimate (n-weighted, comparable arms only) with CI and observed range as a band behind every view.
4. **User assumption is a caption, not a mark.** v2 prints the target in the title; it never touches the data. Fix: draw it as a row/reference line using the same glyph.
5. **Vague labels.** "Result", "Trial 1/2/3", untitled axes. Fix: rules in §4.
6. **Ordering is arbitrary (row order of the CSV).** Fix: §3.
7. **Grouped bars waste height.** Two bars per trial means 6 trials fill the panel; the dumbbell fits ~12 rows in the same 700 px.
8. **Source page missing.** A statistician will want to verify the extracted number; `p.#` in a gutter makes that one click.

## 7. Statistics used

```python
def wilson_ci(p_pct, n, z=1.959964):
    p = p_pct / 100
    denom = 1 + z**2 / n
    centre = (p + z**2 / (2*n)) / denom
    half = z * sqrt(p*(1-p)/n + z**2/(4*n**2)) / denom
    return 100*(centre-half), 100*(centre+half)

def newcombe_diff_ci(p1, n1, p2, n2):          # active − placebo
    l1, u1 = wilson_ci(p1, n1); l2, u2 = wilson_ci(p2, n2)
    d = p1 - p2
    return d - sqrt((p1-l1)**2 + (u2-p2)**2), d + sqrt((u1-p1)**2 + (p2-l2)**2)

# pooled placebo: n-weighted mean over COMPARABLE placebo arms only
rate = Σ(pct_i · n_i) / Σ n_i           # 16.45 % over n=601
lo, hi = wilson_ci(rate, Σ n_i)         # 13.7–19.6 %
band  = [min(pct_i), max(pct_i)]        # 14.7–21.0 % (default view uses the range; placebo view shows both)
```

Derived values for the front-end fixtures:

| Trial | Placebo % (n) | Active % (n) | Δ pts (95 % CI) | Status | p. |
|---|---|---|---|---|---|
| Upadacitinib Measure Up 1 | 16.3 (281) | 79.7 (285) JAK | +63.4 (+56.5 to +69.1) | comparable | 41 |
| Dupilumab SOLO 1 | 14.7 (224) | 51.3 (224) | +36.6 (+28.2 to +44.2) | comparable | 28 |
| Temtokibart P2b | 21.0 (96) | — | — | comparable, placebo only | 88 |
| Abrocitinib JADE MONO-1 | 11.8 (77) | 62.7 (154) JAK | +50.9 (+38.9 to +60.0) | excluded: W12, not W16 | 55 |
| Lebrikizumab P2b | 24.3 (52) | — | — | excluded: TCS background; OCR 0.83 unreviewed | 12 |

## 8. Geometry of the default view (for the SVG port)

Row layout (y in row units, top → bottom):

```python
def y_layout(order, with_user, gap=0.7):
    pos, y = {}, 0.0
    if with_user:
        pos["USER"] = y
        y -= 1.25  # user row + a slightly larger gap
    seen_excluded = False
    for i, row in enumerate(order):
        if not row.comparable and not seen_excluded:
            y -= gap
            seen_excluded = True  # divider sits at pos[i] + 0.5 + gap/2
        pos[i] = y
        y -= 1.0
    return pos
```

Per row (x-axis 0–100 %):

```python
# pooled band (behind everything)
rect(x=pooled.min_rate, w=pooled.max_rate-pooled.min_rate, fill=teal-100, opacity=.6); vline(pooled.rate, dotted teal)

for row, y in rows:
    a = 1.0 if row.comparable else 0.38
    # placebo Wilson CI whisker (thin grey), then connector, then dots on top
    hline(row.placebo_lo → row.placebo_hi, y, grey, lw=1.2, opacity=a*.7)
    if row.has_active:
        hline(row.placebo_pct → row.active_pct, y, colour=jak?violet:teal, lw=2.6, dash=none if comparable else "6 4", opacity=a)
        text(mid, y+0.22, f"Δ {Δ:+.1f} pts   (95% CI {lo:+.1f} to {hi:+.1f})", bold if comparable)
        marker(row.active_pct, y, shape=jak?diamond:circle, area=30+0.55*active_n, fill=colour, hatch if excluded)
        text(active_pct + 1.5, y, f"{active_pct:.1f}%  n={active_n}", colour)
    else:
        text(row.placebo_hi + 1.5, y, "active arm not yet extracted", italic faint)
    circle(row.placebo_pct, y, area=30+0.55*placebo_n, fill=grey-400, stroke white, hatch if excluded)
    text(row.placebo_pct − 1 − r, y, f"{placebo_pct:.1f}%  n={placebo_n}", right-aligned, grey-700)   # flips right-above if < 13 %
    gutter_text(1.005, y, f"p.{source_page}", mono, faint)

# user row (y=0): same geometry, open amber circle at 16.0, filled amber circle at 45.0, connector amber lw=2.6,
#                 label "Δ +29.0 pts" above the connector.
# divider: dashed grey line + red-orange small-caps "EXCLUDED FROM POOLING — shown for context, not equivalent"
```

Figure margins used for the 1400×700 PNG: left 0.285, right 0.945, top 0.85, bottom 0.15 (left gutter holds the two-line row labels, right gutter the `p.#`).

## 9. Reproduce

```bash
pip install pandas matplotlib seaborn
python viz.py            # candidates + finals → out/
python viz.py --only final
python cvd_check.py out/final_default_dumbbell.png   # colour-vision-deficiency check
```

Full source: `viz.py` (attached).
