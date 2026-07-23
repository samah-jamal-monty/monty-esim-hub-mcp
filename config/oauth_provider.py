"""OAuth 2.1 authorization server that passes the user's Client Secret through as their token.

Claude (Desktop and claude.ai custom connectors) authenticates remote MCP servers via
OAuth: it discovers /.well-known/oauth-authorization-server, runs an authorization-code +
PKCE flow, and then sends the resulting access token as a bearer token on every MCP request.

This server is multi-tenant: each user's credential IS their mm-hub API key. The user
enters any Client ID and their mm-hub API key as the Client Secret in Claude's connector
Advanced settings. The flow auto-approves, and the token endpoint issues that same secret
back as the access token, so tools that read the bearer via get_token(ctx) forward it to
the mm hub. The server does not validate the key itself — the OAuth handshake always
succeeds, and an invalid key simply fails later at the mm-hub call.
"""

import secrets
import time
from contextvars import ContextVar

from fastmcp.server.auth import OAuthProvider
from mcp.server.auth.handlers.token import TokenHandler
from mcp.server.auth.middleware.client_auth import ClientAuthenticator
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.server.auth.routes import TOKEN_PATH, cors_middleware
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl
from starlette.routing import Route

# Claude's OAuth callback endpoints (Desktop and web both use these)
CLAUDE_REDIRECT_URIS = [
    AnyUrl("https://claude.ai/api/mcp/auth_callback"),
    AnyUrl("https://claude.com/api/mcp/auth_callback"),
]

AUTH_CODE_TTL_SECONDS = 300

# The plaintext client_secret from the current /token request. Set by
# SecretCapturingAuthenticator and read by exchange_authorization_code, which both
# run inside the same request task.
_request_client_secret: ContextVar[str | None] = ContextVar("request_client_secret", default=None)


class SecretCapturingAuthenticator(ClientAuthenticator):
    """Captures the plaintext client_secret so it can be issued as the access token.

    Secret comparison in the parent class is skipped because get_client always returns
    a client with client_secret=None — any secret is accepted by design.
    """

    async def authenticate(self, client_id: str, client_secret: str | None) -> OAuthClientInformationFull:
        _request_client_secret.set(client_secret)
        return await super().authenticate(client_id, client_secret)


class EsimHubOAuthProvider(OAuthProvider):
    """Stateless pass-through OAuth provider for a multi-tenant MCP server.

    Any client_id/client_secret pair is accepted; the secret is echoed back as the
    access token. Dynamic Client Registration is disabled, so users must fill in the
    Client ID and Client Secret fields in Claude's connector Advanced settings.
    """

    def __init__(self, base_url: str):
        super().__init__(base_url=base_url)
        self._codes: dict[str, AuthorizationCode] = {}

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        # Every client_id "exists"; client_secret=None makes ClientAuthenticator
        # accept whatever secret the user typed into Claude
        return OAuthClientInformationFull(
            client_id=client_id,
            client_secret=None,
            redirect_uris=CLAUDE_REDIRECT_URIS,
        )

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        raise NotImplementedError("Dynamic client registration is disabled")

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        # No consent page: approve immediately and redirect back to Claude
        now = time.time()
        self._codes = {c: v for c, v in self._codes.items() if v.expires_at > now}

        code = secrets.token_urlsafe(32)
        self._codes[code] = AuthorizationCode(
            code=code,
            client_id=client.client_id,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            scopes=params.scopes or [],
            expires_at=now + AUTH_CODE_TTL_SECONDS,
            code_challenge=params.code_challenge,
            resource=params.resource,
        )
        return construct_redirect_uri(str(params.redirect_uri), code=code, state=params.state)

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        code = self._codes.get(authorization_code)
        if code is None or code.client_id != client.client_id or code.expires_at <= time.time():
            return None
        return code

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        # Single-use: the PKCE challenge was already verified by the token handler
        self._codes.pop(authorization_code.code, None)

        secret = _request_client_secret.get()
        if not secret:
            raise TokenError(
                "invalid_request",
                "client_secret is required: enter your mm-hub API key as the OAuth Client Secret",
            )
        # The user's secret IS their mm-hub API key; issue it back as the access token
        return OAuthToken(access_token=secret, token_type="Bearer")

    async def load_access_token(self, token: str) -> AccessToken | None:
        # Pass-through: any bearer token is accepted here and forwarded to the mm hub,
        # which is the actual authorizer — an invalid key fails at the mm-hub call
        if not token:
            return None
        return AccessToken(token=token, client_id="esim-hub-user", scopes=[], expires_at=None)

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        return None

    async def exchange_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]
    ) -> OAuthToken:
        # Access tokens never expire, so refresh is never needed
        raise TokenError("unsupported_grant_type", "Refresh tokens are not supported")

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        pass

    def get_routes(self, mcp_path=None, mcp_endpoint=None) -> list[Route]:
        # Rebuild the /token route with the capturing authenticator so the plaintext
        # client_secret is available to exchange_authorization_code
        routes = super().get_routes(mcp_path, mcp_endpoint)
        token_handler = TokenHandler(self, SecretCapturingAuthenticator(self))
        for i, route in enumerate(routes):
            if isinstance(route, Route) and route.path == TOKEN_PATH:
                routes[i] = Route(
                    TOKEN_PATH,
                    endpoint=cors_middleware(token_handler.handle, ["POST", "OPTIONS"]),
                    methods=["POST", "OPTIONS"],
                )
        return routes
