import logging
import requests
import cv2
import numpy as np
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
        self.frame_buffers = {}
        self.buffer_locks = {}
        self.stream_threads = {}
        self.video_captures = {}

    def _buffer_video_stream(self, stream_url, stream_id):
        """Buffer video frames from a video file stream"""
        frame_buffer = self.frame_buffers[stream_id]
        buffer_lock = self.buffer_locks[stream_id]

        while True:
            try:
                # Create or get existing video capture
                if stream_id not in self.video_captures:
                    cap = cv2.VideoCapture(stream_url)
                    if not cap.isOpened():
                        logger.error(f"Failed to open video stream {stream_id}")
                        time.sleep(1)
                        continue
                    self.video_captures[stream_id] = cap
                    logger.info(f"Successfully opened video stream {stream_id}")

                cap = self.video_captures[stream_id]
                ret, frame = cap.read()

                if not ret:
                    # Video ended, reset capture to loop
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    logger.info(f"Restarting video stream {stream_id}")
                    continue

                # Convert frame to JPEG
                _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                jpeg_frame = buffer.tobytes()

                with buffer_lock:
                    try:
                        frame_buffer.put_nowait(jpeg_frame)
                    except:
                        try:
                            frame_buffer.get_nowait()  # Remove old frame
                            frame_buffer.put_nowait(jpeg_frame)
                        except:
                            pass

                # Control frame rate
                time.sleep(0.033)  # ~30 FPS

            except Exception as e:
                logger.error(f"Error in video stream {stream_id}: {str(e)}")
                # Reset video capture
                if stream_id in self.video_captures:
                    self.video_captures[stream_id].release()
                    del self.video_captures[stream_id]
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
            logger.info(f"Initializing buffer for stream {stream_id}")

            self.frame_buffers[stream_id] = Queue(maxsize=2)
            self.buffer_locks[stream_id] = threading.Lock()

            # Stop existing thread if any
            if stream_id in self.stream_threads and self.stream_threads[stream_id].is_alive():
                if stream_id in self.video_captures:
                    self.video_captures[stream_id].release()
                    del self.video_captures[stream_id]
                self.stream_threads[stream_id] = None

            self.stream_threads[stream_id] = threading.Thread(
                target=self._buffer_video_stream,
                args=(stream_url, stream_id),
                daemon=True
            )
            self.stream_threads[stream_id].start()
            logger.info(f"Started buffer thread for stream {stream_id}")

    def proxy_stream(self, stream_url, stream_id=None):
        """Proxy a stream with buffering"""
        if stream_id is not None:
            self.ensure_stream_buffer(stream_url, stream_id)
            return Response(
                self._generate_from_buffer(stream_id),
                mimetype='multipart/x-mixed-replace; boundary=frame'
            )
        return Response(status=400)

    def _generate_from_buffer(self, stream_id):
        """Generate frames from the buffer"""
        logger.info(f"Starting frame generation from buffer for stream {stream_id}")
        while True:
            frame = self.get_frame(stream_id)
            if frame is not None:
                yield (b'--frame\r\n'
                      b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
            else:
                time.sleep(0.033)  # ~30 FPS

    def __del__(self):
        """Cleanup video captures on deletion"""
        for cap in self.video_captures.values():
            cap.release()

stream_proxy = StreamProxy()