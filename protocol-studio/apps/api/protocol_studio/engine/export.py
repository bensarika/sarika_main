"""Export a draft state to LaTeX / PDF / DOCX and hash the artifacts.

Artifacts for a *working draft* are rendered on demand into
``data/exports/<work>/rev-<n>/`` and carry a DRAFT label; artifacts for a
*frozen version* are rendered once at freeze time into
``data/versions/<work>/<label>/`` and their SHA-256 is stored on the version.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from protocol_studio.engine.state import DraftState
from protocol_studio.settings import settings
from ps_render import RenderMeta, build_ast, compile_pdf, tectonic_available, to_docx, to_latex


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def render_all(
    state: DraftState, *, out_dir: Path, version_label: str, want_pdf: bool = True
) -> dict[str, dict[str, Any]]:
    """Render .tex, .docx and (when Tectonic is present) .pdf. Returns {kind: {path, sha256}}."""
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = RenderMeta(version_label=version_label, generated_at=datetime.now(UTC).date().isoformat())
    doc = build_ast(state.model, [b.model_dump() for b in state.blocks], meta)
    latex = to_latex(doc)
    tex_path = out_dir / "protocol.tex"
    tex_path.write_text(latex, encoding="utf-8")
    artifacts: dict[str, dict[str, Any]] = {"tex": {"path": str(tex_path), "sha256": _sha256(tex_path)}}
    docx_path = to_docx(doc, out_dir / "protocol.docx")
    artifacts["docx"] = {"path": str(docx_path), "sha256": _sha256(docx_path)}
    if want_pdf and tectonic_available():
        pdf_path = compile_pdf(latex, out_dir)
        artifacts["pdf"] = {"path": str(pdf_path), "sha256": _sha256(pdf_path)}
    elif want_pdf:
        artifacts["pdf"] = {"path": None, "sha256": None, "error": "tectonic not installed"}
    return artifacts


def draft_export_dir(work_id: str, revision: int) -> Path:
    return settings.data_dir / "exports" / work_id / f"rev-{revision}"


def version_export_dir(work_id: str, label: str) -> Path:
    return settings.data_dir / "versions" / work_id / label
