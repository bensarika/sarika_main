"""StudyRecord: the canonical JSON for one parsed study package.

Design (docs/01_architecture.md §7): one record per study *package* (a protocol
and its amendments/SAP), keyed by a stable id. Every fact is a small typed
object with a ``Provenance`` so a reader can jump to the page. Values are kept
close to how the source states them (``transformation: percent_change`` rather
than a paraphrase) so comparisons are mechanical, not interpretive.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SourceStatus = Literal["quoted", "registry", "synthetic", "unverified"]
"""How a fact was obtained.

quoted      text quoted from a retrieved document page (page number in Provenance)
registry    taken from ClinicalTrials.gov / EU CTR fields, not from the document body
synthetic   invented planning fixture — never a real trial result
unverified  stated in a source we could not machine-read; needs human confirmation
"""

Transformation = Literal["absolute_change", "percent_change", "responder", "score", "time_to_event", "other"]


class Provenance(BaseModel):
    document: str = ""  # human label: "Protocol Amendment 1 (07 Jun 2024)"
    source_id: str = ""  # SourceRecord id or inventory source_id
    page: int | None = None  # physical PDF page, 1-based
    section: str = ""  # "§5.1", "Criterion 2"
    quote: str = ""  # short verbatim excerpt when status == quoted
    status: SourceStatus = "unverified"
    url: str = ""


class StudyDocument(BaseModel):
    source_id: str
    kind: Literal["protocol", "sap", "fda_review", "label", "registry", "other"] = "protocol"
    title: str = ""
    version_label: str = ""
    date: str = ""
    url: str = ""
    sha256: str = ""
    bytes: int = 0
    pages: int | None = None
    text_extractable: bool | None = None


class Arm(BaseModel):
    id: str
    label: str
    role: Literal["investigational", "placebo", "active_comparator", "other"] = "investigational"
    regimen: str = ""
    planned_n: int | None = None


class Endpoint(BaseModel):
    id: str
    role: Literal["primary", "key_secondary", "secondary", "exploratory", "safety", "other"]
    label: str  # "Percent change in EASI from baseline to Week 16"
    instrument: str = ""  # EASI, IGA, NRS
    transformation: Transformation = "other"
    responder_threshold: str = ""  # "75%" for EASI-75
    timepoint_weeks: float | None = None
    population: str = ""  # "Biologic-naive group" etc.
    provenance: Provenance = Field(default_factory=Provenance)


class Criterion(BaseModel):
    id: str
    kind: Literal["inclusion", "exclusion"]
    category: str  # age | diagnosis | severity | prior_treatment | contraception | ...
    text: str
    min_age: float | None = None
    max_age: float | None = None
    regional_exceptions: list[str] = Field(default_factory=list)
    provenance: Provenance = Field(default_factory=Provenance)


class ResultPoint(BaseModel):
    endpoint_id: str
    arm_id: str
    timepoint_weeks: float
    value: float  # proportion (0–1) for responder endpoints; mean change otherwise
    unit: str = ""  # "proportion", "points", "%"
    n: int | None = None
    ci_low: float | None = None
    ci_high: float | None = None
    provenance: Provenance = Field(default_factory=Provenance)


class StudyRecord(BaseModel):
    """The common canonical record. ``record_version`` is the schema version, bump on breaking change."""

    record_version: str = "0.2.0"
    id: str  # "lebrikizumab-drm06-ad01"
    indication: str  # "atopic-dermatitis"
    title: str
    intervention: str
    drug_class: str = ""
    mechanism: str = ""
    phase: str = ""
    sponsor: str = ""
    registry_ids: list[str] = Field(default_factory=list)
    protocol_identifier: str = ""
    design: str = ""
    background_therapy: str = ""
    rescue_policy: str = ""
    population_summary: str = ""
    treatment_weeks: float | None = None
    arms: list[Arm] = Field(default_factory=list)
    endpoints: list[Endpoint] = Field(default_factory=list)
    criteria: list[Criterion] = Field(default_factory=list)
    results: list[ResultPoint] = Field(default_factory=list)
    documents: list[StudyDocument] = Field(default_factory=list)
    review_scope: str = ""  # what was actually reviewed; honesty about coverage
    notes: str = ""
    synthetic: bool = False

    def primary(self) -> Endpoint | None:
        return next((e for e in self.endpoints if e.role == "primary"), None)

    def endpoint(self, endpoint_id: str) -> Endpoint | None:
        return next((e for e in self.endpoints if e.id == endpoint_id), None)

    def arm(self, arm_id: str) -> Arm | None:
        return next((a for a in self.arms if a.id == arm_id), None)
