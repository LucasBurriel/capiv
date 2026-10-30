# Design notes

Short record of the product and engineering decisions behind `capiv`. The README
explains *what* it does; this file explains *why* it is shaped this way.

## 1. Who is this for and what question do they ask

An operator (or a non-operating partner, or an analyst at a bank) has monthly
production for its own wells and wants to know **how those wells stack up against
the rest of the basin**. Argentina is unusual in that the regulator publishes
*every* well's monthly oil, gas and water (Capítulo IV of Res. SE 319/93), so the
"rest of the basin" is not a vendor's black box, it is a 300 MB CSV.

The comparisons a reservoir / production engineer actually runs, in order of how
often they come up:

| # | Question | Tool |
|---|----------|------|
| 1 | "Are my wells on the type curve of the area?" | `type_curve` |
| 2 | "Which of my wells are under-performers, and by how much?" | `well_benchmark` |
| 3 | "How do I rank against the neighbouring operators?" | `operator_benchmark` |
| 4 | "Which areas / formations are producing the best wells right now?" | `area_ranking` |
| 5 | "Is my GOR or water cut drifting away from the analogs?" | `gor_water_cut` |
| 6 | "What is in the dataset for this basin, which areas have enough wells?" | `list_areas` |

Everything else (decline-rate fitting, EUR, economics) is downstream of these and
was left out on purpose for v0.1.

## 2. Analog set, not "the market"

Every comparison is **my wells vs. an analog set**, and the analog set is defined by
explicit, parameterised filters: basin, area(s), producing formation, resource
sub-type (SHALE / TIGHT / conventional), well type (oil / gas) and **vintage**
(first-production window). Vintage matters more than people expect: a 2018 Vaca
Muerta well and a 2024 one are different designs (lateral length, stages, proppant),
so a type curve that mixes them is meaningless. The agent must choose a vintage
window; the sensible default is "same window as my wells".

## 3. Normalisation choices

* **Time axis is months-on-production (MOP)**, not calendar months. MOP 0 is the
  first month with non-zero production of the fluid being compared. This is the
  standard way to build a type curve and lets wells drilled in different years be
  overlaid.
* **Rates are calendar-day rates** (`prod / days_in_month`), not `prod / tef`.
  `tef` (effective production time) is self-reported and noisy; calendar-day rates
  are what the royalty is paid on and what every public benchmark uses. A future
  option could expose `tef`-normalised rates.
* **Units are the dataset's units**: oil and water in m³/month, gas in thousands of
  m³/month (`Mm³`). Rates derived from them are m³/d and Mm³/d. GOR is reported as
  m³/m³ (gas ×1000 / oil). No conversion to bbl or scf; the audience is Argentine.
* **Per-well metrics**: peak monthly rate, cumulative 6 and 12 months (only when
  the well has reached that age), 12-month decline (`rate@MOP12 / peak`), GOR and
  water cut averaged over MOP 1..12.
* **Percentiles** of a company well are computed empirically against the analog set
  (share of analog wells below it). P10/P50/P90 bands on the type curve are
  `quantile_cont` per MOP, labelled explicitly ("P90 = 90 % of wells are below")
  to avoid the statistics-vs-petroleum convention clash.

## 4. Why the model does not write SQL

The agent chooses **which** parameterised comparison to run and **with which
filters**. It never writes a `SELECT`. Reasons, in order of weight:

1. **Correctness of the engineering.** The hard part of these comparisons is the
   normalisation above (MOP alignment, vintage, calendar-day rates, "has the well
   reached 12 months before you compute cum12"). A model improvising SQL on a
   40-column table will get one of those subtly wrong and the output will *look*
   right. Encoding them once, in tested code, is the whole value of the tool.
2. **Comparability.** If every answer is the same query with different parameters,
   two answers can be compared with each other. Free-form SQL gives you a different
   definition of "cum12" every time.
3. **Safety and cost.** Bounded queries cannot scan the wrong table, join the
   company's private data into a public aggregate by accident, or run for an hour.
   The company CSV lives in the same DuckDB file as the public data; a closed
   enum of queries is what keeps them from being mixed in an unintended way.
4. **Testability.** Each comparison has a pytest. "The model generates SQL" is not
   testable in the same sense.

The trade-off is flexibility: a question none of the tools can answer gets
"I can't answer that with the tools I have" instead of a creative query. For an
operator's benchmarking workflow that is the right trade. Adding a comparison means
adding a function + a test + a tool entry, which is a code review, not a prompt edit.

The rule in one line: **the model fills in a form, it does not instruct the machine.**

## 5. Data engineering

* **Storage**: one local DuckDB file (`~/.capiv/capiv.duckdb` by default). DuckDB
  reads the 150-330 MB CSVs directly, copes with the mixed number formats across
  years, and runs the window functions for MOP in seconds. No server, no Postgres,
  no 400k×40 pandas frame in memory.
* **Which files**: the dataset is one CSV per year (2006-2026, ~300 MB each, all
  wells) plus a single file with only unconventional wells across all years
  (~150 MB). The default download is the unconventional file: it is the smallest
  thing that gives a complete history of the Vaca Muerta / tight-gas wells, which
  is what anyone benchmarking in 2026 cares about. Yearly files are opt-in
  (`capiv download --year 2024`) for conventional work. When both are loaded, rows
  are de-duplicated on `(idpozo, anio, mes)` keeping the latest `fechaingreso`.
* **Company data**: a CSV with the **same column names as Capítulo IV** (`sigla,
  anio, mes, prod_pet, prod_gas, prod_agua`, plus optional `areayacimiento`,
  `formacion`, `sub_tipo_recurso`, `tipopozo`, `tef`...). Operators already
  produce this file every month for the regulator, so there is nothing to map.
* **Nothing leaves the machine except the question and the tool results.** The
  model sees aggregates and the company's well-level metrics only when a tool
  returns them. The raw CSVs are never sent.

## 6. Agent

* Claude Agent SDK (Python), model `claude-opus-5-5`, adaptive thinking. The SDK
  gives the tool loop, in-process MCP tools (`@tool` + `create_sdk_mcp_server`),
  and image results (charts) without a custom harness.
* Built-in tools (Bash, Read, Write...) are **disabled** (`tools=[]`) and
  filesystem settings are not loaded (`setting_sources=[]`): the agent has exactly
  the comparison tools plus `company_summary`. This is a product, not a coding
  assistant.
* Charts are PNGs written to `./capiv_out/` and also returned to the model as
  images, so it can look at the plot it just made and comment on it.
* `max_turns` is capped and `max_budget_usd` is exposed on the CLI.

## 7. Out of scope for v0.1 (candidates for next)

Decline-curve fitting (Arps) per well and EUR, lateral-length normalisation (the
public dataset has no completion data; the "Capítulo IV - Pozos" register has
depth only), a web UI, and a "monthly report" mode that re-runs the comparisons
every time a new Capítulo IV drop lands.
