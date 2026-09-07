"""Schema loading and validation.

Two validation modes exist on purpose (see docs/01_architecture.md §6.3):

- ``draft-tolerant`` (``strict=False``): structural errors that would corrupt the
  document (wrong types, unknown properties, bad enums) are reported; *missing
  required fields are not* — incompleteness is the job of the rules engine,
  which turns it into ``incomplete`` findings that feed completion.
- ``strict`` (``strict=True``): full schema validation. Required before a
  version can be frozen or a block approved.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

SCHEMA_VERSION = "0.1.0"

# reference/ is a read-only input shipped with the repo; resolve it relative to
# this file so the package works from a checkout and from an installed wheel
# that vendors the folder (see packages/model/README.md).
_REFERENCE_DIR = Path(__file__).resolve().parents[4] / "reference"
_SCHEMA_PATH = _REFERENCE_DIR / "protocol_model.schema.json"


@dataclass(frozen=True)
class ValidationIssue:
    """One schema violation, expressed in a way the UI can point at."""

    path: str  # dotted JSON path, e.g. "endpoints.2.time.offset.value"
    message: str
    keyword: str  # jsonschema keyword that failed (type, enum, required, ...)


def reference_dir() -> Path:
    return _REFERENCE_DIR


@lru_cache(maxsize=1)
def load_schema() -> dict[str, Any]:
    with _SCHEMA_PATH.open(encoding="utf-8") as fh:
        schema: dict[str, Any] = json.load(fh)
    return schema


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    schema = load_schema()
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def validate_model(model: dict[str, Any], *, strict: bool) -> list[ValidationIssue]:
    """Return schema issues for ``model``; empty list means valid for the mode."""
    issues: list[ValidationIssue] = []
    for err in _validator().iter_errors(model):
        if not strict and err.validator == "required":
            continue
        path = ".".join(str(p) for p in err.absolute_path)
        issues.append(ValidationIssue(path=path, message=err.message, keyword=str(err.validator)))
    issues.sort(key=lambda i: (i.path, i.keyword))
    return issues


def empty_model(*, protocol_id: str, name: str, indication: str) -> dict[str, Any]:
    """The smallest document the schema accepts (strict mode)."""
    return {
        "schema_version": SCHEMA_VERSION,
        "document_kind": "authored_draft",
        "protocol": {
            "id": protocol_id,
            "name": name,
            "version_label": "0.1",
            "indication": indication,
        },
    }
