# ps_render — one AST, LaTeX/PDF and DOCX out

Renders a draft (model + authored blocks) into an exporter-neutral AST, then
into deterministic LaTeX (compiled with Tectonic) and DOCX (python-docx). One
AST guarantees the two exports never disagree about content or order.

Design (docs/01_architecture.md §7): model-derived views (synopsis, endpoint
tables, allocation, schedule of activities, analysis sets) are **generated from
the authoritative model**; authored narrative blocks are rendered as-is with
their claim states annotated; missing content is shown explicitly rather than
silently dropped, so a reviewer can see what is not there yet.

## Modules

| Module | Purpose |
| --- | --- |
| `ast.py` | `Document`, `Heading`, `Paragraph` (with `runs` for inline claim marks), `BulletList`, `Table`, `Note` (`kind`: missing / mismatch / unbound / generated). |
| `build.py` | `build_ast(model, blocks, RenderMeta)` walks the 15-entry outline: for each subsection emits generated blocks from the model collections it owns, then the approved/unreviewed authored blocks. Claims in `mismatch`/`unbound` state become inline marks + a `Note`. |
| `latex.py` | `to_latex(doc)` (article class, `\setcounter{tocdepth}{1}`, escaped text, longtable tables); `compile_pdf(latex, workdir)` shells out to Tectonic; `tectonic_available()` for graceful degradation. Output is byte-stable for the same input (golden-file tested). |
| `docx_writer.py` | `to_docx(doc, path)` — navigable headings (Word outline levels), grid tables, coloured claim marks, page break after the title block. |

## Usage

```python
from ps_render.build import RenderMeta, build_ast
from ps_render.latex import to_latex, compile_pdf, tectonic_available
from ps_render.docx_writer import to_docx

doc = build_ast(model, blocks, RenderMeta(version_label="v0.3", generated_at="2026-09-06T21:00Z", watermark="DRAFT"))
tex = to_latex(doc)
if tectonic_available():
    pdf = compile_pdf(tex, workdir)
to_docx(doc, workdir / "protocol.docx")
```

## Tests

`packages/render/tests/test_render.py` — every outline section appears; missing
content produces notes; mismatched claims are annotated; empty model renders;
LaTeX escaping; golden LaTeX (`tests/golden/*.tex`); DOCX structure; PDF
compile when Tectonic is on PATH (skipped otherwise).

## Notes for maintainers

- Tectonic downloads packages on first run; CI caches `~/.cache/Tectonic`.
- Keep `to_latex` free of timestamps except via `RenderMeta.generated_at` so
  golden files stay stable.
- Add a new generated view by writing a `_xxx(model) -> Iterable[Block]` in
  `build.py` and mapping it to the subsection in `_subsection_body`.
