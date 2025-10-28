"""HTTP client with authentication support."""

import json
from pathlib import Path
from typing import Any

import httpx

from .models import AuthConfig, AuthMethod, QueryConfig


class HTTPClient:
    """HTTP client with configurable authentication.

    Supports context manager for proper resource cleanup.
    """

    def __init__(
        self,
        base_url: str,
        auth: AuthConfig,
        verify_ssl: bool = True,
        ca_bundle: str | None = None,
    ):
        """Initialize HTTP client.

        Args:
            base_url: Base URL for all requests
            auth: Authentication configuration
            verify_ssl: Whether to verify SSL certificates
            ca_bundle: Path to custom CA bundle file
        """
        self.base_url = base_url.rstrip("/")
        self.auth = auth

        # Configure SSL verification
        if ca_bundle:
            bundle_path = Path(ca_bundle)
            if not bundle_path.exists():
                raise ValueError(f"CA bundle file not found: {ca_bundle}")
            verify = ca_bundle
        elif verify_ssl:
            verify = True
        else:
            verify = False

        self.client = httpx.Client(
            verify=verify, timeout=None
        )  # Timeout set per-request

    def __enter__(self):
        """Enter context manager."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context manager and close client."""
        self.close()
        return False

    def _build_auth_headers(self) -> dict[str, str]:
        """Build authentication headers based on auth config."""
        headers = {}

        if self.auth.method == AuthMethod.BEARER:
            if self.auth.token:
                headers["Authorization"] = f"Bearer {self.auth.token.get_secret_value()}"
        elif self.auth.method in (AuthMethod.API_KEY, AuthMethod.HEADER):
            # API_KEY and HEADER are the same - just a custom header
            # Validation in AuthConfig ensures token and header_name are present
            if self.auth.header_name and self.auth.token:
                headers[self.auth.header_name] = self.auth.token.get_secret_value()

        return headers

    def request(self, query: QueryConfig) -> dict[str, Any]:
        """Make an HTTP request.

        Args:
            query: Query configuration

        Returns:
            Response as dictionary

        Raises:
            httpx.HTTPError: If request fails
            ValueError: If response is not JSON
        """
        # Build full URL - simplified
        url = f"{self.base_url}/{query.endpoint.lstrip('/')}"

        # Build headers
        headers = self._build_auth_headers()
        headers.update(query.headers)

        # Prepare request kwargs
        kwargs = {
            "headers": headers,
            "params": query.params,
            "timeout": query.timeout,
        }

        # Handle basic auth
        # Validation in AuthConfig ensures username and password are present
        if self.auth.method == AuthMethod.BASIC:
            if self.auth.password:
                kwargs["auth"] = (self.auth.username, self.auth.password.get_secret_value())
            else:
                raise ValueError("Basic auth requires password")

        # Handle body
        if query.body:
            if isinstance(query.body, dict):
                kwargs["json"] = query.body
            else:
                kwargs["data"] = query.body

        # Make request
        response = self.client.request(query.method, url, **kwargs)
        response.raise_for_status()

        # Parse JSON response
        try:
            return response.json()
        except json.JSONDecodeError as e:
            # Non-JSON responses are errors - be explicit
            raise ValueError(
                f"Expected JSON response but got: {response.text[:200]}"
            ) from e

    def close(self):
        """Close the HTTP client."""
        self.client.close()
