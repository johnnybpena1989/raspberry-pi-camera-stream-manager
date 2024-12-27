import logging
import os
from flask import Flask, render_template, jsonify
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
import json
import time

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or "octoprint-stream-viewer-secret-key"

# Configure stream URLs - can be overridden by environment variables
DEFAULT_STREAM_URLS = [
    "http://10.0.0.15:8080/stream",
    "http://10.0.0.15:8081/stream",
    "http://10.0.0.15:8082/stream",
]

# Get stream URLs from environment or use defaults
STREAM_URLS = []
for i in range(len(DEFAULT_STREAM_URLS)):
    env_url = os.environ.get(f'CAMERA_STREAM_{i+1}_URL')
    if env_url:
        STREAM_URLS.append(env_url)
    else:
        STREAM_URLS.append(DEFAULT_STREAM_URLS[i])

# Add test streams for development
if os.environ.get('INCLUDE_TEST_STREAMS', 'true').lower() == 'true':
    STREAM_URLS.extend([
        "https://picsum.photos/seed/test1/800/600",
        "https://picsum.photos/seed/test2/800/600"
    ])

def check_stream_status(url):
    """Check if a stream URL is accessible with retry logic"""
    max_retries = 2
    base_timeout = 5.0  # More lenient base timeout

    for attempt in range(max_retries):
        try:
            # Increase timeout with each retry
            current_timeout = base_timeout * (attempt + 1)
            logger.debug(f"Checking stream {url} (attempt {attempt + 1}/{max_retries}, timeout={current_timeout}s)")

            # Create a Request object with a User-Agent header
            req = Request(
                url,
                headers={'User-Agent': 'OctoPrint-Stream-Viewer/1.0'}
            )

            response = urlopen(req, timeout=current_timeout)
            return {
                'status': True,
                'error': None
            }
        except HTTPError as e:
            logger.error(f"HTTP error checking stream {url}: {e.code} - {e.reason}")
            return {
                'status': False,
                'error': f"HTTP {e.code}: {e.reason}"
            }
        except URLError as e:
            if attempt < max_retries - 1:
                # Wait before retry with exponential backoff
                time.sleep(1 * (attempt + 1))
                continue
            logger.error(f"Error checking stream {url} after {max_retries} attempts: {str(e)}")
            return {
                'status': False,
                'error': str(e)
            }
        except Exception as e:
            logger.error(f"Unexpected error checking stream {url}: {str(e)}")
            return {
                'status': False,
                'error': f"Unexpected error: {str(e)}"
            }

@app.route('/')
def index():
    """Render the main page with stream views"""
    # Get initial stream statuses
    stream_statuses = []
    for i, url in enumerate(STREAM_URLS):
        status_info = check_stream_status(url)
        if status_info is None:
            status_info = {'status': False, 'error': 'Failed to check stream status'}
        stream_statuses.append({
            'id': i + 1,
            'url': url,
            'status': status_info.get('status', False),
            'error': status_info.get('error', 'Unknown error')
        })

    # Check if we're running on Replit
    is_replit = os.environ.get('REPL_ID') is not None

    return render_template('index.html', 
                         streams=stream_statuses,
                         is_replit=is_replit)

@app.route('/check_streams')
def check_streams():
    """API endpoint to check stream statuses"""
    stream_statuses = []
    for i, url in enumerate(STREAM_URLS):
        status_info = check_stream_status(url)
        if status_info is None:
            status_info = {'status': False, 'error': 'Failed to check stream status'}
        stream_statuses.append({
            'id': i + 1,
            'url': url,
            'status': status_info.get('status', False),
            'error': status_info.get('error', 'Unknown error')
        })
    return jsonify(stream_statuses)

# Error handlers
@app.errorhandler(404)
def not_found_error(error):
    return render_template('index.html', error="Page not found"), 404

@app.errorhandler(500)
def internal_error(error):
    return render_template('index.html', error="Internal server error"), 500