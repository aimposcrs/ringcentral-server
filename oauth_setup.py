#!/usr/bin/env python3
"""
OAuth2 Setup Script for RingCentral OneDrive Integration
Run this ONCE locally to authenticate and get a refresh token.

Usage:
    python oauth_setup.py

This script will:
1. Print an authorization URL
2. Ask you to visit that URL and authenticate in your browser
3. Extract the auth code from the redirect
4. Exchange it for a refresh token
5. Print the refresh token to paste into Railway environment variables
"""

import sys
import os
from urllib.parse import urlparse, parse_qs
from onedrive_auth import OAuth2TokenManager


def main():
    """Run OAuth2 setup flow."""

    # Get credentials from environment or .env
    client_id = os.getenv('AZURE_CLIENT_ID')
    client_secret = os.getenv('AZURE_CLIENT_SECRET')
    tenant_id = os.getenv('AZURE_TENANT_ID')

    if not all([client_id, client_secret, tenant_id]):
        print("ERROR: Missing Azure credentials!")
        print("\nRequired environment variables:")
        print("  AZURE_CLIENT_ID")
        print("  AZURE_CLIENT_SECRET")
        print("  AZURE_TENANT_ID")
        print("\nSet these in your .env file or shell environment, then retry.")
        sys.exit(1)

    print("=" * 70)
    print("RingCentral OneDrive OAuth2 Setup")
    print("=" * 70)

    # Initialize token manager
    manager = OAuth2TokenManager(client_id, client_secret, tenant_id)

    # Generate auth URL
    redirect_uri = "http://localhost:8080/callback"
    auth_url = manager.get_auth_code_url(
        redirect_uri,
        scopes=['https://graph.microsoft.com/.default', 'offline_access']
    )

    print(f"\n1. Click this link to authenticate:\n")
    print(f"   {auth_url}\n")

    print("2. You'll be taken to Microsoft login. Sign in with your account.")
    print("3. You'll see a consent screen. Click 'Accept'.")
    print("4. You'll be redirected to a URL that starts with 'http://localhost:8080/callback?code='")
    print("5. Copy the entire URL from your browser's address bar.\n")

    redirect_url = input("Paste the full redirect URL here: ").strip()

    try:
        # Extract auth code from redirect URL
        parsed = urlparse(redirect_url)
        params = parse_qs(parsed.query)

        if 'code' not in params:
            print("\nERROR: No authorization code found in URL!")
            print("Make sure you pasted the full redirect URL with ?code=...")
            sys.exit(1)

        auth_code = params['code'][0]
        print(f"\n✓ Auth code extracted: {auth_code[:20]}...\n")

        # Exchange code for tokens
        print("Exchanging code for tokens...")
        tokens = manager.exchange_code_for_tokens(auth_code, redirect_uri)

        print("\n" + "=" * 70)
        print("✓ SUCCESS! Here's your refresh token:")
        print("=" * 70)
        print(f"\nRefresh Token:\n{tokens['refresh_token']}\n")

        print("=" * 70)
        print("Next steps:")
        print("=" * 70)
        print("\n1. Go to Railway.app dashboard")
        print("2. Open your RingCentral project")
        print("3. Click 'Variables' tab")
        print("4. Add new variable: ONEDRIVE_REFRESH_TOKEN")
        print("5. Paste the refresh token above as the value")
        print("6. Click 'Deploy' to redeploy the server\n")

        print("The refresh token will be used to automatically refresh access tokens")
        print("each time the daily task runs. You won't need to do this setup again.\n")

    except Exception as e:
        print(f"\nERROR: {str(e)}")
        sys.exit(1)


if __name__ == '__main__':
    main()
