import pytest

from capiv import tools


ARGS = {"cuenca": "NEUQUINA", "formacion": "vaca muerta", "sub_tipo_recurso": "SHALE", "plot": False}


def test_registry_is_closed():
    names = [t.name for t in tools.TOOLS]
    assert names == ["company_summary", "list_areas", "type_curve", "well_benchmark",
                     "operator_benchmark", "area_ranking", "gor_water_cut"]
    # no tool accepts free text that could reach the SQL layer as code
    for t in tools.TOOLS:
        assert t.schema.get("additionalProperties") is False
        assert not any(k in ("sql", "query", "where") for k in t.schema["properties"])


@pytest.mark.parametrize("name", [t.name for t in tools.TOOLS])
def test_every_tool_runs_and_returns_markdown(con, name):
    args = {"company_summary": {}, "list_areas": {k: v for k, v in ARGS.items() if k != "plot"}}.get(name, ARGS)
    out = tools.run_tool(con, name, args)
    assert isinstance(out.text, str) and "|" in out.text
    assert out.png is None


def test_tools_render_charts(con, tmp_path, monkeypatch):
    monkeypatch.setenv("CAPIV_OUT", str(tmp_path))
    out = tools.run_tool(con, "type_curve", {**ARGS, "plot": True, "months": 12})
    assert out.png is not None and out.png.exists() and out.png.stat().st_size > 10_000
    mcp = out.to_mcp()
    assert mcp["content"][0]["type"] == "text"
    assert mcp["content"][1]["type"] == "image" and mcp["content"][1]["mimeType"] == "image/png"


def test_argument_validation(con):
    with pytest.raises(ValueError, match="unknown argument"):
        tools.run_tool(con, "type_curve", {"sql": "select 1"})
    with pytest.raises(ValueError, match="one of"):
        tools.run_tool(con, "well_benchmark", {"metric": "eur"})
    with pytest.raises(ValueError, match="list of strings"):
        tools.run_tool(con, "type_curve", {"areas": "AREA NORTE"})
    with pytest.raises(KeyError):
        tools.run_tool(con, "drop_table", {})


def test_tools_without_company_data(con_public_only):
    out = tools.run_tool(con_public_only, "company_summary", {})
    assert "No company data" in out.text
    out = tools.run_tool(con_public_only, "well_benchmark", {**ARGS})
    assert "no company data" in out.text


def test_md_table_formatting():
    import pandas as pd
    df = pd.DataFrame({"a": [1234.5, 0.123, None], "b": ["x", "y", "z"], "d": pd.to_datetime(["2024-01-01"] * 3)})
    t = tools.md_table(df)
    assert "1,234" in t and "0.12" in t and "2024-01" in t and "| a | b | d |" in t
