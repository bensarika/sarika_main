"""Dotted-path access into the model.

Paths look like ``protocol.name``, ``endpoints[easi75].time.offset.value`` or
``endpoints.2.name``. Inside a collection an ``[id]`` segment addresses an
entity by its stable ``id`` (preferred: ids survive reordering), while a bare
integer addresses by position (used only by schema error paths).
"""

from __future__ import annotations

import re
from typing import Any

_SEG = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)(?:\[([^\]]+)\])?|(\d+)")


class PathError(KeyError):
    """The path does not resolve in this model."""


def parse_path(path: str) -> list[str | int | tuple[str, str]]:
    """``"endpoints[easi75].time"`` → ``["endpoints", ("id", "easi75"), "time"]``."""
    out: list[str | int | tuple[str, str]] = []
    for part in path.split("."):
        m = _SEG.fullmatch(part)
        if not m:
            raise PathError(f"bad path segment {part!r} in {path!r}")
        name, ident, idx = m.groups()
        if idx is not None:
            out.append(int(idx))
            continue
        out.append(name)
        if ident is not None:
            out.append(("id", ident))
    return out


def _step(node: Any, seg: str | int | tuple[str, str], path: str) -> Any:
    if isinstance(seg, tuple):
        if not isinstance(node, list):
            raise PathError(f"{path}: expected a collection before [{seg[1]}]")
        for item in node:
            if isinstance(item, dict) and item.get("id") == seg[1]:
                return item
        raise PathError(f"{path}: no entity with id {seg[1]!r}")
    if isinstance(seg, int):
        if not isinstance(node, list) or seg >= len(node):
            raise PathError(f"{path}: index {seg} out of range")
        return node[seg]
    if not isinstance(node, dict) or seg not in node:
        raise PathError(f"{path}: missing key {seg!r}")
    return node[seg]


def get_path(model: dict[str, Any], path: str, default: Any = ...) -> Any:
    node: Any = model
    try:
        for seg in parse_path(path):
            node = _step(node, seg, path)
    except PathError:
        if default is not ...:
            return default
        raise
    return node


def set_path(model: dict[str, Any], path: str, value: Any) -> None:
    """Set ``path`` to ``value`` in place, creating intermediate objects.

    Intermediate *collections* are not created implicitly (adding an entity is
    a separate command), so an ``[id]`` segment must already resolve.
    """
    segs = parse_path(path)
    node: Any = model
    for i, seg in enumerate(segs[:-1]):
        if isinstance(seg, str) and isinstance(node, dict) and seg not in node:
            nxt = segs[i + 1]
            node[seg] = [] if isinstance(nxt, tuple | int) else {}
        node = _step(node, seg, path)
    last = segs[-1]
    if isinstance(last, tuple):
        raise PathError(f"{path}: cannot set an entity by id; use add_entity")
    if isinstance(last, int):
        node[last] = value
    else:
        node[last] = value


def delete_path(model: dict[str, Any], path: str) -> None:
    segs = parse_path(path)
    node: Any = model
    for seg in segs[:-1]:
        node = _step(node, seg, path)
    last = segs[-1]
    if isinstance(last, tuple):
        idx = next(i for i, it in enumerate(node) if it.get("id") == last[1])
        del node[idx]
    else:
        del node[last]
