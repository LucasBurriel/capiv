"""`capiv` command line."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from . import __version__, config, data, schema


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # tables carry m³ and accents; Windows consoles default to cp1252
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(prog="capiv", description="Benchmark your wells against Argentina's public Capítulo IV data.")
    p.add_argument("--version", action="version", version=f"capiv {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("download", help="download Capítulo IV CSVs and (re)build the local DuckDB")
    d.add_argument("--year", action="append", default=[], help="add a yearly file (all wells), e.g. --year 2024; repeatable")
    d.add_argument("--no-unconventional", action="store_true", help="skip the default all-years unconventional file")
    d.add_argument("--url", help="explicit CSV URL (if the Secretaría changed a resource id)")
    d.add_argument("--force", action="store_true", help="re-download even if present")
    d.add_argument("--no-load", action="store_true", help="only download, do not rebuild the table")

    l = sub.add_parser("load", help="(re)build the capiv table from CSVs already in CAPIV_HOME/raw or given paths")
    l.add_argument("paths", nargs="*", help="CSV paths; default: every *.csv in CAPIV_HOME/raw")

    c = sub.add_parser("load-company", help="load your company's monthly production CSV (Capítulo IV column names)")
    c.add_argument("csv")
    c.add_argument("--name", help="company name to use when the CSV has no `empresa` column")

    sub.add_parser("status", help="what is loaded")
    sub.add_parser("schema", help="print the expected company CSV schema")

    m = sub.add_parser("make-demo", help="write the synthetic demo company CSV")
    m.add_argument("path", nargs="?", default="my_company.csv")

    r = sub.add_parser("run", help="run one comparison directly, no model (same tools the agent uses)")
    r.add_argument("tool", help="company_summary | list_areas | type_curve | well_benchmark | operator_benchmark | area_ranking | gor_water_cut")
    r.add_argument("--args", default="{}", help='JSON arguments, e.g. \'{"areas":["BANDURRIA SUR"],"vintage_from":"2022-01"}\'')

    a = sub.add_parser("ask", help="ask the agent one question")
    a.add_argument("prompt")
    _agent_flags(a)

    ch = sub.add_parser("chat", help="interactive multi-turn session with the agent")
    _agent_flags(ch)

    ns = p.parse_args(argv)
    return {
        "download": cmd_download, "load": cmd_load, "load-company": cmd_load_company, "status": cmd_status,
        "schema": cmd_schema, "make-demo": cmd_make_demo, "run": cmd_run, "ask": cmd_ask, "chat": cmd_chat,
    }[ns.cmd](ns)


def _agent_flags(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("--model", default=None, help=f"model id (default {config.MODEL}, env CAPIV_MODEL)")
    sp.add_argument("--max-turns", type=int, default=24)
    sp.add_argument("--max-budget-usd", type=float, default=None)
    sp.add_argument("--effort", choices=["low", "medium", "high", "xhigh", "max"], default=None)
    sp.add_argument("--quiet", action="store_true", help="do not echo tool calls to stderr")


def cmd_download(ns) -> int:
    keys = [] if ns.no_unconventional else ["unconventional"]
    keys += [str(y) for y in ns.year]
    if not keys and not ns.url:
        print("nothing to download (use --year or drop --no-unconventional)", file=sys.stderr)
        return 2
    print(f"downloading into {config.raw_dir()}", file=sys.stderr)
    paths = data.download(keys, url=ns.url, force=ns.force)
    if ns.no_load:
        return 0
    return _load(sorted(set(paths) | set(config.raw_dir().glob("*.csv"))))


def cmd_load(ns) -> int:
    paths = [Path(x) for x in ns.paths] or sorted(config.raw_dir().glob("*.csv"))
    if not paths:
        print(f"no CSVs found in {config.raw_dir()}; run `capiv download` first", file=sys.stderr)
        return 2
    return _load(paths)


def _load(paths) -> int:
    print(f"loading {len(paths)} file(s) into {config.db_path()} ...", file=sys.stderr)
    con = data.connect()
    n = data.load_capiv(con, list(paths))
    st = data.status(con)["capiv"]
    print(f"capiv table: {n:,} rows, {st['wells']:,} wells, {st['from']} .. {st['to']}", file=sys.stderr)
    return 0


def cmd_load_company(ns) -> int:
    con = data.connect()
    try:
        n = data.load_company(con, Path(ns.csv), ns.name)
    except schema.SchemaError as e:
        print(f"schema error: {e}", file=sys.stderr)
        return 2
    st = data.status(con)["company"]
    print(f"company table: {n:,} rows, {st['wells']} wells, {st['from']} .. {st['to']} ({st['empresa']})", file=sys.stderr)
    return 0


def cmd_status(ns) -> int:
    con = data.connect(read_only=True) if config.db_path().exists() else None
    if con is None:
        print(f"no database at {config.db_path()}; run `capiv download`")
        return 0
    print(json.dumps(data.status(con), indent=2, default=str))
    return 0


def cmd_schema(ns) -> int:
    print(schema.describe())
    return 0


def cmd_make_demo(ns) -> int:
    from . import synthetic
    synthetic.write_csv(synthetic.demo_company(), Path(ns.path))
    print(f"wrote {ns.path}", file=sys.stderr)
    return 0


def cmd_run(ns) -> int:
    from . import tools
    con = data.connect(read_only=False)
    try:
        args = json.loads(ns.args)
    except json.JSONDecodeError as e:
        print(f"--args must be JSON: {e}", file=sys.stderr)
        return 2
    try:
        out = tools.run_tool(con, ns.tool, args)
    except (KeyError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(out.text)
    if out.png:
        print(f"\nchart: {out.png}")
    return 0


def _agent_ready() -> bool:
    if not config.db_path().exists():
        print(f"no database at {config.db_path()}; run `capiv download` first", file=sys.stderr)
        return False
    return True


def cmd_ask(ns) -> int:
    if not _agent_ready():
        return 2
    from . import agent
    return asyncio.run(agent.ask(ns.prompt, model=ns.model, max_turns=ns.max_turns, max_budget_usd=ns.max_budget_usd,
                                 effort=ns.effort, show_tools=not ns.quiet))


def cmd_chat(ns) -> int:
    if not _agent_ready():
        return 2
    from . import agent
    return asyncio.run(agent.chat(model=ns.model, max_turns=ns.max_turns, max_budget_usd=ns.max_budget_usd, effort=ns.effort))


if __name__ == "__main__":
    sys.exit(main())
