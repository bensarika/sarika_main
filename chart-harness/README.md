# Chart harness 0.2

Every image-bearing stage in the standard CLI now requires a visual check authored by the exact same provider instance/model that performed that stage. A separate model call describes its own saved work. Python renders the annotations over the original image at fixed coordinates. No generated image pixels are used for measurement.

Run `python -m chart_harness run --help` for arguments. With dependencies available, an example is:

```
python -m chart_harness run --source chart.png --config configs/meta.json --out run01 --query "Observed PK measurements"
```

Supply `XAI_API_KEY` (`configs/grok.json`, xAI Responses API) or `META_API_KEY` (`configs/meta.json`, Muse Chat Completions) through the process environment. No keys are bundled. The example configurations include explicit per-role call/output-token budgets; annotation calls consume these budgets. The same API adapter supports Chat Completions and Responses. For exchange/replay operation, supply the primary response followed by its visual-check response for each image-bearing stage. Final output needs its own additional visual-check response. Existing pre-0.2 replay packets are not complete under this contract.

## Required visual checks

- Interpretation, review, page/layout selection and calibration image calls each receive a same-provider annotation stage.
- The final coordinate result receives an additional visual check by the interpretation model.
- Each fixed anchor must appear exactly once in annotation JSON. IDs and positions cannot be replaced by model-generated geometry.
- Source and rendered-image hashes accompany each visual check. Original images are untouched. Label text is laid out in a separate column to avoid covering the chart.
- Model concerns prevent whole-chart acceptance. Annotation failure, truncation, malformed output or exhausted budgets cannot silently finish a stage. Primary responses and failure records remain available for diagnosis/resume.
- A deleted/changed visual-check image is regenerated during resume using the same provider/cache rather than treated as present.
- `visual_checks/<role>/<stage>.png` and matching JSON contain the results. `result.json` lists the PNGs and includes the final visual check.

The raw Provider class is a low-level HTTP/replay primitive for testing. Application callers should use CLI `make_provider` or explicitly wrap it with VisualCheckProvider. Legacy experiment runners from earlier audit packages are not this revised workflow.

## Accuracy changes

The reviewer must independently report each observed marker's center. A missing center or separation over two pixels from the fixed candidate makes it unresolved. Coordinates from the reviewer are stored only in a separate audit; they never replace measured coordinates. This regression targets the Figure 12 false acceptance found in the Muse run. Agreement is still not proof that either model location is correct.

Bounded coarse ring search is enabled by default in the CLI to reduce poor local optima, while retaining the existing support thresholds. Axis-stroke snapping remains experimental and is not enabled automatically. Its helper no longer grants extrapolation permission merely because an outer tick is dropped. Normalized-coordinate conversion remains available as an experimental adapter; whole-panel normalized grounding did not solve the observed errors and is not silently enabled for all models.

This release does not claim to solve dense Figure 13A extraction. Model-authored overlays and model agreement are review aids, not ground truth.

## Deterministic axis tick cross-check

A tick residual test only shows that a reader's anchors are mutually consistent. A reader that shifts every anchor by the same amount still fits a straight line, and on the scanned Novartis IL-13xIL-18 patent (US20230357381A1, FIG. 7) both readers did exactly that: their anchors were internally consistent yet sat 83 px (x) and 195 px (y), respectively 22 px and 13 px, away from the printed ticks.

`axis_detect` therefore measures the axis rules and tick marks from the raw pixels and compares them with the reader's anchors. On a conclusive disagreement the harness runs one bounded repair call in which Python supplies the measured tick positions and the model only names the printed value of each tick; repaired anchors are snapped back onto detected ticks, so a globally shifted calibration cannot survive. The plot box is trimmed to the measured axis rules, which keeps tick labels outside the frame from being matched as markers. A remaining disagreement is recorded as `axis_agreement.detected_ticks` and withholds every row from `observed.csv`. Undetectable ticks are inconclusive, not evidence against the anchors, and do not gate export.

When the ticks are measured and agree with the anchors, that measurement outranks the reviewer's own re-reading of the same ticks: the reviewer's pixel-level axis disagreement is kept under `axis_agreement.<axis>.independent_review` instead of withholding rows. A reviewer that disagrees about the *kind* of axis (scale or unit) still blocks export.

Configuration: `detect_ticks`, `repair_axes_from_ticks`, `axis_tick_tolerance_px`, `clamp_plot_bbox_to_axes`.

## Batched review on original crops

One review call covering the whole figure is slow, easy to stall and
all-or-nothing: a single unfinished response discards the entire stage. Review is
therefore split into one calibration call on the full image plus one call per
small group of neighbouring candidates. Each of those calls receives exactly one
image: an unresampled crop of the original chart around that group, with the
candidate coordinates expressed in crop pixels, so the reply maps back by
translation alone and no generated overlay is ever measured. Batches are
individually cached stages, so a failed or slow batch only repeats itself.

A batch that does not accept everything it was shown, or an axis reader that
disagrees, keeps the whole review at `review_required`, and an undecided
candidate stays unresolved rather than becoming an exported row.

Configuration: `review_batch_size`, `review_batch_padding_px`,
`review_batch_min_side_px`, plus `model.timeout_s` as a wall-clock deadline for
each individual call.

## Cross-provider comparison

```
python -m chart_harness compare runs/grok_fig7 runs/meta_fig7 --out runs/consensus.json
```

Reports axis calibration, series label, per-point and coverage disagreement between two completed runs of the same figure. It never merges values or promotes a row that either run withheld: agreement is evidence for review, not proof, since both readers can share a bias.

## Tests

`python -m unittest discover -s tests`

The provider tests use a localhost HTTP stub and may need local socket permission. Tests cover resume, batch processing, annotation completeness, fixed anchors, failure records, independent-center disagreement, ring refinement and existing calibration/export behavior.
