import logging
import os
from flask import Flask, render_template, jsonify, Response
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
import time
from stream_mixer import StreamMixer
from stream_proxy import stream_proxy
from urllib.parse import urljoin
import flask

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or "octoprint-stream-viewer-secret-key"

# Configure stream URLs - can be overridden by environment variables
DEFAULT_STREAM_URLS = [
    "http://24.23.32.16:8080/webcam1/?action=stream",
    "http://24.23.32.16:8080/webcam2/?action=stream",
    "http://24.23.32.16:8080/webcam3/?action=stream",
]

# Get stream URLs from environment or use defaults
STREAM_URLS = []
for i in range(len(DEFAULT_STREAM_URLS)):
    env_url = os.environ.get(f'CAMERA_STREAM_{i+1}_URL')
    if env_url:
        STREAM_URLS.append(env_url)
    else:
        STREAM_URLS.append(DEFAULT_STREAM_URLS[i])

def get_server_url():
    """Get the server's base URL"""
    if 'X-Forwarded-Host' in flask.request.headers:
        proto = flask.request.headers.get('X-Forwarded-Proto', 'https')  # Default to https
        host = flask.request.headers['X-Forwarded-Host']
        return f"{proto}://{host}"
    return "https://localhost:5000"  # Use https by default

# Initialize the stream mixer with full URLs (will be set in before_request)
stream_mixer = None

@app.before_request
def setup_stream_mixer():
    global stream_mixer
    if stream_mixer is None:
        # Initialize proxy streams first
        for i, url in enumerate(STREAM_URLS[:2], 1):  # Only first two streams for mixing
            logger.info(f"Initializing proxy stream {i} with URL: {url}")
            stream_proxy.ensure_stream_buffer(url, i)

        base_url = get_server_url()
        logger.info(f"Using base URL for stream mixer: {base_url}")
        stream_mixer = StreamMixer(
            urljoin(base_url, f"/proxy-stream/1"),
            urljoin(base_url, f"/proxy-stream/2")
        )
        stream_mixer.start()
        logger.info("Stream mixer initialized and started")

@app.route('/proxy-stream/<int:stream_id>')
def proxy_stream(stream_id):
    """Proxy the camera stream through a secure connection"""
    if 1 <= stream_id <= len(STREAM_URLS):
        logger.debug(f"Proxying stream {stream_id} from URL: {STREAM_URLS[stream_id - 1]}")
        return stream_proxy.proxy_stream(STREAM_URLS[stream_id - 1], stream_id)
    return Response(status=404)

def check_stream_status(url):
    """Check if a stream URL is accessible with retry logic"""
    max_retries = 2
    base_timeout = 5.0  # More lenient base timeout

    for attempt in range(max_retries):
        try:
            current_timeout = base_timeout * (attempt + 1)
            logger.debug(f"Checking stream {url} (attempt {attempt + 1}/{max_retries}, timeout={current_timeout}s)")

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

def generate_mixed_frames():
    """Generator function for mixed stream frames"""
    while True:
        frame = stream_mixer.get_latest_frame() if stream_mixer else None
        if frame is not None:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
        else:
            time.sleep(0.033)  # Approximate 30 FPS

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
            'url': f"/proxy-stream/{i + 1}",  # Use proxied URLs for viewing
            'status': status_info.get('status', False),
            'error': status_info.get('error', 'Unknown error')
        })

    return render_template('index.html', 
                         streams=stream_statuses,
                         STREAM_URLS=STREAM_URLS)  # Pass the actual URLs to template

@app.route('/mixed-stream')
def mixed_stream():
    """Stream the mixed video feed"""
    return Response(generate_mixed_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

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
            'url': f"/proxy-stream/{i + 1}",  # Use proxied URLs in status checks
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

# Cleanup when the application exits
import atexit

@atexit.register
def cleanup():
    if stream_mixer:
        stream_mixer.stop()