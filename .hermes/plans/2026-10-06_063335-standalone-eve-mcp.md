# Standalone Multi-Character EVE MCP Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Build a separately versioned, shareable, self-hosted EVE Online MCP project that supplies read-only character information, skills, assets, mining data, and industry jobs for multiple independently authorized characters.

**Architecture:** Create a new repository at `/home/plk3000/src/eve-mcp`. It must be a complete Python package and MCP server in its own right—no imports from, runtime dependencies on, or shared local database/token store with `eve-mining-support`. It uses official EVE SSO/ESI only, a per-installation local SQLite metadata/cache database, and one secret-store namespace per authorized character. MCP runs over stdio by default for portable client configuration; Streamable HTTP is an optional local-loopback-only transport.

**Tech Stack:** Python 3.11, official `mcp` SDK/FastMCP, Typer CLI, Pydantic settings, SQLAlchemy/SQLite, httpx, `keyring`/Secret Service/KWallet, pytest, pytest-asyncio, respx, Ruff, mypy, `uv`, and an OSI license selected by Ghost before public publication.

---

## Product boundary

### What this project is

A sharable local tool/data bridge:

```text
MCP client (Hermes / Claude Desktop / VS Code / other)
        │ stdio by default
        ▼
     eve-mcp
        │ official EVE SSO + ESI, read-only
        ▼
Multiple independently authorized EVE characters
```

It exposes out-of-game ESI data. It is not a dashboard, game launcher, bot, overlay, macro, or client companion.

### What this project is not

- Not a package, plugin, submodule, or companion process of `eve-mining-support`.
- No direct shared code, local database, or token-store integration with the support-suite repository. Similar implementation patterns may be reimplemented deliberately with project-local tests and documentation.
- No EVE client process inspection, memory/cache/packet access, screenshots/OCR, window inspection, input synthesis, broadcasting, macro behavior, gameplay automation, or client modification.
- No corporate/alliance/fleet scopes in v1.
- No write-capable ESI tools: no orders, jobs, assets, fittings, contracts, or gameplay actions can be created/changed.
- No hosted/public deployment in v1. A user runs their own local installation and authorizes their own characters.

### Shareability requirements

- Publishable as a standalone Git repository and installable Python package.
- One-command local development/install workflow using `uv`.
- `README.md`, `LICENSE`, `SECURITY.md`, `CONTRIBUTING.md`, and `.env.example` included before public publication.
- No user-specific client ID, OAuth client secret, tokens, database, character data, or EVE static data in Git.
- Each installer registers/configures their own EVE developer application if current CCP SSO policy requires it; the project must not distribute Forge/Ghost credentials or a reusable private client secret.
- Documentation supports generic MCP clients, beginning with stdio JSON configuration.

---

## Multi-character and SSO design

### Scope approval gate

Before the first real authorization, use the official [EVE API Explorer](https://developers.eveonline.com/api-explorer) and current CCP SSO documentation to verify the exact endpoint/scope contract. Then show the scope list to the operator for approval:

```text
openid
esi-skills.read_skills.v1
esi-skills.read_skillqueue.v1
esi-assets.read_assets.v1
esi-industry.read_character_jobs.v1
esi-industry.read_character_mining.v1
```

Do not request a scope merely because it might become useful. Remove scopes unsupported by released v1 tools. Do not request corporation scopes.

### Profile model

The canonical profile key is the immutable EVE `character_id`, not the display name.

**Non-secret SQLite metadata** (`~/.local/share/eve-mcp/eve-mcp.db`):

```text
character_id
character_name
authorized_at
granted_scopes
token_expires_at             # never a token
enabled
last_successful_fetch_at
last_authorization_status
```

**Secret storage:**

```text
service: eve-mcp
key:     character/<character_id>/refresh-token
```

- Prefer the OS keyring/Secret Service/KWallet.
- If a fallback encrypted/local file is supported, it is explicit opt-in, mode `0600`, documented, excluded from Git, and tested for permissions.
- Access/refresh tokens must never appear in SQLite, exceptions, logs, fixtures, tool output, or CLI output.
- Multiple profiles are independent. Reauthorizing a character updates that character’s metadata/token only; it never overwrites another profile.

### Human-operated auth CLI

MCP tools must not initiate a login. Use a local, operator-run CLI:

```text
eve-mcp auth add
  → shows client/redirect host and exact scopes
  → creates PKCE verifier + state
  → starts temporary loopback callback listener
  → prints/opens official CCP authorization URL
  → operator logs in and consents in their browser
  → validates callback/state, exchanges code, verifies character identity
  → stores token under that character ID
```

Required management commands:

```text
eve-mcp auth list
eve-mcp auth status <character-id-or-exact-name>
eve-mcp auth disable <character-id-or-exact-name>
eve-mcp auth enable <character-id-or-exact-name>
eve-mcp auth revoke <character-id-or-exact-name>
```

`revoke` must clearly display the selected profile and require interactive confirmation. It first uses the official CCP revocation path if supported by current documentation, then deletes only that local profile’s secrets/metadata. It must not revoke silently.

---

## v1 MCP tool surface

Every character-data tool requires `character: str`, resolving only to a numeric ID or an exact unique authorized character name. There is deliberately no implicit active/default character.

### Profile / diagnostic tools

```text
eve_list_characters()
eve_get_character_status(character: str)
```

Return only safe profile metadata: character ID/name, enabled state, scopes, token expiry timestamp, cache/fetch status, and recovery guidance. Never return tokens or raw SSO claims.

### v1 read-only character tools (Ghost-selected)

```text
eve_get_character_summary(character: str)
eve_get_character(character: str)
eve_get_skills(character: str)
eve_get_skill_queue(character: str, limit: int = 50)
eve_get_assets(character: str, location_id: int | None = None,
               type_id: int | None = None, include_nested: bool = False,
               limit: int = 250)
eve_get_mining_ledger(character: str, days: int = 30, limit: int = 250)
eve_get_industry_jobs(character: str, include_completed: bool = False,
                      limit: int = 100)
```

`character` must be a numeric character ID or exact unique authorized character
name on every tool call. v1 has no implicit/default character.

`eve_get_character_summary` is the agent-oriented first call: identity,
authorization health, skill-queue summary, and freshness/count summaries for
assets, mining, and industry data—without a large raw-data dump.

Every response includes:

```text
character_id / character_name
as_of
cache_expires_at
returned_count
total_available (when ESI provides it)
truncated
next_page (when applicable)
```

Use `Decimal` for ISK/volume internally and serialize it as a documented string/fixed-point representation. Return data/caveats honestly: cached and incomplete data must be labeled, not silently flattened.

### Phase 2 (explicitly deferred)

Add blueprints, wallet transactions, and character market orders after v1 is
validated with real multi-character data. Public market analysis, ore
profitability, manufacturing recommendations, and timers remain separate
concerns and are not part of this MCP's initial release.

---

## Project layout

```text
/home/plk3000/src/eve-mcp/
├── AGENTS.md
├── README.md
├── LICENSE
├── SECURITY.md
├── CONTRIBUTING.md
├── pyproject.toml
├── .gitignore
├── .env.example
├── src/eve_mcp/
│   ├── __init__.py
│   ├── cli.py
│   ├── config.py
│   ├── db.py
│   ├── models.py
│   ├── profiles.py
│   ├── auth/
│   │   ├── __init__.py
│   │   ├── pkce.py
│   │   ├── callback.py
│   │   ├── sso.py
│   │   └── token_store.py
│   ├── esi/
│   │   ├── __init__.py
│   │   ├── client.py
│   │   ├── cache.py
│   │   └── endpoints.py
│   └── mcp/
│       ├── __init__.py
│       ├── server.py
│       ├── serializers.py
│       ├── profile_tools.py
│       └── character_tools.py
├── tests/
│   ├── auth/
│   ├── esi/
│   ├── mcp/
│   └── fixtures/esi/
└── docs/
    ├── authorization.md
    ├── mcp-clients.md
    └── privacy-and-security.md
```

Local data only:

```text
~/.local/share/eve-mcp/eve-mcp.db
~/.cache/eve-mcp/
~/.config/eve-mcp/                 # only explicit fallback secret configuration
```

---

## Implementation tasks

### Task 1: Scaffold the standalone repository and public-project contract

**Objective:** Create a clean, independently installable package without importing any local EVE support-suite code.

**Files:**
- Create: `AGENTS.md`, `README.md`, `LICENSE`, `SECURITY.md`, `CONTRIBUTING.md`
- Create: `pyproject.toml`, `.gitignore`, `.env.example`
- Create: `src/eve_mcp/__init__.py`, `src/eve_mcp/config.py`, `src/eve_mcp/cli.py`
- Create: `tests/test_project_contract.py`

**Step 1: Write failing tests.**

Assert package metadata has no local-path dependency on `eve-mining-support`; `eve-mcp --help` starts with no EVE credentials; default transport is stdio; default host, if HTTP is enabled later, is `127.0.0.1`; and production source has no prohibited OCR/input/window/process-control imports.

**Step 2: Run RED.**

```bash
cd /home/plk3000/src/eve-mcp
uv run pytest tests/test_project_contract.py -v
```

**Step 3: Implement minimal package/config/CLI.**

Set Python `>=3.11`; add `mcp` as an optional extra; add a dev extra for pytest/Ruff/mypy/respx. Add console script `eve-mcp = "eve_mcp.cli:main"`. Put names only—not credentials—in `.env.example`.

**Step 4: Run GREEN.**

```bash
uv run pytest tests/test_project_contract.py -v
uv run ruff check .
uv run mypy src
```

**Step 5: Commit.**

```bash
git add AGENTS.md README.md LICENSE SECURITY.md CONTRIBUTING.md pyproject.toml .gitignore .env.example src tests
git commit -m "chore: scaffold standalone EVE MCP"
```

### Task 2: Build non-secret profile persistence and resolver

**Objective:** Keep multiple character profiles isolated in local SQLite.

**Files:**
- Create: `src/eve_mcp/db.py`, `src/eve_mcp/models.py`, `src/eve_mcp/profiles.py`
- Create: `tests/test_profiles.py`

**Step 1: Write failing tests.**

Test adding two profiles with different character IDs, updating a reauthorized profile without duplicating it, exact-name and numeric-ID resolution, duplicate-name ambiguity, disabled profile rejection, valid status transitions, and absence of token columns in the schema.

**Step 2: Run RED.**

```bash
uv run pytest tests/test_profiles.py -v
```

**Step 3: Implement only metadata persistence.**

Use injected temporary paths in tests and user-local data paths at runtime. Make character ID the unique key. Store scopes/expiry/status but no secret fields.

**Step 4: Run GREEN and commit.**

```bash
uv run pytest tests/test_profiles.py -v
git add src/eve_mcp/db.py src/eve_mcp/models.py src/eve_mcp/profiles.py tests/test_profiles.py
git commit -m "feat: add isolated multi-character profiles"
```

### Task 3: Add per-character token-store abstraction

**Objective:** Store secrets outside project data and prove no cross-profile/token leakage.

**Files:**
- Create: `src/eve_mcp/auth/token_store.py`
- Create: `tests/auth/test_token_store.py`
- Modify: `.gitignore`

**Step 1: Write failing tests.**

Use a fake secret backend. Assert tokens are keyed by character ID, Character A cannot read/delete Character B’s token, missing-token error text contains no test secret, and fallback storage refuses unsafe file permissions.

**Step 2: RED → GREEN.**

```bash
uv run pytest tests/auth/test_token_store.py -v
```

Implement a protocol plus fake/test adapter and primary desktop-keyring adapter. Make file fallback explicit opt-in. Do not author literal secret values into project fixtures.

**Step 3: Commit.**

```bash
git add src/eve_mcp/auth/token_store.py tests/auth/test_token_store.py .gitignore
git commit -m "feat: store EVE tokens per character"
```

### Task 4: Implement ESI HTTP/cache primitives

**Objective:** Build the standalone cache-aware ESI client all tools will use.

**Files:**
- Create: `src/eve_mcp/esi/client.py`, `src/eve_mcp/esi/cache.py`
- Create: `tests/esi/test_client.py`

**Step 1: Write failing tests.**

Using mocked HTTP/clock, cover per-character Authorization handling, public calls with no auth, ETag/Expires cache usage, conditional 304, pagination, cache keys segregated by character, error-budget headers, timeout normalization, and no token values in logs/errors.

**Step 2: RED → GREEN.**

```bash
uv run pytest tests/esi/test_client.py -v
```

Use an injectable transport. Honor ESI cache headers rather than polling on an invented interval. Add descriptive versioned user agent.

**Step 3: Commit.**

```bash
git add src/eve_mcp/esi tests/esi/test_client.py
git commit -m "feat: add cache-aware ESI client"
```

### Task 5: Verify live SSO contract and add human auth CLI

**Objective:** Implement multiple-character SSO authorization only after scope review.

**Files:**
- Create: `src/eve_mcp/auth/pkce.py`, `src/eve_mcp/auth/callback.py`, `src/eve_mcp/auth/sso.py`
- Modify: `src/eve_mcp/cli.py`
- Create: `tests/auth/test_sso.py`
- Create: `docs/authorization.md`

**Step 1: Read-only official discovery.**

Verify EVE SSO/OIDC endpoints, exact scope requirements, loopback redirect allowance, PKCE support, refresh behavior, identity verification, and revocation from current CCP documentation/API Explorer. Record links and results in `docs/authorization.md`.

**Step 2: Obtain explicit operator approval.**

Show the exact verified scope list. Do not register an OAuth application, launch a browser, or create tokens before approval.

**Step 3: Write failing tests.**

Test state/verifier randomness, state mismatch, expired/cancelled callback, mock token exchange, identity validation, duplicate-character reauthorization, and cancellation producing no profile/token write.

**Step 4: RED → GREEN.**

```bash
uv run pytest tests/auth/test_sso.py -v
```

Implement loopback-only one-shot callback listener and CLI commands. Redact sensitive HTTP content from errors/logs. Use a self-hosted app configuration model; never bake a developer client secret into source.

**Step 5: Commit.**

```bash
git add src/eve_mcp/auth src/eve_mcp/cli.py tests/auth/test_sso.py docs/authorization.md
git commit -m "feat: add multi-character EVE SSO authorization"
```

### Task 6: Normalize ESI character endpoint adapters

**Objective:** Return bounded, typed, cached data before it reaches MCP tools.

**Files:**
- Create: `src/eve_mcp/esi/endpoints.py`
- Create: `tests/esi/test_endpoints.py`, `tests/fixtures/esi/`

**Step 1: Work vertical slices with test-first loops.**

For each, write one failing fixture-backed test, run it, implement minimum adapter, then run green:

1. Character public identity.
2. Skills.
3. Skill queue.
4. Assets (top-level, optional bounded nested traversal).
5. Mining ledger.
6. Industry jobs.

Tests must prove records/caches never cross Character A/Character B boundaries and must cover pagination, missing scope, disabled profile, stale cache, and partial-page failure.

**Step 2: Run full endpoint suite.**

```bash
uv run pytest tests/esi/test_endpoints.py -v
```

**Step 3: Commit.**

```bash
git add src/eve_mcp/esi/endpoints.py tests/esi/test_endpoints.py tests/fixtures/esi
git commit -m "feat: add read-only EVE character endpoint adapters"
```

### Task 7: Build MCP serialization/error contract

**Objective:** Prevent sensitive/error-prone ESI internals from becoming MCP output.

**Files:**
- Create: `src/eve_mcp/mcp/serializers.py`
- Create: `tests/mcp/test_serializers.py`

**Step 1: Write failing tests.**

Cover Decimal/datetime serialization, freshness/pagination fields, unknown/ambiguous/disabled profile errors, insufficient scope, upstream ESI failures, and test-token redaction.

**Step 2: RED → GREEN.**

```bash
uv run pytest tests/mcp/test_serializers.py -v
```

Responses use a stable structured error object with `code`, safe message, optional safe character ID, and recovery instruction—never traceback/token/raw OAuth body.

**Step 3: Commit.**

```bash
git add src/eve_mcp/mcp/serializers.py tests/mcp/test_serializers.py
git commit -m "feat: add safe MCP response serialization"
```

### Task 8: Implement FastMCP server and profile tools

**Objective:** Expose non-secret profile discovery over local MCP stdio.

**Files:**
- Create: `src/eve_mcp/mcp/__init__.py`, `src/eve_mcp/mcp/server.py`, `src/eve_mcp/mcp/profile_tools.py`
- Create: `tests/mcp/test_profile_tools.py`

**Step 1: Write failing tests.**

Build server with fixture dependencies. Assert `eve_list_characters` returns two safe profiles and `eve_get_character_status` requires/resolves explicit selection. Assert no listener/port is opened by default.

**Step 2: RED → GREEN.**

```bash
uv run pytest tests/mcp/test_profile_tools.py -v
```

Defer `FastMCP` import until server construction, use stdio as default, inject dependencies for testing, and supply read-only server instructions.

**Step 3: Commit.**

```bash
git add src/eve_mcp/mcp tests/mcp/test_profile_tools.py
git commit -m "feat: add EVE MCP profile tools"
```

### Task 9: Implement the read-only character-data MCP tools

**Objective:** Map each normalized endpoint to documented MCP tools.

**Files:**
- Create: `src/eve_mcp/mcp/character_tools.py`
- Create: `tests/mcp/test_character_tools.py`
- Modify: `src/eve_mcp/mcp/server.py`

**Step 1: Test one tool at a time.**

Start with `eve_get_skills`, then identity, queue, assets, mining ledger, and industry jobs. Every test proves explicit character selection, bounded inputs, correct character isolation, and freshness metadata.

**Step 2: RED → GREEN per tool.**

```bash
uv run pytest tests/mcp/test_character_tools.py -k get_skills -v
```

Repeat one red/green loop per tool. Tool documentation must declare read-only ESI data and never imply live EVE-client monitoring.

**Step 3: Run suite and commit.**

```bash
uv run pytest tests/mcp -v
git add src/eve_mcp/mcp tests/mcp
git commit -m "feat: add EVE character information MCP tools"
```

### Task 10: Add sharable install/client documentation and smoke test

**Objective:** Enable another user to install/configure the standalone project without access to Ghost’s workstation or data.

**Files:**
- Create: `docs/mcp-clients.md`, `docs/privacy-and-security.md`
- Modify: `README.md`, `CONTRIBUTING.md`, `SECURITY.md`
- Create: `tests/mcp/test_stdio_smoke.py`

**Step 1: Write failing subprocess/handshake test.**

Launch `eve-mcp serve` using stdio in an isolated temporary home/data directory; perform MCP initialize/tools-list handshake; verify expected tool names and no TCP listener by default.

**Step 2: RED → GREEN.**

```bash
uv run pytest tests/mcp/test_stdio_smoke.py -v
```

Document install with `uv`, EVE developer-app setup without publishing secrets, auth steps for each character, generic MCP client JSON examples, scope list, profile management, token revocation, privacy, cache freshness, and limitations.

**Step 3: Commit.**

```bash
git add README.md SECURITY.md CONTRIBUTING.md docs tests/mcp/test_stdio_smoke.py src/eve_mcp/cli.py
git commit -m "docs: publish standalone EVE MCP setup guide"
```

### Task 11: Real authorized verification and release gate

**Objective:** Verify the complete data path without leaking data or changing game state.

**Step 1: Get final scope approval.**

Show current API-Explorer-confirmed scopes and redirect URI. Obtain Ghost’s explicit go-ahead.

**Step 2: Authorize Character A, then Character B.**

Run `eve-mcp auth add` twice with Ghost completing CCP SSO in browser. Confirm `auth list` returns two distinct safe profiles.

**Step 3: Test MCP isolation.**

Using an MCP inspector/client, call `eve_list_characters`, then `eve_get_skills` and `eve_get_assets` for each exact profile. Confirm source character metadata matches the requested character; no cross-profile data appears.

**Step 4: Test safe disable.**

Disable one profile and confirm its tool calls return the expected safe state while the other continues working. Do not test permanent token revocation unless Ghost requests it.

**Step 5: Run full release gates.**

```bash
cd /home/plk3000/src/eve-mcp
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy src
git grep -n -E 'pyautogui|pynput|mss|easyocr|pytesseract|xdotool|ydotool|wmctrl|scrot|ImageGrab' -- ':!tests' && exit 1 || true
git diff --check
```

Review all secret-scan results manually so necessary protocol field names are not mistaken for credentials. Confirm no actual token/data file is tracked.

**Step 6: PR-only landing.**

Create feature branch, stage explicit authored paths, inspect staged diff/stat, and open a PR. Never push directly to `main`. PR report includes tool inventory, exact scopes, tests, live verification status, and compliance boundary.

---

## Risks and decisions

- **Shared project vs shared credentials:** the code can be shared; EVE app credentials and character tokens cannot. Documentation must make self-hosted authorization explicit.
- **Multi-character mix-up:** explicit selector on every tool, immutable-ID storage, no active/default profile, ambiguity is an error.
- **Scope creep:** verified API Explorer mapping plus approval gate; no corporation scopes.
- **Token leakage:** OS secret store, no token columns/logs/fixtures, redaction tests, Git review/security checks.
- **Stale/partial ESI data:** HTTP cache headers, ETag, pagination, source freshness and truncation metadata.
- **MCP response size:** bounded defaults/limits and explicit pagination metadata; no giant aggregate tool.
- **Future dashboard overlap:** possible feature overlap is acceptable, but shared code is deliberately avoided until both projects are mature and a separately versioned library is justified.

## Decisions still needed from Ghost

1. License for the shareable project: MIT, Apache-2.0, GPL-3.0, or another.
2. Initial distribution target: source repository only, or package-index publication later.
3. First MCP clients to document/test: Hermes, Claude Desktop, VS Code, or another.
4. Whether multi-character live authorization happens in first validation or Character B stays fixture-only until Character A is proven.
5. Suitable default caps for asset/ledger/wallet result sizes.
