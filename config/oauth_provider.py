"""OAuth 2.1 authorization server that bridges Claude's OAuth flow to the eSIM Hub API key.

Claude (Desktop and claude.ai custom connectors) authenticates remote MCP servers via
OAuth: it discovers /.well-known/oauth-authorization-server, registers as a client (or
uses the client id/secret entered in the connector's Advanced settings), runs an
authorization-code + PKCE flow, and then sends the resulting access token as a bearer
token on every MCP request.

This provider auto-approves the authorization step (single-tenant server, no user login)
and issues the configured ESIM_HUB_API_KEY as the access token, so tools that read the
bearer token via get_token(ctx) keep receiving the mm-hub API key unchanged.
"""

import os
import secrets
import time

from fastmcp.server.auth import OAuthProvider
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.server.auth.settings import ClientRegistrationOptions
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl

# Claude's OAuth callback endpoints (Desktop and web both use these)
CLAUDE_REDIRECT_URIS = [
    AnyUrl("https://claude.ai/api/mcp/auth_callback"),
    AnyUrl("https://claude.com/api/mcp/auth_callback"),
]

AUTH_CODE_TTL_SECONDS = 300


class EsimHubOAuthProvider(OAuthProvider):
    """Minimal in-memory OAuth provider for a single-tenant MCP server.

    Supports both a pre-configured client (MCP_OAUTH_CLIENT_ID / MCP_OAUTH_CLIENT_SECRET,
    for Claude's Advanced settings fields) and Dynamic Client Registration (leave the
    fields blank in Claude). Authorization codes and DCR clients live in memory only;
    the static client and the access token survive restarts because both come from env.
    """

    def __init__(self, base_url: str):
        super().__init__(
            base_url=base_url,
            client_registration_options=ClientRegistrationOptions(enabled=True),
        )
        self._api_key = os.environ["ESIM_HUB_API_KEY"]
        self._clients: dict[str, OAuthClientInformationFull] = {}
        self._codes: dict[str, AuthorizationCode] = {}

        static_id = os.getenv("MCP_OAUTH_CLIENT_ID")
        static_secret = os.getenv("MCP_OAUTH_CLIENT_SECRET")
        if static_id and static_secret:
            self._clients[static_id] = OAuthClientInformationFull(
                client_id=static_id,
                client_secret=static_secret,
                redirect_uris=CLAUDE_REDIRECT_URIS,
            )

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return self._clients.get(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        self._clients[client_info.client_id] = client_info

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        # Single-tenant: no consent page, approve immediately and redirect back to Claude
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
        return OAuthToken(access_token=self._api_key, token_type="Bearer")

    async def load_access_token(self, token: str) -> AccessToken | None:
        if secrets.compare_digest(token, self._api_key):
            return AccessToken(token=token, client_id="esim-hub", scopes=[], expires_at=None)
        return None

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
        # The access token is the upstream API key; revocation is a no-op
        pass
