# Skill-Aware Saved Fittings Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Add a safe fitting-planning workflow to the standalone `eve-mcp` project: Aura can freestyle and validate an explicit-character fitting from Ghost’s context and the character’s skills, inspect saved fittings, and create exactly one new approved fitting in that character’s EVE Saved Fittings library—never update or delete an existing fitting.

**Architecture:** Add a production ESI fitting adapter for saved-fitting reads and an LLM-led fitting-planning layer backed by a pinned, public EVE static-data catalog. Aura may call one explicitly named **create-only** MCP tool after it has validated an exact proposal: it requires the selected character plus the exact canonical proposal ID, never updates a fitting, never calls a delete endpoint, deduplicates identical proposals, and immediately reads back the created record. A local non-secret creation ledger makes retries safe after uncertain network outcomes.

**Tech Stack:** Existing Python 3.11, FastMCP stdio, Typer, httpx, keyring, pytest, Ruff, mypy; add a project-local static-data catalog/importer only after selecting and pinning an authoritative public EVE static-data source and checksum/version.

---

## Current context

- Repository: `/home/plk3000/src/eve-mcp`
- Local/default branch: `main`, synchronized with both `github/main` and Forgejo `origin/main` at the same tree.
- Existing character-scoped ESI stack:
  - `src/eve_mcp/esi/client.py` provides cache-aware authenticated HTTP and safe error mapping.
  - `src/eve_mcp/esi/endpoints.py` has production and fixture endpoint adapters.
  - `src/eve_mcp/mcp/character_tools.py` resolves every character explicitly.
  - `src/eve_mcp/mcp/server.py` is stdio-only and currently exposes twelve tools.
  - `src/eve_mcp/auth/pkce.py` owns the centrally requested OAuth scope tuple.
- Two authorized profiles exist locally and Phase 2 was live-validated. Do not assume their existing grants include fitting scopes.
- Existing server/package framing says “read-only.” This feature adds one explicitly labeled, create-only MCP side effect; every other tool remains read-only. The write path must never update or delete a saved fitting.

## Scope and non-goals

### In scope

1. Read a selected character’s saved fittings with `esi-fittings.read_fittings.v1`.
2. Build deterministic fitting proposals from explicit inputs and a selected character’s skills.
3. Validate proposal structure, hull/module slot compatibility, fitting resources, required skills, and named constraints using pinned static data.
4. Optionally compare required fitting items against the character’s ESI assets as a factual availability report.
5. Save a specifically approved proposal with `esi-fittings.write_fittings.v1` through a human-operated CLI; read it back to verify the exact created fitting ID/name/contents.
6. Provide EFT export for a proposal when all involved type names are available from the static catalog.

### Explicitly out of scope

- Any EVE client inspection, fitting-screen control, import clipboard automation, purchase, asset movement, ship fitting, undocking, or input automation.
- Deleting or overwriting saved fittings. A future delete capability is a separate destructive-feature decision.
- “Best fit” claims without declared objective/constraints and recorded assumptions.
- Corporational fittings/scopes, fleet scopes, or unrelated character scopes.
- A generic market optimizer, combat/mining simulator, or live-state estimator.
- Automatic authorization or scope escalation.

## Product contract

### Proposed read-only MCP tools

```text
eve_get_fittings(
  character: str,
  ship_type_id: int | None = None,
  limit: int = 100
)

eve_search_fitting_types(
  query: str,
  kind: "hull" | "module" | "charge" | "drone" | "rig" | null = null,
  limit: int = 20
)

eve_get_fitting_context(
  character: str,
  hull_type_id: int | None = null
)

eve_validate_fitting(
  character: str,
  fitting: {name, description, ship_type_id, items[{type_id, flag, quantity}]},
  include_asset_check: bool = true
)
```

This is **LLM-led, catalog-grounded fitting design**:

1. Aura gathers the selected character’s skills and optional hull context.
2. Aura searches the locally cached static catalog for named hulls/modules/charges/drones rather than guessing type IDs.
3. Aura reasons over Ghost’s natural-language objective and context to propose a fitting payload.
4. `eve_validate_fitting` deterministically checks the proposal against static fitting facts and selected-character skills, then returns a canonical proposal ID only for the exact submitted payload.
5. Aura explains its recommendation and the validator’s facts to Ghost; Ghost may iterate, reject it, or explicitly save the reviewed proposal through the CLI.

The MCP does **not** contain a hidden optimizer, activity whitelist, or fixed “best” policy. The LLM is allowed to freestyle the design based on the conversation—mining, gas, exploration, PvE, hauling, a special doctrine, budget, available assets, or any other context—but no free-form answer becomes a fitting proposal until its type IDs are resolved against the pinned catalog and it passes validation.

`eve_validate_fitting` returns:

```text
proposal_schema_version
proposal_id                 # SHA-256 over canonical, non-secret proposal JSON
character_id / character_name
catalog_version
submitted fitting payload: name, description, ship_type_id, items[type_id, flag, quantity]
validation: valid / invalid / incomplete
skill gaps and fitting-resource calculations
slot violations and unknown type IDs
asset availability summary when requested
EFT export when type names are known
assumptions / dimensions not validated
```

A valid response means only: “this exact saved-fitting payload is structurally valid according to the installed static catalog and the selected character’s recorded skills.” It does **not** certify that the fit is tactically good, affordable, current-meta, available in a market, safe in the target system, or fitted to an active ship.

The validator is intentionally strict about facts and permissive about intent:

```text
LLM chooses:     activity, doctrine, tradeoffs, candidate modules, rationale
Catalog checks:  type existence, hull/module class, slot flag, CPU, powergrid, calibration,
                 required skills, quantities, named static facts
ESI checks:      selected character skills and optional asset quantities
Ghost decides:   whether to accept the plan and whether to save it
```

If information is absent, Aura must label the recommendation as an assumption rather than manufacture a fact. Examples: public-market price requires a later market-data lookup; current threat level/live ship state are outside ESI/static data; combat effectiveness needs a future explicitly modeled simulator.

### Proposed create-only MCP contract

```text
eve_create_fitting(
  character: str,
  proposal: {canonical proposal returned by eve_validate_fitting},
  proposal_id: str,
  confirm_create: true
)
```

This is the only fitting mutation exposed to Aura. Its description must begin with a side-effect warning: **“Creates one new saved fitting for the selected character; never updates or deletes.”** The agent may call it only when Ghost has directly asked to save/create the reviewed fitting in the current conversation.

Before a POST, the tool returns without mutation unless all conditions hold:

- The selected profile is enabled and has the required write scope after reauthorization.
- The proposal schema validates, the canonical hash equals `proposal_id`, and the proposal character ID equals the selected profile ID.
- The referenced static-catalog version is installed locally and the fitting remains valid under it.
- `confirm_create` is exactly `true`.
- The proposal does not match a previously completed creation for that character in the local creation ledger.
- A fresh, uncached fitting-list read finds no existing saved fitting with the same canonical payload fingerprint. A same-name but different-payload fit is not overwritten; it returns `name_conflict` and asks Ghost/Aura to choose a distinct name.

Creation/retry behavior:

```text
1. Persist non-secret creation intent: character ID + proposal ID + state=creating.
2. Perform exactly one POST /characters/{character_id}/fittings/ attempt.
3. Invalidate/bypass the fitting-list cache; read back the new fitting by returned ID or exact canonical contents.
4. Persist state=created plus fitting ID; return safe source metadata.
5. If POST times out or its outcome is unknown, do not retry POST automatically.
   Reconcile with a fresh uncached GET. If not provably found, persist state=unknown and
   return recovery guidance; later calls reconcile before any possible new POST.
```

No implementation file, MCP tool, CLI command, or scope in this tranche may call ESI `DELETE`, an update/replacement endpoint, or an endpoint that alters an existing fitting. The local ledger is not an authorization bypass; it only prevents duplicate creations during retries.

## OAuth scope lifecycle

The code-side scope tuple will contain exactly these two additions:

```text
esi-fittings.read_fittings.v1
esi-fittings.write_fittings.v1
```

Before any live authorization:

1. Verify current endpoint and scope requirements through the official EVE API Explorer/current CCP documentation.
2. Ghost enables both scopes in the EVE developer application’s **Enabled scopes** settings.
3. Update code, docs, and tests together.
4. Ghost explicitly reauthorizes only the characters intended to read/save fittings.
5. Live-smoke a bounded fitting read, then a deliberately named test fitting only after Ghost separately approves creating that external EVE record.

No code, MCP tool, or CLI command may begin an OAuth flow automatically.

## Implementation tasks

### Task 1: Record the fitting write boundary and exact upstream contract

**Objective:** Establish a verified, least-privilege API contract before adding code or requesting scopes.

**Files:**
- Create: `docs/fittings.md`
- Modify: `docs/authorization.md`
- Modify: `README.md`
- Test: `tests/test_fitting_contract.py`

**Step 1: Read-only official discovery.**

Confirm from current CCP documentation/API Explorer:

```text
GET    /characters/{character_id}/fittings/  → esi-fittings.read_fittings.v1
POST   /characters/{character_id}/fittings/  → esi-fittings.write_fittings.v1
```

Confirm the exact POST request/response schema, saved-fitting limits, response codes, cache headers, and whether the POST response returns a fitting ID.

**Step 2: Write failing contract tests.**

Assert that the planned read/write fitting scopes are present only when the fitting feature is enabled, that no corporation/fleet scopes or delete/update capability are introduced, and that documentation declares the create-only MCP boundary, duplicate/retry behavior, and no-overwrite/no-delete guarantee.

**Step 3: Implement the minimal documentation/scope-contract changes.**

Document that saving a fitting changes only the character’s saved-fitting library, never an active ship or assets. Document required Enabled Scopes and explicit reauthorization.

**Step 4: Verify.**

```bash
.venv/bin/python -m pytest tests/test_fitting_contract.py -q
```

Expected: passing contract tests with no live OAuth or ESI call.

**Step 5: Commit.**

```bash
git add README.md docs/authorization.md docs/fittings.md tests/test_fitting_contract.py
git commit -m "docs: define saved fitting scope and write boundary"
```

### Task 2: Add strict fitting domain models and canonical proposal IDs

**Objective:** Make a fit proposal immutable, validate its ESI-compatible payload, and prevent a reviewed proposal from being modified before saving.

**Files:**
- Create: `src/eve_mcp/fittings/__init__.py`
- Create: `src/eve_mcp/fittings/models.py`
- Create: `src/eve_mcp/fittings/proposal.py`
- Create: `tests/test_fitting_proposals.py`

**Step 1: Write failing tests.**

Test synthetic data only:

- Valid payload canonicalizes deterministically and returns the same proposal ID independent of item input order.
- Item `type_id` and `quantity` must be positive integers; flags must be nonempty known catalog flags.
- A proposal cannot be saved for a different character ID.
- Changing a module, quantity, hull, or catalog version changes the proposal ID.
- Proposal serialization contains no OAuth/token field.

**Step 2: Run RED.**

```bash
.venv/bin/python -m pytest tests/test_fitting_proposals.py -q
```

Expected: failure because fitting models/proposal hashing do not exist.

**Step 3: Implement minimal models.**

Use frozen dataclasses or Pydantic models already available in the project. Canonical JSON must use stable key ordering and normalized item order before hashing. Do not accept arbitrary provider payload fields.

**Step 4: Run GREEN and full local regression.**

```bash
.venv/bin/python -m pytest tests/test_fitting_proposals.py -q
.venv/bin/python -m pytest -q
```

**Step 5: Commit.**

```bash
git add src/eve_mcp/fittings tests/test_fitting_proposals.py
git commit -m "feat: add immutable fitting proposals"
```

### Task 3: Add an official cached EVE static-data catalog and lifecycle CLI

**Objective:** Download only the public static facts needed for fitting validation from CCP’s official Static Data Export (SDE), cache/version them locally, and give the operator explicit status, refresh, and safe-clear commands.

**Source contract:** CCP’s official static-data service publishes the current Tranquility build marker at:

```text
https://developers.eveonline.com/static-data/tranquility/latest.jsonl
```

The record keyed `sde` identifies the latest SDE build. The implementation must read current official documentation at implementation time to discover the exact build-manifest schema and only the JSONL files required for released fitting validation. Do not scrape third-party websites and do not bundle an unpinned SDE dump in Git.

**Files:**
- Create: `docs/static-data.md`
- Create: `src/eve_mcp/static_data/__init__.py`
- Create: `src/eve_mcp/static_data/catalog.py`
- Create: `src/eve_mcp/static_data/manifest.py`
- Create: `src/eve_mcp/static_data/refresh.py`
- Create: `src/eve_mcp/static_data/storage.py`
- Create: `tests/test_static_catalog.py`
- Create: `tests/test_static_data_lifecycle.py`
- Modify: `src/eve_mcp/cli.py`
- Modify: `.gitignore`, `pyproject.toml` only if a justified parser/dependency is required

**Local storage contract:**

```text
~/.cache/eve-mcp/sde/<build-id>/raw/          # downloaded public SDE files; replaceable cache
~/.local/share/eve-mcp/static-data/<build-id>/catalog.sqlite3
~/.local/share/eve-mcp/static-data/<build-id>/manifest.json
~/.local/share/eve-mcp/static-data/current.json
```

`manifest.json` contains only public provenance: source URL(s), build ID, file names, downloaded-byte counts, SHA-256 checksums when the official manifest provides them (otherwise locally calculated content checksums), import timestamp, and catalog schema version. It contains no OAuth data, profile metadata, proposals, or character data.

**Operator commands:**

```text
eve-mcp static-data status
eve-mcp static-data refresh
eve-mcp static-data refresh --force
eve-mcp static-data clear --build <build-id> --yes
eve-mcp static-data clear --all --yes
```

Command behavior:

- `status` is offline/read-only. It reports installed builds, active build, catalog schema, disk usage, provenance, and whether an optional manifest check says a newer official build exists. It never downloads data by default.
- `refresh` is an explicit public-network operation. It checks `latest.jsonl`, exits without download when the active build matches, otherwise downloads into a unique staging directory, validates the manifest/schema/checksums, imports the narrow catalog, and atomically updates `current.json` only after successful validation. Failed/partial stages must not replace the current working catalog.
- `refresh --force` re-downloads/re-imports the identified active/latest build through the same staging and validation path.
- `clear --build` removes only the named local build’s raw cache and imported catalog. It refuses to clear the active build unless `--yes` is present and the caller acknowledges that fitting drafting/saving will be unavailable until another build is refreshed.
- `clear --all --yes` removes only the local SDE cache/catalog directories; it must never delete profiles, keyring secrets, ESI HTTP cache, fitting proposals, or any Git-tracked file. It prints the exact paths and total bytes before deletion.
- MCP startup and fitting draft/save calls never auto-refresh or auto-clear. If no usable catalog exists, they return a safe `static_data_unavailable` recovery response naming `eve-mcp static-data refresh`.

**Step 1: Read-only official discovery and data minimization.**

Confirm the current SDE JSONL manifest/build layout and identify the minimum data needed to support the released planner:

```text
Type IDs and names
Group/category metadata sufficient to classify hull/module/charge/drone types
Dogma attributes/effects required for slot, CPU, powergrid, calibration, and skill requirements
Type-to-dogma relationships and required-skill levels
```

Record exact official URLs, schema/version observations, license, compatibility caveats, and files deliberately not downloaded in `docs/static-data.md`.

**Step 2: Write lifecycle tests first.**

Use `httpx.MockTransport`, a temporary `EVE_MCP_DATA_DIR`, and small synthetic JSONL payloads. Assert:

- `status` on a new installation is safe and indicates that no catalog is installed.
- `refresh` builds a catalog from an official-manifest-shaped payload and updates `current.json` only after all validation/import steps pass.
- A same-build refresh performs no catalog replacement; `--force` does.
- Bad checksum, malformed JSONL, missing required dataset, and importer failure preserve the previously active catalog byte-for-byte.
- `clear --build` requires `--yes`, touches only the exact build directory, and never deletes an adjacent profile DB/proposal.
- `clear --all --yes` removes only the defined cache/catalog roots and leaves a synthetic keyring/profile/proposal location untouched.
- Two concurrent refresh attempts serialize through a local lock; the second exits safely rather than corrupting `current.json`.

**Step 3: Run RED.**

```bash
.venv/bin/python -m pytest tests/test_static_data_lifecycle.py -q
```

Expected: failures because lifecycle storage/import commands do not exist.

**Step 4: Implement atomic storage and manifest verification.**

- Use an in-process/file lock scoped to the static-data root.
- Download to a same-filesystem staging directory; calculate/check checksums before import.
- Build a SQLite catalog in staging, run integrity queries, then atomically promote the directory/current pointer.
- Retain previous builds by default. `refresh` never deletes an earlier build, so a reviewed fitting proposal remains reproducible while its catalog version is installed.
- Do not log raw downloaded records unnecessarily; logs contain build/file/count/checksum summaries only.

**Step 5: Implement the narrow catalog protocol.**

The planner depends on a `StaticCatalog` protocol, not JSONL or SQLite directly. It exposes only required type/fitting facts. Catalog lookup is local/offline after refresh.

**Step 6: Write catalog behavior tests.**

Use a tiny synthetic catalog fixture to prove:

- Hull and module lookup by type ID.
- Unknown type reports safe, actionable validation failure.
- Required skills, slot class, CPU, powergrid, calibration, and type name are exposed by the narrow interface.
- Catalog version mismatch blocks save rather than silently using newer/different data.

**Step 7: Verify and commit.**

```bash
.venv/bin/python -m pytest tests/test_static_data_lifecycle.py tests/test_static_catalog.py -q
.venv/bin/eve-mcp static-data --help
git add .gitignore pyproject.toml docs/static-data.md src/eve_mcp/static_data src/eve_mcp/cli.py tests/test_static_data_lifecycle.py tests/test_static_catalog.py
git commit -m "feat: add cached official EVE static-data catalog"
```

### Task 4: Add read-only saved-fitting retrieval

**Objective:** Retrieve bounded saved fittings for the exact selected character and preserve existing provenance/cache semantics.

**Files:**
- Modify: `src/eve_mcp/auth/pkce.py`
- Modify: `src/eve_mcp/esi/endpoints.py`
- Modify: `src/eve_mcp/mcp/character_tools.py`
- Modify: `src/eve_mcp/mcp/server.py`
- Modify: `tests/test_live_esi_endpoints.py`
- Modify: `tests/test_mcp_tools.py`
- Create or modify: `tests/test_fitting_tools.py`

**Step 1: Write a failing fixture test.**

Establish two synthetic profiles with distinct fittings. Assert:

```python
result = asyncio.run(tools.fittings("Alice", ship_type_id=123, limit=1))
assert result["character_id"] == "100"
assert result["returned_count"] == 1
assert result["items"] == [{"fitting_id": 1, "ship_type_id": 123, ...}]
```

Also test exact-name/ID resolution, `limit` clamp, hull filtering, a no-fitting response, and no cross-character records.

**Step 2: Run RED.**

```bash
.venv/bin/python -m pytest tests/test_fitting_tools.py -k retrieval -q
```

**Step 3: Implement vertical slice.**

- Add `fittings(character_id, limit)` to `CharacterEndpoints`, `EsiCharacterEndpoints`, and `FixtureCharacterEndpoints`.
- Use the authenticated `GET /characters/{id}/fittings/` endpoint through existing `EsiClient` cache/error behavior.
- Filter `ship_type_id` after retrieval without making false total-count claims.
- Add `CharacterTools.fittings` and `eve_get_fittings` with explicit character and bounded `limit`.

**Step 4: Run GREEN.**

```bash
.venv/bin/python -m pytest tests/test_fitting_tools.py -k retrieval -q
.venv/bin/python -m pytest tests/test_live_esi_endpoints.py tests/test_mcp_tools.py -q
```

**Step 5: Commit.**

```bash
git add src/eve_mcp/auth/pkce.py src/eve_mcp/esi/endpoints.py src/eve_mcp/mcp tests
git commit -m "feat: add read-only character saved fittings"
```

### Task 5: Build deterministic skill-aware validation

**Objective:** Validate a candidate fitting against a selected character’s trained skills and static fitting constraints without pretending to choose a universally optimal fit.

**Files:**
- Create: `src/eve_mcp/fittings/validation.py`
- Create: `tests/test_fitting_validation.py`
- Modify: `src/eve_mcp/fittings/models.py`
- Modify: `src/eve_mcp/static_data/catalog.py`

**Step 1: Write a failing test per rule.**

Use synthetic static facts and skills payloads to cover separately:

- Hull skill missing or insufficient level.
- Module/charge/drone prerequisite missing or insufficient level.
- Wrong slot/flag for an item.
- Exceeded high/medium/low/rig/service slot count.
- Exceeded CPU, powergrid, or calibration.
- Unknown static fact returns `incomplete`, never `valid`.
- Valid proposal reports computed totals and zero gaps.

**Step 2: Run each test RED before implementation.**

```bash
.venv/bin/python -m pytest tests/test_fitting_validation.py -k cpu -q
```

**Step 3: Implement the smallest validator.**

Return structured results:

```text
valid: bool
complete: bool
skill_gaps: [{type_id, required_level, trained_level}]
slot_violations: [...]
resource_totals: {cpu, powergrid, calibration}
resource_limits: {cpu, powergrid, calibration}
unknown_type_ids: [...]
```

No simulation claims beyond catalog facts. Effects such as boosted yield, heat, damage, capacitor stability, and combat projection remain outside the first validator.

**Step 4: Run GREEN and commit.**

```bash
.venv/bin/python -m pytest tests/test_fitting_validation.py -q
git add src/eve_mcp/fittings src/eve_mcp/static_data tests/test_fitting_validation.py
git commit -m "feat: validate fitting skills and resources"
```

### Task 6: Add catalog discovery, context, and LLM-led fitting validation

**Objective:** Give Aura grounded static facts and deterministic validation so it can freely reason from Ghost’s live conversational context without making an unvalidated fitting claim.

**Files:**
- Create: `src/eve_mcp/fittings/context.py`
- Create: `src/eve_mcp/fittings/search.py`
- Create: `tests/test_fitting_context.py`
- Create: `tests/test_fitting_validation_tools.py`
- Modify: `src/eve_mcp/mcp/character_tools.py`
- Modify: `src/eve_mcp/mcp/server.py`
- Modify: `src/eve_mcp/fittings/proposal.py`

**Step 1: Write failing type-discovery tests.**

Using a synthetic static catalog, verify:

- `eve_search_fitting_types` performs bounded, case-insensitive name search and returns only type ID, name, kind/group, and enough safe fitting facts for selection.
- A `kind` filter excludes mismatched hull/module/charge/drone/rig records.
- A blank/over-broad query is rejected or bounded; it cannot dump the SDE.
- Results carry the active catalog version.

**Step 2: Run RED.**

```bash
.venv/bin/python -m pytest tests/test_fitting_context.py -k search -q
```

**Step 3: Add `eve_get_fitting_context`.**

Return the selected character’s safe fitting-relevant facts: character ID/name, trained skills and levels, optional selected hull’s resource/slot facts, active catalog version, and clear limitations. Do not perform a write and do not fabricate market, route, ship-state, or combat facts.

**Step 4: Write failing validator-tool tests.**

Pass a synthetic LLM-authored fitting payload directly to `CharacterTools.validate_fitting`. Assert it:

- Resolves the character explicitly and never crosses profiles.
- Resolves all type IDs through the installed catalog.
- Returns deterministic `valid`, `invalid`, or `incomplete` output for skill gaps, wrong flags, resource overflow, unknown types, and valid payloads.
- Produces the same canonical proposal ID for semantically identical ordered/unordered item inputs.
- Never invokes ESI POST/DELETE and never treats free-form rationale as a static fact.
- Optionally aggregates existing assets after validation and labels quantity/location caveats.

**Step 5: Run RED, then implement the minimal vertical slice.**

```bash
.venv/bin/python -m pytest tests/test_fitting_validation_tools.py -q
```

Expose exactly these MCP tools:

```text
eve_search_fitting_types
eve_get_fitting_context
eve_validate_fitting
```

`eve_validate_fitting` accepts a structured fitting payload; the LLM’s natural-language rationale stays in Aura’s conversation, not in a trusted executable policy. The server returns the canonical reviewed proposal object/ID only after validation. Its docstring must state that validation does not save, buy, or fit anything.

**Step 6: Verify and commit.**

```bash
.venv/bin/python -m pytest tests/test_fitting_context.py tests/test_fitting_validation_tools.py -q
git add src/eve_mcp/fittings src/eve_mcp/mcp tests/test_fitting_context.py tests/test_fitting_validation_tools.py
git commit -m "feat: add LLM-led fitting validation tools"
```

### Task 7: Add create-only saved-fitting MCP action with idempotent reconciliation

**Objective:** Let Aura create one newly validated saved fitting after direct Ghost intent, while making overwrite, deletion, and duplicate retry impossible through the released MCP surface.

**Files:**
- Create: `src/eve_mcp/fittings/creation_ledger.py`
- Create: `src/eve_mcp/fittings/writer.py`
- Modify: `src/eve_mcp/esi/client.py` only to add narrowly typed authenticated POST and cache-invalidation/fresh-GET helpers if needed
- Modify: `src/eve_mcp/esi/endpoints.py`
- Modify: `src/eve_mcp/mcp/character_tools.py`
- Modify: `src/eve_mcp/mcp/server.py`
- Create: `tests/test_fitting_creation.py`
- Modify: `tests/test_sso_and_auth_cli.py`

**Step 1: Write failing safety tests before a POST implementation.**

Test with `httpx.MockTransport` and a temporary creation-ledger SQLite database:

- Missing `confirm_create=True` causes zero HTTP calls.
- Character mismatch, modified proposal, unknown catalog version, invalid fit, disabled profile, and missing write scope cause zero HTTP calls.
- Only the selected character’s bearer token is attached to POST.
- Exactly one POST reaches `/characters/{character_id}/fittings/` for a valid approved proposal.
- No test/module path invokes `DELETE`, PUT/PATCH, or a fitting-update endpoint.
- An exact completed `character_id + proposal_id` returns `already_created` without POST.
- A same-name existing fit with a different canonical payload returns `name_conflict` without POST.
- An exact matching saved fitting discovered before POST returns `already_created` without POST, even if the local ledger was lost.
- A successful POST invalidates cached fitting-list data and reads the fitting back; returned ID/name/hull/items must match the approved proposal.
- POST timeout records `unknown`, makes no automatic second POST, and a later create call performs fresh-GET reconciliation before any action.
- A reconciliation result cannot be proven returns `creation_outcome_unknown`, not a retryable create request.

**Step 2: Run RED.**

```bash
.venv/bin/python -m pytest tests/test_fitting_creation.py -q
```

**Step 3: Implement the non-secret creation ledger and writer.**

The ledger schema stores only:

```text
character_id
proposal_id
state: creating | created | unknown
created_fitting_id (when verified)
attempted_at / verified_at
```

It must never store access/refresh tokens, raw SSO data, or an opaque ESI response. It must be partitioned by immutable character ID and use a uniqueness constraint on `(character_id, proposal_id)`.

**Step 4: Implement fresh read-back and conflict behavior.**

Implement a cache-bypassing fitting-list read solely for mutation preflight/read-back. Generate a canonical comparison fingerprint from returned fitting contents; do not depend only on fitting name. The name-conflict rule is deliberately conservative: never alter an existing same-name fitting; return a safe response asking Aura/Ghost to choose a new name.

**Step 5: Expose exactly `eve_create_fitting`.**

Register the one side-effecting tool in `server.py`. Its description begins with the create-only warning and lists its preconditions. It accepts only a canonical validated proposal, the matching proposal ID, and literal `confirm_create=True`. Do not expose writer methods via broad generic CRUD plumbing.

**Step 6: Run GREEN and commit.**

```bash
.venv/bin/python -m pytest tests/test_fitting_creation.py tests/test_sso_and_auth_cli.py -q
git add src/eve_mcp/esi src/eve_mcp/fittings src/eve_mcp/mcp tests
git commit -m "feat: add create-only saved fitting action"
```

### Task 8: Documentation, SSO reauthorization, and live acceptance

**Objective:** Ship a shareable feature with correct consent documentation and prove the write boundary deliberately.

**Files:**
- Modify: `README.md`
- Modify: `docs/authorization.md`
- Modify: `docs/mcp-clients.md`
- Modify: `docs/privacy-and-security.md`
- Modify: `docs/fittings.md`
- Modify: `tests/test_stdio_smoke.py`

**Step 1: Documentation updates.**

Document:

- Exact two new scopes and CCP Enabled Scopes requirement.
- Each authorized character needs explicit reauthorization after the scope update.
- Read/search/context/validation tools remain factual MCP tools; `eve_create_fitting` is the one explicitly labeled side-effecting tool and can create only a new saved fitting after proposal/confirmation validation.
- The no-overwrite/no-delete guarantee, same-name conflict behavior, creation ledger, unknown-outcome recovery, and mandatory read-back verification.
- Proposal review, `confirm_create=true`, mandatory read-back verification, token handling, static-data setup/update, and unknown-outcome recovery.
- No active ship/asset/game client change occurs.

**Step 2: Stdio discovery test.**

Update the expected MCP tool list to include `eve_get_fittings`, `eve_search_fitting_types`, `eve_get_fitting_context`, `eve_validate_fitting`, and the explicitly side-effecting `eve_create_fitting`. Assert that no `delete`, `update`, `replace`, or generic fitting-write tool is discoverable.

**Step 3: Full local quality gate.**

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy src
git diff --check
git grep -n -E 'pyautogui|pynput|mss|easyocr|pytesseract|xdotool|ydotool|wmctrl|scrot|ImageGrab' -- ':!tests' ':!.hermes/plans/*' && exit 1 || true
```

**Step 4: Explicit operator authorization gate.**

Do not initiate this automatically. After Ghost has enabled the fitting scopes in CCP’s developer app and explicitly authorizes the operation:

1. Reauthorize each intended character with `eve-mcp auth add`.
2. Verify `auth status` reports authorized profiles.
3. Live-smoke `eve_get_fittings` for each selected character.
4. Live-smoke `eve_validate_fitting` with a named, deliberately non-production proposal; inspect its assumptions and proposal ID.
5. Ask Ghost for a separate explicit go-ahead naming the character and exact validated fitting before invoking `eve_create_fitting(..., confirm_create=true)`.
6. Verify POST result by fresh uncached read-back, then confirm the fitting appears through `eve_get_fittings`.
7. Repeat the same `eve_create_fitting` request and prove it returns `already_created` without a second POST; do not test delete/update because no such capability exists.

**Step 5: PR-only release.**

Create `feat/skill-aware-saved-fittings` from current `main`, commit each completed vertical slice, push both Forgejo and GitHub remotes, and open PRs. Do not push direct changes to `main`. Report mock-tested versus live-verified behavior and the exact granted scopes.

## Risks and decisions

- **Write scope blast radius:** `esi-fittings.write_fittings.v1` allows a saved-fitting write. The released MCP surface is narrowed to one create-only action requiring a validated exact proposal ID and `confirm_create=true`; it contains no update/delete path. A per-character creation ledger, name-conflict block, fresh preflight, and uncertain-outcome reconciliation prevent automatic duplicate POSTs. Creation remains externally irreversible through this project.
- **Static-data correctness:** ESI character skills alone cannot validate a legal fit. Pinning a catalog version and returning `incomplete` for missing facts is safer than guessing from stale/unversioned web data.
- **Fit recommendation claims:** “Best” is not an objective outcome. Aura may reason freely from Ghost’s context, but every recommendation must distinguish LLM judgment from catalog/ESI facts and disclose catalog version, assumptions, and excluded dimensions.
- **Scope rollout:** Add read and write fitting scopes to CCP Enabled Scopes before reauthorizing. Existing grants do not gain either permission.
- **Saved-fitting limits:** CCP may reject a create based on account-side fitting limits or server validation. Surface only a safe error and leave the proposal untouched.
- **No live-state confusion:** Saved fitting data is not a current ship fitting or cargo state. Documentation and tool descriptions must state this.

## Decisions needed from Ghost before implementation

1. Confirm which characters should receive the fitting **write** scope initially (read-only fitting scope may be granted more broadly).
2. Confirm the create-only MCP boundary: `eve_create_fitting` may create a new fitting only after direct Ghost intent plus `confirm_create=true`; no update/delete capability will be shipped.
3. Approve the selected pinned static-data source after Task 3 discovery, before any download/import is treated as authoritative.
4. Define which factual dimensions Aura should fetch before freestyling a fit (for example assets, public market pricing, or only skills/static fitting facts).
