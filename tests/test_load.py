from pathlib import Path

import pytest

from capiv import data, schema, synthetic
from capiv.synthetic import write_csv
from tests.conftest import public_rows


def test_load_capiv_keeps_columns_and_dedups(con_public_only, public_csv):
    con = con_public_only
    cols = {r[0] for r in con.execute("describe capiv").fetchall()}
    assert set(data.KEEP_COLUMNS) <= cols and "fecha" in cols
    # loading the same file twice must not duplicate (idpozo, anio, mes)
    data.load_capiv(con, [public_csv, public_csv])
    n, nd = con.execute("select count(*), count(distinct (idpozo, anio, mes)) from capiv").fetchone()
    assert n == nd == len(public_rows())
    assert con.execute("select count(distinct idpozo) from capiv").fetchone()[0] == 40


def test_load_company_schema(con):
    n, wells, emp = con.execute("select count(*), count(distinct idpozo), any_value(empresa) from company").fetchone()
    assert wells == 12 and emp == "PETROLERA EJEMPLO S.A." and n > 300
    # idpozo is kept when provided
    assert con.execute("select min(idpozo) from company").fetchone()[0] == 900001


def test_company_without_optional_columns(tmp_path, con_public_only):
    p = tmp_path / "min.csv"
    write_csv(synthetic.demo_company(), p, columns=schema.REQUIRED)
    data.load_company(con_public_only, p, company_name="ACME")
    wells, emp, area = con_public_only.execute(
        "select count(distinct idpozo), any_value(empresa), any_value(areayacimiento) from company").fetchone()
    assert wells == 12 and emp == "ACME" and area is None


def test_company_missing_required_column_raises(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("sigla,anio,mes,prod_pet\nA,2024,1,10\n", encoding="utf-8")
    with pytest.raises(schema.SchemaError, match="prod_gas"):
        schema.validate_company_csv(p)


def test_resource_urls_are_well_formed():
    for key in data.RESOURCES:
        u = data.resource_url(key)
        assert u.startswith("https://datos.energia.gob.ar/dataset/") and u.endswith(".csv")
    assert "unconventional" in data.RESOURCES and "2025" in data.RESOURCES


def test_status(con):
    st = data.status(con)
    assert st["capiv"]["wells"] == 40 and st["company"]["wells"] == 12
