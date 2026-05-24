"""
Microsoft Graph API Client for OneDrive Upload
Handles file and folder operations on OneDrive via Microsoft Graph
"""

import os
import json
import time
from typing import Optional, Dict, Any
from datetime import datetime
import requests
from onedrive_auth import OAuth2TokenManager


class GraphAPIClient:
    """
    Client for Microsoft Graph API operations on OneDrive.
    Manages file uploads, folder creation, and error handling.
    """

    def __init__(self, token_manager: OAuth2TokenManager):
        """
        Initialize Graph API client.

        Args:
            token_manager: OAuth2TokenManager instance for auth
        """
        self.token_manager = token_manager
        self.base_url = "https://graph.microsoft.com/v1.0"
        self.onedrive_root = "me/drive/root"

    def _get_headers(self) -> Dict[str, str]:
        """Get authorization headers with fresh access token."""
        access_token = self.token_manager.get_access_token()
        return {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }

    def create_folder(self, folder_name: str, parent_path: str = "") -> Dict[str, Any]:
        """
        Create a folder in OneDrive.

        Args:
            folder_name: Name of folder to create
            parent_path: Path in OneDrive (e.g., "RingCentral data" or empty for root)

        Returns:
            API response with folder metadata

        Raises:
            Exception: If folder creation fails
        """
        headers = self._get_headers()

        # Construct parent path
        if parent_path:
            # Try to navigate to parent path first
            parent_id = self._get_item_id(parent_path)
            if not parent_id:
                raise ValueError(f"Parent path not found: {parent_path}")
            endpoint = f"{self.base_url}/me/drive/items/{parent_id}/children"
        else:
            endpoint = f"{self.base_url}/{self.onedrive_root}/children"

        payload = {
            "name": folder_name,
            "folder": {}
        }

        try:
            response = requests.post(
                endpoint,
                headers=headers,
                json=payload
            )

            if response.status_code == 201:  # Created
                return response.json()
            elif response.status_code == 409:  # Conflict - folder already exists
                # Try to get the existing folder
                return self._get_item_id(f"{parent_path}/{folder_name}" if parent_path else folder_name)
            else:
                response.raise_for_status()

        except requests.exceptions.RequestException as e:
            raise Exception(f"Failed to create folder '{folder_name}': {str(e)}")

    def _get_item_id(self, item_path: str) -> Optional[str]:
        """
        Get the item ID for a file or folder at a given path.

        Args:
            item_path: Path like "RingCentral data" or "RingCentral data/transcriptions"

        Returns:
            Item ID or None if not found
        """
        headers = self._get_headers()

        # Use path-based search
        try:
            endpoint = f"{self.base_url}/me/drive/root:/{item_path}:"
            response = requests.get(endpoint, headers=headers)

            if response.status_code == 200:
                return response.json().get('id')
            return None

        except requests.exceptions.RequestException:
            return None

    def upload_file(self,
                    file_path: str,
                    onedrive_path: str,
                    file_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Upload a file to OneDrive.

        Args:
            file_path: Local file path
            onedrive_path: Destination path in OneDrive (e.g., "RingCentral data")
            file_name: Override file name (defaults to basename of file_path)

        Returns:
            API response with file metadata

        Raises:
            Exception: If upload fails
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        file_name = file_name or os.path.basename(file_path)
        headers = self._get_headers()

        # Get parent folder ID
        parent_id = self._get_item_id(onedrive_path)
        if not parent_id:
            raise ValueError(f"OneDrive path not found: {onedrive_path}")

        # Upload endpoint
        endpoint = f"{self.base_url}/me/drive/items/{parent_id}:/{file_name}:/content"

        try:
            with open(file_path, 'rb') as f:
                response = requests.put(
                    endpoint,
                    headers=headers,
                    data=f
                )

            if response.status_code in [200, 201]:
                return response.json()
            else:
                response.raise_for_status()

        except requests.exceptions.RequestException as e:
            raise Exception(f"Failed to upload '{file_name}' to '{onedrive_path}': {str(e)}")

    def upload_csv_logs(self, csv_file_path: str, onedrive_root_path: str = "RingCentral data") -> Dict[str, Any]:
        """
        Upload call logs CSV to OneDrive.

        Args:
            csv_file_path: Local path to CSV file
            onedrive_root_path: Root folder in OneDrive

        Returns:
            Upload result
        """
        file_name = os.path.basename(csv_file_path)
        return self.upload_file(csv_file_path, onedrive_root_path, file_name)

    def upload_execution_logs(self,
                              log_content: str,
                              onedrive_root_path: str = "RingCentral data") -> Dict[str, Any]:
        """
        Upload execution logs to OneDrive.

        Args:
            log_content: Log text content
            onedrive_root_path: Root folder in OneDrive

        Returns:
            Upload result
        """
        # Create a temporary log file
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        log_file_name = f"execution_log_{timestamp}.txt"

        # Get logs folder path
        logs_folder_path = f"{onedrive_root_path}/logs"

        # Ensure logs folder exists
        parent_id = self._get_item_id(onedrive_root_path)
        if parent_id:
            try:
                self.create_folder("logs", onedrive_root_path)
            except Exception:
                pass  # Folder might already exist

        # Upload the log file
        return self.upload_file(log_file_path, logs_folder_path, log_file_name)

    def ensure_transcription_folder(self, onedrive_root_path: str = "RingCentral data") -> str:
        """
        Ensure transcription folder structure exists in OneDrive.
        Creates: RingCentral data/transcriptions

        Args:
            onedrive_root_path: Root folder in OneDrive

        Returns:
            Folder ID of transcriptions folder
        """
        # Ensure root folder exists
        root_id = self._get_item_id(onedrive_root_path)
        if not root_id:
            raise ValueError(f"Root OneDrive path not found: {onedrive_root_path}")

        # Create transcriptions subfolder
        transcriptions_path = f"{onedrive_root_path}/transcriptions"
        trans_id = self._get_item_id(transcriptions_path)

        if not trans_id:
            result = self.create_folder("transcriptions", onedrive_root_path)
            trans_id = result.get('id')

        # Create subfolders for current and archive
        try:
            self.create_folder("current", transcriptions_path)
            self.create_folder("archive", transcriptions_path)
        except Exception:
            pass  # Folders might already exist

        return trans_id

    def health_check(self) -> bool:
        """
        Test connection to Microsoft Graph API.

        Returns:
            True if connection successful, False otherwise
        """
        try:
            headers = self._get_headers()
            response = requests.get(
                f"{self.base_url}/me/drive",
                headers=headers,
                timeout=5
            )
            return response.status_code == 200
        except Exception:
            return False
