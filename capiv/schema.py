"""Schema of the company CSV: same column names as Capítulo IV, so nothing to map."""

from __future__ import annotations

import csv
from pathlib import Path

REQUIRED = ["sigla", "anio", "mes", "prod_pet", "prod_gas", "prod_agua"]
OPTIONAL = [
    "idpozo", "empresa", "tef", "areayacimiento", "cuenca", "formacion",
    "sub_tipo_recurso", "tipopozo", "profundidad",
]
UNITS = {
    "prod_pet": "m³ / month", "prod_gas": "thousand m³ / month", "prod_agua": "m³ / month",
    "tef": "days of effective production in the month",
}


class SchemaError(ValueError):
    pass


def validate_company_csv(path: Path) -> list[str]:
    """Check header; return the list of columns present. Raises SchemaError."""
    path = Path(path)
    if not path.exists():
        raise SchemaError(f"{path} does not exist")
    with open(path, encoding="utf-8-sig", newline="") as f:
        header = next(csv.reader(f), None)
    if not header:
        raise SchemaError(f"{path} is empty")
    header = [h.strip().lower() for h in header]
    missing = [c for c in REQUIRED if c not in header]
    if missing:
        raise SchemaError(
            f"{path.name} is missing required columns {missing}. "
            f"Required: {REQUIRED}; optional: {OPTIONAL}"
        )
    unknown = [c for c in header if c not in REQUIRED + OPTIONAL]
    if unknown:
        # not fatal: extra columns are ignored by the loader
        pass
    return header


def describe() -> str:
    lines = ["Company CSV columns (same names as Capítulo IV):", "  required:"]
    lines += [f"    {c}" + (f"  [{UNITS[c]}]" if c in UNITS else "") for c in REQUIRED]
    lines.append("  optional:")
    lines += [f"    {c}" + (f"  [{UNITS[c]}]" if c in UNITS else "") for c in OPTIONAL]
    return "\n".join(lines)
