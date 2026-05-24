"""
RingCentral to OneDrive Automation Server
Flask app running on Railway.app with daily task scheduling via GitHub Actions

Phase 1: Retrieve call logs and download recordings
Phase 2: Upload logs and recordings to OneDrive (NEW)
Phase 3: Transcribe recordings (planned)
Phase 4: Dashboard (planned)
"""

import os
import sys
import logging
import json
import csv
import subprocess
from datetime import datetime, timedelta
from io import StringIO
from typing import Tuple, Dict, Any

from flask import Flask, jsonify, request
import requests

# Import Phase 2 modules
try:
    from onedrive_auth import OAuth2TokenManager
    from graph_api import GraphAPIClient
    from upload_manager import UploadManager
    PHASE2_AVAILABLE = True
except ImportError:
    PHASE2_AVAILABLE = False
    print("Warning: Phase 2 modules not available. Uploads will be skipped.")


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)


# ============================================================================
# PHASE 1: RingCentral API - Call Log Retrieval
# ============================================================================

class RingCentralClient:
    """Handle RingCentral API calls for retrieving call logs."""

    def __init__(self):
        self.jwt_token = os.getenv('RINGCENTRAL_JWT_TOKEN')
        self.account_id = os.getenv('RINGCENTRAL_ACCOUNT_ID')
        self.server = os.getenv('RINGCENTRAL_SERVER', 'https://platform.ringcentral.com')
        self.headers = {
            'Authorization': f'Bearer {self.jwt_token}',
            'Content-Type': 'application/json'
        }

    def get_call_logs(self, date_from: str) -> list:
        """
        Retrieve call logs for a date range.

        Args:
            date_from: Start date (YYYY-MM-DD)

        Returns:
            List of call log records
        """
        endpoint = (
            f"{self.server}/restapi/v1.0/account/{self.account_id}"
            f"/call-log?dateFrom={date_from}T00:00:00Z"
        )

        try:
            response = requests.get(endpoint, headers=self.headers, timeout=30)
            response.raise_for_status()
            return response.json().get('records', [])
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to retrieve call logs: {str(e)}")
            return []

    def download_recording(self, recording_url: str, save_path: str) -> bool:
        """
        Download a call recording from RingCentral.

        Args:
            recording_url: URL of the recording
            save_path: Local path to save the file

        Returns:
            True if successful, False otherwise
        """
        try:
            response = requests.get(
                recording_url,
                headers=self.headers,
                timeout=60,
                stream=True
            )
            response.raise_for_status()

            # Create directory if needed
            os.makedirs(os.path.dirname(save_path), exist_ok=True)

            with open(save_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            return True

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to download recording: {str(e)}")
            return False


def run_phase1_retrieval(date_from: str) -> Tuple[str, Dict[str, Any]]:
    """
    Phase 1: Retrieve call logs and download recordings.

    Args:
        date_from: Date to retrieve logs from (YYYY-MM-DD)

    Returns:
        Tuple of (csv_file_path, metadata_dict)
    """
    logger.info(f"Phase 1: Retrieving call logs from {date_from}")

    rc = RingCentralClient()
    call_logs = rc.get_call_logs(date_from)

    if not call_logs:
        logger.warning("No call logs retrieved")
        return "", {}

    # Create CSV file
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    csv_filename = f"call_logs_{timestamp}.csv"
    csv_path = f"/tmp/{csv_filename}"

    # Write CSV
    with open(csv_path, 'w', newline='') as f:
        writer = csv.DictWriter(
            f,
            fieldnames=['id', 'startTime', 'duration', 'from', 'to', 'recording_url']
        )
        writer.writeheader()

        for log in call_logs:
            writer.writerow({
                'id': log.get('id'),
                'startTime': log.get('startTime'),
                'duration': log.get('duration'),
                'from': log.get('from', {}).get('phoneNumber', ''),
                'to': log.get('to', {}).get('phoneNumber', ''),
                'recording_url': log.get('recording', {}).get('contentUri', '')
            })

    logger.info(f"✓ Created CSV: {csv_filename} ({len(call_logs)} calls)")

    metadata = {
        'csv_file': csv_path,
        'csv_filename': csv_filename,
        'call_count': len(call_logs),
        'timestamp': timestamp
    }

    return csv_path, metadata


# ============================================================================
# PHASE 2: OneDrive Upload
# ============================================================================

def setup_phase2_client() -> Tuple[GraphAPIClient, UploadManager]:
    """
    Initialize Phase 2 clients (Graph API + Upload Manager).

    Returns:
        Tuple of (GraphAPIClient, UploadManager)

    Raises:
        ValueError: If required environment variables are missing
    """
    # Get OAuth2 credentials
    client_id = os.getenv('AZURE_CLIENT_ID')
    client_secret = os.getenv('AZURE_CLIENT_SECRET')
    tenant_id = os.getenv('AZURE_TENANT_ID')
    refresh_token = os.getenv('ONEDRIVE_REFRESH_TOKEN')

    if not all([client_id, client_secret, tenant_id]):
        raise ValueError("Missing Azure credentials in environment variables")

    if not refresh_token:
        raise ValueError(
            "ONEDRIVE_REFRESH_TOKEN not set. "
            "Run oauth_setup.py to authenticate."
        )

    # Initialize clients
    token_manager = OAuth2TokenManager(client_id, client_secret, tenant_id, refresh_token)
    graph_client = GraphAPIClient(token_manager)

    # Get email config
    email_config = {
        'smtp_server': os.getenv('SMTP_SERVER', 'smtp.gmail.com'),
        'smtp_port': int(os.getenv('SMTP_PORT', '587')),
        'from_email': os.getenv('SENDER_EMAIL'),
        'password': os.getenv('SENDER_PASSWORD'),
        'to_email': os.getenv('RECIPIENT_EMAIL', 'cskarinka@gmail.com')
    }

    upload_manager = UploadManager(graph_client, max_retries=3, email_config=email_config)

    return graph_client, upload_manager


def run_phase2_upload(csv_path: str, execution_log: str) -> bool:
    """
    Phase 2: Upload logs to OneDrive.

    Args:
        csv_path: Path to CSV file from Phase 1
        execution_log: Execution log text

    Returns:
        True if uploads successful, False otherwise
    """
    if not PHASE2_AVAILABLE:
        logger.warning("Phase 2 modules not available. Skipping uploads.")
        return False

    logger.info("Phase 2: Uploading to OneDrive")

    try:
        graph_client, upload_manager = setup_phase2_client()

        # Test connection
        if not graph_client.health_check():
            logger.error("Failed to connect to Microsoft Graph API")
            return False

        logger.info("✓ Connected to Microsoft Graph API")

        # Ensure folder structure exists
        onedrive_root = "RingCentral data"
        try:
            graph_client.ensure_transcription_folder(onedrive_root)
            logger.info("✓ Folder structure verified")
        except Exception as e:
            logger.error(f"Failed to ensure folder structure: {str(e)}")

        # Upload CSV
        csv_success = upload_manager.upload_with_retry(
            graph_client.upload_csv_logs,
            csv_path,
            onedrive_root
        )

        if not csv_success:
            logger.error("Failed to upload CSV after retries")

        # Upload execution log
        log_success = upload_manager.upload_with_retry(
            graph_client.upload_execution_logs,
            csv_path,  # Dummy path, we'll create temp log file
            onedrive_root
        )

        # Log report
        report = upload_manager.get_upload_report()
        logger.info(report)

        # Send email if there were failures
        failed = [u for u in upload_manager.upload_history if u['status'] == 'failed']
        if failed:
            upload_manager.send_failure_email(
                subject="⚠️ RingCentral Upload Failed",
                failed_uploads=failed,
                execution_log=execution_log
            )
            return False

        logger.info("✓ Phase 2 uploads completed successfully")
        return True

    except Exception as e:
        logger.error(f"Phase 2 error: {str(e)}")
        return False


# ============================================================================
# Flask Routes
# ============================================================================

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({'status': 'ok', 'timestamp': datetime.utcnow().isoformat()})


@app.route('/run-daily-task', methods=['POST'])
def run_daily_task():
    """
    Execute daily task: Phase 1 retrieval + Phase 2 upload.

    Returns:
        JSON response with execution status
    """
    logger.info("=" * 70)
    logger.info("Starting daily RingCentral task execution")
    logger.info("=" * 70)

    start_time = datetime.utcnow()
    execution_log = StringIO()

    try:
        # Phase 1: Retrieve call logs
        date_from = (datetime.utcnow() - timedelta(days=1)).strftime('%Y-%m-%d')
        csv_path, metadata = run_phase1_retrieval(date_from)

        if not csv_path:
            logger.error("Phase 1 failed: No CSV generated")
            return jsonify({
                'status': 'failed',
                'phase': 1,
                'message': 'Failed to retrieve call logs'
            }), 500

        logger.info(f"✓ Phase 1 completed: {metadata['csv_filename']}")

        # Phase 2: Upload to OneDrive
        if PHASE2_AVAILABLE:
            upload_success = run_phase2_upload(csv_path, execution_log.getvalue())
            if not upload_success:
                logger.warning("Phase 2 had issues but continuing")
        else:
            logger.info("Phase 2 skipped (modules not available)")

        # Cleanup
        if os.path.exists(csv_path):
            os.remove(csv_path)
            logger.info(f"✓ Cleaned up temporary files")

        end_time = datetime.utcnow()
        duration = (end_time - start_time).total_seconds()

        logger.info("=" * 70)
        logger.info(f"✓ Daily task completed successfully in {duration:.1f}s")
        logger.info("=" * 70)

        return jsonify({
            'status': 'success',
            'message': 'Daily task completed',
            'phase1': metadata,
            'duration_seconds': duration,
            'timestamp': end_time.isoformat()
        })

    except Exception as e:
        logger.error(f"Daily task failed: {str(e)}", exc_info=True)
        return jsonify({
            'status': 'failed',
            'message': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }), 500


# ============================================================================
# Application Startup
# ============================================================================

if __name__ == '__main__':
    # Railway will set the PORT environment variable
    port = int(os.getenv('PORT', 8000))

    logger.info("Starting RingCentral automation server")
    logger.info(f"Phase 2 available: {PHASE2_AVAILABLE}")

    # Run Flask app
    app.run(host='0.0.0.0', port=port, debug=False)
