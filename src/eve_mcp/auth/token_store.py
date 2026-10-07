"""Secret-store interfaces; refresh tokens never enter SQLite."""

from __future__ import annotations

from typing import Protocol


class MissingTokenError(LookupError):
    """Raised without including any token value."""


class TokenStore(Protocol):
    def get(self, character_id: str) -> str: ...
    def put(self, character_id: str, refresh_token: str) -> None: ...
    def delete(self, character_id: str) -> None: ...


class InMemoryTokenStore:
    """Test-only secret adapter, keyed by immutable character ID."""

    def __init__(self) -> None:
        self._tokens: dict[str, str] = {}

    def get(self, character_id: str) -> str:
        try:
            return self._tokens[character_id]
        except KeyError as error:
            raise MissingTokenError("No refresh token is available for this character.") from error

    def put(self, character_id: str, refresh_token: str) -> None:
        self._tokens[character_id] = refresh_token

    def delete(self, character_id: str) -> None:
        self._tokens.pop(character_id, None)


class KeyringTokenStore:
    """Desktop keyring adapter; import keyring only when configured."""

    service_name = "eve-mcp"

    @staticmethod
    def _key(character_id: str) -> str:
        return f"character/{character_id}/refresh-token"

    def get(self, character_id: str) -> str:
        import keyring

        value = keyring.get_password(self.service_name, self._key(character_id))
        if value is None:
            raise MissingTokenError("No refresh token is available for this character.")
        return value

    def put(self, character_id: str, refresh_token: str) -> None:
        import keyring

        keyring.set_password(self.service_name, self._key(character_id), refresh_token)

    def delete(self, character_id: str) -> None:
        import keyring

        try:
            keyring.delete_password(self.service_name, self._key(character_id))
        except keyring.errors.PasswordDeleteError:
            pass
