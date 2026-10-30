"""Download the Capítulo IV CSVs and load them (plus the company CSV) into DuckDB.

Dataset: "Producción de petróleo y gas por pozo (Capítulo IV)", Secretaría de Energía,
https://datos.energia.gob.ar/dataset/produccion-de-petroleo-y-gas-por-pozo (CC-BY 4.0).
Resource ids below were read from the CKAN API on 2026-10-30; they are stable but the
Secretaría occasionally re-uploads a year under a new id, so `capiv download` also
accepts an explicit `--url`.
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

import duckdb

from . import config
from .schema import validate_company_csv

DATASET_ID = "c846e79c-026c-4040-897f-1ad3543b407c"
BASE = f"https://datos.energia.gob.ar/dataset/{DATASET_ID}/resource"

# key -> (resource id, file name)
RESOURCES: dict[str, tuple[str, str]] = {
    "unconventional": ("b5b58cdc-9e07-41f9-b392-fb9ec68b0725", "produccin-de-pozos-de-gas-y-petrleo-no-convencional.csv"),
    "2026": ("fb7a47a0-cba9-4667-a004-6f6c1c346c23", "produccin-de-pozos-de-gas-y-petrleo-2026.csv"),
    "2025": ("d774b5d7-0756-48fe-88f2-8729b57b22da", "produccin-de-pozos-de-gas-y-petrleo-2025.csv"),
    "2024": ("43a09dce-1742-44d0-bc13-f193deaab563", "produccin-de-pozos-de-gas-y-petrleo-2024.csv"),
    "2023": ("231c39b3-e81e-4398-af8d-b115807f2c25", "produccin-de-pozos-de-gas-y-petrleo-2023.csv"),
    "2022": ("876b3746-85e2-4039-adeb-b1354436159f", "produccin-de-pozos-de-gas-y-petrleo-2022.csv"),
    "2021": ("465be754-a372-4c31-b855-81dc5fe3309f", "produccin-de-pozos-de-gas-y-petrleo-2021.csv"),
    "2020": ("c4a4a6a0-e75a-4e12-ae5c-54d53a70348c", "produccin-de-pozos-de-gas-y-petrleo-2020.csv"),
    "2019": ("8bc0d61c-0408-43d4-a7bc-7178fcb5d37e", "produccin-de-pozos-de-gas-y-petrleo-2019.csv"),
    "2018": ("333fd72a-9b83-4bc1-bc94-0f5940b52331", "produccin-de-pozos-de-gas-y-petrleo-2018.csv"),
    "2017": ("df4857e1-7c3f-4980-b5b5-184fe78bfcf0", "produccin-de-pozos-de-gas-y-petrleo-2017.csv"),
    "2016": ("d8539ae8-0a71-4339-a16c-139b21bd2cd0", "produccin-de-pozos-de-gas-y-petrleo-2016.csv"),
    "2015": ("e375aa35-fd8d-41d6-aa0c-e6879ca567a1", "produccin-de-pozos-de-gas-y-petrleo-2015.csv"),
    "2014": ("cd9813a7-1e19-4f60-a02a-7903dd81aff7", "produccin-de-pozos-de-gas-y-petrleo-2014.csv"),
    "2013": ("bc7ac8fe-2cec-4dab-acdd-322ea1ccc887", "produccin-de-pozos-de-gas-y-petrleo-2013.csv"),
    "2012": ("0dce0e75-1556-47ee-8615-1955fbd54ade", "produccin-de-pozos-de-gas-y-petrleo-2012.csv"),
    "2011": ("4817272c-7365-4bdd-b02d-75b118218b10", "produccin-de-pozos-de-gas-y-petrleo-2011.csv"),
    "2010": ("364ca28e-d069-4bd6-8771-925f0db152a8", "produccin-de-pozos-de-gas-y-petrleo-2010.csv"),
    "2009": ("48585038-055a-4437-bb1d-4fe36073f453", "produccin-de-pozos-de-gas-y-petrleo-2009.csv"),
    "2008": ("3430b5a8-a516-42ca-a47d-2e1ce45925fb", "produccin-de-pozos-de-gas-y-petrleo-2008.csv"),
    "2007": ("be663a63-f020-4e28-8f31-c5f81d47554d", "produccin-de-pozos-de-gas-y-petrleo-2007.csv"),
    "2006": ("4e1c55e5-1f1b-4fc8-aa37-2080d9795f29", "produccin-de-pozos-de-gas-y-petrleo-2006.csv"),
}

# Columns we keep from the ~40 in the source. Everything else (injection volumes,
# user ids, audit timestamps, coordinates) is not needed for benchmarking.
KEEP_COLUMNS = [
    "idempresa", "empresa", "idpozo", "sigla", "anio", "mes",
    "prod_pet", "prod_gas", "prod_agua", "tef",
    "tipoextraccion", "tipoestado", "tipopozo",
    "formprod", "formacion", "profundidad",
    "idareayacimiento", "areayacimiento", "areapermisoconcesion",
    "cuenca", "provincia", "tipo_de_recurso", "sub_tipo_recurso", "clasificacion",
    "fechaingreso",
]


def resource_url(key: str) -> str:
    rid, fname = RESOURCES[key]
    return f"{BASE}/{rid}/download/{fname}"


def download(keys: list[str], url: str | None = None, force: bool = False) -> list[Path]:
    """Download the requested resources into CAPIV_HOME/raw. Returns local paths."""
    config.raw_dir().mkdir(parents=True, exist_ok=True)
    jobs: list[tuple[str, Path]] = []
    if url:
        jobs.append((url, config.raw_dir() / url.rsplit("/", 1)[-1]))
    for k in keys:
        if k not in RESOURCES:
            raise SystemExit(f"unknown resource {k!r}; options: {', '.join(RESOURCES)}")
        jobs.append((resource_url(k), config.raw_dir() / f"{k}.csv"))
    paths = []
    for src, dst in jobs:
        if dst.exists() and not force:
            print(f"  {dst.name}: already present ({dst.stat().st_size/1e6:.0f} MB), skipping", file=sys.stderr)
        else:
            _fetch(src, dst)
        paths.append(dst)
    return paths


def _fetch(src: str, dst: Path) -> None:
    req = urllib.request.Request(src, headers={"User-Agent": "capiv/0.1 (+https://github.com/LucasBurriel/capiv)"})
    tmp = dst.with_suffix(".part")
    with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while chunk := r.read(1 << 20):
            f.write(chunk)
            done += len(chunk)
            if total:
                print(f"\r  {dst.name}: {done/1e6:6.0f} / {total/1e6:.0f} MB", end="", file=sys.stderr)
    print(file=sys.stderr)
    tmp.replace(dst)


def connect(path: Path | None = None, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    p = path or config.db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(p), read_only=read_only)


def load_capiv(con: duckdb.DuckDBPyConnection, csv_paths: list[Path]) -> int:
    """(Re)build the `capiv` table from one or more Capítulo IV CSVs.

    Rows are de-duplicated on (idpozo, anio, mes) keeping the latest `fechaingreso`,
    because the unconventional file and the yearly files overlap.
    """
    files = [str(p).replace("\\", "/") for p in csv_paths]
    cols = ", ".join(KEEP_COLUMNS)
    con.execute(
        f"""
        create or replace table capiv as
        with raw as (
            select {cols}
            from read_csv(?, header=true, union_by_name=true, sample_size=-1,
                          ignore_errors=true, encoding='utf-8')
        )
        select *, make_date(anio::int, mes::int, 1) as fecha
        from raw
        where anio is not null and mes between 1 and 12 and idpozo is not null
        qualify row_number() over (partition by idpozo, anio, mes order by fechaingreso desc nulls last) = 1
        """,
        [files],
    )
    con.execute("create or replace table capiv_meta as select now() as loaded_at, ? as files", [files])
    return con.execute("select count(*) from capiv").fetchone()[0]


def load_company(con: duckdb.DuckDBPyConnection, csv_path: Path, company_name: str | None = None) -> int:
    """Load the company's own monthly production (same column names as Capítulo IV)."""
    present = set(validate_company_csv(csv_path))
    name = company_name or "MY COMPANY"
    # optional columns absent from the file become NULL so the typed select below always resolves
    from .schema import OPTIONAL
    missing = ", ".join(f"NULL as {c}" for c in OPTIONAL if c not in present)
    raw_select = "select *" + (f", {missing}" if missing else "")
    con.execute(
        f"""
        create or replace table company as
        with raw as (
            {raw_select} from read_csv(?, header=true, sample_size=-1, encoding='utf-8')
        ),
        typed as (
            select
                coalesce(try_cast(idpozo as bigint), -dense_rank() over (order by sigla::varchar)) as idpozo,
                sigla::varchar as sigla,
                coalesce(empresa::varchar, ?) as empresa,
                anio::int as anio, mes::int as mes,
                coalesce(prod_pet::double, 0) as prod_pet,
                coalesce(prod_gas::double, 0) as prod_gas,
                coalesce(prod_agua::double, 0) as prod_agua,
                try_cast(tef as double) as tef,
                areayacimiento::varchar as areayacimiento,
                cuenca::varchar as cuenca,
                formacion::varchar as formacion,
                sub_tipo_recurso::varchar as sub_tipo_recurso,
                tipopozo::varchar as tipopozo,
                try_cast(profundidad as double) as profundidad
            from raw
        )
        select *, make_date(anio, mes, 1) as fecha from typed
        where mes between 1 and 12
        """,
        [str(csv_path).replace("\\", "/"), name],
    )
    return con.execute("select count(*) from company").fetchone()[0]


def status(con: duckdb.DuckDBPyConnection) -> dict:
    out: dict = {"db": str(config.db_path())}
    tables = {r[0] for r in con.execute("show tables").fetchall()}
    if "capiv" in tables:
        n, wells, lo, hi = con.execute(
            "select count(*), count(distinct idpozo), min(fecha), max(fecha) from capiv"
        ).fetchone()
        out["capiv"] = {"rows": n, "wells": wells, "from": str(lo), "to": str(hi)}
        try:
            out["capiv"]["files"] = con.execute("select files from capiv_meta").fetchone()[0]
        except duckdb.Error:
            pass
    if "company" in tables:
        n, wells, lo, hi, emp = con.execute(
            "select count(*), count(distinct idpozo), min(fecha), max(fecha), any_value(empresa) from company"
        ).fetchone()
        out["company"] = {"rows": n, "wells": wells, "from": str(lo), "to": str(hi), "empresa": emp}
    return out
