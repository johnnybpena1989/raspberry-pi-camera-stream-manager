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
    # Production cameras (currently offline)
    "http://10.0.0.15:8080/stream",
    "http://10.0.0.15:8081/stream",
    "http://10.0.0.15:8082/stream",
    # Test streams for development
    "https://picsum.photos/800/600", # Static test image
    "https://media.istockphoto.com/id/1147544807/video/thumbnail-of-3d-printer-working-timelapse-modern-3d-printer-printing-an-object.jpg?s=640x640&k=20&c=B6rjkEUA0k4aBzq3xtAvxHkoAde6TaD5bGh7ZX_H3_I=" # Another test image
]

def check_stream_status(url):
    """Check if a stream URL is accessible"""
    try:
        response = urllib.request.urlopen(url, timeout=1)  # Reduced timeout for faster feedback
        return {
            'status': True,
            'error': None
        }
    except (URLError, TimeoutError) as e:
        logger.error(f"Error checking stream {url}: {str(e)}")
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