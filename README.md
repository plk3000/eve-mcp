# eve-mcp

A standalone, self-hosted EVE Online MCP server for multiple independently
authorized characters. Its ESI data and fitting-planning tools are read-only;
the sole exception is an explicitly labeled, create-only saved-fitting action.

It communicates only with official EVE SSO/ESI endpoints. It never observes,
modifies, or controls the EVE client: no process inspection, cache scraping,
OCR, input automation, macros, or window control.

## Read-only tools and create-only fitting action

- Authorized-profile list and status.
- Character summary and public character information.
- Skills and skill queue.
- Assets.
- Mining ledger.
- Industry jobs.
- Blueprints.
- Recent wallet transactions (bounded by days and result limit).
- Character market orders (`order_state` defaults to `active`; historical `cancelled`, `expired`, and `fulfilled` states are available).
- Saved fittings, offline static-catalog search, fitting context, and deterministic fitting validation.
- `eve_create_fitting` can create one new saved fitting for the selected character after exact proposal/hash/confirmation checks; it never updates or deletes.

Blueprint, wallet-transaction, and market-order tools are Phase 2 additions. They
are ESI data only—not public-market analysis, recommendations, or any in-game
client monitoring or automation.

Fitting validation requires an installed static catalog. Install or update it
explicitly with `eve-mcp static-data refresh`; MCP startup never downloads SDE
data. See [static-data operations](docs/static-data.md) for the official CCP
source, cache lifecycle, and validation limits. The fitting write boundary,
consent scopes, idempotency, conflict handling, and no-overwrite guarantee are
documented in [saved fittings](docs/fittings.md).

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
application setup and multi-character authorization. Existing profiles must be
explicitly reauthorized with `eve-mcp auth add` for any newly granted fitting
scopes; MCP tools never initiate that flow.

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
