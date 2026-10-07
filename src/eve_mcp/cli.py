"""Human-operated CLI; MCP tools never start login or mutate profiles."""

from __future__ import annotations

import asyncio
from typing import Annotated

import typer

from eve_mcp.auth.pkce import SCOPES
from eve_mcp.auth.sso import SsoClient, SsoWorkflow
from eve_mcp.auth.token_store import KeyringTokenStore
from eve_mcp.config import Settings
from eve_mcp.profiles import ProfileRepository

app = typer.Typer(help="Read-only, standalone EVE Online MCP server.")
auth_app = typer.Typer(help="Manage independently authorized EVE characters.")
app.add_typer(auth_app, name="auth")


def _repository() -> ProfileRepository:
    settings = Settings.from_environment()
    return ProfileRepository(settings.data_dir / "eve-mcp.db")


def _scope_text() -> str:
    return "\n".join(f"  {scope}" for scope in SCOPES)


@app.command()
def serve() -> None:
    """Run the MCP server over stdio; this does not open a network listener."""
    from eve_mcp.mcp.server import run_stdio

    run_stdio()


@auth_app.command("add")
def auth_add() -> None:
    """Start an operator-approved, loopback-only PKCE authorization flow."""
    settings = Settings.from_environment()
    typer.echo("The following exact read-only scopes will be requested:")
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
