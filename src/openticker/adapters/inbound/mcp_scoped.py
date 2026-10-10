"""MCP over HTTP on openticker-serve (ADR 29 in docs/adr), for agent jobs.

The same tools as the stdio server, held to the caller's API key by the
same table REST uses (`scopes.py`). Every HTTP request needs a key, in
`X-API-Key` or as a bearer token; a job's key sees and calls only the tools
its scope allows. The stdio server is the user's own session, started by
their agent on their machine, and keeps the user's full authority.

Every tool call also runs as its MCP client (ADR 35): the name the client
gave when it connected ("claude-code", "codex"), which the tools record in
`triggered_by` as "mcp:<name>".
"""

import json
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from mcp.server.context import ServerRequestContext
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.context import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, InputRequiredResult, ListToolsResult, PaginatedRequestParams
from starlette.types import ASGIApp, Receive, Scope, Send

from openticker.adapters.inbound.scopes import TOOL_ROUTES, refusal
from openticker.core.pnl import client_name
from openticker.storage.sqlite import runs_repo
from openticker.storage.sqlite.api_keys_repo import StoredApiKey
from openticker.use_cases.api_keys import DEBRIEF_SCOPE_PREFIX, REVIEW_SCOPE_PREFIX, authenticate

MCP_PATH = "/mcp"
API_KEY_HEADER = "x-api-key"


def key_from_headers(headers: Mapping[str, str]) -> StoredApiKey | None:
    """The active key in `X-API-Key`, or in `Authorization: Bearer`."""
    key = headers.get(API_KEY_HEADER)
    if not key:
        scheme, _, token = headers.get("authorization", "").partition(" ")
        key = token if scheme.lower() == "bearer" else ""
    return authenticate(key.strip()) if key else None


_client: ContextVar[str | None] = ContextVar("openticker_mcp_client", default=None)


def current_client() -> str | None:
    """The MCP client whose tool call is running, by name; None when it gave none."""
    return _client.get()


_job: ContextVar[str | None] = ContextVar("openticker_mcp_job", default=None)
_JOB_SCOPES = (REVIEW_SCOPE_PREFIX, DEBRIEF_SCOPE_PREFIX)


def current_job() -> str | None:
    """The agent job's key scope ("review:<id>", "debrief:<date>") when an
    unattended job made the call: who did it (ADR 35). None otherwise."""
    return _job.get()


@contextmanager
def as_client(name: str | None, job: str | None = None) -> Iterator[None]:
    token, job_token = _client.set(name), _job.set(job)
    try:
        yield
    finally:
        _client.reset(token)
        _job.reset(job_token)


def _client_of(context: Context[Any, Any] | None) -> tuple[str | None, str | None]:
    """The client's name and version from its initialize handshake."""
    try:
        params = context.session.client_params if context is not None else None
    except ValueError:  # no request in flight
        return None, None
    info = params.client_info if params is not None else None
    if info is None or not info.name.strip():
        return None, None
    return client_name(info.name), info.version


def _strategy_of_run(run_id: str) -> str | None:
    run = runs_repo.find_run(run_id)
    return run.strategy_id if run is not None else None


def _tool_refusal(
    scope: str, tool: str, arguments: Mapping[str, object], *, listing: bool = False
) -> str | None:
    route = TOOL_ROUTES.get(tool)
    if route is None:
        return f"{tool} has no route, so no key but a full one may call it"
    method, path = route
    return refusal(scope, method, path, arguments, _strategy_of_run, whole_call=not listing)


class ScopedMCPServer(MCPServer):
    """An MCPServer whose HTTP callers see and call only what their key allows.
    A call without an HTTP request is the stdio session, the user's own.

    `on_client(name, transport, version, tool)` hears of every call from a
    named client."""

    on_client: Callable[[str, str, str | None, str], None] | None = None

    async def _handle_list_tools(
        self, ctx: ServerRequestContext[Any], params: PaginatedRequestParams | None
    ) -> ListToolsResult:
        listed = await super()._handle_list_tools(ctx, params)
        scope = _scope(ctx.request)
        if scope is None:
            return listed
        allowed = [
            tool
            for tool in listed.tools
            if _tool_refusal(scope, tool.name, {}, listing=True) is None
        ]
        return ListToolsResult(tools=allowed)

    async def call_tool(
        self, name: str, arguments: dict[str, Any], context: Context[Any, Any] | None = None
    ) -> CallToolResult | InputRequiredResult:
        request = None
        if context is not None:
            try:
                request = context.request_context.request
            except ValueError:
                request = None
        scope = _scope(request)
        if scope is not None:
            why = _tool_refusal(scope, name, arguments)
            if why is not None:
                raise ToolError(f"{name} refused: {why}")
        client, client_version = _client_of(context)
        if client is not None and self.on_client is not None:
            self.on_client(client, "stdio" if request is None else "http", client_version, name)
        job = scope if scope is not None and scope.startswith(_JOB_SCOPES) else None
        with as_client(client, job):  # sync tools run in a thread, which copies it
            return await super().call_tool(name, arguments, context)


def _scope(request: object) -> str | None:
    """The key's scope for an HTTP request; None for the stdio session. An
    HTTP request without a valid key never gets here (`with_mcp`), and is
    refused everything if it does."""
    if request is None:
        return None
    headers = getattr(request, "headers", None)
    stored = key_from_headers(headers) if headers is not None else None
    return stored.scope if stored is not None else "none"


class WithMcp:
    """openticker-serve's app with MCP at /mcp: a request there needs an
    API key, and is then served by `server` over streamable HTTP."""

    def __init__(self, api: ASGIApp, server: MCPServer) -> None:
        self._api = api
        self._server = server
        # Every request carries a key, which a page rebinding DNS doesn't have.
        self._mcp = server.streamable_http_app(
            streamable_http_path=MCP_PATH,
            stateless_http=True,
            json_response=True,
            transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            async with self._server.session_manager.run():
                await self._api(scope, receive, send)
            return
        if scope["type"] == "http" and scope["path"].rstrip("/") == MCP_PATH:
            headers = {
                k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]
            }
            if key_from_headers(headers) is None:
                await _unauthorized(send)
                return
            await self._mcp({**scope, "path": MCP_PATH}, receive, send)
            return
        await self._api(scope, receive, send)


async def _unauthorized(send: Send) -> None:
    body = json.dumps(
        {"detail": "missing or invalid API key: send one in X-API-Key or as a bearer token"}
    ).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [(b"content-type", b"application/json")],
        }
    )
    await send({"type": "http.response.body", "body": body})
