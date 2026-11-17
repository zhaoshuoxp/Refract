"""Prism user-equation language -> vectorised Python functions.

Supports what Prism's built-in equations use: numbers, case-insensitive
identifiers (parameters, X, intermediate variables, pi), + - * / ^ (right
associative, binding tighter than unary minus: -X^2 = -(X^2)), parentheses,
functions (exp, ln, log = log10, sqrt, abs, sin, cos, tan, arctan, sinh,
cosh, tanh, int, sign, min, max, if(cond, a, b)) and comparisons inside
if(); "text" in double quotes (a text result of if()). A definition is one or more lines "name = expr"; the line assigning Y
gives the model, earlier lines define intermediate variables.

The parser builds an expression tree from tokens and emits code that only
references the tree's own names, so evaluation runs no user-supplied code.
"""

from __future__ import annotations

import re

import numpy as np

_TOKEN = re.compile(r"\s*(?:(\d+\.?\d*(?:[eE][-+]?\d+)?|\.\d+(?:[eE][-+]?\d+)?)|([A-Za-z_][A-Za-z_0-9]*)|(<=|>=|<>|[-+*/^(),<>=])|(\"[^\"]*\"))")

FUNCS = {
    "exp": "np.exp", "ln": "np.log", "log": "np.log10", "sqrt": "np.sqrt", "abs": "np.abs", "sin": "np.sin",
    "cos": "np.cos", "tan": "np.tan", "arctan": "np.arctan", "atan": "np.arctan", "sinh": "np.sinh", "cosh": "np.cosh",
    "tanh": "np.tanh", "int": "np.trunc", "sign": "np.sign", "min": "np.minimum", "max": "np.maximum",
}
CONSTS = {"pi": "np.pi"}


class EquationError(ValueError):
    pass


def _tokens(s: str) -> list[str]:
    out, pos = [], 0
    s = s.strip()
    while pos < len(s):
        m = _TOKEN.match(s, pos)
        if not m or m.end() == pos:
            raise EquationError(f"cannot parse near {s[pos:pos + 12]!r}")
        out.append(next(g for g in m.groups() if g is not None))
        pos = m.end()
    return out


class _Parser:
    def __init__(self, toks: list[str], names: dict[str, str]):
        self.t, self.i, self.names = toks, 0, names

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self, want=None):
        tok = self.peek()
        if tok is None or (want is not None and tok != want):
            raise EquationError(f"expected {want!r}, got {tok!r}")
        self.i += 1
        return tok

    def parse(self) -> str:
        e = self.comparison()
        if self.peek() is not None:
            raise EquationError(f"unexpected {self.peek()!r}")
        return e

    def comparison(self) -> str:
        a = self.additive()
        ops = {"<": "<", ">": ">", "<=": "<=", ">=": ">=", "=": "==", "<>": "!="}
        if self.peek() in ops:
            op = ops[self.take()]
            b = self.additive()
            return f"({a} {op} {b})"
        return a

    def additive(self) -> str:
        a = self.multiplicative()
        while self.peek() in ("+", "-"):
            op = self.take()
            a = f"({a} {op} {self.multiplicative()})"
        return a

    def multiplicative(self) -> str:
        a = self.unary()
        while self.peek() in ("*", "/"):
            op = self.take()
            a = f"({a} {op} {self.unary()})"
        return a

    def unary(self) -> str:
        if self.peek() in ("-", "+"):
            op = self.take()
            return f"({op}{self.unary()})"
        return self.power()

    def power(self) -> str:
        base = self.atom()
        if self.peek() == "^":
            self.take()
            exp = self.unary()  # right associative; 2^-3 allowed
            return f"np.power({base}, {exp})"
        return base

    def atom(self) -> str:
        tok = self.take()
        if tok == "(":
            e = self.comparison()
            self.take(")")
            return e
        if re.fullmatch(r"\d+\.?\d*(?:[eE][-+]?\d+)?|\.\d+(?:[eE][-+]?\d+)?", tok):
            return repr(float(tok))
        if tok.startswith('"'):  # a text value (Select and transform: if(E<=100, "Normal", ...)), a literal
            return repr(tok[1:-1])
        key = tok.lower()
        if self.peek() == "(" and (key in FUNCS or key == "if"):
            self.take("(")
            args = [self.comparison()]
            while self.peek() == ",":
                self.take()
                args.append(self.comparison())
            self.take(")")
            if key == "if":
                if len(args) != 3:
                    raise EquationError("IF needs three arguments")
                return f"np.where({args[0]}, {args[1]}, {args[2]})"
            return f"{FUNCS[key]}({', '.join(args)})"
        if key in self.names:
            return self.names[key]
        if key in CONSTS:
            return CONSTS[key]
        raise EquationError(f"unknown name {tok!r}")


def _safe(name: str) -> str:
    return "v_" + re.sub(r"\W", "_", name.lower())


class Model:
    """A compiled equation: model(x, params_vector) -> y."""

    def __init__(self, definition: str, parameters: list[str]):
        self.parameters = list(parameters)
        names = {p.lower(): _safe(p) for p in parameters}
        names["x"] = "x"
        lines = [ln.strip() for ln in definition.replace("\r", "\n").split("\n") if ln.strip()]
        body = []
        y_expr = None
        for ln in lines:
            if "=" not in ln:
                raise EquationError(f"not an assignment: {ln!r}")
            lhs, rhs = ln.split("=", 1)
            lhs = lhs.strip()
            code = _Parser(_tokens(rhs), names).parse()
            if lhs.lower() == "y":
                y_expr = code
            else:
                names[lhs.lower()] = _safe(lhs)
                body.append(f"    {_safe(lhs)} = {code}")
        if y_expr is None:
            raise EquationError("no Y = ... line")
        unpack = "".join(f"    {_safe(p)} = p[{i}]\n" for i, p in enumerate(self.parameters))
        src = "def f(x, p):\n" + unpack + "\n".join(body) + ("\n" if body else "") + f"    return {y_expr} + 0 * x\n"
        ns: dict = {"np": np}
        exec(compile(src, "<equation>", "exec"), ns)  # noqa: S102 - code generated from parsed tokens only
        self._f = ns["f"]
        self.source = src

    def __call__(self, x, p):
        with np.errstate(all="ignore"):
            return self._f(np.asarray(x, float), np.asarray(p, float))


def expression(definition: str, parameters: list[str]):
    """Compile a transform such as "10^logEC50" -> f(params_vector)."""
    names = {p.lower(): f"p[{i}]" for i, p in enumerate(parameters)}
    code = _Parser(_tokens(definition), names).parse()
    ns: dict = {"np": np}
    exec(compile(f"def g(p):\n    return {code}\n", "<transform>", "exec"), ns)  # noqa: S102 - parsed tokens only
    return ns["g"]
