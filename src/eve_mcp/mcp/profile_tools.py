"""Safe profile MCP tool implementations."""

from __future__ import annotations

from typing import Any

from eve_mcp.profiles import ProfileRepository


class ProfileTools:
    def __init__(self, profiles: ProfileRepository) -> None:
        self.profiles = profiles

    def list_characters(self) -> dict[str, Any]:
        items = [self._safe(profile) for profile in self.profiles.list()]
        return {
            "items": items,
            "returned_count": len(items),
            "total_available": len(items),
            "truncated": False,
        }

    def status(self, character: str) -> dict[str, Any]:
        return self._safe(self.profiles.resolve_including_disabled(character))

    @staticmethod
    def _safe(profile: Any) -> dict[str, Any]:
        return {
            "character_id": profile.character_id,
            "character_name": profile.character_name,
            "enabled": profile.enabled,
            "granted_scopes": list(profile.granted_scopes),
            "token_expires_at": profile.token_expires_at.isoformat()
            if profile.token_expires_at
            else None,
            "last_successful_fetch_at": profile.last_successful_fetch_at.isoformat()
            if profile.last_successful_fetch_at
            else None,
            "last_authorization_status": profile.last_authorization_status,
        }
