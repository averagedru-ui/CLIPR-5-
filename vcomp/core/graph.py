"""Graph model: nodes, typed connections, topological evaluation.

* DAG with cycle detection (offending nodes are reported, not crashed on).
* Pull-based evaluation from the single ``Output`` node.
* Coarse frame cache: if no param/topology changed since the last evaluation of
  the same time, the previous result is returned. Fine-grained per-node texture
  caching is a later perf pass.

Qt-free. Thread-safe for the "mutate on GUI thread / evaluate on render thread"
split via a single RLock.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

from vcomp.core.params import WireType
from vcomp.nodes.base import VNode
from vcomp.nodes.registry import get as get_node_type

log = logging.getLogger("vcomp.graph")


@dataclass(frozen=True)
class Connection:
    from_node: str
    from_port: str
    to_node: str
    to_port: str


class GraphError(Exception):
    pass


@dataclass
class EvalContext:
    compositor: Any                    # render.compositor.Compositor
    t: float
    canvas_w: int
    canvas_h: int
    render_scale: float = 1.0
    frames: dict[str, np.ndarray] = field(default_factory=dict)   # ClipSource id -> RGB
    _fbos: list = field(default_factory=list)
    _textures: list = field(default_factory=list)

    @property
    def cw(self) -> int:
        return max(2, int(round(self.canvas_w * self.render_scale)))

    @property
    def ch(self) -> int:
        return max(2, int(round(self.canvas_h * self.render_scale)))

    def acquire_fbo(self, w: int | None = None, h: int | None = None):
        fbo = self.compositor.ctx.acquire_fbo(w or self.cw, h or self.ch)
        self._fbos.append(fbo)
        return fbo

    def upload(self, arr: np.ndarray):
        tex = self.compositor.ctx.texture_from_array(arr)
        self._textures.append(tex)
        return tex

    def release_all(self) -> None:
        for fbo in self._fbos:
            self.compositor.ctx.release_fbo(fbo)
        self._fbos.clear()
        for tex in self._textures:
            try:
                tex.release()
            except Exception:  # noqa: BLE001
                pass
        self._textures.clear()


class Graph:
    def __init__(self) -> None:
        self.nodes: dict[str, VNode] = {}
        self.connections: list[Connection] = []
        self.lock = threading.RLock()
        self._counter = 0
        self._cache_key: tuple | None = None
        self._cache_val: np.ndarray | None = None
        self.on_changed: list[Callable[[], None]] = []

    # ------------------------------------------------------------- mutation
    def _notify(self) -> None:
        self._cache_key = None
        for cb in list(self.on_changed):
            try:
                cb()
            except Exception:  # noqa: BLE001
                log.exception("graph change callback failed")

    def new_id(self, type_name: str) -> str:
        self._counter += 1
        return f"{type_name}_{self._counter}"

    def add_node(self, type_name: str, node_id: str | None = None,
                 title: str | None = None) -> VNode:
        with self.lock:
            cls = get_node_type(type_name)
            if cls.max_instances is not None:
                have = sum(1 for n in self.nodes.values() if n.type_name == type_name)
                if have >= cls.max_instances:
                    raise GraphError(f"only {cls.max_instances} {type_name} allowed")
            nid = node_id or self.new_id(type_name)
            node = cls(nid, title)
            self.nodes[nid] = node
            self._notify()
            return node

    def remove_node(self, node_id: str) -> None:
        with self.lock:
            node = self.nodes.get(node_id)
            if node is None:
                return
            if not node.deletable:
                raise GraphError(f"{node.type_name} cannot be deleted")
            self.connections = [c for c in self.connections
                                if node_id not in (c.from_node, c.to_node)]
            del self.nodes[node_id]
            self._notify()

    def connect(self, from_node: str, from_port: str, to_node: str, to_port: str) -> Connection:
        with self.lock:
            src = self.nodes[from_node]
            dst = self.nodes[to_node]
            op = src.port(from_port, is_input=False)
            ip = dst.port(to_port, is_input=True)
            if op is None or ip is None:
                raise GraphError("unknown port")
            if op.wire != ip.wire:
                raise GraphError(f"type mismatch: {op.wire.value} -> {ip.wire.value}")
            if not ip.multi:
                self.connections = [c for c in self.connections
                                    if not (c.to_node == to_node and c.to_port == to_port)]
            conn = Connection(from_node, from_port, to_node, to_port)
            if conn not in self.connections:
                self.connections.append(conn)
            if self._creates_cycle():
                self.connections.remove(conn)
                raise GraphError("connection would create a cycle")
            self._notify()
            return conn

    def disconnect(self, conn: Connection) -> None:
        with self.lock:
            if conn in self.connections:
                self.connections.remove(conn)
                self._notify()

    def set_param(self, node_id: str, name: str, value: Any) -> None:
        with self.lock:
            self.nodes[node_id].params[name].set(value)
            self._notify()

    def set_enabled(self, node_id: str, on: bool) -> None:
        with self.lock:
            self.nodes[node_id].enabled = bool(on)
            self._notify()

    # ----------------------------------------------------------- topology
    def _incoming(self, node_id: str) -> list[Connection]:
        return [c for c in self.connections if c.to_node == node_id]

    def _adjacency(self) -> dict[str, set[str]]:
        adj: dict[str, set[str]] = {n: set() for n in self.nodes}
        for c in self.connections:
            adj[c.to_node].add(c.from_node)
        return adj

    def _creates_cycle(self) -> bool:
        try:
            self.topo_order()
            return False
        except GraphError:
            return True

    def topo_order(self) -> list[str]:
        adj = self._adjacency()
        visited: dict[str, int] = {}
        order: list[str] = []

        def visit(n: str) -> None:
            state = visited.get(n, 0)
            if state == 1:
                raise GraphError(f"cycle at {n}")
            if state == 2:
                return
            visited[n] = 1
            for dep in adj[n]:
                visit(dep)
            visited[n] = 2
            order.append(n)

        for n in self.nodes:
            visit(n)
        return order

    def cycle_nodes(self) -> set[str]:
        """Best-effort set of nodes participating in a cycle (for red marking)."""
        adj = self._adjacency()
        color: dict[str, int] = {}
        bad: set[str] = set()
        stack: list[str] = []

        def dfs(n: str) -> None:
            color[n] = 1
            stack.append(n)
            for d in adj[n]:
                if color.get(d, 0) == 1:
                    i = stack.index(d)
                    bad.update(stack[i:])
                elif color.get(d, 0) == 0:
                    dfs(d)
            stack.pop()
            color[n] = 2

        for n in self.nodes:
            if color.get(n, 0) == 0:
                dfs(n)
        return bad

    def output_node(self) -> VNode:
        outs = [n for n in self.nodes.values() if n.type_name == "Output"]
        if not outs:
            raise GraphError("no Output node")
        return outs[0]

    # --------------------------------------------------------------- eval
    def _state_key(self, t: float) -> tuple:
        conns = tuple(sorted((c.from_node, c.from_port, c.to_node, c.to_port)
                             for c in self.connections))
        phash = tuple(sorted(n.param_hash(t) for n in self.nodes.values()))
        any_time = any(n.is_time_dependent() for n in self.nodes.values())
        return (conns, phash, round(t, 6) if any_time else 0)

    def evaluate(self, ctx: EvalContext) -> np.ndarray:
        with self.lock:
            key = self._state_key(ctx.t)
            if key == self._cache_key and self._cache_val is not None:
                return self._cache_val

            order = self.topo_order()
            results: dict[str, dict[str, Any]] = {}

            for nid in order:
                node = self.nodes[nid]
                resolved: dict[str, Any] = {}
                for port in node.inputs:
                    conns = [c for c in self._incoming(nid) if c.to_port == port.name]
                    vals = []
                    for c in conns:
                        up = results.get(c.from_node, {})
                        vals.append(up.get(c.from_port))
                    if port.multi:
                        resolved[port.name] = [v for v in vals if v is not None]
                    else:
                        resolved[port.name] = vals[0] if vals else None

                if not node.enabled:
                    results[nid] = self._passthrough(node, resolved)
                    continue
                try:
                    results[nid] = node.render(ctx, resolved) or {}
                except Exception:  # noqa: BLE001
                    log.exception("node %s (%s) render failed", nid, node.type_name)
                    results[nid] = {}

            out = self.output_node()
            final = results.get(out.id, {}).get("result")
            if final is None:
                final = np.zeros((ctx.canvas_h, ctx.canvas_w, 4), np.uint8)

            self._cache_key = key
            self._cache_val = final
            return final

    @staticmethod
    def _passthrough(node: VNode, resolved: dict[str, Any]) -> dict[str, Any]:
        # A disabled layer contributes nothing; a disabled modifier is bypassed.
        if not node.bypass_when_disabled:
            return {}
        img_in = next((resolved[p.name] for p in node.inputs
                       if p.wire == WireType.IMAGE and resolved.get(p.name) is not None), None)
        img_out = next((p.name for p in node.outputs if p.wire == WireType.IMAGE), None)
        return {img_out: img_in} if img_out else {}

    # ---------------------------------------------------------- serialize
    def to_dict(self) -> dict:
        return {
            "nodes": [n.to_dict() for n in self.nodes.values()],
            "connections": [c.__dict__ for c in self.connections],
        }

    def load_dict(self, data: dict) -> None:
        with self.lock:
            self.nodes.clear()
            self.connections.clear()
            for nd in data.get("nodes", []):
                node = get_node_type(nd["type"])(nd["id"], nd.get("title"))
                node.load_dict(nd)
                self.nodes[node.id] = node
                num = int(nd["id"].rsplit("_", 1)[-1]) if "_" in nd["id"] else 0
                self._counter = max(self._counter, num)
            for cd in data.get("connections", []):
                self.connections.append(Connection(**cd))
            self._notify()

    def ensure_output(self) -> VNode:
        try:
            return self.output_node()
        except GraphError:
            return self.add_node("Output")

    def canvas_params(self) -> tuple[int, int, float]:
        o = self.output_node()
        return (int(o.params["canvas_width"].value),
                int(o.params["canvas_height"].value),
                float(o.params["render_scale"].value))

    def clip_source_nodes(self) -> list[VNode]:
        return [n for n in self.nodes.values() if n.type_name == "Clip Source"]


def build_default_graph(g: Graph) -> Graph:
    """Clip Source -> Main Framing -> Stack ; Solid Background -> Stack ; Stack -> Output."""
    clip = g.add_node("Clip Source")
    framing = g.add_node("Main Framing")
    bg = g.add_node("Solid Background")
    stack = g.add_node("Stack")
    out = g.ensure_output()

    g.connect(clip.id, "image", framing.id, "image")
    g.connect(bg.id, "image", stack.id, "layers")       # layer 0 (bottom)
    g.connect(framing.id, "image", stack.id, "layers")  # layer 1 (top)
    g.connect(stack.id, "image", out.id, "image")
    g.connect(clip.id, "audio", out.id, "audio")
    return g
