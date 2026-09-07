"""Entity index and cross-reference discovery.

The toolkit schema references other entities through fields whose names end in
``_id`` / ``_ids`` (``endpoint_id``, ``assessment_ids`` …). The expected target
collection is derived from the field name, which is what R01 (reference
integrity) checks. Field names that do not follow the convention are listed in
``_SPECIAL_TARGETS``.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

# Top-level collections of identified entities (everything except protocol /
# collection_status / assertions bookkeeping).
COLLECTIONS: tuple[str, ...] = (
    "sources",
    "criteria",
    "populations",
    "products",
    "anchors",
    "regimens",
    "periods",
    "paths",
    "allocations",
    "transitions",
    "assessments",
    "encounters",
    "scheduled_activities",
    "objectives",
    "endpoints",
    "events",
    "estimands",
    "analysis_sets",
    "analyses",
    "testing_families",
    "rules",
    "roles",
    "governance",
    "dependencies",
    "assertions",
    "unresolved",
)

# singular field stem -> collection
_STEM_TO_COLLECTION: dict[str, str] = {
    "source": "sources",
    "criterion": "criteria",
    "population": "populations",
    "parent_population": "populations",
    "eligible_population": "populations",
    "product": "products",
    "anchor": "anchors",
    "elapsed_zero_anchor": "anchors",
    "regimen": "regimens",
    "period": "periods",
    "from_period": "periods",
    "to_period": "periods",
    "path": "paths",
    "from_path": "paths",
    "to_path": "paths",
    "allocation": "allocations",
    "transition": "transitions",
    "assessment": "assessments",
    "encounter": "encounters",
    "activity": "scheduled_activities",
    "before_activity": "scheduled_activities",
    "after_activity": "scheduled_activities",
    "objective": "objectives",
    "endpoint": "endpoints",
    "event": "events",
    "parent_event": "events",
    "estimand": "estimands",
    "analysis_set": "analysis_sets",
    "analysis": "analyses",
    "testing_family": "testing_families",
    "rule": "rules",
    "confirmation_rule": "rules",
    "overrides_rule": "rules",
    "role": "roles",
    "owner_role": "roles",
    "assessor_role": "roles",
    "dependency": "dependencies",
    "handling_dependency": "dependencies",
    "evidence_dependency": "dependencies",
    "method_dependency": "dependencies",
    "prior_dependency": "dependencies",
    "assertion": "assertions",
    "footnote_assertion": "assertions",
    "optional_consent": "dependencies",
}

_REF_FIELD = re.compile(r"^(?P<stem>[a-z_]+?)_(?P<plural>ids?)$")


@dataclass
class Reference:
    path: str  # dotted path of the referencing field
    target_collection: str
    target_id: str


@dataclass
class EntityIndex:
    """``by_collection[collection][id] -> entity`` plus duplicate detection."""

    by_collection: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
    duplicates: list[tuple[str, str]] = field(default_factory=list)  # (collection, id)

    def exists(self, collection: str, entity_id: str) -> bool:
        return entity_id in self.by_collection.get(collection, {})

    def get(self, collection: str, entity_id: str) -> dict[str, Any] | None:
        return self.by_collection.get(collection, {}).get(entity_id)


def index_entities(model: dict[str, Any]) -> EntityIndex:
    idx = EntityIndex()
    for coll in COLLECTIONS:
        items = model.get(coll) or []
        bucket: dict[str, dict[str, Any]] = {}
        for item in items:
            if not isinstance(item, dict) or "id" not in item:
                continue
            eid = str(item["id"])
            if eid in bucket:
                idx.duplicates.append((coll, eid))
            bucket[eid] = item
        idx.by_collection[coll] = bucket
    return idx


def collection_for_field(field_name: str) -> str | None:
    m = _REF_FIELD.match(field_name)
    if not m:
        return None
    return _STEM_TO_COLLECTION.get(m.group("stem"))


def iter_references(model: dict[str, Any]) -> Iterator[Reference]:
    """Yield every ``*_id`` / ``*_ids`` reference in the document with its path."""

    def walk(node: Any, path: str) -> Iterator[Reference]:
        if isinstance(node, dict):
            for k, v in node.items():
                p = f"{path}.{k}" if path else k
                coll = collection_for_field(k)
                if coll and isinstance(v, str):
                    yield Reference(p, coll, v)
                elif coll and isinstance(v, list):
                    for i, x in enumerate(v):
                        if isinstance(x, str):
                            yield Reference(f"{p}.{i}", coll, x)
                else:
                    yield from walk(v, p)
        elif isinstance(node, list):
            for i, x in enumerate(node):
                # prefer [id] addressing for entities so paths stay stable
                key = f"{path}[{x['id']}]" if isinstance(x, dict) and "id" in x else f"{path}.{i}"
                yield from walk(x, key)

    yield from walk(model, "")
