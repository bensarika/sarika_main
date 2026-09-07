"""Synthetic starter: Phase 2b, placebo-controlled, anti-IL-13 antibody in moderate-to-severe AD.

The source drug is the invented antibody **ADX-101** so the adaptation flow has
something to rewrite. Numbers (dose, weeks, thresholds) are illustrative and
internally consistent; they are bound to the prose through claims so a change
in either place surfaces as a CL01 mismatch.
"""

from __future__ import annotations

from typing import Any

from protocol_studio.engine.state import Block, Claim

AD_ANTIBODY_ID = "template:ad-antibody-p2b"
SOURCE_DRUG = "ADX-101"
SOURCE_MECHANISM = "anti-IL-13 monoclonal antibody"


def _q(value: float, unit: str) -> dict[str, Any]:
    return {"value": value, "unit": unit}


def _t(anchor: str, value: float | None = None, unit: str = "week", **extra: Any) -> dict[str, Any]:
    t: dict[str, Any] = {"anchor_id": anchor}
    if value is not None:
        t["offset"] = _q(value, unit)
    t.update(extra)
    return t


def _field(path: str) -> dict[str, Any]:
    return {"kind": "field", "path": path}


def _lit(v: Any) -> dict[str, Any]:
    return {"kind": "literal", "value": v}


def _call(op: str, *args: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "call", "operator": op, "arguments": list(args)}


def _pct_reduction(metric: str, week: str) -> dict[str, Any]:
    return _call(
        "multiply",
        _lit(100),
        _call(
            "divide",
            _call("subtract", _field(f"measurements.{metric}.baseline"), _field(f"measurements.{metric}.{week}")),
            _field(f"measurements.{metric}.baseline"),
        ),
    )


def _wk16() -> dict[str, Any]:
    return _t("randomization", 16)


def ad_antibody_model(*, protocol_id: str, name: str, indication: str) -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "document_kind": "authored_draft",
        "protocol": {
            "id": protocol_id,
            "name": name,
            "version_label": "0.1",
            "phase": "2b",
            "indication": indication or "atopic dermatitis",
            "purpose": "Dose-ranging efficacy and safety of ADX-101 versus placebo in adults with moderate-to-severe atopic dermatitis.",
            "intent": "exploratory",
            "sponsor": "Sarika",
            "study_identifiers": [{"system": "sponsor", "value": "ADX-101-201"}],
            "planned_enrollment": 126,
            "sample_size": {
                "basis": "power",
                "assumptions": [
                    "EASI-75 at Week 16: 60% active vs 30% placebo",
                    "Two-sided alpha 0.05, power 90%, 1:1 allocation",
                    "10% non-evaluable participants",
                ],
                "calculation": "56 evaluable participants per arm (63 randomized) detect a 30-percentage-point difference in EASI-75 response at Week 16 with 90% power at two-sided alpha 0.05.",
            },
            "notes": "Synthetic starter. Illustrative design; not a proposal for use in a trial.",
        },
        "roles": [
            {
                "id": "investigator",
                "name": "Investigator",
                "responsibility": "Site conduct, eligibility, safety decisions",
            },
            {
                "id": "sponsor_medical_monitor",
                "name": "Sponsor medical monitor",
                "responsibility": "Medical oversight, SAE review",
            },
            {"id": "dmc", "name": "Data monitoring committee", "responsibility": "Periodic unblinded safety review"},
            {"id": "participant", "name": "Participant"},
        ],
        "sources": [
            {
                "id": "ib_adx101",
                "name": "ADX-101 Investigator's Brochure",
                "document_type": "other",
                "retrieval_status": "not_retrieved",
                "notes": "Edition and date to be confirmed at adaptation.",
            }
        ],
        "dependencies": [
            {
                "id": "dep_ib",
                "name": "Investigator's Brochure (current edition)",
                "kind": "investigator_brochure",
                "source_id": "ib_adx101",
                "status": "missing",
            },
            {"id": "dep_sap", "name": "Statistical analysis plan", "kind": "sap", "status": "missing"},
        ],
        "anchors": [
            {"id": "screening_start", "name": "Screening visit", "event_type": "screening"},
            {
                "id": "randomization",
                "name": "Randomization (Day 1)",
                "event_type": "randomization",
                "definition": "Day 1 is the day of randomization and first dose.",
            },
            {"id": "last_dose", "name": "Last dose of study intervention", "event_type": "last_dose"},
        ],
        "populations": [
            {
                "id": "eligible_adults",
                "name": "Adults with moderate-to-severe AD inadequately controlled by topical therapy",
                "role": "eligible",
                "clinical_definition": "Adults 18–75 years with chronic AD for ≥1 year, EASI ≥16, vIGA-AD ≥3, BSA ≥10% and documented inadequate response to topical therapy.",
                "criterion_ids": [
                    "inc_age",
                    "inc_diagnosis",
                    "inc_severity",
                    "inc_topical_failure",
                    "exc_biologic",
                    "exc_infection",
                    "exc_pregnancy",
                ],
            },
            {
                "id": "itt",
                "name": "Randomized participants",
                "role": "estimand",
                "clinical_definition": "All participants randomized, analysed by randomized arm.",
                "parent_population_id": "eligible_adults",
            },
            {
                "id": "nrs4_eligible",
                "name": "Participants with baseline Peak Pruritus NRS ≥ 4",
                "role": "responder_subset",
                "clinical_definition": "Randomized participants with a baseline weekly average Peak Pruritus NRS of at least 4.",
                "parent_population_id": "itt",
            },
        ],
        "criteria": [
            {
                "id": "inc_age",
                "name": "Age 18 to 75 years",
                "type": "inclusion",
                "predicate": _call(
                    "and",
                    _call("gte", _field("participant.age_years"), _lit(18)),
                    _call("lte", _field("participant.age_years"), _lit(75)),
                ),
                "evaluation_times": [_t("screening_start")],
            },
            {
                "id": "inc_diagnosis",
                "name": "Chronic AD for at least 1 year",
                "type": "inclusion",
                "predicate": _call("gte", _field("history.ad_duration_years"), _lit(1)),
                "documentation_requirement": "Hanifin and Rajka criteria documented in source.",
            },
            {
                "id": "inc_severity",
                "name": "EASI ≥ 16, vIGA-AD ≥ 3, BSA ≥ 10% at screening and baseline",
                "type": "inclusion",
                "predicate": _call(
                    "and",
                    _call("gte", _field("measurements.EASI.baseline"), _lit(16)),
                    _call("gte", _field("measurements.vIGA.baseline"), _lit(3)),
                    _call("gte", _field("measurements.BSA.baseline"), _lit(10)),
                ),
                "assessment_ids": ["easi", "viga", "bsa"],
                "evaluation_times": [_t("screening_start"), _t("randomization")],
            },
            {
                "id": "inc_topical_failure",
                "name": "Inadequate response to medium-potency topical corticosteroids within 6 months",
                "type": "inclusion",
                "documentation_requirement": "Documented in medical history; investigator judgment permitted for intolerance.",
                "rationale": "Aligns the population with systemic-therapy candidates.",
            },
            {
                "id": "exc_biologic",
                "name": "Prior biologic or JAK inhibitor for AD within 5 half-lives or 12 weeks",
                "type": "exclusion",
                "predicate": _call("lt", _field("history.weeks_since_last_biologic"), _lit(12)),
                "rationale": "Avoids carry-over of prior systemic immunomodulation.",
            },
            {
                "id": "exc_infection",
                "name": "Active or chronic infection requiring systemic treatment within 2 weeks",
                "type": "exclusion",
                "rationale": "Safety: immunomodulatory mechanism.",
            },
            {
                "id": "exc_pregnancy",
                "name": "Pregnant or breastfeeding",
                "type": "exclusion",
                "assessment_ids": ["preg_test"],
            },
        ],
        "products": [
            {
                "id": "adx101",
                "name": SOURCE_DRUG,
                "role": "investigational",
                "substance": f"{SOURCE_DRUG} ({SOURCE_MECHANISM})",
                "formulation": "Solution for subcutaneous injection, 150 mg/mL",
                "strength": _q(150, "mg/mL"),
                "route": "subcutaneous",
                "evidence_dependency_ids": ["dep_ib"],
            },
            {
                "id": "placebo",
                "name": "Placebo",
                "role": "placebo",
                "substance": "Matching vehicle",
                "formulation": "Solution for subcutaneous injection",
                "route": "subcutaneous",
            },
            {
                "id": "tcs_background",
                "name": "Low-to-medium potency topical corticosteroid",
                "role": "background",
                "substance": "Topical corticosteroid",
                "formulation": "Cream or ointment",
                "route": "topical",
            },
            {
                "id": "rescue_systemic",
                "name": "Systemic rescue therapy",
                "role": "rescue",
                "substance": "Systemic corticosteroid or non-steroidal immunosuppressant",
                "formulation": "Per local practice",
                "route": "oral",
            },
        ],
        "regimens": [
            {
                "id": "reg_high",
                "name": f"{SOURCE_DRUG} 300 mg every 2 weeks",
                "product_id": "adx101",
                "administrations": [
                    {
                        "id": "high_load",
                        "dose": {"kind": "literal", "value": 600, "unit": "mg"},
                        "route": "subcutaneous",
                        "time": _t("randomization", 0, "day"),
                        "loading_or_maintenance": "loading",
                    },
                    {
                        "id": "high_maint",
                        "dose": {"kind": "literal", "value": 300, "unit": "mg"},
                        "route": "subcutaneous",
                        "time": _t("randomization", 2),
                        "repeat_every": _q(2, "week"),
                        "repeat_count": 7,
                        "loading_or_maintenance": "maintenance",
                    },
                ],
                "rationale": "Upper dose predicted to achieve >90% target engagement from Phase 1 PK/PD.",
            },
            {
                "id": "reg_low",
                "name": f"{SOURCE_DRUG} 150 mg every 2 weeks",
                "product_id": "adx101",
                "administrations": [
                    {
                        "id": "low_maint",
                        "dose": {"kind": "literal", "value": 150, "unit": "mg"},
                        "route": "subcutaneous",
                        "time": _t("randomization", 0, "day"),
                        "repeat_every": _q(2, "week"),
                        "repeat_count": 8,
                        "loading_or_maintenance": "maintenance",
                    }
                ],
            },
            {
                "id": "reg_placebo",
                "name": "Placebo every 2 weeks",
                "product_id": "placebo",
                "administrations": [
                    {
                        "id": "pbo",
                        "route": "subcutaneous",
                        "time": _t("randomization", 0, "day"),
                        "repeat_every": _q(2, "week"),
                        "repeat_count": 8,
                    }
                ],
            },
        ],
        "periods": [
            {
                "id": "screening",
                "name": "Screening",
                "kind": "screening",
                "start": _t("screening_start"),
                "duration": _q(4, "week"),
            },
            {
                "id": "treatment",
                "name": "Treatment",
                "kind": "induction",
                "start": _t("randomization"),
                "duration": _q(16, "week"),
            },
            {
                "id": "follow_up",
                "name": "Safety follow-up",
                "kind": "follow_up",
                "start": _t("last_dose"),
                "duration": _q(12, "week"),
            },
        ],
        "paths": [
            {
                "id": "arm_high",
                "name": f"{SOURCE_DRUG} 300 mg Q2W",
                "population_id": "itt",
                "period_ids": ["screening", "treatment", "follow_up"],
                "regimen_assignments": [{"period_id": "treatment", "regimen_ids": ["reg_high"]}],
            },
            {
                "id": "arm_low",
                "name": f"{SOURCE_DRUG} 150 mg Q2W",
                "population_id": "itt",
                "period_ids": ["screening", "treatment", "follow_up"],
                "regimen_assignments": [{"period_id": "treatment", "regimen_ids": ["reg_low"]}],
            },
            {
                "id": "arm_placebo",
                "name": "Placebo Q2W",
                "population_id": "itt",
                "period_ids": ["screening", "treatment", "follow_up"],
                "regimen_assignments": [{"period_id": "treatment", "regimen_ids": ["reg_placebo"]}],
            },
        ],
        "allocations": [
            {
                "id": "rand",
                "name": "Randomization 1:1:1",
                "occasion": _t("randomization"),
                "eligible_population_id": "eligible_adults",
                "method": "randomized",
                "choices": [
                    {"path_id": "arm_high", "weight": 1},
                    {"path_id": "arm_low", "weight": 1},
                    {"path_id": "arm_placebo", "weight": 1},
                ],
                "strata": ["baseline vIGA-AD (3 vs 4)", "region"],
                "concealment": "Central interactive response technology",
                "masking": [
                    {"role_id": "participant", "status": "blinded"},
                    {"role_id": "investigator", "status": "blinded"},
                    {"role_id": "dmc", "status": "unblinded"},
                ],
            },
        ],
        "transitions": [
            {
                "id": "t_screen_fail",
                "name": "Screen failure",
                "from_period_id": "screening",
                "terminal_state": "other",
                "condition": _call("not", _field("eligibility.met")),
            },
            {
                "id": "t_rand",
                "name": "Randomization",
                "from_period_id": "screening",
                "to_period_id": "treatment",
                "allocation_id": "rand",
            },
            {
                "id": "t_complete",
                "name": "Treatment completion",
                "from_period_id": "treatment",
                "to_period_id": "follow_up",
            },
            {"id": "t_end", "name": "End of study", "from_period_id": "follow_up", "terminal_state": "complete"},
        ],
        "assessments": [
            {
                "id": "easi",
                "name": "Eczema Area and Severity Index",
                "kind": "clinician_reported",
                "instrument": "EASI",
                "unit": "score",
                "range": {"min": 0, "max": 72},
                "assessor_role_id": "investigator",
            },
            {
                "id": "viga",
                "name": "Validated Investigator Global Assessment for AD",
                "kind": "clinician_reported",
                "instrument": "vIGA-AD",
                "unit": "score",
                "range": {"min": 0, "max": 4},
            },
            {
                "id": "bsa",
                "name": "Body surface area affected",
                "kind": "clinician_reported",
                "instrument": "BSA",
                "unit": "%",
            },
            {
                "id": "ppnrs",
                "name": "Peak Pruritus NRS (weekly average)",
                "kind": "patient_reported",
                "instrument": "PP-NRS",
                "unit": "score",
                "range": {"min": 0, "max": 10},
                "recall_period": _q(24, "hour"),
            },
            {
                "id": "dlqi",
                "name": "Dermatology Life Quality Index",
                "kind": "patient_reported",
                "instrument": "DLQI",
                "unit": "score",
            },
            {"id": "vitals", "name": "Vital signs", "kind": "physical"},
            {"id": "labs", "name": "Haematology and chemistry", "kind": "laboratory"},
            {"id": "preg_test", "name": "Pregnancy test", "kind": "laboratory"},
            {"id": "pk", "name": f"{SOURCE_DRUG} serum concentration", "kind": "pk"},
            {"id": "ada", "name": "Anti-drug antibodies", "kind": "immunogenicity"},
            {"id": "ae", "name": "Adverse event review", "kind": "other"},
        ],
        "encounters": [
            {
                "id": "v_screen",
                "name": "Screening",
                "kind": "clinic",
                "time": _t("screening_start"),
                "period_id": "screening",
            },
            {
                "id": "v_w0",
                "name": "Baseline / Day 1",
                "kind": "clinic",
                "time": _t("randomization", 0, "day"),
                "period_id": "treatment",
            },
            {
                "id": "v_w2",
                "name": "Week 2",
                "kind": "clinic",
                "time": _t("randomization", 2, window={"earlier": _q(3, "day"), "later": _q(3, "day")}),
                "period_id": "treatment",
            },
            {
                "id": "v_w4",
                "name": "Week 4",
                "kind": "clinic",
                "time": _t("randomization", 4, window={"earlier": _q(3, "day"), "later": _q(3, "day")}),
                "period_id": "treatment",
            },
            {
                "id": "v_w8",
                "name": "Week 8",
                "kind": "clinic",
                "time": _t("randomization", 8, window={"earlier": _q(3, "day"), "later": _q(3, "day")}),
                "period_id": "treatment",
            },
            {
                "id": "v_w12",
                "name": "Week 12",
                "kind": "clinic",
                "time": _t("randomization", 12, window={"earlier": _q(3, "day"), "later": _q(3, "day")}),
                "period_id": "treatment",
            },
            {
                "id": "v_w16",
                "name": "Week 16 (primary endpoint)",
                "kind": "clinic",
                "time": _t("randomization", 16, window={"earlier": _q(3, "day"), "later": _q(3, "day")}),
                "period_id": "treatment",
            },
            {
                "id": "v_fu",
                "name": "Safety follow-up",
                "kind": "telephone",
                "time": _t("last_dose", 12, window={"earlier": _q(7, "day"), "later": _q(7, "day")}),
                "period_id": "follow_up",
            },
            {
                "id": "v_unsched",
                "name": "Unscheduled",
                "kind": "event_triggered",
                "time": _t("randomization"),
                "condition": _call(
                    "or", _field("events.qualifying_rescue.occurred"), _field("events.adverse_event.occurred")
                ),
            },
        ],
        "scheduled_activities": _schedule(),
        "objectives": [
            {
                "id": "obj_primary",
                "name": "Primary efficacy",
                "role": "primary",
                "clinical_question": f"Does {SOURCE_DRUG} increase the proportion of participants achieving EASI-75 at Week 16 compared with placebo?",
                "endpoint_ids": ["easi75"],
            },
            {
                "id": "obj_secondary",
                "name": "Secondary efficacy",
                "role": "secondary",
                "clinical_question": f"Does {SOURCE_DRUG} improve skin clearance, itch and quality of life versus placebo at Week 16?",
                "endpoint_ids": ["easi90", "viga01", "nrs4", "easi_pct"],
            },
            {
                "id": "obj_safety",
                "name": "Safety and tolerability",
                "role": "secondary",
                "clinical_question": f"What is the safety profile of {SOURCE_DRUG} over 16 weeks of treatment and 12 weeks of follow-up?",
                "endpoint_ids": ["teae"],
            },
            {
                "id": "obj_pk",
                "name": "Pharmacokinetics and immunogenicity",
                "role": "exploratory",
                "clinical_question": f"What are the serum concentrations and anti-drug antibody incidence of {SOURCE_DRUG}?",
                "endpoint_ids": ["pk_conc"],
            },
        ],
        "endpoints": [
            {
                "id": "easi75",
                "name": "EASI-75 response at Week 16",
                "role": "primary",
                "objective_ids": ["obj_primary"],
                "assessment_ids": ["easi"],
                "variable_type": "binary",
                "transformation": "responder",
                "response_predicate": _call("gte", _pct_reduction("EASI", "week16"), _lit(75)),
                "time": _wk16(),
                "baseline_definition": "Last non-missing EASI before first dose (Day 1).",
                "aggregation": "proportion",
                "eligible_population_id": "itt",
            },
            {
                "id": "easi90",
                "name": "EASI-90 response at Week 16",
                "role": "key_secondary",
                "objective_ids": ["obj_secondary"],
                "assessment_ids": ["easi"],
                "variable_type": "binary",
                "transformation": "responder",
                "response_predicate": _call("gte", _pct_reduction("EASI", "week16"), _lit(90)),
                "time": _wk16(),
                "baseline_definition": "Last non-missing EASI before first dose (Day 1).",
                "aggregation": "proportion",
                "eligible_population_id": "itt",
            },
            {
                "id": "viga01",
                "name": "vIGA-AD 0/1 with ≥2-point improvement at Week 16",
                "role": "key_secondary",
                "objective_ids": ["obj_secondary"],
                "assessment_ids": ["viga"],
                "variable_type": "binary",
                "transformation": "responder",
                "response_predicate": _call(
                    "and",
                    _call("lte", _field("measurements.vIGA.week16"), _lit(1)),
                    _call(
                        "gte",
                        _call("subtract", _field("measurements.vIGA.baseline"), _field("measurements.vIGA.week16")),
                        _lit(2),
                    ),
                ),
                "time": _wk16(),
                "baseline_definition": "vIGA-AD at Day 1 before first dose.",
                "aggregation": "proportion",
                "eligible_population_id": "itt",
            },
            {
                "id": "nrs4",
                "name": "≥4-point improvement in Peak Pruritus NRS at Week 16",
                "role": "key_secondary",
                "objective_ids": ["obj_secondary"],
                "assessment_ids": ["ppnrs"],
                "variable_type": "binary",
                "transformation": "responder",
                "response_predicate": _call(
                    "gte",
                    _call("subtract", _field("measurements.PPNRS.baseline"), _field("measurements.PPNRS.week16")),
                    _lit(4),
                ),
                "time": _wk16(),
                "baseline_definition": "Weekly average of daily PP-NRS in the 7 days before Day 1.",
                "aggregation": "proportion",
                "eligible_population_id": "nrs4_eligible",
                "eligible_subset": _call("gte", _field("measurements.PPNRS.baseline"), _lit(4)),
            },
            {
                "id": "easi_pct",
                "name": "Percent change from baseline in EASI at Week 16",
                "role": "secondary",
                "objective_ids": ["obj_secondary"],
                "assessment_ids": ["easi"],
                "variable_type": "continuous",
                "transformation": "percent_change",
                "expression": _call(
                    "multiply",
                    _lit(100),
                    _call(
                        "divide",
                        _call("subtract", _field("measurements.EASI.week16"), _field("measurements.EASI.baseline")),
                        _field("measurements.EASI.baseline"),
                    ),
                ),
                "time": _wk16(),
                "baseline_definition": "Last non-missing EASI before first dose (Day 1).",
                "aggregation": "least-squares mean",
                "eligible_population_id": "itt",
            },
            {
                "id": "teae",
                "name": "Treatment-emergent adverse events through follow-up",
                "role": "secondary",
                "objective_ids": ["obj_safety"],
                "assessment_ids": ["ae"],
                "variable_type": "count",
                "transformation": "raw",
                "time": _t("last_dose", 12),
                "aggregation": "incidence",
            },
            {
                "id": "pk_conc",
                "name": f"Serum {SOURCE_DRUG} concentration over time",
                "role": "exploratory",
                "objective_ids": ["obj_pk"],
                "assessment_ids": ["pk"],
                "variable_type": "continuous",
                "transformation": "raw",
                "time": _wk16(),
                "aggregation": "geometric mean",
            },
        ],
        "events": [
            {
                "id": "qualifying_rescue",
                "name": "Qualifying rescue therapy before Week 16",
                "kind": "rescue",
                "definition": "Any systemic corticosteroid, systemic immunosuppressant, phototherapy or high-potency TCS taken for AD before the Week 16 assessment.",
                "event_time_definition": "First administration of the qualifying rescue treatment.",
                "reason_categories": ["intolerable symptoms", "investigator judgment"],
            },
            {
                "id": "tx_discontinuation",
                "name": "Permanent discontinuation of study intervention",
                "kind": "treatment_discontinuation",
                "definition": "Study intervention permanently stopped before the Week 14 dose for any reason.",
                "event_time_definition": "Date of the decision to discontinue.",
            },
            {
                "id": "study_withdrawal",
                "name": "Withdrawal from study",
                "kind": "study_withdrawal",
                "definition": "Participant withdraws consent for all further procedures and data collection.",
            },
            {
                "id": "adverse_event",
                "name": "Adverse event",
                "kind": "adverse_event",
                "definition": "Any untoward medical occurrence in a participant administered study intervention, whether or not related.",
                "event_time_definition": "Onset date reported by the participant or investigator.",
            },
            {
                "id": "serious_ae",
                "name": "Serious adverse event",
                "kind": "adverse_event",
                "parent_event_id": "adverse_event",
                "definition": "An AE that results in death, is life-threatening, requires or prolongs hospitalisation, results in persistent disability, is a congenital anomaly, or is otherwise medically important.",
            },
            {
                "id": "aesi_conjunctivitis",
                "name": "Adverse event of special interest: conjunctivitis",
                "kind": "adverse_event",
                "parent_event_id": "adverse_event",
                "definition": "Any conjunctivitis or keratitis, given the mechanism class.",
            },
            {
                "id": "pregnancy",
                "name": "Pregnancy",
                "kind": "pregnancy",
                "definition": "Pregnancy in a participant during treatment or within 12 weeks of the last dose.",
            },
            {
                "id": "missing_w16",
                "name": "Missing Week 16 EASI",
                "kind": "missing_observation",
                "definition": "Week 16 EASI not collected within the visit window.",
            },
        ],
        "estimands": [
            {
                "id": "est_primary",
                "name": "Primary estimand: EASI-75 composite",
                "role": "primary",
                "population_id": "itt",
                "endpoint_id": "easi75",
                "treatment_conditions": [
                    {
                        "id": "tc_high",
                        "path_ids": ["arm_high"],
                        "description": f"{SOURCE_DRUG} 300 mg Q2W with permitted background TCS",
                    },
                    {
                        "id": "tc_pbo",
                        "path_ids": ["arm_placebo"],
                        "description": "Placebo Q2W with permitted background TCS",
                    },
                ],
                "contrast": "Difference in response proportions, active minus placebo",
                "population_summary": "Difference in proportions with 95% CI",
                "intercurrent_event_strategies": [
                    {
                        "event_id": "qualifying_rescue",
                        "strategy": "composite",
                        "definition": "Participants who take qualifying rescue before Week 16 are counted as non-responders.",
                    },
                    {
                        "event_id": "tx_discontinuation",
                        "strategy": "composite",
                        "definition": "Participants who permanently discontinue study intervention before Week 16 are counted as non-responders.",
                    },
                ],
            },
            {
                "id": "est_supp_policy",
                "name": "Supplementary estimand: EASI-75 treatment policy",
                "role": "supplementary",
                "population_id": "itt",
                "endpoint_id": "easi75",
                "treatment_conditions": [
                    {
                        "id": "tcs_high",
                        "path_ids": ["arm_high"],
                        "description": f"{SOURCE_DRUG} 300 mg Q2W regardless of rescue",
                    },
                    {"id": "tcs_pbo", "path_ids": ["arm_placebo"], "description": "Placebo Q2W regardless of rescue"},
                ],
                "contrast": "Difference in response proportions, active minus placebo",
                "population_summary": "Difference in proportions",
                "intercurrent_event_strategies": [
                    {
                        "event_id": "qualifying_rescue",
                        "strategy": "treatment_policy",
                        "definition": "Observed Week 16 outcome is used regardless of rescue.",
                    },
                    {
                        "event_id": "tx_discontinuation",
                        "strategy": "treatment_policy",
                        "definition": "Observed outcome is used regardless of discontinuation.",
                    },
                ],
            },
            {
                "id": "est_easi_pct",
                "name": "Secondary estimand: percent EASI change, hypothetical for rescue",
                "role": "secondary",
                "population_id": "itt",
                "endpoint_id": "easi_pct",
                "treatment_conditions": [
                    {
                        "id": "tch_high",
                        "path_ids": ["arm_high"],
                        "description": f"{SOURCE_DRUG} 300 mg Q2W had rescue not been taken",
                    },
                    {
                        "id": "tch_pbo",
                        "path_ids": ["arm_placebo"],
                        "description": "Placebo Q2W had rescue not been taken",
                    },
                ],
                "contrast": "Difference in least-squares mean percent change",
                "population_summary": "LS mean difference with 95% CI",
                "intercurrent_event_strategies": [
                    {
                        "event_id": "qualifying_rescue",
                        "strategy": "hypothetical",
                        "definition": "Measurements after qualifying rescue are set to missing and imputed under the assumption that rescue had not been taken.",
                    }
                ],
            },
        ],
        "analysis_sets": [
            {
                "id": "fas",
                "name": "Full analysis set",
                "definition": "All randomized participants, analysed according to randomized arm.",
                "treatment_attribution": "as_randomized",
            },
            {
                "id": "safety_set",
                "name": "Safety analysis set",
                "definition": "All participants who received at least one dose, analysed by treatment received.",
                "treatment_attribution": "as_treated",
            },
            {
                "id": "pk_set",
                "name": "PK analysis set",
                "definition": f"Participants who received {SOURCE_DRUG} and have at least one evaluable post-dose concentration.",
                "treatment_attribution": "as_treated",
            },
        ],
        "analyses": [
            {
                "id": "an_primary",
                "name": "Primary analysis of EASI-75 at Week 16",
                "role": "primary",
                "estimand_id": "est_primary",
                "endpoint_id": "easi75",
                "analysis_set_id": "fas",
                "framework": "frequentist_testing",
                "method": "Cochran–Mantel–Haenszel test stratified by baseline vIGA-AD and region; difference in proportions with 95% CI (stratified Newcombe).",
                "covariates": ["baseline vIGA-AD", "region"],
                "assumptions": ["Rescue and discontinuation are handled by the composite strategy, not by imputation."],
                "post_event_handling": [
                    {"event_id": "qualifying_rescue", "action": "set_nonresponse"},
                    {"event_id": "tx_discontinuation", "action": "set_nonresponse"},
                ],
                "missing_measurement_handling": [
                    {
                        "event_id": "missing_w16",
                        "action": "set_nonresponse",
                        "method": "Non-responder imputation",
                        "assumptions": [
                            "Missing Week 16 EASI for reasons other than rescue is treated as non-response."
                        ],
                    }
                ],
            },
            {
                "id": "an_sens_tipping",
                "name": "Tipping-point sensitivity analysis",
                "role": "sensitivity",
                "estimand_id": "est_primary",
                "endpoint_id": "easi75",
                "analysis_set_id": "fas",
                "framework": "frequentist_estimation",
                "method": "Multiple imputation with delta adjustment across a grid of response-probability shifts in the active arm.",
                "missing_measurement_handling": [
                    {
                        "event_id": "missing_w16",
                        "action": "impute",
                        "method": "Delta-adjusted multiple imputation",
                        "assumptions": ["Missing-not-at-random departures explored over a delta grid."],
                    }
                ],
            },
            {
                "id": "an_supp_policy",
                "name": "Supplementary treatment-policy analysis",
                "role": "supplementary",
                "estimand_id": "est_supp_policy",
                "endpoint_id": "easi75",
                "analysis_set_id": "fas",
                "framework": "frequentist_estimation",
                "method": "Same CMH model using observed Week 16 response regardless of rescue.",
                "post_event_handling": [{"event_id": "qualifying_rescue", "action": "use_observed"}],
                "missing_measurement_handling": [
                    {"event_id": "missing_w16", "action": "impute", "method": "Multiple imputation under MAR by arm"}
                ],
            },
            {
                "id": "an_easi_pct",
                "name": "Percent change in EASI at Week 16",
                "role": "supplementary",
                "estimand_id": "est_easi_pct",
                "endpoint_id": "easi_pct",
                "analysis_set_id": "fas",
                "framework": "frequentist_estimation",
                "method": "Mixed model for repeated measures with treatment, visit, treatment-by-visit, baseline EASI and stratification factors.",
                "covariates": ["baseline EASI", "baseline vIGA-AD", "region"],
                "post_event_handling": [
                    {
                        "event_id": "qualifying_rescue",
                        "action": "replace_value",
                        "method": "Set post-rescue values to missing",
                    }
                ],
                "missing_measurement_handling": [
                    {"event_id": "missing_w16", "action": "impute", "method": "Implicit MAR imputation within MMRM"}
                ],
            },
        ],
        "testing_families": [
            {
                "id": "tf_primary",
                "name": "Primary and key secondary hierarchy",
                "framework": "frequentist",
                "hypothesis_testing": True,
                "method": "Fixed-sequence: EASI-75, then EASI-90, then vIGA-AD 0/1, then NRS-4, each at two-sided 0.05 for the 300 mg arm.",
                "alpha": 0.05,
                "sidedness": "two_sided",
                "hypotheses": [
                    {
                        "id": "h_easi75",
                        "analysis_id": "an_primary",
                        "null": "EASI-75 response equal between 300 mg and placebo",
                        "alternative": "EASI-75 response differs",
                    }
                ],
            },
        ],
        "rules": [
            {
                "id": "rule_rescue",
                "name": "Rescue therapy",
                "domain": "rescue",
                "modality": "permitted",
                "trigger": {
                    "kind": "judgment",
                    "actor_role_id": "investigator",
                    "question": "Are symptoms intolerable despite background therapy?",
                },
                "actions": [
                    {
                        "type": "administer",
                        "target_id": "rescue_systemic",
                        "actor_role_id": "investigator",
                        "details": "Rescue is discouraged before Week 4. Record agent, dose and dates.",
                    },
                    {
                        "type": "record",
                        "actor_role_id": "investigator",
                        "details": "Record the rescue event; the participant continues scheduled assessments.",
                    },
                ],
                "owner_role_id": "investigator",
            },
            {
                "id": "rule_stop_rescue",
                "name": "Continue study intervention after rescue",
                "domain": "treatment",
                "modality": "permitted",
                "trigger": _call("eq", _field("events.qualifying_rescue.occurred"), _lit(True)),
                "actions": [
                    {
                        "type": "continue_follow_up",
                        "actor_role_id": "investigator",
                        "details": "Study intervention may continue after rescue unless a stopping rule applies.",
                    }
                ],
                "owner_role_id": "investigator",
            },
            {
                "id": "rule_stop_pregnancy",
                "name": "Permanent discontinuation for pregnancy",
                "domain": "treatment",
                "modality": "required",
                "trigger": _call("eq", _field("events.pregnancy.occurred"), _lit(True)),
                "actions": [
                    {"type": "stop_treatment", "target_id": "adx101", "actor_role_id": "investigator"},
                    {
                        "type": "continue_follow_up",
                        "actor_role_id": "investigator",
                        "details": "Follow pregnancy to outcome.",
                    },
                ],
                "owner_role_id": "investigator",
            },
            {
                "id": "rule_stop_sae",
                "name": "Discontinuation for serious hypersensitivity",
                "domain": "treatment",
                "modality": "required",
                "trigger": {
                    "kind": "judgment",
                    "actor_role_id": "investigator",
                    "question": "Is the event a serious systemic hypersensitivity reaction related to study intervention?",
                },
                "actions": [{"type": "stop_treatment", "target_id": "adx101", "actor_role_id": "investigator"}],
                "owner_role_id": "investigator",
            },
            {
                "id": "rule_sae_report",
                "name": "SAE reporting",
                "domain": "safety",
                "modality": "required",
                "trigger": _call("eq", _field("events.serious_ae.occurred"), _lit(True)),
                "actions": [
                    {
                        "type": "report",
                        "actor_role_id": "investigator",
                        "deadline": _q(24, "hour"),
                        "details": "Report to the sponsor within 24 hours of awareness.",
                    }
                ],
                "owner_role_id": "investigator",
            },
            {
                "id": "rule_ae_collection",
                "name": "AE collection window",
                "domain": "safety",
                "modality": "required",
                "actions": [
                    {
                        "type": "record",
                        "actor_role_id": "investigator",
                        "details": "Collect AEs from informed consent through the safety follow-up visit.",
                    }
                ],
                "owner_role_id": "investigator",
            },
            {
                "id": "rule_followup_after_stop",
                "name": "Follow-up after discontinuation",
                "domain": "follow_up",
                "modality": "required",
                "trigger": _call("eq", _field("events.tx_discontinuation.occurred"), _lit(True)),
                "actions": [
                    {
                        "type": "continue_follow_up",
                        "actor_role_id": "investigator",
                        "details": "Participants who stop study intervention remain in the study for scheduled efficacy and safety assessments unless consent is withdrawn.",
                    }
                ],
                "owner_role_id": "investigator",
            },
            {
                "id": "rule_prohibited",
                "name": "Prohibited concomitant therapy",
                "domain": "treatment",
                "modality": "prohibited",
                "actions": [
                    {
                        "type": "record",
                        "actor_role_id": "investigator",
                        "details": "Systemic immunosuppressants, phototherapy, other biologics and JAK inhibitors are prohibited except as rescue.",
                    }
                ],
                "owner_role_id": "investigator",
            },
        ],
        "governance": [
            {
                "id": "gov_ethics",
                "name": "Ethics review and consent",
                "topic": "ethics",
                "owner_role_ids": ["investigator"],
                "policy": "IRB/IEC approval before enrolment; written informed consent before any study procedure.",
            },
            {
                "id": "gov_dmc",
                "name": "Data monitoring committee",
                "topic": "committees",
                "owner_role_ids": ["dmc"],
                "policy": "Independent DMC reviews unblinded safety data after 40 and 80 participants complete Week 8.",
            },
            {
                "id": "gov_monitoring",
                "name": "Monitoring",
                "topic": "monitoring",
                "owner_role_ids": ["sponsor_medical_monitor"],
                "policy": "Risk-based monitoring with source data verification of eligibility, primary endpoint and SAEs.",
            },
            {
                "id": "gov_data",
                "name": "Data governance",
                "topic": "data",
                "owner_role_ids": ["sponsor_medical_monitor"],
                "policy": "Electronic data capture with audit trail; database lock after the last follow-up visit.",
            },
        ],
        "assertions": [
            {
                "id": "a_synthetic",
                "name": "Synthetic starter declaration",
                "target_pointer": "/protocol",
                "evidence_state": "author_supplied",
                "extraction_method": "human_authored",
                "review_state": "reviewed",
                "normalization_rationale": "Constructed as a reviewed teaching template; not extracted from a real trial.",
            }
        ],
    }


def _schedule() -> list[dict[str, Any]]:
    visits = ["v_screen", "v_w0", "v_w2", "v_w4", "v_w8", "v_w12", "v_w16", "v_fu"]
    plan: dict[str, list[str]] = {
        "easi": ["v_screen", "v_w0", "v_w2", "v_w4", "v_w8", "v_w12", "v_w16"],
        "viga": ["v_screen", "v_w0", "v_w2", "v_w4", "v_w8", "v_w12", "v_w16"],
        "bsa": ["v_screen", "v_w0", "v_w4", "v_w8", "v_w12", "v_w16"],
        "ppnrs": ["v_w0", "v_w2", "v_w4", "v_w8", "v_w12", "v_w16"],
        "dlqi": ["v_w0", "v_w4", "v_w8", "v_w16"],
        "vitals": visits,
        "labs": ["v_screen", "v_w0", "v_w4", "v_w8", "v_w16", "v_fu"],
        "preg_test": ["v_screen", "v_w0", "v_w4", "v_w8", "v_w12", "v_w16", "v_fu"],
        "pk": ["v_w0", "v_w2", "v_w8", "v_w16", "v_fu"],
        "ada": ["v_w0", "v_w8", "v_w16", "v_fu"],
        "ae": visits[1:],
    }
    out: list[dict[str, Any]] = []
    for aid, vs in plan.items():
        for v in vs:
            item: dict[str, Any] = {
                "id": f"sa_{aid}_{v.removeprefix('v_')}",
                "name": f"{aid} at {v}",
                "assessment_id": aid,
                "encounter_id": v,
                "action": {"type": "assess", "target_id": aid, "actor_role_id": "investigator"},
            }
            if aid == "preg_test":
                item["condition"] = {"kind": "field", "path": "participant.of_childbearing_potential"}
                item["notes"] = "Participants of childbearing potential only."
            if aid == "ppnrs":
                item["notes"] = "Daily diary; the weekly average is derived from the 7 days before the visit."
            out.append(item)
    return out


# ----------------------------------------------------------------------------- narrative

_D = SOURCE_DRUG


def ad_antibody_blocks() -> list[Block]:
    def b(i: int, sub: str, text: str, claims: list[Claim] | None = None, kind: str = "paragraph") -> Block:
        return Block(
            id=f"b-tpl{i:02d}",
            section_id=".".join(sub.split(".")[:2]),
            subsection_id=sub,
            order=0,
            kind=kind,
            text=text,
            provenance="imported",
            approval="approved",
            claims=claims or [],
        )

    c = Claim
    return [
        b(
            1,
            "section.1.1",
            f"This is a Phase 2b, randomized, double-blind, placebo-controlled, parallel-group, dose-ranging study of {_D} in adults with moderate-to-severe atopic dermatitis inadequately controlled by topical therapy. Approximately 126 participants will be randomized 1:1:1 to {_D} 300 mg every 2 weeks, {_D} 150 mg every 2 weeks, or placebo for 16 weeks, followed by 12 weeks of safety follow-up.",
            [
                c(id="c-tpl01a", path="protocol.phase", value="2b", text="Phase 2b"),
                c(id="c-tpl01b", path="protocol.planned_enrollment", value=126, text="126 participants"),
                c(id="c-tpl01c", path="periods[treatment].duration.value", value=16, text="16 weeks"),
            ],
        ),
        b(
            2,
            "section.2.1",
            "Atopic dermatitis (AD) is a chronic, relapsing, pruritic inflammatory skin disease affecting up to 10% of adults. Moderate-to-severe disease is associated with sleep disturbance, anxiety, depression and substantial impairment of quality of life. A proportion of patients respond inadequately to topical therapy and require systemic treatment.",
        ),
        b(
            3,
            "section.2.2",
            f"{_D} is a humanised {SOURCE_MECHANISM} that binds soluble interleukin-13 and prevents signalling through the IL-4Rα/IL-13Rα1 receptor complex. IL-13 is a central mediator of type 2 inflammation, skin-barrier dysfunction and pruritus in atopic dermatitis.",
        ),
        b(
            4,
            "section.2.3",
            f"In the Phase 1 program, {_D} was well tolerated at single doses up to 600 mg and demonstrated dose-dependent reduction of serum periostin and CCL17 (see Investigator's Brochure). No clinical efficacy data are yet available for {_D} in atopic dermatitis.",
        ),
        b(
            5,
            "section.2.4",
            f"The purpose of this study is to characterise the dose–response of {_D} on skin clearance and itch over 16 weeks and to select a dose for confirmatory development.",
        ),
        b(
            6,
            "section.2.5",
            "Participants may experience improvement in skin lesions and pruritus. Background low-to-medium potency topical corticosteroids are permitted for all participants, and rescue therapy is available for intolerable symptoms.",
        ),
        b(
            7,
            "section.2.6",
            "Anticipated risks based on the mechanism class include conjunctivitis, injection-site reactions, hypersensitivity and infection. Risks are mitigated by exclusion of active infection, ophthalmological referral pathways, stopping rules for serious hypersensitivity and independent safety monitoring.",
        ),
        b(
            8,
            "section.2.7",
            f"The benefit–risk balance is considered acceptable for a placebo-controlled dose-ranging study in adults with moderate-to-severe disease who have access to background topical therapy and rescue, given the tolerability of {_D} in Phase 1 and the unmet need in this population.",
        ),
        b(
            9,
            "section.3.1",
            f"The primary objective is to compare the proportion of participants achieving EASI-75 at Week 16 between {_D} 300 mg every 2 weeks and placebo. Secondary objectives compare EASI-90, vIGA-AD 0/1 with a ≥2-point improvement, a ≥4-point improvement in Peak Pruritus NRS, and percent change in EASI at Week 16. Safety, pharmacokinetics and immunogenicity are assessed throughout.",
            [c(id="c-tpl09a", path="endpoints[easi75].time.offset.value", value=16, text="Week 16")],
        ),
        b(
            10,
            "section.3.2",
            "The primary estimand uses a composite strategy: participants who take qualifying rescue therapy or permanently discontinue study intervention before Week 16 are counted as non-responders. A supplementary treatment-policy estimand uses the observed Week 16 response regardless of rescue. The percent-change endpoint uses a hypothetical strategy for rescue, with post-rescue values set to missing and imputed.",
            [
                c(
                    id="c-tpl10a",
                    path="estimands[est_primary].intercurrent_event_strategies.0.strategy",
                    value="composite",
                    text="composite strategy",
                )
            ],
        ),
        b(
            11,
            "section.4.1",
            f"This is a randomized, double-blind, placebo-controlled, parallel-group study. Participants are randomized 1:1:1 to {_D} 300 mg Q2W (with a 600 mg loading dose), {_D} 150 mg Q2W, or placebo, stratified by baseline vIGA-AD (3 vs 4) and region.",
        ),
        b(
            12,
            "section.4.3",
            "The study comprises a screening period of up to 4 weeks, a 16-week double-blind treatment period and a 12-week safety follow-up period after the last dose.",
            [
                c(id="c-tpl12a", path="periods[screening].duration.value", value=4, text="4 weeks"),
                c(id="c-tpl12b", path="periods[follow_up].duration.value", value=12, text="12-week"),
            ],
        ),
        b(
            13,
            "section.4.7",
            "A placebo control is justified because background topical corticosteroids are permitted for all participants and rescue therapy is available; the 16-week duration is standard for demonstrating efficacy on EASI-based endpoints in atopic dermatitis and permits dose–response characterisation before a confirmatory program.",
        ),
        b(
            14,
            "section.5.1",
            "The population is adults with moderate-to-severe atopic dermatitis who are candidates for systemic therapy, defined by EASI ≥16, vIGA-AD ≥3 and BSA ≥10% together with documented inadequate response to topical therapy. This matches the population in which systemic AD therapies have been evaluated and in which the benefit–risk of an investigational biologic is acceptable.",
        ),
        b(
            15,
            "section.5.2",
            "Participants must be 18 to 75 years of age with chronic AD for at least 1 year and inadequate response to medium-potency topical corticosteroids within 6 months. Participants are excluded if they have received a biologic or JAK inhibitor for AD within 12 weeks or 5 half-lives, have an active or chronic infection requiring systemic treatment, or are pregnant or breastfeeding.",
        ),
        b(
            16,
            "section.6.1",
            f"{_D} is supplied as a 150 mg/mL solution for subcutaneous injection in prefilled syringes. Placebo is a matching vehicle. Study intervention is administered every 2 weeks at the clinic for the first two doses and may be self-administered thereafter after training.",
        ),
        b(
            17,
            "section.6.2",
            f"The 300 mg Q2W regimen with a 600 mg loading dose is predicted from Phase 1 pharmacokinetics to achieve steady-state exposure above the concentration associated with >90% IL-13 target engagement by Week 2. The 150 mg Q2W regimen characterises the lower part of the exposure–response curve. Dose selection will be re-evaluated against the {_D} Investigator's Brochure at adaptation.",
        ),
        b(
            18,
            "section.6.5",
            "Participants, investigators, site staff and sponsor personnel involved in study conduct remain blinded until database lock. An independent unblinded statistician supports the data monitoring committee.",
        ),
        b(
            19,
            "section.6.10",
            "Low-to-medium potency topical corticosteroids are permitted as background therapy. Systemic corticosteroids, systemic immunosuppressants, phototherapy, other biologics and JAK inhibitors are prohibited except as rescue therapy. Rescue is discouraged before Week 4; when given, the agent, dose and dates are recorded and the participant continues scheduled assessments.",
        ),
        b(
            20,
            "section.7.2",
            "Study intervention is permanently discontinued for pregnancy, serious systemic hypersensitivity related to study intervention, or at the participant's request. Participants who stop study intervention remain in the study for scheduled efficacy and safety assessments unless consent is withdrawn.",
        ),
        b(
            21,
            "section.7.8",
            "All participants, including those who discontinue study intervention early, are followed for 12 weeks after the last dose for safety.",
        ),
        b(
            22,
            "section.8.2",
            "EASI and vIGA-AD are assessed by a trained investigator at screening, baseline and Weeks 2, 4, 8, 12 and 16. The same assessor should evaluate a participant throughout where feasible. BSA is assessed at screening, baseline and Weeks 4, 8, 12 and 16.",
        ),
        b(
            23,
            "section.8.3",
            "Participants record Peak Pruritus NRS daily in an electronic diary from screening to Week 16; the weekly average of the 7 days preceding each visit is used. DLQI is completed at baseline and Weeks 4, 8 and 16.",
        ),
        b(
            24,
            "section.8.10",
            "Treatment-period visits have a window of ±3 days relative to Day 1. The safety follow-up contact has a window of ±7 days.",
        ),
        b(
            25,
            "section.9.1",
            "An adverse event (AE) is any untoward medical occurrence in a participant administered study intervention, whether or not considered related. A serious adverse event (SAE) is an AE that results in death, is life-threatening, requires or prolongs hospitalisation, results in persistent disability, is a congenital anomaly, or is otherwise medically important. Conjunctivitis and keratitis are adverse events of special interest.",
        ),
        b(
            26,
            "section.9.3",
            "AEs are collected from informed consent through the safety follow-up visit. SAEs occurring after the follow-up visit that the investigator considers related are also reported.",
        ),
        b(
            27,
            "section.9.4",
            "Severity is graded as mild, moderate or severe. Causality is assessed by the investigator as related or not related to study intervention.",
        ),
        b(
            28,
            "section.9.5",
            "SAEs are reported to the sponsor within 24 hours of the investigator's awareness. The sponsor reports suspected unexpected serious adverse reactions to regulatory authorities and ethics committees within required timelines.",
        ),
        b(
            29,
            "section.10.1",
            f"The full analysis set (FAS) comprises all randomized participants analysed by randomized arm. The safety analysis set comprises all participants who received at least one dose, analysed by treatment received. The PK analysis set comprises participants who received {_D} with at least one evaluable post-dose concentration.",
        ),
        b(
            30,
            "section.10.2",
            "The primary analysis compares EASI-75 response at Week 16 between the 300 mg arm and placebo in the FAS using a Cochran–Mantel–Haenszel test stratified by baseline vIGA-AD and region, with the difference in proportions and 95% CI. Participants with qualifying rescue or permanent discontinuation before Week 16 are non-responders; missing Week 16 EASI for other reasons is imputed as non-response.",
        ),
        b(
            31,
            "section.10.5",
            "For the primary composite estimand, missing Week 16 data are treated as non-response. For the percent-change endpoint, post-rescue values are set to missing and an MMRM assuming missing-at-random is used, with a tipping-point analysis exploring departures from that assumption.",
        ),
        b(
            32,
            "section.10.7",
            "Primary and key secondary endpoints for the 300 mg arm are tested in a fixed sequence (EASI-75, EASI-90, vIGA-AD 0/1, NRS-4) at two-sided alpha 0.05. Comparisons for the 150 mg arm are not part of the confirmatory hierarchy.",
            [c(id="c-tpl32a", path="testing_families[tf_primary].alpha", value=0.05, text="0.05")],
        ),
        b(
            33,
            "section.10.10",
            "With 56 evaluable participants per arm, the study has 90% power to detect a difference in EASI-75 response of 60% versus 30% at two-sided alpha 0.05. Allowing for 10% non-evaluable participants, 63 participants per arm (126 across the two arms used for the primary comparison) will be randomized; the 150 mg arm adds a further 63.",
            [c(id="c-tpl33a", path="protocol.planned_enrollment", value=126, text="126")],
        ),
        b(
            34,
            "section.11.1",
            "The study is conducted in accordance with ICH GCP and the Declaration of Helsinki. IRB/IEC approval is obtained before enrolment, and written informed consent is obtained from every participant before any study procedure.",
        ),
        b(
            35,
            "section.11.2",
            "An independent data monitoring committee reviews unblinded safety data after 40 and 80 participants complete Week 8 and may recommend modification or termination.",
        ),
        b(
            36,
            "section.11.3",
            "Risk-based monitoring is used, with source data verification of eligibility, the primary endpoint and serious adverse events.",
        ),
        b(
            37,
            "section.11.5",
            "Data are captured in a validated electronic data capture system with an audit trail. The database is locked after the last participant's safety follow-up visit and resolution of queries.",
        ),
        b(
            38,
            "section.11.8",
            "Protocol deviations are documented and reported to the sponsor; important deviations are reported to the IRB/IEC according to local requirements.",
        ),
        b(
            39,
            "section.12.4",
            "EASI (0–72), vIGA-AD (0–4), BSA (%), Peak Pruritus NRS (0–10, weekly average) and DLQI (0–30) are scored according to their published scoring manuals, referenced in Section 14.",
        ),
        b(
            40,
            "section.13.1",
            "AD: atopic dermatitis. AE: adverse event. BSA: body surface area. CMH: Cochran–Mantel–Haenszel. DLQI: Dermatology Life Quality Index. DMC: data monitoring committee. EASI: Eczema Area and Severity Index. FAS: full analysis set. IL-13: interleukin-13. MMRM: mixed model for repeated measures. NRS: numeric rating scale. Q2W: every 2 weeks. SAE: serious adverse event. TCS: topical corticosteroid. vIGA-AD: validated Investigator Global Assessment for atopic dermatitis.",
            kind="bullets",
        ),
        b(
            41,
            "section.14.1",
            f"1. Hanifin JM, Rajka G. Diagnostic features of atopic dermatitis. Acta Derm Venereol 1980. 2. Hanifin JM et al. The Eczema Area and Severity Index (EASI). Exp Dermatol 2001. 3. {_D} Investigator's Brochure, current edition (to be confirmed). 4. ICH E9(R1) Addendum on estimands and sensitivity analysis. 5. ICH M11 Clinical electronic Structured Harmonised Protocol.",
            kind="bullets",
        ),
    ]
