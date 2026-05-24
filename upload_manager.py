"""
Upload Manager with Retry Logic and Error Handling
Handles file uploads to OneDrive with automatic retry and email notifications
"""

import os
import time
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import Optional, Callable, Dict, Any
import logging

from graph_api import GraphAPIClient


class UploadManager:
    """
    Manages uploads with retry logic, error handling, and notifications.
    """

    def __init__(self,
                 graph_client: GraphAPIClient,
                 max_retries: int = 3,
                 email_config: Optional[Dict[str, str]] = None):
        """
        Initialize upload manager.

        Args:
            graph_client: GraphAPIClient instance
            max_retries: Number of retry attempts
            email_config: Dict with keys: 'smtp_server', 'from_email', 'to_email', 'password'
        """
        self.graph_client = graph_client
        self.max_retries = max_retries
        self.email_config = email_config or self._get_email_config()
        self.logger = logging.getLogger(__name__)

        # Track upload history for reporting
        self.upload_history = []

    def _get_email_config(self) -> Dict[str, str]:
        """
        Get email config from environment variables.

        Expected env vars:
        - SMTP_SERVER (e.g., smtp.gmail.com)
        - SMTP_PORT (e.g., 587)
        - SENDER_EMAIL
        - SENDER_PASSWORD
        - RECIPIENT_EMAIL
        """
        return {
            'smtp_server': os.getenv('SMTP_SERVER', 'smtp.gmail.com'),
            'smtp_port': int(os.getenv('SMTP_PORT', '587')),
            'from_email': os.getenv('SENDER_EMAIL'),
            'password': os.getenv('SENDER_PASSWORD'),
            'to_email': os.getenv('RECIPIENT_EMAIL', 'cskarinka@gmail.com')
        }

    def upload_with_retry(self,
                          upload_func: Callable,
                          file_path: str,
                          onedrive_path: str,
                          file_name: Optional[str] = None) -> bool:
        """
        Execute upload with automatic retry logic.

        Args:
            upload_func: Function to call (e.g., graph_client.upload_file)
            file_path: Local file path
            onedrive_path: OneDrive destination path
            file_name: Optional file name override

        Returns:
            True if successful, False if all retries failed
        """
        errors = []

        for attempt in range(1, self.max_retries + 1):
            try:
                self.logger.info(f"Upload attempt {attempt}/{self.max_retries}: {file_path}")

                # Execute upload
                result = upload_func(file_path, onedrive_path, file_name)

                # Log success
                record = {
                    'file': file_path,
                    'destination': onedrive_path,
                    'status': 'success',
                    'attempt': attempt,
                    'timestamp': datetime.utcnow().isoformat(),
                    'result': result
                }
                self.upload_history.append(record)
                self.logger.info(f"✓ Upload successful on attempt {attempt}")
                return True

            except Exception as e:
                error_msg = str(e)
                errors.append({
                    'attempt': attempt,
                    'error': error_msg,
                    'timestamp': datetime.utcnow().isoformat()
                })

                self.logger.warning(f"✗ Attempt {attempt} failed: {error_msg}")

                # Exponential backoff: 2^attempt seconds (2, 4, 8 seconds)
                if attempt < self.max_retries:
                    wait_time = 2 ** attempt
                    self.logger.info(f"Retrying in {wait_time}s...")
                    time.sleep(wait_time)

        # All retries failed
        record = {
            'file': file_path,
            'destination': onedrive_path,
            'status': 'failed',
            'attempts': self.max_retries,
            'timestamp': datetime.utcnow().isoformat(),
            'errors': errors
        }
        self.upload_history.append(record)

        return False

    def send_failure_email(self,
                           subject: str,
                           failed_uploads: list,
                           execution_log: Optional[str] = None) -> bool:
        """
        Send email notification of upload failures.

        Args:
            subject: Email subject
            failed_uploads: List of failed upload records
            execution_log: Optional execution log text

        Returns:
            True if email sent successfully, False otherwise
        """
        if not self.email_config.get('from_email'):
            self.logger.warning("Email config incomplete - skipping notification")
            return False

        try:
            # Build email body
            html_body = self._build_email_html(failed_uploads, execution_log)

            # Create message
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = self.email_config['from_email']
            msg['To'] = self.email_config['to_email']

            msg.attach(MIMEText(html_body, 'html'))

            # Send
            with smtplib.SMTP(self.email_config['smtp_server'],
                             self.email_config['smtp_port']) as server:
                server.starttls()
                server.login(
                    self.email_config['from_email'],
                    self.email_config['password']
                )
                server.send_message(msg)

            self.logger.info(f"✓ Failure notification sent to {self.email_config['to_email']}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to send email: {str(e)}")
            return False

    def _build_email_html(self, failed_uploads: list, execution_log: Optional[str] = None) -> str:
        """Build HTML email body."""
        html = f"""
        <html>
            <body style="font-family: Arial, sans-serif; color: #333;">
                <h2 style="color: #d32f2f;">RingCentral OneDrive Upload Failed</h2>

                <p><strong>Timestamp:</strong> {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}</p>

                <h3>Failed Uploads ({len(failed_uploads)}):</h3>
                <ul>
        """

        for upload in failed_uploads:
            file_name = upload.get('file', 'Unknown').split('/')[-1]
            html += f"<li><strong>{file_name}</strong><br/>"
            html += f"Destination: {upload.get('destination', 'Unknown')}<br/>"

            if upload.get('errors'):
                html += "Errors:<ul>"
                for err in upload['errors']:
                    html += f"<li>Attempt {err['attempt']}: {err['error']}</li>"
                html += "</ul>"

            html += "</li>"

        html += """
                </ul>

                <h3>Next Steps:</h3>
                <ol>
                    <li>Check Azure/OneDrive credentials in Railway environment variables</li>
                    <li>Verify refresh token is still valid</li>
                    <li>Test health endpoint: <code>curl https://web-production-7ca12.up.railway.app/health</code></li>
                    <li>Review Railway logs for full error details</li>
                    <li>Retry manually: <code>curl -X POST https://web-production-7ca12.up.railway.app/run-daily-task</code></li>
                </ol>
        """

        if execution_log:
            html += f"""
                <h3>Execution Log:</h3>
                <pre style="background: #f5f5f5; padding: 10px; overflow-x: auto;">
{execution_log[:2000]}
                </pre>
            """

        html += """
            </body>
        </html>
        """

        return html

    def get_upload_report(self) -> str:
        """
        Generate a summary report of all uploads.

        Returns:
            Report string
        """
        if not self.upload_history:
            return "No uploads recorded."

        successful = [u for u in self.upload_history if u['status'] == 'success']
        failed = [u for u in self.upload_history if u['status'] == 'failed']

        report = f"""
Upload Report
=============
Timestamp: {datetime.utcnow().isoformat()}
Total: {len(self.upload_history)}
Successful: {len(successful)}
Failed: {len(failed)}

"""

        if successful:
            report += "Successful Uploads:\n"
            for u in successful:
                report += f"  ✓ {u['file']} → {u['destination']} (attempt {u['attempt']})\n"

        if failed:
            report += "\nFailed Uploads:\n"
            for u in failed:
                report += f"  ✗ {u['file']} → {u['destination']}\n"
                for err in u['errors']:
                    report += f"    Attempt {err['attempt']}: {err['error']}\n"

        return report
