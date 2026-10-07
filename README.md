# eve-mcp

A standalone, self-hosted, **read-only** EVE Online MCP server for multiple
independently authorized characters.

It communicates only with official EVE SSO/ESI endpoints. It never observes,
modifies, or controls the EVE client: no process inspection, cache scraping,
OCR, input automation, macros, or window control.

## Read-only tools

- Authorized-profile list and status.
- Character summary and public character information.
- Skills and skill queue.
- Assets.
- Mining ledger.
- Industry jobs.
- Blueprints.
- Recent wallet transactions (bounded by days and result limit).
- Character market orders (`order_state` defaults to `active`; historical `cancelled`, `expired`, and `fulfilled` states are available).

Blueprint, wallet-transaction, and market-order tools are Phase 2 additions. They
are ESI data only—not public-market analysis, recommendations, or any in-game
client monitoring or automation.

Every data tool requires a numeric character ID or exact authorized character
name. There is no active/default character. Responses include source character,
data freshness, counts, and truncation metadata.

## Install for development

```bash
uv sync --extra dev --extra keyring
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy src
```

## Run as an MCP server

The default transport is stdio and binds no TCP listener:

```bash
uv run eve-mcp serve
```

See [MCP client configuration](docs/mcp-clients.md) for a generic client
configuration and [authorization](docs/authorization.md) for self-hosted CCP
application setup and multi-character authorization. Existing profiles authorized
with the earlier scope set must be explicitly reauthorized with `eve-mcp auth add`
before Phase 2 tools can access their data; MCP tools never initiate that flow.

## Security and data handling

- This repository contains no EVE client credentials or character data.
- Character metadata/cache are stored locally under `~/.local/share/eve-mcp/`.
- Refresh tokens are stored separately per character in the desktop keyring;
  they are never stored in SQLite or returned through MCP.
- Use `eve-mcp auth disable` to stop local data access for one character, or
  `eve-mcp auth revoke` to delete that character's local secret/profile after
  confirmation.

Read [privacy and security](docs/privacy-and-security.md) before adding a
character. Report vulnerabilities according to [SECURITY.md](SECURITY.md).
