"""``VNode`` base class: typed ports, params, and a ``render`` hook.

Qt-free. Node ``render`` receives an :class:`EvalContext` (GL compositor + time +
per-node resource tracking) plus a dict of resolved input values, and returns a
dict of output-name -> value.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from vcomp.core.params import Param, WireType

if TYPE_CHECKING:
    from vcomp.core.graph import EvalContext


@dataclass
class Port:
    name: str
    wire: WireType
    is_input: bool
    multi: bool = False          # accepts many connections (Stack layers)


class VNode:
    type_name: str = "VNode"
    category: str = "Misc"
    title_default: str = "Node"
    color: tuple[int, int, int] = (90, 90, 100)
    max_instances: int | None = None
    deletable: bool = True

    def __init__(self, node_id: str, title: str | None = None) -> None:
        self.id = node_id
        self.title = title or self.title_default
        self.enabled = True
        self.params: dict[str, Param] = {}
        self.inputs: list[Port] = []
        self.outputs: list[Port] = []
        self._define()

    # -------------------------------------------------------------- subclass
    def _define(self) -> None:
        """Populate ``self.params`` / ``self.inputs`` / ``self.outputs``."""

    def render(self, ctx: "EvalContext", inputs: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def is_time_dependent(self) -> bool:
        return False

    # --------------------------------------------------------------- helpers
    def add_param(self, param: Param) -> Param:
        self.params[param.name] = param
        if param.accepts_input:
            self.inputs.append(Port(param.name, param.input_wire, is_input=True))
        return param

    def add_input(self, name: str, wire: WireType, multi: bool = False) -> None:
        self.inputs.append(Port(name, wire, is_input=True, multi=multi))

    def add_output(self, name: str, wire: WireType) -> None:
        self.outputs.append(Port(name, wire, is_input=False))

    def port(self, name: str, is_input: bool) -> Port | None:
        pool = self.inputs if is_input else self.outputs
        return next((p for p in pool if p.name == name), None)

    def p(self, name: str, t: float, resolved_inputs: dict[str, Any]) -> Any:
        """Evaluate a param, honouring a connected input port of the same name."""
        param = self.params[name]
        if param.name in resolved_inputs and resolved_inputs[param.name] is not None:
            return param.evaluate(t, upstream=lambda: resolved_inputs[param.name])
        return param.evaluate(t)

    def param_hash(self, t: float) -> str:
        h = hashlib.blake2b(digest_size=16)
        h.update(self.id.encode())
        h.update(b"1" if self.enabled else b"0")
        for name in sorted(self.params):
            snap = self.params[name].snapshot()
            h.update(name.encode())
            h.update(repr(snap).encode())
        if self.is_time_dependent():
            h.update(f"{t:.6f}".encode())
        return h.hexdigest()

    # ----------------------------------------------------------- serialize
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type_name,
            "title": self.title,
            "enabled": self.enabled,
            "params": {k: v.snapshot() for k, v in self.params.items()},
        }

    def load_dict(self, data: dict) -> None:
        self.title = data.get("title", self.title)
        self.enabled = data.get("enabled", True)
        for k, snap in data.get("params", {}).items():
            if k in self.params:
                self.params[k].restore(snap)
