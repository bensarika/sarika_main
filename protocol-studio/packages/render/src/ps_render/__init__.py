"""ps_render — model + blocks -> Render AST -> LaTeX/PDF and DOCX.

Pipeline (docs/01_architecture.md §6.8):

    build_ast(model, blocks, meta)  -> Document (pure, deterministic)
    to_latex(doc)                   -> str      (deterministic; golden-file tested)
    to_docx(doc, path)              -> file     (python-docx; heading styles checked)
    compile_pdf(latex, workdir)     -> path     (Tectonic; skipped when binary is absent)

Both exporters consume the same AST so headings, tables and numbering cannot
diverge between PDF and DOCX. Model-derived views (synopsis, schema, schedule
of activities) are generated here from the model, never typed by hand.
"""

from ps_render.ast import Block, Document, Heading, Paragraph, Table
from ps_render.build import RenderMeta, build_ast
from ps_render.docx_writer import to_docx
from ps_render.latex import compile_pdf, tectonic_available, to_latex

__all__ = [
    "Block",
    "Document",
    "Heading",
    "Paragraph",
    "RenderMeta",
    "Table",
    "build_ast",
    "compile_pdf",
    "tectonic_available",
    "to_docx",
    "to_latex",
]
