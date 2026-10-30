"""Shared fixtures: a tiny synthetic 'public' Capítulo IV table and a company table.

Everything is generated with capiv.synthetic, so the tests never need the 150 MB
download and never contain real operator data.
"""

from __future__ import annotations

import random
from datetime import date
from pathlib import Path

import duckdb
import pytest

from capiv import data, synthetic
from capiv.synthetic import WellSpec, rows_for, write_csv

CAPIV_COLUMNS = [
    "idempresa", "anio", "mes", "idpozo", "prod_pet", "prod_gas", "prod_agua", "iny_agua", "iny_gas", "iny_co2",
    "iny_otro", "tef", "vida_util", "tipoextraccion", "tipoestado", "tipopozo", "observaciones", "fechaingreso",
    "rectificado", "habilitado", "idusuario", "empresa", "sigla", "formprod", "profundidad", "formacion",
    "idareapermisoconcesion", "areapermisoconcesion", "idareayacimiento", "areayacimiento", "cuenca", "provincia",
    "tipo_de_recurso", "proyecto", "clasificacion", "subclasificacion", "sub_tipo_recurso", "fecha_data",
]


def public_rows(seed: int = 1) -> list[dict]:
    """Two invented operators in two invented areas, 40 wells, vintages 2021-2025."""
    rng = random.Random(seed)
    rows: list[dict] = []
    idp = 1000
    for area, empresa, idemp, qi_mu in (("AREA NORTE", "OPERADORA UNO S.A.", "U001", 180),
                                         ("AREA SUR", "OPERADORA DOS S.A.", "D002", 120)):
        for i in range(20):
            idp += 1
            y = rng.choice([2021, 2022, 2023, 2024, 2025])
            spec = WellSpec(
                sigla=f"{idemp}.{area[:2]}-{i+1}(h)", first_prod=date(y, rng.randint(1, 12), 1),
                qi=rng.gauss(qi_mu, 35), di=rng.uniform(0.09, 0.14), b=rng.uniform(1.0, 1.3),
                gor0=rng.uniform(90, 150), gor_slope=rng.uniform(1, 2), wc0=rng.uniform(0.08, 0.3),
                wc_slope=rng.uniform(0.002, 0.008), months=60,
            )
            for r in rows_for(spec, idpozo=idp, empresa=empresa, area=area, rng=rng, last_month=date(2026, 9, 1)):
                r.update({
                    "idempresa": idemp, "iny_agua": 0, "iny_gas": 0, "iny_co2": 0, "iny_otro": 0, "vida_util": "",
                    "tipoextraccion": "Surgencia Natural", "tipoestado": "Extracción Efectiva", "observaciones": "",
                    "fechaingreso": f"{r['anio']}-{r['mes']:02d}-15 10:00:00", "rectificado": "f", "habilitado": "t",
                    "idusuario": 1, "formprod": "VMUT", "idareapermisoconcesion": area[:3], "areapermisoconcesion": area,
                    "idareayacimiento": area[:3], "provincia": "Neuquén", "tipo_de_recurso": "NO CONVENCIONAL",
                    "proyecto": "Sin Proyecto", "clasificacion": "EXPLOTACION", "subclasificacion": "DESARROLLO",
                    "fecha_data": f"{r['anio']}-{r['mes']:02d}-28",
                })
                rows.append(r)
    return rows


@pytest.fixture(scope="session")
def public_csv(tmp_path_factory) -> Path:
    p = tmp_path_factory.mktemp("raw") / "fake-capiv.csv"
    write_csv(public_rows(), p, CAPIV_COLUMNS)
    return p


@pytest.fixture(scope="session")
def company_csv(tmp_path_factory) -> Path:
    p = tmp_path_factory.mktemp("co") / "my_company.csv"
    write_csv(synthetic.demo_company(), p)
    return p


@pytest.fixture()
def con(public_csv, company_csv) -> duckdb.DuckDBPyConnection:
    c = duckdb.connect()  # in-memory
    data.load_capiv(c, [public_csv])
    data.load_company(c, company_csv)
    return c


@pytest.fixture()
def con_public_only(public_csv) -> duckdb.DuckDBPyConnection:
    c = duckdb.connect()
    data.load_capiv(c, [public_csv])
    return c
