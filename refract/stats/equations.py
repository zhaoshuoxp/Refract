"""The models offered for new curve fits and standard curves: each a
definition in Prism's equation syntax with its parameters, the rules for
their automatic initial values and default constraints (the vocabulary of
Prism's stored equations, E-stats8b). Names are our own wording.
"""

from __future__ import annotations

import copy


def _eq(name: str, definition: str, params: list[str], rules: dict[str, tuple[float, str]],
        constraints: dict | None = None, transforms: list | None = None, min_x: str = "MIN_X") -> dict:
    return {"name": name, "definition": definition + "\r\n", "tip": "", "description": "",
            "parameters": params, "intermediateVariables": [], "defaultMinCurveX": min_x,
            "initialValueRules": {p: {"value": v, "rule": r} for p, (v, r) in rules.items()},
            "defaultConstraints": dict(constraints or {}), "transforms": list(transforms or [])}


_POS = {"type": "GREATER", "value": 0.0}
_EC50 = {"name": "EC50", "definition": "10^LogEC50", "ciMethod": "ASYMMETRICAL"}
_SPAN = {"name": "Span", "definition": "Top-Bottom", "ciMethod": "SYMMETRICAL"}

EQUATIONS: dict[str, dict] = {
    "line": _eq("Straight line", "Y=YIntercept + Slope*X", ["YIntercept", "Slope"],
                {"YIntercept": (1.0, "VALUE"), "Slope": (1.0, "(YMAX-YMIN)/(XMAX-XMIN)")}),
    "quadratic": _eq("Second-order polynomial", "Y=B0 + B1*X + B2*X^2", ["B0", "B1", "B2"],
                     {"B0": (1.0, "VALUE"), "B1": (1.0, "VALUE"), "B2": (1.0, "VALUE")}),
    "log_3p": _eq("Dose-response, log(dose), standard slope (3 parameters)",
                  "Y=Bottom + (Top-Bottom)/(1+10^((LogEC50-X)))", ["Bottom", "Top", "LogEC50"],
                  {"Bottom": (1.0, "*YMIN"), "Top": (1.0, "*YMAX"), "LogEC50": (1.0, "X_AT_YMID")},
                  transforms=[_EC50, _SPAN]),
    "log_4p": _eq("Dose-response, log(dose), variable slope (4 parameters)",
                  "Y=Bottom + (Top-Bottom)/(1+10^((LogEC50-X)*HillSlope))", ["Bottom", "Top", "LogEC50", "HillSlope"],
                  {"Bottom": (1.0, "*YMIN"), "Top": (1.0, "*YMAX"), "LogEC50": (1.0, "X_AT_YMID"),
                   "HillSlope": (1.0, "SIGN(YatXMax - YatXMin)")}, transforms=[_EC50, _SPAN]),
    "binding": _eq("One-site binding (hyperbola)", "Y=Bmax*X/(Kd+X)", ["Bmax", "Kd"],
                   {"Bmax": (1.0, "*YMAX"), "Kd": (0.3, "*XMID")}, {"Bmax": _POS, "Kd": _POS}, min_x="X=0"),
    "decay": _eq("One-phase exponential decay", "Y=(Y0 - Plateau)*exp(-K*X) + Plateau", ["Y0", "Plateau", "K"],
                 {"Y0": (1.0, "*YMAX"), "Plateau": (1.0, "*YMIN"), "K": (1.0, "/X_AT_YMID")}, {"K": _POS}, min_x="X=0"),
    "gaussian": _eq("Gaussian", "Y=(AREA/(SD*(2*pi)^0.5))*exp(-0.5*((X-Mean)/SD)^2)", ["AREA", "SD", "Mean"],
                    {"AREA": (0.2, "(YMAX-YMIN)*(XMAX-XMIN)"), "SD": (0.2, "*(XMAX-XMIN)"), "Mean": (1.0, "*XMID")}),
}
LABELS = [(k, e["name"]) for k, e in EQUATIONS.items()]
STANDARD_CURVES = [(k, EQUATIONS[k]["name"]) for k in ("line", "quadratic", "log_4p", "log_3p")]


def model(key: str, sets: list[int]) -> dict:
    """The model block of a fit's parameters: the equation, its default
    constraints and automatic initial values for each data set."""
    eq = copy.deepcopy(EQUATIONS[key])
    return {"equation": eq, "constraints": copy.deepcopy(eq["defaultConstraints"]),
            "initialValues": {p: [{"dataSet": {"col": {"idx": int(i)}}, "isAuto": True, "value": 0.0} for i in sets]
                              for p in eq["parameters"]}}
