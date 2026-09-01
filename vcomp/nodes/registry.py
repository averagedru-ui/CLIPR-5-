"""Node type registry + menu categories."""
from __future__ import annotations

from typing import Iterable, Type

from vcomp.nodes.base import VNode

_REGISTRY: dict[str, Type[VNode]] = {}


def register(cls: Type[VNode]) -> Type[VNode]:
    if not cls.type_name or cls.type_name == "VNode":
        raise ValueError(f"{cls} needs a unique type_name")
    if cls.type_name in _REGISTRY:
        raise ValueError(f"duplicate node type {cls.type_name!r}")
    _REGISTRY[cls.type_name] = cls
    return cls


def get(type_name: str) -> Type[VNode]:
    return _REGISTRY[type_name]


def all_types() -> Iterable[Type[VNode]]:
    return list(_REGISTRY.values())


def by_category() -> dict[str, list[Type[VNode]]]:
    out: dict[str, list[Type[VNode]]] = {}
    for cls in _REGISTRY.values():
        out.setdefault(cls.category, []).append(cls)
    for v in out.values():
        v.sort(key=lambda c: c.title_default)
    return out


def load_builtin_nodes() -> None:
    """Import modules that register node types (call once at startup)."""
    from vcomp.nodes import (  # noqa: F401
        adjust, background, composite, framing, layout, region, source, text, value,
    )
