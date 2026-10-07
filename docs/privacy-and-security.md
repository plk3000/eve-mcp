# Privacy and security

`eve-mcp` is a local bridge to official EVE SSO/ESI data. Fitting reads and
planning are read-only; the sole mutation is create-only saved-fitting
creation. It does
not inspect, monitor, modify, or control the EVE client. In particular, it does
not use client memory, cache files, packets, screenshots/OCR, window inspection,
mouse/keyboard input, or input broadcasting.

## Local data

The SQLite metadata/cache database under `~/.local/share/eve-mcp/` contains only
character ID/name, granted scopes, authorization-expiry/status information, and
ESI cache metadata/data. It never contains OAuth access or refresh tokens.

Refresh tokens are stored separately per character in the configured desktop
keyring under the `eve-mcp` service namespace. MCP tools and CLI status/list
commands never print tokens or raw SSO grants.

## Scope and control

Authorize each character independently through your browser using your own CCP
application configuration. All character-data MCP tools require an explicit
character selector. `disable` blocks local MCP access while retaining the
secret; confirmed `revoke` deletes only the selected character's local secret
and metadata.

ESI responses may be cached. Tool responses report data freshness, expiry, and
truncation so MCP consumers do not mistake stale or partial data for live game
state.

The fitting creation ledger under `~/.local/share/eve-mcp/` stores only
non-secret idempotency metadata (character ID, proposal hash, state, and
verified fitting ID). It records uncertain outcomes so requests are reconciled
by fresh read rather than automatically posting again. Static catalogs are
replaceable public data stored separately from profiles and tokens. See
[saved fittings](fittings.md) and [static-data status](static-data.md).
