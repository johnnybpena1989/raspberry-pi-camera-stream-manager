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

    def start(self):
        """Start the stream mixing process"""
        self.running = True
        self.mixing_thread = threading.Thread(target=self._mix_streams)
        self.mixing_thread.daemon = True
        self.mixing_thread.start()

    def stop(self):
        """Stop the stream mixing process"""
        self.running = False
        if hasattr(self, 'mixing_thread'):
            self.mixing_thread.join()

    def get_latest_frame(self):
        """Get the latest mixed frame"""
        try:
            return self.frame_queue.get_nowait()
        except:
            return None

    def _get_stream_frame(self, url):
        """Get a frame from a stream URL"""
        try:
            stream_bytes = b''
            stream = urlopen(url)
            bytes_array = b''
            
            for b in stream.read(1024):
                bytes_array += bytes([b])
                if bytes_array.endswith(b'\xff\xd9'):
                    stream_bytes = bytes_array
                    bytes_array = b''
                    
            if stream_bytes:
                nparr = np.frombuffer(stream_bytes, np.uint8)
                return cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            return None
        except urllib.error.URLError as e:
            logger.error(f"Error reading stream from {url}: {str(e)}")
            return None

    def _mix_streams(self):
        """Main mixing loop"""
        while self.running:
            try:
                current_time = time.time()
                time_since_transition = current_time - self.last_transition

                # Check if it's time for transition
                if time_since_transition >= self.transition_interval:
                    # Start transition
                    transition_start = current_time
                    self.current_stream = 1 if self.current_stream == 2 else 2
                    self.last_transition = current_time

                    # Calculate alpha based on transition progress
                    transition_progress = min(1.0, (current_time - transition_start) / self.transition_duration)
                    alpha = transition_progress if self.current_stream == 2 else (1 - transition_progress)
                else:
                    # No transition, show current stream fully
                    alpha = 1.0 if self.current_stream == 2 else 0.0

                # Get frames from both streams
                frame1 = self._get_stream_frame(self.url1)
                frame2 = self._get_stream_frame(self.url2)

                if frame1 is None and frame2 is None:
                    logger.error("Both streams are unavailable")
                    time.sleep(0.1)
                    continue

                # Create blank frame if one stream is missing
                if frame1 is None:
                    frame1 = np.zeros_like(frame2)
                if frame2 is None:
                    frame2 = np.zeros_like(frame1)

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

                time.sleep(0.033)  # Approximate 30 FPS

            except Exception as e:
                logger.error(f"Error in stream mixing: {str(e)}")
                time.sleep(0.1)
