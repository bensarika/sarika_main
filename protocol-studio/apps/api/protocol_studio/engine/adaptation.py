"""Adapt Starter: turn a starter written for one drug into proposals for the target drug(s).

This is deliberately *not* find-and-replace. Every sentence or model field that
mentions the source drug is classified:

    retain    the sentence does not depend on the molecule (disease background, GCP) → no change offered
    rewrite   the sentence is drug-agnostic apart from the name → name substituted, no evidence needed
    evidence  the sentence carries drug-specific facts (mechanism, dose, PK, class risks,
              Phase 1 results, IB references) → name substituted **and** an evidence
              requirement is opened; the author must confirm or supply the fact for the new drug
    remove    the sentence only makes sense for the source mechanism and the target has a
              different one (e.g. IL-13 pathway text when the target is not anti-IL-13)
    add       new drugs beyond the first get their own product entity and IB requirement

The classification is deterministic (keyword families below) so the same
starter and drugs always produce the same list; the model-assisted question
minimisation in Key Inputs sits on top, not underneath. Accepting a change
only replaces the text of that block (or that model field). Rejecting keeps
the source text and marks the block for author attention.
"""

from __future__ import annotations

import re
from typing import Any

from protocol_studio.engine.state import (
    Adaptation,
    AdaptationChange,
    Block,
    DraftState,
    DrugSpec,
    EvidenceRequirement,
)
from ps_model.paths import get_path, set_path

# Phrase families that make a sentence *drug-specific* (needs evidence for the new molecule).
_EVIDENCE_FAMILIES: dict[str, tuple[str, list[str]]] = {
    "mechanism": (
        "Mechanism of action for {drug}",
        [
            r"\bIL-13\b",
            r"\binterleukin",
            r"\bIL-4R",
            r"\breceptor\b",
            r"\bbinds?\b",
            r"\bsignall?ing\b",
            r"\bmonoclonal\b",
            r"\bhumani[sz]ed\b",
            r"\bmechanism\b",
            r"\btarget engagement\b",
        ],
    ),
    "dose": (
        "Dose, loading regimen and interval for {drug}",
        [
            r"\b\d+\s?mg\b",
            r"\bloading\b",
            r"\bQ2W\b",
            r"\bevery \d+ weeks?\b",
            r"\bdose[- ]response\b",
            r"\bexposure\b",
            r"\bprefilled\b",
            r"\bmg/mL\b",
        ],
    ),
    "clinical_evidence": (
        "Nonclinical and Phase 1 data for {drug} (Investigator's Brochure)",
        [
            r"\bPhase 1\b",
            r"\bInvestigator'?s Brochure\b",
            r"\bwell tolerated\b",
            r"\bperiostin\b",
            r"\bCCL17\b",
            r"\bpharmacokinetic",
            r"\bPK\b",
            r"\bhalf-li(?:fe|ves)\b",
        ],
    ),
    "class_risk": (
        "Class and molecule-specific risks for {drug} (conjunctivitis, injection-site, hypersensitivity)",
        [
            r"\bconjunctivitis\b",
            r"\bkeratitis\b",
            r"\binjection-site\b",
            r"\bhypersensitivity\b",
            r"\binfection\b.*\bmechanism\b",
            r"\bmechanism class\b",
        ],
    ),
}

# Sentences that are only meaningful for the source mechanism; offered as "remove" when the
# target mechanism differs.
_MECHANISM_ONLY = [r"\bIL-13 is a central mediator\b", r"\bprevents signalling through the IL-4Rα/IL-13Rα1\b"]

# Model paths whose *string value* can carry the source drug name.
_MODEL_TEXT_PATHS = [
    ("products[{pid}].name", "section.6"),
    ("products[{pid}].substance", "section.6"),
    ("regimens[reg_high].name", "section.6"),
    ("regimens[reg_low].name", "section.6"),
    ("paths[arm_high].name", "section.4"),
    ("paths[arm_low].name", "section.4"),
    ("objectives[obj_primary].clinical_question", "section.3"),
    ("objectives[obj_secondary].clinical_question", "section.3"),
    ("objectives[obj_safety].clinical_question", "section.3"),
    ("objectives[obj_pk].clinical_question", "section.3"),
    ("endpoints[pk_conc].name", "section.3"),
    ("assessments[pk].name", "section.8"),
    ("analysis_sets[pk_set].definition", "section.10"),
    ("estimands[est_primary].treatment_conditions.0.description", "section.3"),
    ("estimands[est_supp_policy].treatment_conditions.0.description", "section.3"),
    ("estimands[est_easi_pct].treatment_conditions.0.description", "section.3"),
    ("sources[ib_{pid}].name", "section.0"),
    ("protocol.purpose", "section.0"),
]


def _mentions(text: str, drug: str) -> bool:
    return re.search(rf"\b{re.escape(drug)}\b", text) is not None


def _families(text: str) -> list[str]:
    return [k for k, (_, pats) in _EVIDENCE_FAMILIES.items() if any(re.search(p, text, re.IGNORECASE) for p in pats)]


def _substitute(text: str, source: str, target: str) -> str:
    return re.sub(rf"\b{re.escape(source)}\b", target, text)


_GENERIC_MECHANISM_WORDS = {
    "monoclonal",
    "antibody",
    "anti",
    "inhibitor",
    "molecule",
    "small",
    "oral",
    "humanised",
    "humanized",
    "fully",
    "human",
}


def _same_mechanism(source_mech: str, target: DrugSpec) -> bool:
    """Share a *target* token (IL-13, OX40, JAK1) — not just the modality word (antibody)."""
    if not target.mechanism:
        return False

    def toks(s: str) -> set[str]:
        return {t.strip("-") for t in re.findall(r"[a-z0-9][a-z0-9-]*", s.lower().replace("anti-", ""))}

    specific = (toks(source_mech) & toks(target.mechanism)) - _GENERIC_MECHANISM_WORDS
    return any(len(tok) > 2 for tok in specific)


def build_adaptation(
    state: DraftState, *, source_drug: str, source_mechanism: str, targets: list[DrugSpec], actor: str, now: str
) -> Adaptation:
    if not targets:
        raise ValueError("at least one target drug is required")
    primary = targets[0]
    changes: list[AdaptationChange] = []
    requirements: list[EvidenceRequirement] = []
    req_by_key: dict[tuple[str, str], EvidenceRequirement] = {}

    def requirement(family: str, drug: DrugSpec) -> EvidenceRequirement:
        key = (family, drug.name)
        if key not in req_by_key:
            label_tpl = (
                _EVIDENCE_FAMILIES[family][0] if family in _EVIDENCE_FAMILIES else "Investigator's Brochure for {drug}"
            )
            kind = {
                "mechanism": "nonclinical",
                "dose": "clinical",
                "clinical_evidence": "investigator_brochure",
                "class_risk": "clinical",
            }.get(family, "investigator_brochure")
            r = EvidenceRequirement(
                id=f"req-{family}-{re.sub(r'[^a-z0-9]+', '', drug.name.lower())}",
                label=label_tpl.format(drug=drug.name),
                drug_name=drug.name,
                kind=kind,
                status="linked" if (family == "clinical_evidence" and drug.ib_source_id) else "open",
                source_id=drug.ib_source_id if family == "clinical_evidence" else None,
            )
            req_by_key[key] = r
            requirements.append(r)
        return req_by_key[key]

    same_mech = _same_mechanism(source_mechanism, primary)
    n = 0

    # ---- narrative blocks -------------------------------------------------------------
    for b in state.blocks:
        if not _mentions(b.text, source_drug) and not any(re.search(p, b.text) for p in _MECHANISM_ONLY):
            continue
        n += 1
        fams = _families(b.text)
        mech_only = any(re.search(p, b.text) for p in _MECHANISM_ONLY)
        proposed = _substitute(b.text, source_drug, primary.name)
        if primary.mechanism and source_mechanism:
            proposed = proposed.replace(source_mechanism, primary.mechanism)
        if mech_only and not same_mech:
            category = "remove"
            question = f"The mechanism text describes the {source_mechanism}. {primary.name} is described as {primary.mechanism or 'a different mechanism'}: replace this paragraph with the correct pathway description."
            proposed = ""
            reqs = [requirement("mechanism", primary)]
        elif fams:
            category = "evidence"
            question = _question_for(fams, primary)
            reqs = [requirement(f, primary) for f in fams]
        else:
            category = "rewrite"
            question = ""
            reqs = []
        changes.append(
            AdaptationChange(
                id=f"chg-{n:03d}",
                kind="block",
                category=category,
                section_id=b.section_id,
                subsection_id=b.subsection_id,
                block_id=b.id,
                source_text=b.text,
                proposed_text=proposed,
                clinical_question=question,
                evidence_needed=[r.label for r in reqs],
                requirement_ids=[r.id for r in reqs],
                drug_names=[primary.name],
            )
        )

    # ---- model fields -----------------------------------------------------------------
    source_pid = _source_product_id(state.model, source_drug)
    for tpl, section in _MODEL_TEXT_PATHS:
        path = tpl.format(pid=source_pid or "adx101")
        val = get_path(state.model, path, None)
        if not isinstance(val, str) or not _mentions(val, source_drug):
            continue
        n += 1
        new_val = _substitute(val, source_drug, primary.name)
        if primary.mechanism and source_mechanism:
            new_val = new_val.replace(source_mechanism, primary.mechanism)
        changes.append(
            AdaptationChange(
                id=f"chg-{n:03d}",
                kind="model",
                category="rewrite",
                section_id=section,
                path=path,
                source_text=val,
                proposed_text=new_val,
                proposed_value=new_val,
                drug_names=[primary.name],
            )
        )

    # ---- additional drugs → add product + IB requirement ---------------------------------
    for extra in targets[1:]:
        n += 1
        r = requirement("clinical_evidence", extra)
        pid = re.sub(r"[^a-z0-9]+", "_", extra.name.lower()).strip("_")
        changes.append(
            AdaptationChange(
                id=f"chg-{n:03d}",
                kind="model",
                category="add",
                section_id="section.6",
                path=f"products[{pid}]",
                source_text="",
                proposed_text=f"Add {extra.name} ({extra.mechanism or extra.role}) as a study product with its own regimen, arm and evidence dependency.",
                proposed_value={
                    "id": pid,
                    "name": extra.name,
                    "role": extra.role,
                    "substance": f"{extra.name} ({extra.mechanism})" if extra.mechanism else extra.name,
                    "route": "subcutaneous",
                },
                clinical_question=f"Which regimen and arm does {extra.name} receive, and is it compared with {primary.name}, placebo or both?",
                evidence_needed=[r.label],
                requirement_ids=[r.id],
                drug_names=[extra.name],
            )
        )

    # Every drug needs an IB regardless of what the text mentioned.
    for d in targets:
        requirement("clinical_evidence", d)

    return Adaptation(
        source_drug=source_drug,
        source_mechanism=source_mechanism,
        target_drugs=targets,
        changes=changes,
        requirements=requirements,
        started_by=actor,
        started_at=now,
    )


def _question_for(fams: list[str], drug: DrugSpec) -> str:
    parts = []
    if "mechanism" in fams:
        parts.append(f"Confirm the mechanism description applies to {drug.name}.")
    if "dose" in fams:
        parts.append(
            f"Dose, loading and interval must come from {drug.name}'s own PK/PD; the source numbers are placeholders."
        )
    if "clinical_evidence" in fams:
        parts.append(f"Replace Phase 1 / IB statements with {drug.name}'s data.")
    if "class_risk" in fams:
        parts.append(f"Confirm which class risks apply to {drug.name} and add molecule-specific ones.")
    return " ".join(parts)


def _source_product_id(model: dict[str, Any], source_drug: str) -> str | None:
    for p in model.get("products") or []:
        if isinstance(p, dict) and p.get("name") == source_drug:
            pid = p.get("id")
            return str(pid) if pid is not None else None
    return None


def apply_decision(state: DraftState, change_id: str, decision: str, *, actor: str, now: str) -> str:
    """Accept or reject one change. Accepting a block change replaces only that block's text."""
    if state.adaptation is None:
        raise KeyError("no adaptation in progress")
    ch = state.adaptation.change(change_id)
    ch.decision = decision
    ch.decided_by = actor
    if decision != "accepted":
        return f"Rejected adaptation change {ch.id} ({ch.category})"
    if ch.kind == "block" and ch.block_id:
        b = state.block(ch.block_id)
        if ch.category == "remove":
            state.blocks = [x for x in state.blocks if x.id != b.id]
            return f"Removed block {b.id} ({ch.subsection_id}) per adaptation"
        b.text = ch.proposed_text
        b.provenance = "generated"
        b.approval = "unreviewed"
        b.updated_by, b.updated_at = actor, now
        return f"Adapted block {b.id} in {ch.subsection_id} for {', '.join(ch.drug_names)}"
    if ch.kind == "model" and ch.path:
        if ch.category == "add" and isinstance(ch.proposed_value, dict):
            coll = state.model.setdefault("products", [])
            if not any(isinstance(x, dict) and x.get("id") == ch.proposed_value["id"] for x in coll):
                coll.append(dict(ch.proposed_value))
            return f"Added product {ch.proposed_value['name']} per adaptation"
        set_path(state.model, ch.path, ch.proposed_value)
        return f"Adapted {ch.path} for {', '.join(ch.drug_names)}"
    raise KeyError(f"change {change_id} cannot be applied")


def adaptation_summary(a: Adaptation | None) -> dict[str, Any]:
    if a is None:
        return {"active": False}
    by_cat: dict[str, int] = {}
    for c in a.changes:
        by_cat[c.category] = by_cat.get(c.category, 0) + 1
    pending = sum(1 for c in a.changes if c.decision == "pending")
    open_reqs = sum(1 for r in a.requirements if r.status == "open")
    return {
        "active": True,
        "source_drug": a.source_drug,
        "target_drugs": [d.model_dump() for d in a.target_drugs],
        "total": len(a.changes),
        "pending": pending,
        "accepted": sum(1 for c in a.changes if c.decision == "accepted"),
        "rejected": sum(1 for c in a.changes if c.decision == "rejected"),
        "by_category": by_cat,
        "open_requirements": open_reqs,
        "complete": pending == 0,
    }


def blocks_for_drug_mentions(blocks: list[Block], drug: str) -> list[str]:
    return [b.id for b in blocks if _mentions(b.text, drug)]
