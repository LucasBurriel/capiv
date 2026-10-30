"""Synthetic wells in Capítulo IV schema, for the demo CSV and the tests.

Nothing here is real: operator names, areas and well names are invented. Magnitudes
are calibrated to look like Vaca Muerta shale-oil wells (peak ~100-250 m³/d, Arps
hyperbolic decline) so that comparisons against the public data are meaningful.
"""

from __future__ import annotations

import csv
import random
from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass
class WellSpec:
    sigla: str
    first_prod: date          # first month with production
    qi: float                 # peak calendar-day oil rate, m³/d
    di: float                 # initial decline, 1/month
    b: float                  # Arps b
    gor0: float               # initial GOR, m³/m³
    gor_slope: float          # GOR increase per month, m³/m³
    wc0: float                # initial water cut
    wc_slope: float           # water cut increase per month
    months: int               # months of history to emit


def arps(qi: float, di: float, b: float, t: float) -> float:
    if b <= 0:
        return qi * (2.718281828 ** (-di * t))
    return qi / (1.0 + b * di * t) ** (1.0 / b)


def _add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    return date(d.year + y, m + 1, 1)


def _days(d: date) -> int:
    nxt = _add_months(d, 1)
    return (nxt - d).days


def rows_for(spec: WellSpec, *, idpozo: int, empresa: str, area: str, cuenca: str = "NEUQUINA",
             formacion: str = "vaca muerta", sub_tipo: str = "SHALE", tipopozo: str = "Petrolífero",
             rng: random.Random | None = None, last_month: date | None = None) -> list[dict]:
    rng = rng or random.Random(0)
    out = []
    for t in range(spec.months):
        d = _add_months(spec.first_prod, t)
        if last_month and d > last_month:
            break
        nd = _days(d)
        # ramp-up in month 0 (well comes on mid-month), then Arps
        q = arps(spec.qi, spec.di, spec.b, max(t - 1, 0)) * (0.45 if t == 0 else 1.0)
        q *= rng.uniform(0.92, 1.08)
        oil = q * nd
        gor = max(spec.gor0 + spec.gor_slope * t, 20) * rng.uniform(0.95, 1.05)
        wc = min(max(spec.wc0 + spec.wc_slope * t, 0.02), 0.95) * rng.uniform(0.9, 1.1)
        water = oil * wc / (1 - wc)
        gas = oil * gor / 1000.0  # thousand m³
        out.append({
            "idpozo": idpozo, "sigla": spec.sigla, "empresa": empresa, "anio": d.year, "mes": d.month,
            "prod_pet": round(oil, 2), "prod_gas": round(gas, 3), "prod_agua": round(water, 2),
            "tef": nd - rng.choice([0, 0, 0, 1, 2]),
            "areayacimiento": area, "cuenca": cuenca, "formacion": formacion,
            "sub_tipo_recurso": sub_tipo, "tipopozo": tipopozo, "profundidad": 3000 + idpozo % 400,
        })
    return out


def demo_company(seed: int = 7, last_month: date = date(2026, 9, 1)) -> list[dict]:
    """12 invented wells of 'Petrolera Ejemplo S.A.' in the invented 'BLOQUE DEMO' area.

    A deliberate mix: a few strong wells, most average, two clear under-performers and
    one with a water problem, so every comparison in the demo has something to say.
    """
    rng = random.Random(seed)
    specs = [
        # sigla,            first prod,      qi,  di,    b,   gor0, gor_slope, wc0, wc_slope, months
        WellSpec("PE.Nq.BD-1(h)",  date(2022, 3, 1), 150, 0.11, 1.2, 110, 1.5, 0.12, 0.004, 60),
        WellSpec("PE.Nq.BD-2(h)",  date(2022, 4, 1), 165, 0.10, 1.2, 105, 1.5, 0.10, 0.004, 60),
        WellSpec("PE.Nq.BD-3(h)",  date(2022, 9, 1),  95, 0.14, 1.0, 130, 2.0, 0.20, 0.006, 60),  # weak
        WellSpec("PE.Nq.BD-4(h)",  date(2023, 2, 1), 210, 0.10, 1.3,  95, 1.2, 0.08, 0.003, 60),  # strong
        WellSpec("PE.Nq.BD-5(h)",  date(2023, 3, 1), 175, 0.11, 1.2, 100, 1.4, 0.10, 0.004, 60),
        WellSpec("PE.Nq.BD-6(h)",  date(2023, 7, 1), 140, 0.12, 1.1, 115, 1.8, 0.35, 0.012, 60),  # water problem
        WellSpec("PE.Nq.BD-7(h)",  date(2023, 11, 1), 230, 0.09, 1.3,  90, 1.2, 0.08, 0.003, 60), # strong
        WellSpec("PE.Nq.BD-8(h)",  date(2024, 2, 1), 160, 0.11, 1.2, 105, 1.5, 0.11, 0.004, 60),
        WellSpec("PE.Nq.BD-9(h)",  date(2024, 5, 1),  80, 0.16, 0.9, 140, 2.5, 0.18, 0.006, 60),  # weak
        WellSpec("PE.Nq.BD-10(h)", date(2024, 8, 1), 185, 0.10, 1.2, 100, 1.4, 0.09, 0.004, 60),
        WellSpec("PE.Nq.BD-11(h)", date(2025, 1, 1), 200, 0.10, 1.3,  95, 1.3, 0.09, 0.003, 60),
        WellSpec("PE.Nq.BD-12(h)", date(2025, 6, 1), 170, 0.11, 1.2, 100, 1.5, 0.10, 0.004, 60),
    ]
    rows: list[dict] = []
    for i, s in enumerate(specs, start=1):
        rows += rows_for(s, idpozo=900000 + i, empresa="PETROLERA EJEMPLO S.A.", area="BLOQUE DEMO",
                         rng=rng, last_month=last_month)
    return rows


COLUMNS = ["idpozo", "sigla", "empresa", "anio", "mes", "prod_pet", "prod_gas", "prod_agua", "tef",
           "areayacimiento", "cuenca", "formacion", "sub_tipo_recurso", "tipopozo", "profundidad"]


def write_csv(rows: list[dict], path: Path, columns: list[str] | None = None) -> None:
    cols = columns or COLUMNS
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
