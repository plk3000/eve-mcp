"""One-shot loopback callback receiver for the operator-run SSO command."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from urllib.parse import parse_qs, urlparse

from eve_mcp.auth.sso import SsoError


class LoopbackCallback:
    """Binds an explicit 127.0.0.1 callback URI and accepts one request only."""

    def __init__(self, redirect_uri: str) -> None:
        parsed = urlparse(redirect_uri)
        if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.port is None:
            raise ValueError("SSO callback must use an explicit http://127.0.0.1:<port>/ URI.")
        self.host, self.port, self.path = parsed.hostname, parsed.port, parsed.path or "/"

    @staticmethod
    def parse_query(query: str) -> dict[str, str]:
        parsed: Mapping[str, list[str]] = parse_qs(query, strict_parsing=True)
        return {key: values[0] for key, values in parsed.items() if len(values) == 1}

    async def receive(self, timeout_seconds: float = 300) -> dict[str, str]:
        result: asyncio.Future[dict[str, str]] = asyncio.get_running_loop().create_future()

        async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                request = await reader.readline()
                target = request.decode("ascii", "replace").split(" ")[1]
                parsed = urlparse(target)
                if parsed.path != self.path:
                    raise SsoError("SSO callback path did not match; no profile was changed.")
                result.set_result(self.parse_query(parsed.query))
                body = b"Authorization received. You may close this page."
                writer.write(
                    b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 47\r\n\r\n"
                    + body
                )
                await writer.drain()
            except (IndexError, UnicodeDecodeError, ValueError, SsoError):
                if not result.done():
                    result.set_exception(SsoError("Invalid SSO callback; no profile was changed."))
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(handler, self.host, self.port)
        try:
            return await asyncio.wait_for(result, timeout_seconds)
        except TimeoutError as error:
            raise SsoError("Authorization callback timed out; no profile was changed.") from error
        finally:
            server.close()
            await server.wait_closed()
