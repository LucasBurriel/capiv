"""The closed set of parameterised comparisons.

Every public function takes a DuckDB connection, an `AnalogFilter` and a fluid, and
returns pandas DataFrames. SQL is built from fixed templates with `?` placeholders;
no user- or model-supplied text is ever interpolated into a query.

Vocabulary
----------
MOP   months on production: 0 = first month with non-zero production of the fluid.
rate  calendar-day rate = monthly volume / days in that month (m³/d for oil and
      water, thousand m³/d for gas).
cum6 / cum12  cumulative volume over MOP 0..5 / 0..11, only for wells that have
      reached MOP 5 / 11.
decline12  rate at MOP 12 divided by the peak monthly rate (1.0 = no decline).
GOR   gas/oil ratio in m³/m³ over MOP 1..12 (gas is stored in thousands of m³).
WC    water cut = water / (water + oil) over MOP 1..12.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date

import duckdb
import pandas as pd

FLUIDS = {
    "oil": ("prod_pet", "m³", "Petrol%"),
    "gas": ("prod_gas", "Mm³", "Gas%"),
}


@dataclass
class AnalogFilter:
    """Which public wells form the analog set. All fields optional (AND-ed)."""

    cuenca: str | None = None
    areas: list[str] = field(default_factory=list)      # areayacimiento, exact match, case-insensitive
    formacion: str | None = None                        # e.g. "vaca muerta"
    sub_tipo_recurso: str | None = None                 # SHALE | TIGHT | ...
    tipo_de_recurso: str | None = None                  # CONVENCIONAL | NO CONVENCIONAL
    vintage_from: str | None = None                     # "YYYY-MM": first production >= this
    vintage_to: str | None = None                       # "YYYY-MM": first production <= this
    exclude_empresa: str | None = None                  # drop one operator (e.g. yourself if you are in the public data)

    def describe(self) -> str:
        parts = [f"{k}={v}" for k, v in asdict(self).items() if v]
        return ", ".join(parts) or "all wells"


def _month(s: str | None, default: date) -> date:
    if not s:
        return default
    y, m = s.split("-")[:2]
    return date(int(y), int(m), 1)


def _where(f: AnalogFilter, fluid: str, params: list) -> str:
    """WHERE clause for the public table. Appends bound values to `params`."""
    conds = ["1=1"]
    if f.cuenca:
        conds.append("upper(cuenca) = upper(?)"); params.append(f.cuenca)
    if f.areas:
        conds.append("upper(areayacimiento) in (" + ",".join("upper(?)" for _ in f.areas) + ")")
        params.extend(f.areas)
    if f.formacion:
        conds.append("lower(formacion) = lower(?)"); params.append(f.formacion)
    if f.sub_tipo_recurso:
        conds.append("upper(sub_tipo_recurso) = upper(?)"); params.append(f.sub_tipo_recurso)
    if f.tipo_de_recurso:
        conds.append("upper(tipo_de_recurso) = upper(?)"); params.append(f.tipo_de_recurso)
    if f.exclude_empresa:
        conds.append("upper(empresa) <> upper(?)"); params.append(f.exclude_empresa)
    # well type: only wells classified as oil (or gas) wells at some point
    like = FLUIDS[fluid][2]
    conds.append(f"idpozo in (select idpozo from capiv where tipopozo like '{like}')")
    return " and ".join(conds)


def _wells_cte(table: str, fluid: str, f: AnalogFilter | None, params: list) -> str:
    """CTE `w`: one row per (well, month) with mop and rate, restricted by filter/vintage."""
    col = FLUIDS[fluid][0]
    where = _where(f, fluid, params) if (f is not None and table == "capiv") else "1=1"
    vf = _month(f.vintage_from if f else None, date(1900, 1, 1))
    vt = _month(f.vintage_to if f else None, date(2100, 1, 1))
    params.extend([vf, vt])
    return f"""
    src as (
        select idpozo, any_value(sigla) sigla, any_value(empresa) empresa,
               any_value(areayacimiento) area, fecha,
               sum(prod_pet) prod_pet, sum(prod_gas) prod_gas, sum(prod_agua) prod_agua
        from {table}
        where {where}
        group by idpozo, fecha
    ),
    first as (
        select idpozo, min(fecha) d0 from src where {col} > 0 group by idpozo
    ),
    w as (
        select s.*, f.d0,
               datediff('month', f.d0, s.fecha) as mop,
               day(last_day(s.fecha)) as nd,
               {col} / day(last_day(s.fecha)) as rate
        from src s join first f using (idpozo)
        where s.fecha >= f.d0 and f.d0 between ? and ?
    )"""


_METRICS = """
    select idpozo, any_value(sigla) sigla, any_value(empresa) empresa, any_value(area) area,
           any_value(d0) first_prod, max(mop) n_months,
           max(rate) peak_rate,
           case when max(mop) >= 5  then sum(case when mop <= 5  then {col} end) end as cum6,
           case when max(mop) >= 11 then sum(case when mop <= 11 then {col} end) end as cum12,
           case when max(mop) >= 12 then max(case when mop = 12 then rate end) / nullif(max(rate), 0) end as decline12,
           sum(case when mop between 1 and 12 then prod_gas end) * 1000.0
             / nullif(sum(case when mop between 1 and 12 then prod_pet end), 0) as gor,
           sum(case when mop between 1 and 12 then prod_agua end)
             / nullif(sum(case when mop between 1 and 12 then prod_agua + prod_pet end), 0) as water_cut
    from w group by idpozo
"""


def well_metrics(con: duckdb.DuckDBPyConnection, table: str, fluid: str, f: AnalogFilter | None) -> pd.DataFrame:
    params: list = []
    sql = "with " + _wells_cte(table, fluid, f, params) + _METRICS.format(col=FLUIDS[fluid][0])
    return con.execute(sql, params).df()


def has_company(con: duckdb.DuckDBPyConnection) -> bool:
    return con.execute("select count(*) from information_schema.tables where table_name='company'").fetchone()[0] > 0


# ----------------------------------------------------------------------------- tools

def list_areas(con, f: AnalogFilter, fluid: str = "oil", min_wells: int = 5, limit: int = 40) -> pd.DataFrame:
    """Areas in the analog filter with enough wells: operators, well count, median cum12."""
    params: list = []
    sql = "with " + _wells_cte("capiv", fluid, f, params) + f"""
    , m as ({_METRICS.format(col=FLUIDS[fluid][0])})
    select area, count(*) wells, count(distinct empresa) operators,
           string_agg(distinct empresa, ' | ' order by empresa) operator_names,
           min(first_prod) first_vintage, max(first_prod) last_vintage,
           round(median(peak_rate), 1) p50_peak_rate, round(median(cum12)) p50_cum12
    from m group by area having count(*) >= ? order by wells desc limit ?
    """
    params += [min_wells, limit]
    return con.execute(sql, params).df()


def type_curve(con, f: AnalogFilter, fluid: str = "oil", months: int = 36) -> tuple[pd.DataFrame, pd.DataFrame]:
    """P10/P50/P90 calendar-day rate per MOP for the analog set, and the company wells' rates.

    Returns (curve, company_rates). company_rates is a wide table: one column per well.
    """
    params: list = []
    sql = "with " + _wells_cte("capiv", fluid, f, params) + """
    select mop, count(*) wells,
           quantile_cont(rate, 0.10) p10, quantile_cont(rate, 0.50) p50, quantile_cont(rate, 0.90) p90,
           avg(rate) mean
    from w where mop between 0 and ? group by mop order by mop
    """
    params.append(months)
    curve = con.execute(sql, params).df()
    mine = pd.DataFrame()
    if has_company(con):
        p2: list = []
        sql2 = "with " + _wells_cte("company", fluid, None, p2) + "select sigla, mop, rate from w where mop between 0 and ? order by 1,2"
        p2.append(months)
        long = con.execute(sql2, p2).df()
        if not long.empty:
            mine = long.pivot(index="mop", columns="sigla", values="rate")
    return curve, mine


def well_benchmark(con, f: AnalogFilter, fluid: str = "oil", metric: str = "cum12") -> tuple[pd.DataFrame, pd.DataFrame]:
    """Each company well's metric and its empirical percentile within the analog set.

    Returns (company_table, analog_summary). metric in peak_rate|cum6|cum12|decline12.
    """
    if metric not in ("peak_rate", "cum6", "cum12", "decline12"):
        raise ValueError("metric must be peak_rate, cum6, cum12 or decline12")
    analog = well_metrics(con, "capiv", fluid, f)
    a = analog[metric].dropna().sort_values().to_numpy()
    summary = pd.DataFrame({
        "metric": [metric], "analog_wells": [len(a)],
        "p10": [float(pd.Series(a).quantile(0.10)) if len(a) else None],
        "p50": [float(pd.Series(a).quantile(0.50)) if len(a) else None],
        "p90": [float(pd.Series(a).quantile(0.90)) if len(a) else None],
    })
    if not has_company(con):
        return pd.DataFrame(), summary
    mine = well_metrics(con, "company", fluid, None)[["sigla", "area", "first_prod", "n_months", metric]].copy()
    import numpy as np
    def pct(v):
        if pd.isna(v) or len(a) == 0:
            return None
        return float(100.0 * np.searchsorted(a, v, side="right") / len(a))
    mine["percentile"] = mine[metric].map(pct)
    mine["vs_p50_%"] = (mine[metric] / summary.loc[0, "p50"] * 100 - 100).round(1) if summary.loc[0, "p50"] else None
    mine["flag"] = mine["percentile"].map(lambda p: None if p is None else ("under P25" if p < 25 else ("over P75" if p > 75 else "in range")))
    return mine.sort_values("percentile", na_position="last").reset_index(drop=True), summary


def operator_benchmark(con, f: AnalogFilter, fluid: str = "oil", min_wells: int = 3) -> pd.DataFrame:
    """Operators in the analog set ranked by median cum12 per well; the company appended as a row."""
    analog = well_metrics(con, "capiv", fluid, f)
    def agg(df: pd.DataFrame) -> pd.Series:
        return pd.Series({
            "wells": len(df), "wells_with_12m": int(df["cum12"].notna().sum()),
            "p50_peak_rate": df["peak_rate"].median(), "p50_cum6": df["cum6"].median(),
            "p50_cum12": df["cum12"].median(), "p50_decline12": df["decline12"].median(),
            "p50_gor": df["gor"].median(), "p50_water_cut": df["water_cut"].median(),
        })
    rows = analog.groupby("empresa").apply(agg, include_groups=False).reset_index()
    rows = rows[rows["wells"] >= min_wells]
    rows["who"] = "analog"
    if has_company(con):
        mine = well_metrics(con, "company", fluid, None)
        me = agg(mine).to_frame().T
        me.insert(0, "empresa", mine["empresa"].iloc[0] if len(mine) else "MY COMPANY")
        me["who"] = "company"
        rows = pd.concat([rows, me], ignore_index=True)
    rows = rows.sort_values("p50_cum12", ascending=False, na_position="last").reset_index(drop=True)
    rows.insert(0, "rank", range(1, len(rows) + 1))
    return rows


def area_ranking(con, f: AnalogFilter, fluid: str = "oil", min_wells: int = 5, top: int = 15) -> pd.DataFrame:
    """Areas ranked by median cum12 per well, for wells whose first production is inside the vintage window."""
    analog = well_metrics(con, "capiv", fluid, f)
    g = analog.groupby("area").agg(
        wells=("idpozo", "size"), operators=("empresa", "nunique"),
        p50_peak_rate=("peak_rate", "median"), p50_cum12=("cum12", "median"),
        p90_cum12=("cum12", lambda s: s.quantile(0.9)), p50_decline12=("decline12", "median"),
    ).reset_index()
    g = g[g["wells"] >= min_wells].sort_values("p50_cum12", ascending=False, na_position="last").head(top)
    g.insert(0, "rank", range(1, len(g) + 1))
    if has_company(con):
        mine = well_metrics(con, "company", fluid, None)
        g.attrs["company_p50_cum12"] = float(mine["cum12"].median()) if mine["cum12"].notna().any() else None
    return g.reset_index(drop=True)


def gor_water_cut(con, f: AnalogFilter, months: int = 36) -> pd.DataFrame:
    """Median GOR (m³/m³) and water cut per MOP: analog set vs company wells (oil wells)."""
    def run(table: str, filt: AnalogFilter | None) -> pd.DataFrame:
        params: list = []
        sql = "with " + _wells_cte(table, "oil", filt, params) + """
        select mop, count(*) wells,
               quantile_cont(prod_gas * 1000.0 / nullif(prod_pet, 0), 0.5) gor_p50,
               quantile_cont(prod_agua / nullif(prod_agua + prod_pet, 0), 0.5) wc_p50
        from w where mop between 0 and ? and prod_pet > 0 group by mop order by mop
        """
        params.append(months)
        return con.execute(sql, params).df()
    analog = run("capiv", f).rename(columns={"wells": "analog_wells", "gor_p50": "analog_gor_p50", "wc_p50": "analog_wc_p50"})
    if has_company(con):
        mine = run("company", None).rename(columns={"wells": "company_wells", "gor_p50": "company_gor_p50", "wc_p50": "company_wc_p50"})
        analog = analog.merge(mine, on="mop", how="outer").sort_values("mop")
    return analog.reset_index(drop=True)


def company_summary(con) -> pd.DataFrame:
    """One row per company well: area, formation, first/last month, months with oil, cum oil/gas/water."""
    if not has_company(con):
        return pd.DataFrame()
    return con.execute("""
        select sigla, any_value(empresa) empresa, any_value(areayacimiento) area, any_value(cuenca) cuenca,
               any_value(formacion) formacion, any_value(sub_tipo_recurso) sub_tipo_recurso, any_value(tipopozo) tipopozo,
               min(fecha) filter (where prod_pet > 0 or prod_gas > 0) first_prod, max(fecha) last_month,
               count(*) filter (where prod_pet > 0) months_oil,
               round(sum(prod_pet)) cum_oil_m3, round(sum(prod_gas)) cum_gas_Mm3, round(sum(prod_agua)) cum_water_m3
        from company group by sigla order by first_prod, sigla
    """).df()
