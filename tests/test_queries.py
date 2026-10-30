import pandas as pd
import pytest

from capiv import queries
from capiv.queries import AnalogFilter

ALL = AnalogFilter(cuenca="NEUQUINA", formacion="vaca muerta", sub_tipo_recurso="SHALE")


def test_well_metrics_definitions(con):
    m = queries.well_metrics(con, "capiv", "oil", ALL)
    assert len(m) == 40
    # cum12 only for wells with >= 12 months, and cum12 >= cum6 whenever both exist
    both = m.dropna(subset=["cum6", "cum12"])
    assert (both["cum12"] >= both["cum6"]).all()
    assert m.loc[m["n_months"] < 11, "cum12"].isna().all()
    # peak is a calendar-day rate: must be below 400 m3/d for these synthetic wells
    assert (m["peak_rate"] < 400).all() and (m["peak_rate"] > 0).all()
    # decline12 is a fraction of peak
    d = m["decline12"].dropna()
    assert ((d > 0) & (d <= 1)).all()
    assert ((m["water_cut"] >= 0) & (m["water_cut"] <= 1)).all()


def test_filter_vintage_and_area(con):
    f = AnalogFilter(areas=["area norte"], vintage_from="2023-01", vintage_to="2023-12")
    m = queries.well_metrics(con, "capiv", "oil", f)
    assert (m["area"] == "AREA NORTE").all()
    assert (m["first_prod"].astype(str) >= "2023-01-01").all() and (m["first_prod"].astype(str) <= "2023-12-01").all()
    assert len(m) < 20


def test_filter_exclude_empresa(con):
    m = queries.well_metrics(con, "capiv", "oil", AnalogFilter(exclude_empresa="OPERADORA UNO S.A."))
    assert set(m["empresa"]) == {"OPERADORA DOS S.A."}


def test_type_curve_shape(con):
    curve, mine = queries.type_curve(con, ALL, "oil", months=24)
    assert list(curve["mop"]) == list(range(25))
    assert (curve["p10"] <= curve["p50"]).all() and (curve["p50"] <= curve["p90"]).all()
    # a type curve declines: p50 at MOP 12 is lower than at MOP 2
    assert curve.loc[12, "p50"] < curve.loc[2, "p50"]
    assert mine.shape == (25, 12)   # 12 company wells as columns
    assert "PE.Nq.BD-7(h)" in mine.columns


def test_type_curve_public_only(con_public_only):
    curve, mine = queries.type_curve(con_public_only, ALL, "oil", months=12)
    assert len(curve) == 13 and mine.empty


def test_well_benchmark_percentiles(con):
    mine, summary = queries.well_benchmark(con, ALL, "oil", "cum12")
    assert summary.loc[0, "analog_wells"] > 0
    pct = mine["percentile"].dropna()
    assert ((pct >= 0) & (pct <= 100)).all()
    # the deliberately weak synthetic wells rank at the bottom, the strong ones at the top
    order = list(mine["sigla"])
    assert order.index("PE.Nq.BD-9(h)") < order.index("PE.Nq.BD-7(h)")
    assert set(mine["flag"].dropna()) <= {"under P25", "in range", "over P75"}
    with pytest.raises(ValueError):
        queries.well_benchmark(con, ALL, "oil", "eur")


def test_operator_benchmark_includes_company(con):
    rows = queries.operator_benchmark(con, ALL, "oil", min_wells=3)
    assert set(rows["empresa"]) == {"OPERADORA UNO S.A.", "OPERADORA DOS S.A.", "PETROLERA EJEMPLO S.A."}
    assert (rows["who"] == "company").sum() == 1
    assert list(rows["rank"]) == [1, 2, 3]
    assert rows["p50_cum12"].is_monotonic_decreasing
    # UNO was generated with higher qi than DOS
    assert rows.set_index("empresa").loc["OPERADORA UNO S.A.", "p50_cum12"] > rows.set_index("empresa").loc["OPERADORA DOS S.A.", "p50_cum12"]


def test_area_ranking(con):
    g = queries.area_ranking(con, ALL, "oil", min_wells=5, top=10)
    assert list(g["area"]) == ["AREA NORTE", "AREA SUR"]
    assert g.attrs["company_p50_cum12"] > 0


def test_gor_water_cut(con):
    df = queries.gor_water_cut(con, ALL, months=12)
    assert len(df) == 13
    assert {"analog_gor_p50", "company_gor_p50", "analog_wc_p50", "company_wc_p50"} <= set(df.columns)
    assert (df["analog_gor_p50"] > 0).all() and ((df["analog_wc_p50"] >= 0) & (df["analog_wc_p50"] <= 1)).all()


def test_company_summary(con):
    s = queries.company_summary(con)
    assert len(s) == 12 and (s["cum_oil_m3"] > 0).all()


def test_gas_fluid_runs(con):
    curve, _ = queries.type_curve(con, AnalogFilter(), "gas", months=6)
    # synthetic wells are oil wells (tipopozo Petrolífero), so there are no gas wells in the analog set
    assert curve.empty


def test_filter_values_never_interpolated(con):
    """A filter value that looks like SQL must be treated as a literal and match nothing."""
    f = AnalogFilter(areas=["AREA NORTE' or '1'='1"], formacion="vaca muerta'); drop table capiv; --")
    m = queries.well_metrics(con, "capiv", "oil", f)
    assert m.empty
