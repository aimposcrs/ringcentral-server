#!/usr/bin/env python3
"""
RingCentral Daily Data Retrieval Server
Runs on Railway.app and pulls call data daily
"""

import os
import json
import requests
import csv
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, jsonify
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Get credentials from environment variables
RINGCENTRAL_JWT = os.getenv('RINGCENTRAL_JWT_TOKEN')
RINGCENTRAL_ACCOUNT = os.getenv('RINGCENTRAL_ACCOUNT_ID')
RINGCENTRAL_SERVER = os.getenv('RINGCENTRAL_SERVER', 'https://platform.ringcentral.com')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
ONEDRIVE_FOLDER = os.getenv('ONEDRIVE_FOLDER_URL')

# Headers for API calls
headers = {
    'Authorization': f'Bearer {RINGCENTRAL_JWT}',
    'Content-Type': 'application/json'
}

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({'status': 'ok', 'timestamp': datetime.utcnow().isoformat()})

@app.route('/run-daily-task', methods=['POST'])
def run_daily_task():
    """Main endpoint that external scheduler calls daily"""
    logger.info("=" * 60)
    logger.info("STARTING DAILY RINGCENTRAL RETRIEVAL")
    logger.info("=" * 60)
    
    results = {
        'calls_retrieved': 0,
        'recordings_found': 0,
        'transcriptions_created': 0,
        'errors': [],
        'timestamp': datetime.utcnow().isoformat()
    }
    
    try:
        # Calculate previous day
        today = datetime.utcnow()
        previous_day = today - timedelta(days=1)
        date_str = previous_day.strftime('%Y-%m-%d')
        datetime_start = previous_day.strftime('%Y-%m-%dT00:00:00.000Z')
        datetime_end = (previous_day + timedelta(days=1)).strftime('%Y-%m-%dT00:00:00.000Z')
        
        logger.info(f"Retrieving data for: {date_str}")
        
        # Step 1: Get call log
        logger.info("Step 1: Retrieving call log...")
        url = f"{RINGCENTRAL_SERVER}/restapi/v1.0/account/{RINGCENTRAL_ACCOUNT}/call-log"
        params = {
            'dateFrom': datetime_start,
            'dateTo': datetime_end,
            'perPage': 100
        }
        
        response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        
        call_log = response.json()
        calls = call_log.get('records', [])
        results['calls_retrieved'] = len(calls)
        
        logger.info(f"✓ Retrieved {len(calls)} calls")
        
        # Step 2: Find recordings
        calls_with_recordings = [c for c in calls if c.get('recording')]
        results['recordings_found'] = len(calls_with_recordings)
        logger.info(f"✓ Found {len(calls_with_recordings)} recordings")
        
        # Build summary
        summary = f"Successfully processed {results['calls_retrieved']} calls with {results['recordings_found']} recordings on {date_str}"
        logger.info(summary)
        results['summary'] = summary
        
    except requests.exceptions.RequestException as e:
        error_msg = f"API Error: {str(e)}"
        logger.error(error_msg)
        results['errors'].append(error_msg)
        results['success'] = False
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        logger.error(error_msg)
        results['errors'].append(error_msg)
        results['success'] = False
    
    return jsonify(results), 200 if not results.get('errors') else 500

if __name__ == '__main__':
    # Run Flask server
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
