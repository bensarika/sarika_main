"""ps_model — the authoritative trial model.

Public surface (keep this list in sync with README.md):

- ``schema``      load/validate documents against ``reference/protocol_model.schema.json``
- ``outline``     the 15-entry canonical outline (Section 0 + ICH M11 1–14)
- ``slots``       required-slot map: which model fields each section needs
- ``completion``  ``% = filled_required_slots / applicable_required_slots`` per section
- ``refs``        reference-integrity helpers (entity index, dangling references)
- ``paths``       dotted-path get/set used by the edit/commit engine

The model is a plain ``dict`` conforming to the toolkit schema. We deliberately
do not wrap it in a class hierarchy: the schema is still evolving (0.1.0) and
JSON in/out is what the API, the rules and the renderer all consume.
"""

from ps_model.completion import NarrativeState, SectionCompletion, completion_for_model, overall_completion
from ps_model.outline import OUTLINE, Section, section_by_id
from ps_model.paths import PathError, get_path, set_path
from ps_model.refs import EntityIndex, index_entities
from ps_model.schema import SCHEMA_VERSION, ValidationIssue, empty_model, load_schema, validate_model

__all__ = [
    "OUTLINE",
    "SCHEMA_VERSION",
    "EntityIndex",
    "NarrativeState",
    "PathError",
    "Section",
    "SectionCompletion",
    "ValidationIssue",
    "completion_for_model",
    "empty_model",
    "get_path",
    "index_entities",
    "load_schema",
    "overall_completion",
    "section_by_id",
    "set_path",
    "validate_model",
]
