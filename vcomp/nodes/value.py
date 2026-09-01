"""Time and Expression value nodes (Value / Color live in source.py)."""
from __future__ import annotations

import ast
import math
import operator
from typing import Any

from vcomp.core.params import Param, ParamType, WireType
from vcomp.nodes.base import VNode
from vcomp.nodes.registry import register


@register
class Time(VNode):
    type_name = "Time"
    category = "Input"
    title_default = "Time"
    color = (120, 120, 150)

    def _define(self) -> None:
        self.add_param(Param("clip_duration", ParamType.FLOAT, 1.0, min=0.001, group="Time",
                             tooltip="Used to normalise progress."))
        self.add_param(Param("fps", ParamType.FLOAT, 30.0, min=1, group="Time"))
        self.add_output("seconds", WireType.NUMBER)
        self.add_output("frame", WireType.NUMBER)
        self.add_output("normalized_progress", WireType.NUMBER)

    def is_time_dependent(self) -> bool:
        return True

    def render(self, ctx, inputs: dict[str, Any]) -> dict[str, Any]:
        dur = max(1e-3, float(self.params["clip_duration"].value))
        return {
            "seconds": float(ctx.t),
            "frame": float(ctx.t * float(self.params["fps"].value)),
            "normalized_progress": max(0.0, min(1.0, ctx.t / dur)),
        }


_ALLOWED_FUNCS = {
    "min": min, "max": max, "abs": abs, "sin": math.sin, "cos": math.cos,
    "floor": math.floor, "ceil": math.ceil,
    "clamp": lambda x, lo, hi: max(lo, min(hi, x)),
    "lerp": lambda a, b, t: a + (b - a) * t,
    "smoothstep": lambda e0, e1, x: (lambda t: t * t * (3 - 2 * t))(
        max(0.0, min(1.0, (x - e0) / (e1 - e0))) if e1 != e0 else 0.0),
}
_BIN_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Mod: operator.mod, ast.Pow: operator.pow,
}


class ExpressionError(Exception):
    pass


def _safe_eval(node: ast.AST, env: dict) -> float:
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body, env)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return float(node.value)
        raise ExpressionError("only numeric constants allowed")
    if isinstance(node, ast.Name):
        if node.id in env:
            return float(env[node.id])
        raise ExpressionError(f"unknown name {node.id!r}")
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        return _BIN_OPS[type(node.op)](_safe_eval(node.left, env), _safe_eval(node.right, env))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        v = _safe_eval(node.operand, env)
        return v if isinstance(node.op, ast.UAdd) else -v
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        fn = _ALLOWED_FUNCS.get(node.func.id)
        if fn is None:
            raise ExpressionError(f"function {node.func.id!r} not allowed")
        return float(fn(*[_safe_eval(a, env) for a in node.args]))
    raise ExpressionError(f"illegal syntax: {ast.dump(node)}")


def safe_expression(expr: str, env: dict) -> float:
    tree = ast.parse(expr, mode="eval")
    return _safe_eval(tree, env)


@register
class Expression(VNode):
    type_name = "Expression"
    category = "Input"
    title_default = "Expression"
    color = (130, 120, 150)

    def _define(self) -> None:
        for name in ("a", "b", "c", "d"):
            self.add_param(Param(name, ParamType.FLOAT, 0.0, group="Inputs",
                                 accepts_input=True, input_wire=WireType.NUMBER))
        self.add_param(Param("expr", ParamType.STR, "a + b", group="Expression",
                             tooltip="Whitelist: + - * / % ** ( ) min max clamp abs "
                                     "sin cos floor ceil lerp smoothstep pi t"))
        self.add_output("value", WireType.NUMBER)

    def is_time_dependent(self) -> bool:
        return "t" in str(self.params["expr"].value)

    def render(self, ctx, inputs: dict[str, Any]) -> dict[str, Any]:
        env = {
            "a": self.p("a", ctx.t, inputs), "b": self.p("b", ctx.t, inputs),
            "c": self.p("c", ctx.t, inputs), "d": self.p("d", ctx.t, inputs),
            "pi": math.pi, "t": ctx.t,
        }
        try:
            return {"value": float(safe_expression(str(self.params["expr"].value), env))}
        except (ExpressionError, SyntaxError, ValueError, ZeroDivisionError):
            return {"value": 0.0}
