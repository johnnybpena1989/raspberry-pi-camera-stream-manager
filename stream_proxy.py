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
        self.chunk_size = 1024
        self.frame_buffers = {}
        self.buffer_locks = {}
        self.stream_threads = {}

    def _buffer_stream(self, stream_url, stream_id):
        """Buffer stream frames in memory"""
        frame_buffer = self.frame_buffers[stream_id]
        buffer_lock = self.buffer_locks[stream_id]

        while True:
            try:
                response = self.session.get(
                    stream_url,
                    stream=True,
                    timeout=5
                )

                if response.status_code != 200:
                    logger.error(f"Failed to connect to stream {stream_id}: HTTP {response.status_code}")
                    time.sleep(1)
                    continue

                bytes_array = b''
                for chunk in response.iter_content(chunk_size=self.chunk_size):
                    if not chunk:
                        break
                    bytes_array += chunk
                    if bytes_array.endswith(b'\xff\xd9'):
                        with buffer_lock:
                            # Keep only the latest frame
                            while not frame_buffer.empty():
                                try:
                                    frame_buffer.get_nowait()
                                except:
                                    break
                            frame_buffer.put(bytes_array)
                        bytes_array = b''

            except Exception as e:
                logger.error(f"Error buffering stream {stream_id}: {str(e)}")
                time.sleep(1)

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
            self.frame_buffers[stream_id] = Queue(maxsize=1)
            self.buffer_locks[stream_id] = threading.Lock()
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
        while True:
            frame = self.get_frame(stream_id)
            if frame is not None:
                yield (b'--frame\r\n'
                      b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
            else:
                time.sleep(0.033)  # ~30 FPS

    def _stream_generator(self, response):
        """Generate streaming response"""
        for chunk in response.iter_content(chunk_size=self.chunk_size):
            if chunk:
                yield chunk
            else:
                break

stream_proxy = StreamProxy()