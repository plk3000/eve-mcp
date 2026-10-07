# Authorization

`eve-mcp` is self-hosted. This project does **not** include an EVE application
client ID, client secret, access token, or refresh token. Each operator must
register/configure their own EVE developer application according to CCP's
current developer documentation, then configure the matching loopback redirect
URI.

Before authorizing a character, enable every listed scope in your EVE developer
application's **Enabled scopes** settings, then verify the current endpoint/scope
contract in [official EVE API Explorer](https://developers.eveonline.com/api-explorer). The
Phase 2 mapping used here is: `GET /characters/{character_id}/blueprints/` →
`esi-characters.read_blueprints.v1`; `GET /characters/{character_id}/wallet/transactions/`
→ `esi-wallet.read_character_wallet.v1`; and `GET /characters/{character_id}/orders/`
→ `esi-markets.read_character_orders.v1`. The Explorer was not reachable from
the offline implementation environment on 2026-10-07, and network access was
prohibited for the fitting work, so no live endpoint or authorization request
was made. In addition to the existing read scopes, the fitting feature
requests the plan-specified fitting scopes below; independently verify those
current upstream contracts before authorizing a character. No corporation or
fleet scopes are requested.

```text
esi-skills.read_skills.v1
esi-skills.read_skillqueue.v1
esi-assets.read_assets.v1
esi-industry.read_character_jobs.v1
esi-industry.read_character_mining.v1
esi-characters.read_blueprints.v1
esi-wallet.read_character_wallet.v1
esi-markets.read_character_orders.v1
esi-fittings.read_fittings.v1
esi-fittings.write_fittings.v1
```

`esi-fittings.write_fittings.v1` authorizes saved-fitting creation through the
single explicitly create-only `eve_create_fitting` MCP tool. The tool never
updates or deletes existing fittings, and it does not change the active ship or
assets. The exact boundary and unverified-live-contract status are documented
in [saved fittings](fittings.md).

## Existing profiles must be reauthorized

A previously authorized profile only retains the scopes approved at its last
consent. To use Phase 2 tools, explicitly run `eve-mcp auth add` and complete CCP
consent again for **each** intended character. The normal per-character
reauthorization updates only that character profile and keyring refresh token.
MCP tools return an actionable ESI missing-scope/authentication error and never
start a browser, register an application, or reauthorize automatically.

## Configure your local installation

```bash
export EVE_MCP_CLIENT_ID='your-own-eve-application-client-id'
export EVE_MCP_REDIRECT_URI='http://127.0.0.1:8080/callback'
```

The redirect URI must exactly match the URI registered with CCP and must be an
`http://127.0.0.1:<port>/...` callback. The server refuses non-loopback callback
addresses.

## Add one character

Run this only when you are ready to authorize that specific character:

```bash
eve-mcp auth add
```

The command prints the requested scopes and official authorization URL, starts
a temporary loopback callback listener, and waits for you to complete CCP SSO in
your own browser. It uses PKCE and validates callback state before writing any
profile metadata or secret. It does not inspect or control the EVE client.

Repeat `eve-mcp auth add` for each character. Profiles are keyed by immutable
character ID, so reauthorizing one character cannot overwrite another.

## Manage local profiles

```bash
eve-mcp auth list
eve-mcp auth status <character-id-or-exact-name>
eve-mcp auth disable <character-id-or-exact-name>
eve-mcp auth enable <character-id-or-exact-name>
eve-mcp auth revoke <character-id-or-exact-name>
```

`disable` stops local MCP data access while retaining the local secret.
`revoke` displays the selected profile and requires confirmation before deleting
only that profile's local secret and metadata. It does not silently affect other
characters. Before relying on remote token revocation, verify CCP's current SSO
revocation support; v1's `revoke` command deletes local authorization state.
