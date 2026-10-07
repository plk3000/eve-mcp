# Saved fittings

Fitting tools are explicitly character-scoped. `eve_get_fittings` reads saved
fittings only; it does not inspect the active ship. Catalog search and fitting
context are read-only. `eve_validate_fitting` deterministically checks the
submitted payload against an installed catalog and the selected character's
recorded skills. It does not save, buy, or fit anything. Validation does not
claim tactical effectiveness, price, market availability, or live ship state.

The one mutation is `eve_create_fitting`. **Creates one new saved fitting for
the selected character; never updates or deletes.** Aura must call it only
after Ghost directly asks to save the reviewed fitting. It accepts only the
canonical proposal returned by validation, its matching SHA-256 proposal ID,
the same selected character, and literal `confirm_create=true`. EVE Saved
Fittings are changed; active ships, assets, and the game client are not.

Before the single POST, the implementation checks that the character is
enabled and has both fitting scopes, the referenced catalog is installed, the
proposal hash and character match, skills/static facts still validate, and
`confirm_create` is true. It performs a fresh fitting-list read. An exact
existing fit is reported as already created; an existing **name conflict**
with different contents is refused and requires a distinct name. No existing
fit is ever overwritten.

The local SQLite creation ledger stores only character ID, proposal ID, state
(`creating`, `created`, or `unknown`), fitting ID, and timestamps. It contains
no tokens or raw ESI responses. After the one create request, the tool bypasses
the ESI cache and reads saved fittings back. It reports `created` only when
the exact name, description, hull, and item payload are present and the
returned fitting ID agrees when the upstream response provides one.

If the POST times out or readback cannot prove its outcome, the proposal is
marked `unknown`. A later call reconciles with a fresh GET and **never
automatically retries the POST**. If no exact fit can be proved, inspect the
character's saved fittings manually before deciding what to do. A same-name
different-payload fitting is never treated as a match.

## Authorization

The added scopes are:

```text
esi-fittings.read_fittings.v1
esi-fittings.write_fittings.v1
```

Enable them in the EVE developer application's **Enabled scopes** and
explicitly reauthorize each intended character using `eve-mcp auth add`.
The feature does not start OAuth or broaden a profile automatically. Existing
grants do not gain these scopes without renewed consent. See
[authorization](authorization.md).

The fitting routes used by this implementation are the plan-provided
character routes `GET /characters/{character_id}/fittings/` and
`POST /characters/{character_id}/fittings/`. Network access and live CCP
documentation checks were prohibited for this implementation session, so no
live endpoint, scope, authorization, or external fitting creation was tested.
Only synthetic HTTP fixtures are used by the tests; verify the current official
API Explorer contract before authorizing or relying on live use.
