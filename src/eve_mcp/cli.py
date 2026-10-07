"""Human-operated CLI; MCP tools never start login or mutate profiles."""

from __future__ import annotations

import asyncio
import json
from typing import Annotated

import httpx
import typer

from eve_mcp.auth.pkce import SCOPES
from eve_mcp.auth.sso import SsoClient, SsoWorkflow
from eve_mcp.auth.token_store import KeyringTokenStore
from eve_mcp.config import Settings
from eve_mcp.profiles import ProfileRepository
from eve_mcp.static_data.refresh import StaticDataManager, StaticDataSourceUnavailable

app = typer.Typer(help="Standalone EVE Online MCP server with create-only fitting support.")
auth_app = typer.Typer(help="Manage independently authorized EVE characters.")
static_data_app = typer.Typer(help="Inspect and manage the local static-data cache.")
app.add_typer(auth_app, name="auth")
app.add_typer(static_data_app, name="static-data")


def _repository() -> ProfileRepository:
    settings = Settings.from_environment()
    return ProfileRepository(settings.data_dir / "eve-mcp.db")


def _scope_text() -> str:
    return "\n".join(f"  {scope}" for scope in SCOPES)


def _static_data() -> StaticDataManager:
    return StaticDataManager(Settings.from_environment().data_dir)


@static_data_app.command("status")
def static_data_status() -> None:
    """Report local catalogs without contacting a network service."""
    typer.echo(json.dumps(_static_data().status(), indent=2, sort_keys=True))


@static_data_app.command("refresh")
def static_data_refresh(
    force: Annotated[bool, typer.Option("--force", help="Replace the installed build.")] = False,
) -> None:
    """Fetch and validate the current official CCP SDE archive."""
    try:
        result = _static_data().refresh_official(force=force)
        typer.echo(json.dumps(result, sort_keys=True))
    except (
        StaticDataSourceUnavailable,
        httpx.HTTPError,
        OSError,
        RuntimeError,
        ValueError,
    ) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(2) from error


@static_data_app.command("clear")
def static_data_clear(
    build: Annotated[str | None, typer.Option("--build", help="Exact build ID to clear.")] = None,
    all_builds: Annotated[bool, typer.Option("--all", help="Clear all local static data.")] = False,
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            help="Confirm deletion; clearing the active build disables fitting until refreshed.",
        ),
    ] = False,
) -> None:
    """Clear only static-data cache/catalog paths."""
    if (build is None) == (not all_builds):
        typer.echo("Specify exactly one of --build or --all.", err=True)
        raise typer.Exit(2)
    manager = _static_data()
    if all_builds and yes:
        paths = (manager.root, manager.cache_root)
        total_bytes = sum(manager._bytes(path) for path in paths)
        typer.echo(f"Clearing {total_bytes} bytes from: " + ", ".join(str(path) for path in paths))
    if build and yes:
        current = manager._current()
        if current and current.get("build_id") == build:
            typer.echo(
                "Warning: fitting drafting and saving will be unavailable until another "
                "catalog is refreshed."
            )
    try:
        result = (
            manager.clear_all(yes=yes) if all_builds else manager.clear_build(build or "", yes=yes)
        )
    except ValueError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(2) from error
    typer.echo(json.dumps(result, indent=2, sort_keys=True))


@app.command()
def serve() -> None:
    """Run the MCP server over stdio; this does not open a network listener."""
    from eve_mcp.mcp.server import run_stdio

    run_stdio()


@auth_app.command("add")
def auth_add() -> None:
    """Start an operator-approved, loopback-only PKCE authorization flow."""
    settings = Settings.from_environment()
    typer.echo("The following exact character scopes will be requested:")
    typer.echo(_scope_text())
    try:
        client_id, redirect_uri = settings.require_sso_configuration()
    except ValueError as error:
        typer.echo(str(error))
        raise typer.Exit(2) from error
    workflow = SsoWorkflow(SsoClient(client_id, redirect_uri), _repository(), KeyringTokenStore())
    transaction = workflow.begin()
    typer.echo(f"Open this official EVE SSO URL in your browser:\n{transaction.authorization_url}")
    typer.echo(
        "Waiting only on the configured loopback callback; no MCP tool can authorize a character."
    )

    async def finish_authorization() -> None:
        from eve_mcp.auth.callback import LoopbackCallback

        callback = await LoopbackCallback(redirect_uri).receive()
        profile = await workflow.complete(transaction, callback)
        typer.echo(f"Authorized {profile.character_id} ({profile.character_name}).")

    asyncio.run(finish_authorization())


@auth_app.command("list")
def auth_list() -> None:
    """List safe metadata only; tokens are never printed."""
    for profile in _repository().list():
        typer.echo(f"{profile.character_id}\t{profile.character_name}\tenabled={profile.enabled}")


@auth_app.command("status")
def auth_status(character: str) -> None:
    """Show safe authorization metadata for an exact ID or exact unique name."""
    profile = _repository().resolve_including_disabled(character)
    typer.echo(
        f"{profile.character_id}\t{profile.character_name}\tenabled={profile.enabled}\t"
        f"status={profile.last_authorization_status}\texpires={profile.token_expires_at}"
    )


@auth_app.command("disable")
def auth_disable(character: str) -> None:
    """Disable local data access without deleting a refresh token."""
    _repository().set_enabled(character, False)
    typer.echo("Character disabled locally; its secret was retained.")


@auth_app.command("enable")
def auth_enable(character: str) -> None:
    """Enable a locally disabled character profile."""
    _repository().set_enabled(character, True)
    typer.echo("Character enabled locally.")


@auth_app.command("revoke")
def auth_revoke(
    character: str,
    yes: Annotated[
        bool, typer.Option("--yes", help="Confirm local secret/profile deletion.")
    ] = False,
) -> None:
    """Require confirmation before deleting exactly one local profile and secret."""
    repository = _repository()
    profile = repository.resolve_including_disabled(character)
    typer.echo(f"Selected profile: {profile.character_id} ({profile.character_name})")
    if not yes and not typer.confirm("Delete this local refresh token and profile?", default=False):
        typer.echo("Revocation cancelled; no local data changed.")
        raise typer.Exit()
    # CCP revocation availability varies; this local action is deliberately explicit and scoped.
    KeyringTokenStore().delete(profile.character_id)
    repository.delete(profile.character_id)
    typer.echo("Deleted only the selected local secret and profile.")


def main() -> None:
    """Console-script entrypoint."""
    app()


if __name__ == "__main__":
    main()
