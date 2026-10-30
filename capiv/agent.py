"""The Claude agent: Claude Agent SDK + in-process MCP server with the capiv tools.

The model never sees SQL. It sees seven tools with typed arguments and decides which
comparison to run with which analog filter. Built-in Claude Code tools are disabled.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any, AsyncIterator

import duckdb
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    create_sdk_mcp_server,
    query,
    tool,
)

from . import config, data, tools

SERVER = "capiv"

SYSTEM_PROMPT = """You are capiv, a production-benchmarking analyst for oil & gas operators in Argentina.

You have the public Capítulo IV dataset (Secretaría de Energía, Res. SE 319/93: monthly oil, gas and
water per well for every well in the country) loaded locally, plus the user's own company wells in
the same schema. Your job is to compare the company's wells against an analog set of public wells
and explain what you find like a reservoir engineer would.

How to work:
1. Start with `company_summary` to learn what the company has (areas, formation, vintages, ages).
2. Choose the analog set explicitly. Use `list_areas` when you are not sure of area names. Match
   formation and resource sub-type to the company's wells, and ALWAYS restrict `vintage_from` /
   `vintage_to` to a window comparable to the company's first-production dates (a 2018 and a 2024
   Vaca Muerta well are different designs). Say which filter you used.
3. Run the comparison(s) that answer the question. Prefer `type_curve` for "are we on the curve",
   `well_benchmark` for "which wells under-perform", `operator_benchmark` for "vs neighbours",
   `area_ranking` for "where are the best wells", `gor_water_cut` for fluid-ratio drift.
4. Read the tables (and the chart you get back) and answer with numbers: percentiles, % vs P50,
   well names. Flag caveats: small analog sets (< 20 wells), young wells (cum12 undefined),
   calendar-day rates (not tef-normalised), no lateral-length normalisation in the public data.

Units are the dataset's: oil and water in m³, gas in thousand m³ (Mm³), rates per calendar day,
GOR in m³/m³. P90 means 90% of wells are below. Do not convert to barrels unless asked.
Answer in the user's language (Spanish or English). Be concise: a short paragraph, then tables or
bullets with the key numbers, then the chart paths. You cannot write SQL or access files; if a
question is outside the tools, say so and suggest the nearest comparison you can run.
"""


def build_server(con: duckdb.DuckDBPyConnection):
    """Wrap every ToolSpec as an SDK MCP tool bound to this connection."""
    sdk_tools = []
    for spec in tools.TOOLS:
        def make(spec=spec):
            @tool(spec.name, spec.description, spec.schema)
            async def _t(args: dict[str, Any]) -> dict[str, Any]:
                try:
                    out = await asyncio.to_thread(tools.run_tool, con, spec.name, dict(args))
                    return out.to_mcp()
                except Exception as e:  # the model gets the error text and can retry with other args
                    return {"content": [{"type": "text", "text": f"error in {spec.name}: {e}"}], "is_error": True}
            return _t
        sdk_tools.append(make())
    return create_sdk_mcp_server(name=SERVER, version="0.1.0", tools=sdk_tools)


def build_options(con: duckdb.DuckDBPyConnection, *, model: str | None = None, max_turns: int = 24,
                  max_budget_usd: float | None = None, effort: str | None = None) -> ClaudeAgentOptions:
    server = build_server(con)
    names = [f"mcp__{SERVER}__{t.name}" for t in tools.TOOLS]
    return ClaudeAgentOptions(
        model=model or config.MODEL,
        system_prompt=SYSTEM_PROMPT,
        mcp_servers={SERVER: server},
        tools=[],                       # no Bash/Read/Write/...: the agent only has the capiv tools
        allowed_tools=names,            # auto-approve them
        setting_sources=[],             # do not load the user's CLAUDE.md / settings
        permission_mode="default",
        max_turns=max_turns,
        max_budget_usd=max_budget_usd,
        thinking={"type": "adaptive"},
        effort=effort,
        cwd=str(config.out_dir().parent),
    )


def _print_block(block, *, show_tools: bool) -> None:
    if isinstance(block, TextBlock):
        print(block.text, flush=True)
    elif isinstance(block, ToolUseBlock) and show_tools:
        args = ", ".join(f"{k}={v!r}" for k, v in block.input.items())
        print(f"  → {block.name.replace(f'mcp__{SERVER}__', '')}({args})", file=sys.stderr, flush=True)


async def _consume(messages: AsyncIterator, *, show_tools: bool) -> ResultMessage | None:
    result = None
    async for m in messages:
        if isinstance(m, AssistantMessage):
            for b in m.content:
                _print_block(b, show_tools=show_tools)
        elif isinstance(m, ResultMessage):
            result = m
    return result


def _report(result: ResultMessage | None) -> None:
    if result is None:
        return
    cost = f"${result.total_cost_usd:.3f}" if result.total_cost_usd is not None else "n/a"
    print(f"\n[{result.num_turns} turns, {result.duration_ms/1000:.0f}s, cost {cost}]", file=sys.stderr)
    if result.is_error:
        print(f"[ended with {result.subtype}]", file=sys.stderr)


async def ask(prompt: str, *, model: str | None = None, max_turns: int = 24,
              max_budget_usd: float | None = None, effort: str | None = None, show_tools: bool = True) -> int:
    con = data.connect(read_only=False)
    opts = build_options(con, model=model, max_turns=max_turns, max_budget_usd=max_budget_usd, effort=effort)
    result = await _consume(query(prompt=prompt, options=opts), show_tools=show_tools)
    _report(result)
    return 1 if (result is None or result.is_error) else 0


async def chat(*, model: str | None = None, max_turns: int = 24, max_budget_usd: float | None = None,
               effort: str | None = None) -> int:
    con = data.connect(read_only=False)
    opts = build_options(con, model=model, max_turns=max_turns, max_budget_usd=max_budget_usd, effort=effort)
    print("capiv chat. Ask about your wells vs the public data; empty line or Ctrl-C to quit.", file=sys.stderr)
    async with ClaudeSDKClient(options=opts) as client:
        while True:
            try:
                line = input("\nyou> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not line:
                break
            await client.query(line)
            result = await _consume(client.receive_response(), show_tools=True)
            _report(result)
    return 0
