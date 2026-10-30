"""Tool layer: the closed set of comparisons exposed to the agent (and to `capiv run`).

Each comparison is a plain function `run_<name>(con, args) -> ToolOutput` that the
MCP tool wrappers in `agent.py` call. Arguments are validated here against a JSON
schema that is also what the model sees, so there is one source of truth.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import duckdb
import pandas as pd

from . import plots, queries
from .queries import FLUIDS, AnalogFilter

# ----------------------------------------------------------------------------- schema bits

_FILTER_PROPS: dict[str, Any] = {
    "cuenca": {"type": "string", "description": "Basin, e.g. NEUQUINA, GOLFO SAN JORGE, AUSTRAL, CUYANA, NOROESTE."},
    "areas": {"type": "array", "items": {"type": "string"},
              "description": "One or more `areayacimiento` names (exact, case-insensitive), e.g. [\"BANDURRIA SUR\", \"LA AMARGA CHICA\"]. Use list_areas to discover them."},
    "formacion": {"type": "string", "description": "Producing formation, lower case as in the dataset, e.g. 'vaca muerta', 'lajas', 'mulichinco'."},
    "sub_tipo_recurso": {"type": "string", "enum": ["SHALE", "TIGHT"], "description": "Unconventional sub-type. Omit for conventional or mixed."},
    "tipo_de_recurso": {"type": "string", "enum": ["CONVENCIONAL", "NO CONVENCIONAL"]},
    "vintage_from": {"type": "string", "description": "YYYY-MM. Only analog wells whose first production is on/after this month."},
    "vintage_to": {"type": "string", "description": "YYYY-MM. Only analog wells whose first production is on/before this month."},
    "exclude_empresa": {"type": "string", "description": "Operator name to exclude from the analog set (e.g. the company itself if it also reports publicly)."},
}
_FLUID = {"type": "string", "enum": ["oil", "gas"], "description": "Fluid to compare (default oil). Picks oil wells / gas wells accordingly."}


def _schema(extra: dict[str, Any] | None = None, required: list[str] | None = None, with_fluid: bool = True) -> dict:
    props = dict(_FILTER_PROPS)
    if with_fluid:
        props["fluid"] = _FLUID
    props.update(extra or {})
    return {"type": "object", "properties": props, "required": required or [], "additionalProperties": False}


def _filter(args: dict) -> AnalogFilter:
    return AnalogFilter(
        cuenca=args.get("cuenca"), areas=list(args.get("areas") or []), formacion=args.get("formacion"),
        sub_tipo_recurso=args.get("sub_tipo_recurso"), tipo_de_recurso=args.get("tipo_de_recurso"),
        vintage_from=args.get("vintage_from"), vintage_to=args.get("vintage_to"),
        exclude_empresa=args.get("exclude_empresa"),
    )


def _fluid(args: dict) -> str:
    f = args.get("fluid") or "oil"
    if f not in FLUIDS:
        raise ValueError("fluid must be 'oil' or 'gas'")
    return f


# ----------------------------------------------------------------------------- output

@dataclass
class ToolOutput:
    text: str
    png: Path | None = None

    def to_mcp(self) -> dict:
        content: list[dict] = [{"type": "text", "text": self.text}]
        if self.png and self.png.exists():
            data = base64.b64encode(self.png.read_bytes()).decode()
            content.append({"type": "image", "data": data, "mimeType": "image/png"})
            content.append({"type": "text", "text": f"(chart saved to {self.png})"})
        return {"content": content}


def _fmt_float(decimals: int):
    def f(v):
        if pd.isna(v):
            return ""
        if float(v).is_integer() and abs(v) >= 10:
            return f"{v:,.0f}"
        if abs(v) < 10:
            return f"{v:,.{max(decimals, 2)}f}"
        return f"{v:,.{decimals}f}" if abs(v) < 1000 else f"{v:,.0f}"
    return f


def md_table(df: pd.DataFrame, max_rows: int = 60, decimals: int = 1) -> str:
    if df is None or df.empty:
        return "_(no rows)_"
    d = df.head(max_rows).copy()
    for c in d.columns:
        if pd.api.types.is_datetime64_any_dtype(d[c]):
            d[c] = d[c].dt.strftime("%Y-%m")
        elif pd.api.types.is_float_dtype(d[c]):
            d[c] = d[c].map(_fmt_float(decimals))
        else:
            d[c] = d[c].map(lambda v: "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v))
    head = "| " + " | ".join(map(str, d.columns)) + " |"
    sep = "|" + "|".join("---" for _ in d.columns) + "|"
    body = "\n".join("| " + " | ".join(r) + " |" for r in d.astype(str).itertuples(index=False))
    more = f"\n_({len(df) - max_rows} more rows not shown)_" if len(df) > max_rows else ""
    return "\n".join([head, sep, body]) + more


def _units(fluid: str) -> str:
    return FLUIDS[fluid][1]


# ----------------------------------------------------------------------------- the tools

def run_company_summary(con: duckdb.DuckDBPyConnection, args: dict) -> ToolOutput:
    df = queries.company_summary(con)
    if df.empty:
        return ToolOutput("No company data loaded. Run `capiv load-company <file.csv>` first.")
    text = (f"Company wells loaded: {len(df)} (operator: {df['empresa'].iloc[0]}).\n"
            f"Units: oil/water m³, gas thousand m³ (Mm³).\n\n" + md_table(df, decimals=0))
    return ToolOutput(text)


def run_list_areas(con, args: dict) -> ToolOutput:
    f, fluid = _filter(args), _fluid(args)
    df = queries.list_areas(con, f, fluid, int(args.get("min_wells", 5)), int(args.get("limit", 40)))
    text = (f"Areas matching [{f.describe()}], {fluid} wells, >= {args.get('min_wells', 5)} wells. "
            f"p50_cum12 in {_units(fluid)} (first 12 months), p50_peak_rate in {_units(fluid)}/d.\n\n" + md_table(df, decimals=0))
    return ToolOutput(text)


def run_type_curve(con, args: dict) -> ToolOutput:
    f, fluid = _filter(args), _fluid(args)
    months = int(args.get("months", 36))
    curve, mine = queries.type_curve(con, f, fluid, months)
    if curve.empty:
        return ToolOutput(f"No analog wells match [{f.describe()}]. Loosen the filter or check names with list_areas.")
    title = f"type curve {fluid} - {f.describe()}"
    png = plots.type_curve(curve, mine, title, _units(fluid)) if args.get("plot", True) else None
    n0 = int(curve["wells"].max())
    txt = [f"Analog set: {n0} {fluid} wells [{f.describe()}]. Rates are calendar-day rates in {_units(fluid)}/d by month on production (MOP). "
           "P90 = 90% of analog wells are below that value.", "", md_table(curve.round(1), max_rows=months + 1)]
    if not mine.empty:
        txt += ["", f"Company wells ({mine.shape[1]}), same normalisation:", md_table(mine.reset_index().round(1), max_rows=months + 1)]
        # quick read: where does each company well sit at MOP 6 and 12 vs P50
        rows = []
        for col in mine.columns:
            for mop in (3, 6, 12, 24):
                if mop in mine.index and mop in curve["mop"].values and not pd.isna(mine.loc[mop, col]):
                    p50 = float(curve.loc[curve["mop"] == mop, "p50"].iloc[0])
                    rows.append({"sigla": col, "mop": mop, "rate": mine.loc[mop, col], "analog_p50": p50,
                                 "vs_p50_%": (mine.loc[mop, col] / p50 - 1) * 100 if p50 else None})
        if rows:
            txt += ["", "Company wells vs analog P50 at selected MOP:", md_table(pd.DataFrame(rows))]
    else:
        txt += ["", "(no company data loaded; analog curve only)"]
    return ToolOutput("\n".join(txt), png)


def run_well_benchmark(con, args: dict) -> ToolOutput:
    f, fluid = _filter(args), _fluid(args)
    metric = args.get("metric", "cum12")
    mine, summary = queries.well_benchmark(con, f, fluid, metric)
    unit = {"peak_rate": f"{_units(fluid)}/d", "cum6": _units(fluid), "cum12": _units(fluid), "decline12": "fraction of peak"}[metric]
    txt = [f"Metric `{metric}` [{unit}] vs analog set [{f.describe()}] ({fluid} wells).", "", "Analog distribution:", md_table(summary)]
    png = None
    if mine.empty:
        txt += ["", "(no company data loaded)"]
    else:
        txt += ["", "Company wells (percentile = share of analog wells below; blank = well too young for this metric):", md_table(mine)]
        if args.get("plot", True):
            png = plots.well_benchmark(mine, summary, f"well benchmark {metric} {fluid} - {f.describe()}", unit)
    return ToolOutput("\n".join(txt), png)


def run_operator_benchmark(con, args: dict) -> ToolOutput:
    f, fluid = _filter(args), _fluid(args)
    rows = queries.operator_benchmark(con, f, fluid, int(args.get("min_wells", 3)))
    if rows.empty:
        return ToolOutput(f"No analog wells match [{f.describe()}].")
    txt = [f"Operators in [{f.describe()}] ({fluid} wells, >= {args.get('min_wells', 3)} wells each), ranked by median cum12 per well "
           f"[{_units(fluid)}]. peak_rate in {_units(fluid)}/d, decline12 = rate@MOP12 / peak, GOR m³/m³.", "", md_table(rows)]
    png = plots.operator_benchmark(rows, f"operator benchmark {fluid} - {f.describe()}", _units(fluid)) if args.get("plot", True) else None
    return ToolOutput("\n".join(txt), png)


def run_area_ranking(con, args: dict) -> ToolOutput:
    f, fluid = _filter(args), _fluid(args)
    rows = queries.area_ranking(con, f, fluid, int(args.get("min_wells", 5)), int(args.get("top", 15)))
    if rows.empty:
        return ToolOutput(f"No analog wells match [{f.describe()}].")
    me = rows.attrs.get("company_p50_cum12")
    txt = [f"Areas in [{f.describe()}] ({fluid} wells, >= {args.get('min_wells', 5)} wells), ranked by median cum12 per well [{_units(fluid)}].",
           f"Company median cum12: {me:,.0f} {_units(fluid)}" if me else "", "", md_table(rows)]
    png = plots.area_ranking(rows, f"area ranking {fluid} - {f.describe()}", _units(fluid)) if args.get("plot", True) else None
    return ToolOutput("\n".join(txt), png)


def run_gor_water_cut(con, args: dict) -> ToolOutput:
    f = _filter(args)
    months = int(args.get("months", 36))
    df = queries.gor_water_cut(con, f, months)
    if df.empty:
        return ToolOutput(f"No analog oil wells match [{f.describe()}].")
    txt = [f"Median GOR [m³/m³] and water cut [-] per month on production, analog set [{f.describe()}] vs company oil wells.", "", md_table(df, max_rows=months + 1, decimals=2)]
    png = plots.gor_water_cut(df, f"GOR and water cut - {f.describe()}") if args.get("plot", True) else None
    return ToolOutput("\n".join(txt), png)


# ----------------------------------------------------------------------------- registry

@dataclass
class ToolSpec:
    name: str
    description: str
    schema: dict
    run: Callable[[duckdb.DuckDBPyConnection, dict], ToolOutput]


_PLOT = {"plot": {"type": "boolean", "description": "Also render a PNG chart (default true)."}}

TOOLS: list[ToolSpec] = [
    ToolSpec("company_summary",
             "One row per company well: area, formation, first/last month, cumulative oil/gas/water. Call this first to know what the company has.",
             {"type": "object", "properties": {}, "additionalProperties": False}, run_company_summary),
    ToolSpec("list_areas",
             "Discover areas (areayacimiento) in the public Capítulo IV data that match a filter, with operators, well counts and median cum12. Use it to pick a sensible analog set before benchmarking.",
             _schema({"min_wells": {"type": "integer", "minimum": 1}, "limit": {"type": "integer", "minimum": 1, "maximum": 200}}), run_list_areas),
    ToolSpec("type_curve",
             "P10/P50/P90 calendar-day rate by month on production for the analog set, overlaid with every company well. The core 'are my wells on the curve?' comparison. Returns a table and a chart.",
             _schema({"months": {"type": "integer", "minimum": 6, "maximum": 120, "description": "MOP horizon (default 36)."}, **_PLOT}), run_type_curve),
    ToolSpec("well_benchmark",
             "Rank each company well by one metric (peak_rate, cum6, cum12 or decline12) against the analog set, with its empirical percentile and a flag for under-performers (below P25). Returns table and chart.",
             _schema({"metric": {"type": "string", "enum": ["peak_rate", "cum6", "cum12", "decline12"], "description": "Default cum12."}, **_PLOT}), run_well_benchmark),
    ToolSpec("operator_benchmark",
             "Operators in the analog set ranked by median cum12 per well (plus peak, decline, GOR, water cut), with the company inserted as one more row. Answers 'how do we rank against the neighbours?'.",
             _schema({"min_wells": {"type": "integer", "minimum": 1, "description": "Minimum wells per operator (default 3)."}, **_PLOT}), run_operator_benchmark),
    ToolSpec("area_ranking",
             "Areas ranked by median cum12 per well for the vintage window, i.e. which blocks are delivering the best wells. The company's median is shown as a reference line.",
             _schema({"min_wells": {"type": "integer", "minimum": 1}, "top": {"type": "integer", "minimum": 1, "maximum": 100}, **_PLOT}), run_area_ranking),
    ToolSpec("gor_water_cut",
             "Median GOR (m³/m³) and water cut by month on production, analog oil wells vs company oil wells. Detects gas breakthrough / water problems relative to the neighbours.",
             _schema({"months": {"type": "integer", "minimum": 6, "maximum": 120}, **_PLOT}, with_fluid=False), run_gor_water_cut),
]

TOOL_BY_NAME = {t.name: t for t in TOOLS}


def run_tool(con: duckdb.DuckDBPyConnection, name: str, args: dict) -> ToolOutput:
    spec = TOOL_BY_NAME.get(name)
    if spec is None:
        raise KeyError(f"unknown tool {name!r}; available: {', '.join(TOOL_BY_NAME)}")
    _validate(args, spec.schema)
    return spec.run(con, args)


def _validate(args: dict, schema: dict) -> None:
    """Minimal JSON-schema check: known keys, basic types, enums. Enough to keep the SQL layer honest."""
    props = schema.get("properties", {})
    for k, v in args.items():
        if k not in props:
            raise ValueError(f"unknown argument {k!r}; allowed: {sorted(props)}")
        p = props[k]
        t = p.get("type")
        if v is None:
            continue
        if t == "string" and not isinstance(v, str):
            raise ValueError(f"{k} must be a string")
        if t == "integer" and not isinstance(v, int):
            raise ValueError(f"{k} must be an integer")
        if t == "boolean" and not isinstance(v, bool):
            raise ValueError(f"{k} must be a boolean")
        if t == "array" and not (isinstance(v, list) and all(isinstance(x, str) for x in v)):
            raise ValueError(f"{k} must be a list of strings")
        if "enum" in p and v not in p["enum"]:
            raise ValueError(f"{k} must be one of {p['enum']}")
    for r in schema.get("required", []):
        if r not in args:
            raise ValueError(f"missing required argument {r!r}")
