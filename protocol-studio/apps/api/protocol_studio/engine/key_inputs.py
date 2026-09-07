"""Key Inputs: the shortest list of grouped questions whose answers fill the model.

Each question binds to one or more model paths. A question is *answered* when the
author has recorded a value (``DraftState.key_inputs``) or the bound model value
already satisfies it (e.g. inherited from a reviewed starter and confirmed at
adaptation). Answering writes the value through to every bound path, so
narrative claims bound to the same paths flip to *mismatch* and the affected
sections are listed for review — that is how "linked-section impacts" are
computed, deterministically, rather than guessed.

Conditional follow-ups (``depends_on``) only appear when their trigger answer
is present, which is how the list stays short: choosing a composite rescue
strategy asks which events count as non-response; choosing hypothetical asks
for the imputation assumption instead.

The model-assisted minimisation described in the architecture (an LLM
collapsing an adaptation's open questions into fewer key inputs) would *add*
questions to this catalogue for a study; it never bypasses the bindings.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from protocol_studio.engine.state import DraftState, KeyInputAnswer
from ps_model.paths import get_path, set_path

Writer = Callable[[dict[str, Any], Any], list[str]]  # (model, value) -> written paths


@dataclass(frozen=True)
class Option:
    value: str
    label: str
    help: str = ""


@dataclass(frozen=True)
class Question:
    id: str
    group: str
    label: str
    help: str
    input_type: str  # text | number | select | boolean | multiselect
    read_path: str | None  # where the current value lives (None → answer only)
    writer: Writer
    linked_sections: tuple[str, ...]
    required: bool = True
    options: tuple[Option, ...] = ()
    unit: str = ""
    depends_on: tuple[str, str] | None = None  # (question_id, value) that must match
    minimum: float | None = None
    maximum: float | None = None
    normalize: Callable[[Any], Any] = field(default=lambda v: v)
    # Starter values for these are placeholders once a different drug is substituted; the author
    # must re-enter (or explicitly confirm) them after an adaptation.
    confirm_after_adaptation: bool = False


def _set(*paths: str) -> Writer:
    def w(model: dict[str, Any], value: Any) -> list[str]:
        for p in paths:
            set_path(model, p, value)
        return list(paths)

    return w


def _primary_timepoint(model: dict[str, Any], weeks: Any) -> list[str]:
    wk = int(weeks)
    previous = get_path(model, "periods[treatment].duration.value", None)
    written: list[str] = []
    for ep in model.get("endpoints") or []:
        t = ep.get("time") if isinstance(ep, dict) else None
        if (
            isinstance(t, dict)
            and t.get("anchor_id") == "randomization"
            and isinstance(t.get("offset"), dict)
            and t["offset"].get("unit") == "week"
            and t["offset"].get("value") == previous
        ):
            t["offset"]["value"] = wk
            written.append(f"endpoints[{ep['id']}].time.offset.value")
    set_path(model, "periods[treatment].duration.value", wk)
    written.append("periods[treatment].duration.value")
    for enc in model.get("encounters") or []:
        if isinstance(enc, dict) and "primary endpoint" in str(enc.get("name", "")):
            enc["time"]["offset"]["value"] = wk
            enc["name"] = f"Week {wk} (primary endpoint)"
            written.append(f"encounters[{enc['id']}].time.offset.value")
    return written


def _rescue_strategy(model: dict[str, Any], value: Any) -> list[str]:
    strategy = str(value)
    definitions = {
        "composite": "Participants who take qualifying rescue before the primary timepoint are counted as non-responders.",
        "treatment_policy": "The observed outcome at the primary timepoint is used regardless of rescue.",
        "hypothetical": "Measurements after qualifying rescue are set to missing and imputed under the assumption that rescue had not been taken.",
    }
    actions = {"composite": "set_nonresponse", "treatment_policy": "use_observed", "hypothetical": "replace_value"}
    written: list[str] = []
    for est in model.get("estimands") or []:
        if isinstance(est, dict) and est.get("role") == "primary":
            for ies in est.get("intercurrent_event_strategies") or []:
                if ies.get("event_id") == "qualifying_rescue":
                    ies["strategy"] = strategy
                    ies["definition"] = definitions[strategy]
                    written.append(f"estimands[{est['id']}].intercurrent_event_strategies.0.strategy")
    for an in model.get("analyses") or []:
        if isinstance(an, dict) and an.get("role") == "primary":
            for peh in an.get("post_event_handling") or []:
                if peh.get("event_id") == "qualifying_rescue":
                    peh["action"] = actions[strategy]
                    written.append(f"analyses[{an['id']}].post_event_handling.0.action")
    return written


def _allocation(model: dict[str, Any], value: Any) -> list[str]:
    weights = [int(x) for x in str(value).split(":")]
    alloc = get_path(model, "allocations[rand]")
    choices = alloc.get("choices") or []
    if len(weights) != len(choices):
        raise ValueError(f"allocation has {len(choices)} arms; ratio {value} names {len(weights)}")
    for c, w in zip(choices, weights, strict=True):
        c["weight"] = w
    alloc["name"] = f"Randomization {value}"
    return ["allocations[rand].choices", "allocations[rand].name"]


def _dose(regimen_id: str, admin_index: int, label_tpl: str) -> Writer:
    def w(model: dict[str, Any], value: Any) -> list[str]:
        mg = float(value)
        mg_i = int(mg) if mg.is_integer() else mg
        set_path(model, f"regimens[{regimen_id}].administrations.{admin_index}.dose.value", mg_i)
        set_path(model, f"regimens[{regimen_id}].name", label_tpl.format(mg=mg_i, drug=_ip_name(model)))
        return [f"regimens[{regimen_id}].administrations.{admin_index}.dose.value", f"regimens[{regimen_id}].name"]

    return w


def _ip_name(model: dict[str, Any]) -> str:
    for p in model.get("products") or []:
        if isinstance(p, dict) and p.get("role") == "investigational":
            return str(p.get("name", "Investigational product"))
    return "Investigational product"


def _study_code(model: dict[str, Any], value: Any) -> list[str]:
    ids = model.setdefault("protocol", {}).setdefault("study_identifiers", [])
    for entry in ids:
        if entry.get("system") == "sponsor":
            entry["value"] = str(value)
            return ["protocol.study_identifiers"]
    ids.append({"system": "sponsor", "value": str(value)})
    return ["protocol.study_identifiers"]


def _follow_up(model: dict[str, Any], value: Any) -> list[str]:
    wk = int(value)
    set_path(model, "periods[follow_up].duration.value", wk)
    written = ["periods[follow_up].duration.value"]
    for enc in model.get("encounters") or []:
        if isinstance(enc, dict) and enc.get("period_id") == "follow_up" and isinstance(enc.get("time"), dict):
            enc["time"].setdefault("offset", {"unit": "week"})["value"] = wk
            written.append(f"encounters[{enc['id']}].time.offset.value")
    for ep in model.get("endpoints") or []:
        if isinstance(ep, dict) and isinstance(ep.get("time"), dict) and ep["time"].get("anchor_id") == "last_dose":
            ep["time"].setdefault("offset", {"unit": "week"})["value"] = wk
            written.append(f"endpoints[{ep['id']}].time.offset.value")
    return written


def _composite_events(model: dict[str, Any], value: Any) -> list[str]:
    chosen = [str(v) for v in (value or [])]
    written: list[str] = []
    for est in model.get("estimands") or []:
        if isinstance(est, dict) and est.get("role") == "primary":
            keep = [
                s for s in est.get("intercurrent_event_strategies") or [] if s.get("event_id") == "qualifying_rescue"
            ]
            for ev in chosen:
                if ev == "qualifying_rescue":
                    continue
                keep.append(
                    {
                        "event_id": ev,
                        "strategy": "composite",
                        "definition": f"Participants with {ev.replace('_', ' ')} before the primary timepoint are counted as non-responders.",
                    }
                )
            est["intercurrent_event_strategies"] = keep
            written.append(f"estimands[{est['id']}].intercurrent_event_strategies")
    return written


def _imputation_assumption(model: dict[str, Any], value: Any) -> list[str]:
    for an in model.get("analyses") or []:
        if isinstance(an, dict) and an.get("role") == "primary":
            an["assumptions"] = [str(value)]
            return [f"analyses[{an['id']}].assumptions"]
    return []


QUESTIONS: tuple[Question, ...] = (
    Question(
        "study_code",
        "Study identity",
        "Sponsor study code",
        "Appears on the title page and in every export header.",
        "text",
        "protocol.study_identifiers.0.value",
        _study_code,
        ("section.0",),
        confirm_after_adaptation=True,
    ),
    Question(
        "phase",
        "Study identity",
        "Phase",
        "Governs the intent statement and the checklist applied at release.",
        "select",
        "protocol.phase",
        _set("protocol.phase"),
        ("section.0", "section.1"),
        options=(Option("1", "Phase 1"), Option("2a", "Phase 2a"), Option("2b", "Phase 2b"), Option("3", "Phase 3")),
    ),
    Question(
        "intent",
        "Study identity",
        "Confirmatory or exploratory?",
        "Confirmatory studies must pre-specify multiplicity control and a full SAP before unblinding.",
        "select",
        "protocol.intent",
        _set("protocol.intent"),
        ("section.0", "section.10"),
        options=(Option("exploratory", "Exploratory"), Option("confirmatory", "Confirmatory")),
    ),
    Question(
        "dose_high_mg",
        "Investigational product",
        "High-dose maintenance dose",
        "Written into the regimen, arm names and Section 6. Use the target drug's own PK/PD evidence.",
        "number",
        "regimens[reg_high].administrations.1.dose.value",
        _dose("reg_high", 1, "{drug} {mg} mg every 2 weeks"),
        ("section.4", "section.6"),
        unit="mg",
        minimum=1,
        confirm_after_adaptation=True,
    ),
    Question(
        "dose_low_mg",
        "Investigational product",
        "Low-dose maintenance dose",
        "Set equal to the high dose to collapse to a two-arm design (then reduce planned enrollment).",
        "number",
        "regimens[reg_low].administrations.0.dose.value",
        _dose("reg_low", 0, "{drug} {mg} mg every 2 weeks"),
        ("section.4", "section.6"),
        unit="mg",
        minimum=1,
        confirm_after_adaptation=True,
    ),
    Question(
        "primary_timepoint_weeks",
        "Design",
        "Primary endpoint timepoint",
        "Moves every Week-16 endpoint, the treatment period and the primary visit together.",
        "number",
        "periods[treatment].duration.value",
        _primary_timepoint,
        ("section.3", "section.4", "section.8", "section.10"),
        unit="weeks",
        minimum=4,
        maximum=52,
    ),
    Question(
        "follow_up_weeks",
        "Design",
        "Safety follow-up after last dose",
        "Sets the follow-up period, the follow-up contact and the AE collection window.",
        "number",
        "periods[follow_up].duration.value",
        _follow_up,
        ("section.4", "section.7", "section.9"),
        unit="weeks",
        minimum=0,
        maximum=52,
    ),
    Question(
        "allocation_ratio",
        "Design",
        "Randomization ratio (high : low : placebo)",
        "Changes the allocation weights; re-run the Trial Calculator for the sample size.",
        "select",
        "allocations[rand].name",
        _allocation,
        ("section.4", "section.10"),
        options=(
            Option("1:1:1", "1 : 1 : 1"),
            Option("2:2:1", "2 : 2 : 1", "Fewer placebo participants; larger total for the same power."),
            Option("2:1:1", "2 : 1 : 1"),
        ),
        normalize=lambda v: str(v).replace(" ", ""),
    ),
    Question(
        "rescue_strategy",
        "Estimand",
        "How does rescue therapy enter the primary estimand?",
        "ICH E9(R1) strategy for the intercurrent event 'qualifying rescue'. Drives Section 3 estimand text and the Section 10 primary analysis.",
        "select",
        "estimands[est_primary].intercurrent_event_strategies.0.strategy",
        _rescue_strategy,
        ("section.3", "section.6", "section.10"),
        options=(
            Option(
                "composite",
                "Composite — rescue counts as non-response",
                "Conservative; standard for AD responder endpoints.",
            ),
            Option("treatment_policy", "Treatment policy — use observed values regardless of rescue"),
            Option(
                "hypothetical",
                "Hypothetical — estimate as if rescue had not been taken",
                "Requires an imputation assumption.",
            ),
        ),
    ),
    Question(
        "composite_events",
        "Estimand",
        "Which other events count as non-response?",
        "Only asked for the composite strategy.",
        "multiselect",
        None,
        _composite_events,
        ("section.3", "section.10"),
        required=False,
        options=(
            Option("tx_discontinuation", "Permanent discontinuation of study intervention"),
            Option("study_withdrawal", "Withdrawal from study"),
        ),
        depends_on=("rescue_strategy", "composite"),
    ),
    Question(
        "imputation_assumption",
        "Estimand",
        "Imputation assumption for post-rescue data",
        "State the missing-data assumption used by the primary analysis.",
        "text",
        None,
        _imputation_assumption,
        ("section.10",),
        depends_on=("rescue_strategy", "hypothetical"),
    ),
    Question(
        "alpha",
        "Statistics",
        "Two-sided alpha for the primary comparison",
        "Applied to the confirmatory hierarchy in Section 10.",
        "select",
        "testing_families[tf_primary].alpha",
        _set("testing_families[tf_primary].alpha"),
        ("section.10",),
        options=(
            Option("0.05", "0.05"),
            Option("0.025", "0.025"),
            Option("0.1", "0.10", "Exploratory dose-ranging only."),
        ),
        normalize=lambda v: float(v),
    ),
    Question(
        "planned_enrollment",
        "Statistics",
        "Planned randomized participants",
        "Copy the total from the Trial Calculator. Bound to the Section 1 synopsis and Section 10 sample-size text.",
        "number",
        "protocol.planned_enrollment",
        _set("protocol.planned_enrollment"),
        ("section.1", "section.10"),
        minimum=1,
        normalize=lambda v: int(v),
        confirm_after_adaptation=True,
    ),
)

_BY_ID = {q.id: q for q in QUESTIONS}


def question(qid: str) -> Question:
    return _BY_ID[qid]


def _current(state: DraftState, q: Question) -> Any:
    if q.id in state.key_inputs:
        return state.key_inputs[q.id].value
    if q.read_path:
        return get_path(state.model, q.read_path, None)
    return None


def _applicable(state: DraftState, q: Question) -> bool:
    if q.depends_on is None:
        return True
    dep_id, dep_val = q.depends_on
    dep = _BY_ID[dep_id]
    return str(_current(state, dep)) == dep_val


def answer(state: DraftState, qid: str, value: Any, *, actor: str, now: str) -> tuple[list[str], list[str]]:
    """Record the answer and write it through. Returns (written paths, affected section ids)."""
    q = _BY_ID[qid]
    if not _applicable(state, q):
        raise ValueError(f"{qid} does not apply given earlier answers")
    v = q.normalize(value)
    if q.input_type == "select" and q.options and str(v) not in {o.value for o in q.options}:
        raise ValueError(f"{qid}: {value!r} is not one of the offered options")
    if q.input_type == "number":
        num = float(v)
        if q.minimum is not None and num < q.minimum:
            raise ValueError(f"{qid}: must be at least {q.minimum}")
        if q.maximum is not None and num > q.maximum:
            raise ValueError(f"{qid}: must be at most {q.maximum}")
    written = q.writer(state.model, v)
    state.key_inputs[qid] = KeyInputAnswer(question_id=qid, value=v, answered_by=actor, answered_at=now)
    return written, list(q.linked_sections)


def questionnaire(state: DraftState) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    answered = 0
    required_total = 0
    for q in QUESTIONS:
        if not _applicable(state, q):
            continue
        cur = _current(state, q)
        recorded = q.id in state.key_inputs
        placeholder = q.confirm_after_adaptation and state.adaptation is not None and not recorded
        is_answered = recorded or (cur is not None and not placeholder)
        if q.required:
            required_total += 1
            answered += int(is_answered)
        groups.setdefault(q.group, []).append(
            {
                "id": q.id,
                "label": q.label,
                "help": q.help,
                "input_type": q.input_type,
                "unit": q.unit,
                "required": q.required,
                "options": [{"value": o.value, "label": o.label, "help": o.help} for o in q.options],
                "current_value": cur,
                "source": "answered"
                if recorded
                else ("placeholder" if placeholder else ("starter" if cur is not None else "unset")),
                "answered": is_answered,
                "linked_sections": list(q.linked_sections),
                "minimum": q.minimum,
                "maximum": q.maximum,
            }
        )
    return {
        "groups": [{"name": g, "questions": qs} for g, qs in groups.items()],
        "answered": answered,
        "required": required_total,
        "pct": round(100 * answered / required_total) if required_total else 100,
    }
