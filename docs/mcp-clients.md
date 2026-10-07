# MCP clients

The default transport is stdio and opens no listener:

```json
{"mcpServers":{"eve":{"command":"eve-mcp","args":["serve"]}}}
```

Every character-data tool requires `character`, either a numeric character ID or an exact authorized name. There is no active/default character. The sole mutation, `eve_create_fitting`, creates only a new saved fitting and never updates or deletes; call it only after direct operator intent and review of the exact validated proposal.
