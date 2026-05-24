"""
OAuth2 Token Management for Microsoft Graph API
Handles token refresh, storage, and lifecycle management
"""

import os
import time
import json
from datetime import datetime, timedelta
import requests
from typing import Optional, Dict, Any


class OAuth2TokenManager:
    """
    Manages OAuth2 tokens for Microsoft Graph API.
    Handles refresh token exchange, access token caching, and expiration.
    """

    def __init__(self,
                 client_id: str,
                 client_secret: str,
                 tenant_id: str,
                 refresh_token: Optional[str] = None):
        """
        Initialize token manager.

        Args:
            client_id: Azure app client ID
            client_secret: Azure app client secret
            tenant_id: Azure tenant ID
            refresh_token: Existing refresh token (from environment or initial auth)
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.tenant_id = tenant_id
        self.refresh_token = refresh_token or os.getenv('ONEDRIVE_REFRESH_TOKEN')

        # Token cache
        self.access_token = None
        self.token_expiry = None

        # Microsoft endpoints
        self.auth_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0"
        self.token_endpoint = f"{self.auth_url}/token"

    def get_access_token(self) -> str:
        """
        Get valid access token. Refreshes if expired.

        Returns:
            Valid access token string

        Raises:
            ValueError: If refresh token is not available
        """
        if not self.refresh_token:
            raise ValueError(
                "No refresh token available. Run OAuth2 setup to authenticate."
            )

        # Check if cached token is still valid (with 5-min buffer)
        if self.access_token and self.token_expiry:
            if datetime.utcnow() < (self.token_expiry - timedelta(minutes=5)):
                return self.access_token

        # Token expired or not cached - refresh it
        self._refresh_access_token()
        return self.access_token

    def _refresh_access_token(self) -> None:
        """
        Exchange refresh token for new access token.
        Updates self.access_token and self.token_expiry

        Raises:
            Exception: If token refresh fails
        """
        data = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'refresh_token': self.refresh_token,
            'grant_type': 'refresh_token',
            'scope': 'https://graph.microsoft.com/.default'
        }

        try:
            response = requests.post(self.token_endpoint, data=data)
            response.raise_for_status()

            token_data = response.json()
            self.access_token = token_data['access_token']

            # Calculate expiry: now + expires_in seconds, minus 5-min buffer
            expires_in = token_data.get('expires_in', 3600)
            self.token_expiry = datetime.utcnow() + timedelta(seconds=expires_in)

            # Update refresh token if a new one was returned
            if 'refresh_token' in token_data:
                self.refresh_token = token_data['refresh_token']

        except requests.exceptions.RequestException as e:
            raise Exception(f"Failed to refresh access token: {str(e)}")

    def get_auth_code_url(self, redirect_uri: str, scopes: Optional[list] = None) -> str:
        """
        Generate OAuth2 authorization URL for user to visit.
        Used for initial one-time authentication.

        Args:
            redirect_uri: Where to redirect after auth (e.g., http://localhost:8000/callback)
            scopes: List of scopes (defaults to Graph default)

        Returns:
            Authorization URL to visit in browser
        """
        if scopes is None:
            scopes = [
                'https://graph.microsoft.com/.default',
                'offline_access'  # This gets us a refresh token
            ]

        scope_str = ' '.join(scopes)

        params = {
            'client_id': self.client_id,
            'redirect_uri': redirect_uri,
            'response_type': 'code',
            'scope': scope_str,
            'response_mode': 'query',
            'prompt': 'consent'  # Force consent screen
        }

        from urllib.parse import urlencode
        return f"{self.auth_url}/authorize?{urlencode(params)}"

    def exchange_code_for_tokens(self, auth_code: str, redirect_uri: str) -> Dict[str, Any]:
        """
        Exchange authorization code for tokens.
        Called after user authenticates via get_auth_code_url().

        Args:
            auth_code: Code returned from authorization endpoint
            redirect_uri: Same redirect_uri used in get_auth_code_url

        Returns:
            Dict with 'access_token' and 'refresh_token'

        Raises:
            Exception: If code exchange fails
        """
        data = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'code': auth_code,
            'redirect_uri': redirect_uri,
            'grant_type': 'authorization_code',
            'scope': 'https://graph.microsoft.com/.default offline_access'
        }

        try:
            response = requests.post(self.token_endpoint, data=data)
            response.raise_for_status()

            token_data = response.json()

            # Cache the tokens
            self.access_token = token_data['access_token']
            self.refresh_token = token_data['refresh_token']

            expires_in = token_data.get('expires_in', 3600)
            self.token_expiry = datetime.utcnow() + timedelta(seconds=expires_in)

            return {
                'access_token': self.access_token,
                'refresh_token': self.refresh_token,
                'expires_in': expires_in
            }

        except requests.exceptions.RequestException as e:
            raise Exception(f"Failed to exchange code for tokens: {str(e)}")
