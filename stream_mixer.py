import cv2
import numpy as np
import threading
import time
from queue import Queue
import logging
from urllib.request import urlopen
import urllib.error

logger = logging.getLogger(__name__)

class StreamMixer:
    def __init__(self, url1, url2, transition_interval=60, transition_duration=3):
        self.url1 = url1
        self.url2 = url2
        self.transition_interval = transition_interval
        self.transition_duration = transition_duration
        self.frame_queue = Queue(maxsize=10)
        self.running = False
        self.current_stream = 1
        self.last_transition = time.time()
        self.stream1_status = {'online': False, 'last_check': 0, 'retry_count': 0}
        self.stream2_status = {'online': False, 'last_check': 0, 'retry_count': 0}
        self.retry_interval = 5  # Base retry interval in seconds
        self.max_retries = 3

    def start(self):
        """Start the stream mixing process"""
        self.running = True
        self.mixing_thread = threading.Thread(target=self._mix_streams)
        self.mixing_thread.daemon = True
        self.mixing_thread.start()
        logger.info("Stream mixer started")

    def stop(self):
        """Stop the stream mixing process"""
        self.running = False
        if hasattr(self, 'mixing_thread'):
            self.mixing_thread.join()
        logger.info("Stream mixer stopped")

    def get_latest_frame(self):
        """Get the latest mixed frame"""
        try:
            return self.frame_queue.get_nowait()
        except:
            return None

    def _get_stream_frame(self, url, stream_number):
        """Get a frame from a stream URL with improved error handling"""
        status = self.stream1_status if stream_number == 1 else self.stream2_status
        current_time = time.time()

        # Check if we should retry based on exponential backoff
        if not status['online'] and current_time - status['last_check'] < (self.retry_interval * (2 ** status['retry_count'])):
            return None

        try:
            stream = urlopen(url, timeout=5)
            bytes_array = b''

            for _ in range(50):  # Limit read attempts
                chunk = stream.read(1024)
                if not chunk:
                    break
                bytes_array += chunk
                if bytes_array.endswith(b'\xff\xd9'):
                    # Successfully got a complete JPEG frame
                    status['online'] = True
                    status['retry_count'] = 0
                    nparr = np.frombuffer(bytes_array, np.uint8)
                    return cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            logger.warning(f"Stream {stream_number}: Incomplete frame received")
            return None

        except Exception as e:
            status['online'] = False
            status['last_check'] = current_time
            status['retry_count'] = min(status['retry_count'] + 1, self.max_retries)

            if status['retry_count'] == 1:  # Log only on first retry to prevent spam
                logger.error(f"Error reading stream {stream_number} ({url}): {str(e)}")
            return None

    def _mix_streams(self):
        """Main mixing loop with improved error handling"""
        last_successful_frame1 = None
        last_successful_frame2 = None

        while self.running:
            try:
                current_time = time.time()
                time_since_transition = current_time - self.last_transition

                # Get frames from both streams
                frame1 = self._get_stream_frame(self.url1, 1)
                frame2 = self._get_stream_frame(self.url2, 2)

                # Update last successful frames if available
                if frame1 is not None:
                    last_successful_frame1 = frame1.copy()
                if frame2 is not None:
                    last_successful_frame2 = frame2.copy()

                # Use last successful frames if current frames are unavailable
                frame1 = frame1 if frame1 is not None else last_successful_frame1
                frame2 = frame2 if frame2 is not None else last_successful_frame2

                if frame1 is None and frame2 is None:
                    time.sleep(1)  # Longer sleep when both streams are down
                    continue

                # Create blank frame if one stream is missing
                if frame1 is None:
                    frame1 = np.zeros_like(frame2)
                if frame2 is None:
                    frame2 = np.zeros_like(frame1)

                # Check if it's time for transition
                if time_since_transition >= self.transition_interval:
                    # Start transition
                    transition_start = current_time
                    self.current_stream = 1 if self.current_stream == 2 else 2
                    self.last_transition = current_time
                    transition_progress = min(1.0, (current_time - transition_start) / self.transition_duration)
                    alpha = transition_progress if self.current_stream == 2 else (1 - transition_progress)
                else:
                    # No transition, show current stream fully
                    alpha = 1.0 if self.current_stream == 2 else 0.0

                # Resize frames to match
                height = max(frame1.shape[0], frame2.shape[0])
                width = max(frame1.shape[1], frame2.shape[1])

                frame1 = cv2.resize(frame1, (width, height))
                frame2 = cv2.resize(frame2, (width, height))

                # Mix frames using alpha blending
                mixed_frame = cv2.addWeighted(frame1, 1 - alpha, frame2, alpha, 0)

                # Convert to JPEG
                _, buffer = cv2.imencode('.jpg', mixed_frame)

                # Put in queue, skip if queue is full
                try:
                    self.frame_queue.put_nowait(buffer.tobytes())
                except:
                    pass

                # Adaptive sleep based on stream availability
                if frame1 is not None or frame2 is not None:
                    time.sleep(0.033)  # ~30 FPS when streams are available
                else:
                    time.sleep(0.1)  # Slower updates when using cached frames

            except Exception as e:
                logger.error(f"Error in stream mixing: {str(e)}")
                time.sleep(0.1)