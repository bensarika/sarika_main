# Harness revision 0.2

The standard CLI now requires a same-model annotated visual check for every image-bearing model stage and for the final coordinate output. The model supplies the annotations; deterministic rendering preserves the source image and fixed point coordinates. The PNG, annotation JSON, source hash and image hash are saved. Missing or invalid annotations leave the stage incomplete. These calls count against explicit budgets, including on exchange/replay workflows.

Reviewers must independently report marker centers. Missing centers or a discrepancy over two pixels downgrade an observation to unresolved. The reported centers are audit evidence only and cannot replace measured coordinates. A regression test covers the roughly 30-pixel Figure 12 mismatch that previously passed.

Bounded coarse ring search is enabled in the CLI. Axis snapping remains experimental and no longer grants extrapolation merely because a tick is dropped. Model concerns prevent whole-chart acceptance. Resume checks that mandatory visual files still exist and match their hashes.

Validation: 63 tests passed, covering the existing suite plus annotation completeness, immutable anchors and independent-center disagreement. A real Muse Spark 1.3 call produced the bundled visual-check example from its saved extraction. This was an annotation-stage integration check, not a new full extraction. It still did not recognize the previously identified misplaced point; an annotated image is a review aid, not proof of correctness.

The ZIP includes the revised source, tests, Meta/Grok example configurations, README, test log and live annotation evidence. No credentials are included. The original harness and earlier experiment results remain unchanged. Use the revised CLI or VisualCheckProvider wrapper; low-level Provider and old experiment scripts do not implement the complete required workflow.

Dense Figure 13A extraction is still unresolved. This revision improves auditability and prevents some false acceptances; it does not claim full extraction accuracy.
