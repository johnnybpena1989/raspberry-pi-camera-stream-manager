import logging
import requests
from flask import Response, stream_with_context
from urllib.parse import urlparse
import time
from queue import Queue
import threading

logger = logging.getLogger(__name__)

class StreamProxy:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'OctoPrint-Stream-Viewer/1.0'
        })
        self.stream_buffers = {}
        self.chunk_size = 4096  # Increased chunk size for better performance
        self.frame_buffers = {}
        self.buffer_locks = {}
        self.stream_threads = {}

    def _buffer_stream(self, stream_url, stream_id):
        """Buffer stream frames in memory"""
        frame_buffer = self.frame_buffers[stream_id]
        buffer_lock = self.buffer_locks[stream_id]
        logger.info(f"Starting buffer thread for stream {stream_id}")

        bytes_array = b''
        while True:
            try:
                response = self.session.get(
                    stream_url,
                    stream=True,
                    timeout=5
                )

                if response.status_code != 200:
                    logger.error(f"Failed to connect to stream {stream_id}: HTTP {response.status_code}")
                    time.sleep(0.5)  # Reduced sleep time
                    continue

                for chunk in response.iter_content(chunk_size=self.chunk_size):
                    if not chunk:
                        break
                    bytes_array += chunk
                    if bytes_array.endswith(b'\xff\xd9'):  # JPEG end marker
                        with buffer_lock:
                            # Keep only the latest frame
                            try:
                                frame_buffer.put_nowait(bytes_array)
                            except:
                                # If buffer is full, get one item to make space
                                try:
                                    frame_buffer.get_nowait()
                                    frame_buffer.put_nowait(bytes_array)
                                except:
                                    pass
                        bytes_array = b''

            except requests.exceptions.RequestException as e:
                logger.error(f"Connection error buffering stream {stream_id}: {str(e)}")
                time.sleep(0.5)  # Reduced sleep time
            except Exception as e:
                logger.error(f"Unexpected error buffering stream {stream_id}: {str(e)}")
                time.sleep(0.5)  # Reduced sleep time

    def get_frame(self, stream_id):
        """Get the latest frame for a stream"""
        if stream_id not in self.frame_buffers:
            return None

        try:
            with self.buffer_locks[stream_id]:
                return self.frame_buffers[stream_id].get_nowait()
        except:
            return None

    def ensure_stream_buffer(self, stream_url, stream_id):
        """Ensure a stream buffer exists and is running"""
        if stream_id not in self.frame_buffers:
            logger.info(f"Initializing buffer for stream {stream_id}")
            self.frame_buffers[stream_id] = Queue(maxsize=2)  # Increased buffer size
            self.buffer_locks[stream_id] = threading.Lock()

            # Stop existing thread if any
            if stream_id in self.stream_threads and self.stream_threads[stream_id].is_alive():
                self.stream_threads[stream_id] = None

            self.stream_threads[stream_id] = threading.Thread(
                target=self._buffer_stream,
                args=(stream_url, stream_id),
                daemon=True
            )
            self.stream_threads[stream_id].start()

    def proxy_stream(self, stream_url, stream_id=None):
        """Proxy a stream, optionally with buffering"""
        if stream_id is not None:
            self.ensure_stream_buffer(stream_url, stream_id)
            return Response(
                self._generate_from_buffer(stream_id),
                mimetype='multipart/x-mixed-replace; boundary=frame'
            )

        try:
            response = self.session.get(
                stream_url,
                stream=True,
                timeout=5
            )

            if response.status_code == 200:
                return Response(
                    stream_with_context(self._stream_generator(response)),
                    content_type=response.headers.get('content-type', 'multipart/x-mixed-replace;boundary=frame')
                )
            else:
                logger.error(f"Failed to proxy stream {stream_url}: HTTP {response.status_code}")
                return Response(status=response.status_code)

        except requests.RequestException as e:
            logger.error(f"Error proxying stream {stream_url}: {str(e)}")
            return Response(status=503)

    def _generate_from_buffer(self, stream_id):
        """Generate frames from the buffer"""
        logger.info(f"Starting frame generation from buffer for stream {stream_id}")
        while True:
            frame = self.get_frame(stream_id)
            if frame is not None:
                yield (b'--frame\r\n'
                      b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
            else:
                time.sleep(0.016)  # ~60 FPS max

    def _stream_generator(self, response):
        """Generate streaming response"""
        for chunk in response.iter_content(chunk_size=self.chunk_size):
            if chunk:
                yield chunk
            else:
                break

stream_proxy = StreamProxy()