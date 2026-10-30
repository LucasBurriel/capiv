"""Matplotlib charts for the comparisons. Each function returns the PNG path."""

from __future__ import annotations

import re
import textwrap
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from . import config

ANALOG = "#5B6770"     # grey-blue for the public analog set
BAND = "#C9D2D9"
MINE = plt.cm.tab10.colors  # company wells


def _wrap(title: str) -> str:
    return chr(10).join(textwrap.wrap(title, 95)[:2])


def _path(name: str) -> Path:
    d = config.out_dir()
    d.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", name).strip("_")[:80]
    return d / f"{safe}.png"


def type_curve(curve: pd.DataFrame, mine: pd.DataFrame, title: str, unit: str) -> Path:
    fig, ax = plt.subplots(figsize=(9, 5.2), dpi=130)
    if not curve.empty:
        ax.fill_between(curve["mop"], curve["p10"], curve["p90"], color=BAND, alpha=0.7, label="analog P10-P90")
        ax.plot(curve["mop"], curve["p50"], color=ANALOG, lw=2.2, label=f"analog P50 (n={int(curve['wells'].max())} wells)")
    for i, col in enumerate(mine.columns if not mine.empty else []):
        ax.plot(mine.index, mine[col], lw=1.4, marker="o", ms=2.5, color=MINE[i % 10], label=str(col))
    ax.set_xlabel("months on production")
    ax.set_ylabel(f"calendar-day rate [{unit}/d]")
    ax.set_title(_wrap(title), fontsize=10)
    ax.grid(alpha=0.3)
    ax.set_ylim(bottom=0)
    ax.legend(fontsize=7, ncol=2, loc="upper right")
    p = _path(title)
    fig.tight_layout(); fig.savefig(p); plt.close(fig)
    return p


def well_benchmark(mine: pd.DataFrame, summary: pd.DataFrame, title: str, unit: str) -> Path:
    metric = summary.loc[0, "metric"]
    fig, ax = plt.subplots(figsize=(9, 5), dpi=130)
    if not mine.empty:
        d = mine.dropna(subset=[metric]).sort_values(metric)
        colors = [("#C0392B" if (p is not None and p < 25) else ("#27AE60" if (p is not None and p > 75) else "#2E86C1")) for p in d["percentile"]]
        ax.barh(d["sigla"].astype(str), d[metric], color=colors)
        for y, (v, p) in enumerate(zip(d[metric], d["percentile"])):
            if p is not None and not pd.isna(p):
                ax.text(v, y, f"  P{p:.0f}", va="center", fontsize=8)
    for q, ls in (("p10", ":"), ("p50", "-"), ("p90", ":")):
        v = summary.loc[0, q]
        if v is not None and not pd.isna(v):
            ax.axvline(v, color=ANALOG, ls=ls, lw=1.5, label=f"analog {q.upper()}")
    ax.set_xlabel(f"{metric} [{unit}]")
    ax.set_title(_wrap(title), fontsize=10)
    ax.grid(axis="x", alpha=0.3)
    ax.legend(fontsize=8)
    p = _path(title)
    fig.tight_layout(); fig.savefig(p); plt.close(fig)
    return p


def operator_benchmark(rows: pd.DataFrame, title: str, unit: str) -> Path:
    fig, ax = plt.subplots(figsize=(9, 0.35 * max(len(rows), 6) + 1.5), dpi=130)
    d = rows.dropna(subset=["p50_cum12"]).iloc[::-1]
    colors = ["#E67E22" if w == "company" else ANALOG for w in d["who"]]
    ax.barh(d["empresa"].astype(str).str.slice(0, 38), d["p50_cum12"], color=colors)
    for y, (v, n) in enumerate(zip(d["p50_cum12"], d["wells"])):
        ax.text(v, y, f"  n={int(n)}", va="center", fontsize=7)
    ax.set_xlabel(f"median cum12 per well [{unit}]")
    ax.set_title(_wrap(title), fontsize=10)
    ax.grid(axis="x", alpha=0.3)
    p = _path(title)
    fig.tight_layout(); fig.savefig(p); plt.close(fig)
    return p


def area_ranking(rows: pd.DataFrame, title: str, unit: str) -> Path:
    fig, ax = plt.subplots(figsize=(9, 0.35 * max(len(rows), 6) + 1.5), dpi=130)
    d = rows.dropna(subset=["p50_cum12"]).iloc[::-1]
    ax.barh(d["area"].astype(str).str.slice(0, 38), d["p50_cum12"], color=ANALOG)
    for y, (v, n) in enumerate(zip(d["p50_cum12"], d["wells"])):
        ax.text(v, y, f"  n={int(n)}", va="center", fontsize=7)
    me = rows.attrs.get("company_p50_cum12")
    if me:
        ax.axvline(me, color="#E67E22", lw=2, label="my company (median cum12)")
        ax.legend(fontsize=8)
    ax.set_xlabel(f"median cum12 per well [{unit}]")
    ax.set_title(_wrap(title), fontsize=10)
    ax.grid(axis="x", alpha=0.3)
    p = _path(title)
    fig.tight_layout(); fig.savefig(p); plt.close(fig)
    return p


def gor_water_cut(df: pd.DataFrame, title: str) -> Path:
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10, 4.4), dpi=130)
    a1.plot(df["mop"], df["analog_gor_p50"], color=ANALOG, lw=2, label="analog P50")
    a2.plot(df["mop"], df["analog_wc_p50"], color=ANALOG, lw=2, label="analog P50")
    if "company_gor_p50" in df:
        a1.plot(df["mop"], df["company_gor_p50"], color="#E67E22", lw=2, marker="o", ms=3, label="my company P50")
        a2.plot(df["mop"], df["company_wc_p50"], color="#E67E22", lw=2, marker="o", ms=3, label="my company P50")
    a1.set_title("GOR [m³/m³]"); a2.set_title("water cut [-]")
    for a in (a1, a2):
        a.set_xlabel("months on production"); a.grid(alpha=0.3); a.legend(fontsize=8); a.set_ylim(bottom=0)
    fig.suptitle(_wrap(title), fontsize=10)
    p = _path(title)
    fig.tight_layout(); fig.savefig(p); plt.close(fig)
    return p
