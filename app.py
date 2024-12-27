import logging
from flask import Flask, render_template
import urllib.request
from urllib.error import URLError
import json

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = "octoprint-stream-viewer-secret-key"

# Configure stream URLs
STREAM_URLS = [
    "http://10.0.0.15:8080/stream",
    "http://10.0.0.15:8081/stream",
    "http://10.0.0.15:8082/stream"
]

def check_stream_status(url):
    """Check if a stream URL is accessible"""
    try:
        response = urllib.request.urlopen(url, timeout=2)
        return response.getcode() == 200
    except (URLError, TimeoutError) as e:
        logger.error(f"Error checking stream {url}: {str(e)}")
        return False

@app.route('/')
def index():
    """Render the main page with stream views"""
    # Get initial stream statuses
    stream_statuses = []
    for i, url in enumerate(STREAM_URLS):
        status = check_stream_status(url)
        stream_statuses.append({
            'id': i + 1,
            'url': url,
            'status': status
        })
    
    return render_template('index.html', streams=stream_statuses)

@app.route('/check_streams')
def check_streams():
    """API endpoint to check stream statuses"""
    stream_statuses = []
    for i, url in enumerate(STREAM_URLS):
        status = check_stream_status(url)
        stream_statuses.append({
            'id': i + 1,
            'url': url,
            'status': status
        })
    return json.dumps(stream_statuses)

# Error handlers
@app.errorhandler(404)
def not_found_error(error):
    return render_template('index.html', error="Page not found"), 404

@app.errorhandler(500)
def internal_error(error):
    return render_template('index.html', error="Internal server error"), 500
