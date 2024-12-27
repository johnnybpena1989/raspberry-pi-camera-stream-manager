import logging
from flask import Flask, render_template
import urllib.request
from urllib.error import URLError
import json
import time

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = "octoprint-stream-viewer-secret-key"

# Configure stream URLs
STREAM_URLS = [
    # Production cameras (currently offline)
    "http://10.0.0.15:8080/stream",
    "http://10.0.0.15:8081/stream",
    "http://10.0.0.15:8082/stream",
    # Test streams for development
    "https://picsum.photos/seed/test1/800/600",  # Static test image with fixed seed
    "https://picsum.photos/seed/test2/800/600"   # Another test image with different seed
]

def check_stream_status(url):
    """Check if a stream URL is accessible with retry logic"""
    max_retries = 2
    base_timeout = 5.0  # More lenient base timeout

    for attempt in range(max_retries):
        try:
            # Increase timeout with each retry
            current_timeout = base_timeout * (attempt + 1)
            logger.debug(f"Checking stream {url} (attempt {attempt + 1}/{max_retries}, timeout={current_timeout}s)")

            response = urllib.request.urlopen(url, timeout=current_timeout)
            return {
                'status': True,
                'error': None
            }
        except (URLError, TimeoutError) as e:
            if attempt < max_retries - 1:
                # Wait before retry with exponential backoff
                time.sleep(1 * (attempt + 1))
                continue
            logger.error(f"Error checking stream {url} after {max_retries} attempts: {str(e)}")
            return {
                'status': False,
                'error': str(e)
            }

@app.route('/')
def index():
    """Render the main page with stream views"""
    # Get initial stream statuses
    stream_statuses = []
    for i, url in enumerate(STREAM_URLS):
        status_info = check_stream_status(url)
        stream_statuses.append({
            'id': i + 1,
            'url': url,
            'status': status_info['status'],
            'error': status_info['error']
        })

    return render_template('index.html', streams=stream_statuses)

@app.route('/check_streams')
def check_streams():
    """API endpoint to check stream statuses"""
    stream_statuses = []
    for i, url in enumerate(STREAM_URLS):
        status_info = check_stream_status(url)
        stream_statuses.append({
            'id': i + 1,
            'url': url,
            'status': status_info['status'],
            'error': status_info['error']
        })
    return json.dumps(stream_statuses)

# Error handlers
@app.errorhandler(404)
def not_found_error(error):
    return render_template('index.html', error="Page not found"), 404

@app.errorhandler(500)
def internal_error(error):
    return render_template('index.html', error="Internal server error"), 500