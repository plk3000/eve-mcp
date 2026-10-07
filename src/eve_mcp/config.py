"""Non-secret runtime configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True)
class Settings:
    """Configuration with stdio default and only self-hosted app identifiers."""

    transport: str = "stdio"
    http_host: str = "127.0.0.1"
    data_dir: Path = Path.home() / ".local" / "share" / "eve-mcp"
    client_id: str | None = None
    redirect_uri: str = "http://127.0.0.1:8080/callback"

    @classmethod
    def from_environment(cls) -> Settings:
        return cls(
            data_dir=Path(
                os.environ.get("EVE_MCP_DATA_DIR", Path.home() / ".local" / "share" / "eve-mcp")
            ),
            client_id=os.environ.get("EVE_MCP_CLIENT_ID") or None,
            redirect_uri=os.environ.get("EVE_MCP_REDIRECT_URI", "http://127.0.0.1:8080/callback"),
        )

    def require_sso_configuration(self) -> tuple[str, str]:
        if not self.client_id:
            raise ValueError(
                "EVE_MCP_CLIENT_ID must identify your self-hosted EVE developer application."
            )
        try:
            callback = urlparse(self.redirect_uri)
            is_loopback_callback = (
                callback.scheme == "http"
                and callback.hostname == "127.0.0.1"
                and callback.port is not None
                and bool(callback.path)
            )
        except ValueError:
            is_loopback_callback = False
        if not is_loopback_callback:
            raise ValueError("EVE_MCP_REDIRECT_URI must be an http://127.0.0.1:<port>/ callback.")
        return self.client_id, self.redirect_uri
