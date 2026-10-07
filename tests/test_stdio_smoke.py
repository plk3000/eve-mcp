from __future__ import annotations

import os
import sys

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


@pytest.mark.asyncio
async def test_serve_stdio_completes_initialize_and_tools_list_without_tcp_listener(
    tmp_path,
) -> None:
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "eve_mcp.cli", "serve"],
        cwd=str(tmp_path),
        env={**os.environ, "EVE_MCP_DATA_DIR": str(tmp_path / "data")},
    )
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            initialized = await session.initialize()
            tools = await session.list_tools()

    names = {tool.name for tool in tools.tools}
    assert initialized.serverInfo.name == "eve-mcp"
    assert {
        "eve_list_characters",
        "eve_get_skills",
        "eve_get_assets",
        "eve_get_blueprints",
        "eve_get_wallet_transactions",
        "eve_get_character_market_orders",
        "eve_get_fittings",
        "eve_search_fitting_types",
        "eve_get_fitting_context",
        "eve_validate_fitting",
        "eve_create_fitting",
    } <= names
    assert not any(
        name.startswith(("eve_delete_fitting", "eve_update_fitting", "eve_replace_fitting"))
        for name in names
    )
