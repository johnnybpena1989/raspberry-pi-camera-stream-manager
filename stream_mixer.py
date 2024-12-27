import cv2
import numpy as np
import threading
import time
from queue import Queue
import logging
from stream_proxy import stream_proxy

logger = logging.getLogger(__name__)

class StreamMixer:
    def __init__(self, url1, url2, transition_interval=60, transition_duration=3):
        self.url1 = url1
        self.url2 = url2
        self.transition_interval = transition_interval
        self.transition_duration = transition_duration
        self.frame_queue = Queue(maxsize=2)  # Reduced queue size for lower latency
        self.running = False
        self.current_stream = 1
        self.last_transition = time.time()
        self.stream1_status = {'online': False, 'last_check': 0}
        self.stream2_status = {'online': False, 'last_check': 0}
        self.transition_in_progress = False
        self.target_size = None
        logger.info(f"StreamMixer initialized with URLs: {url1}, {url2}")

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

    def _get_stream_frame(self, stream_id):
        """Get a frame from the stream proxy's buffer"""
        frame_data = stream_proxy.get_frame(stream_id)
        if frame_data is None:
            logger.debug(f"No frame data available from stream {stream_id}")
            return None

        try:
            nparr = np.frombuffer(frame_data, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if frame is None:
                logger.warning(f"Failed to decode frame from stream {stream_id}")
                return None

            # Initialize target size if not set
            if self.target_size is None and frame is not None:
                self.target_size = frame.shape[:2]
                logger.info(f"Set target size to {self.target_size}")

            return frame
        except Exception as e:
            logger.error(f"Error decoding frame from stream {stream_id}: {str(e)}")
            return None

    def _mix_streams(self):
        """Main mixing loop"""
        last_successful_frame1 = None
        last_successful_frame2 = None

        while self.running:
            try:
                current_time = time.time()
                time_since_transition = current_time - self.last_transition

                # Get frames from both streams
                frame1 = self._get_stream_frame(1)
                frame2 = self._get_stream_frame(2)

                # Update status and cache successful frames
                if frame1 is not None:
                    last_successful_frame1 = frame1.copy()
                    self.stream1_status['online'] = True
                else:
                    self.stream1_status['online'] = False
                    logger.debug("Stream 1 frame unavailable")

                if frame2 is not None:
                    last_successful_frame2 = frame2.copy()
                    self.stream2_status['online'] = True
                else:
                    self.stream2_status['online'] = False
                    logger.debug("Stream 2 frame unavailable")

                # Use cached frames if current ones are unavailable
                frame1 = frame1 if frame1 is not None else last_successful_frame1
                frame2 = frame2 if frame2 is not None else last_successful_frame2

                if frame1 is None and frame2 is None:
                    logger.warning("Both streams currently unavailable")
                    time.sleep(0.016)  # ~60 FPS max
                    continue

                # Create blank frame if one stream is missing
                if self.target_size is None and (frame1 is not None or frame2 is not None):
                    self.target_size = (frame1 or frame2).shape[:2]
                    logger.info(f"Initialized target size to {self.target_size}")

                if self.target_size is None:
                    logger.error("Cannot determine target size - no valid frames available")
                    time.sleep(0.016)
                    continue

                height, width = self.target_size
                if frame1 is None:
                    frame1 = np.zeros((height, width, 3), dtype=np.uint8)
                    logger.debug("Using blank frame for stream 1")
                if frame2 is None:
                    frame2 = np.zeros((height, width, 3), dtype=np.uint8)
                    logger.debug("Using blank frame for stream 2")

                # Handle transition
                if time_since_transition >= self.transition_interval:
                    if not self.transition_in_progress:
                        self.transition_in_progress = True
                        self.current_stream = 1 if self.current_stream == 2 else 2
                        self.last_transition = current_time
                        logger.info(f"Starting transition to stream {self.current_stream}")
                    transition_progress = min(1.0, (current_time - self.last_transition) / self.transition_duration)
                    alpha = transition_progress if self.current_stream == 2 else (1 - transition_progress)
                    if transition_progress >= 1.0:
                        self.transition_in_progress = False
                else:
                    alpha = 1.0 if self.current_stream == 2 else 0.0

                # Resize frames if needed
                if frame1.shape[:2] != self.target_size:
                    frame1 = cv2.resize(frame1, (width, height))
                if frame2.shape[:2] != self.target_size:
                    frame2 = cv2.resize(frame2, (width, height))

                # Mix frames
                mixed_frame = cv2.addWeighted(frame1, 1 - alpha, frame2, alpha, 0)

                # Convert to JPEG
                _, buffer = cv2.imencode('.jpg', mixed_frame, [cv2.IMWRITE_JPEG_QUALITY, 85])

                # Update frame queue
                try:
                    self.frame_queue.put_nowait(buffer.tobytes())
                except:
                    try:
                        self.frame_queue.get_nowait()  # Remove old frame
                        self.frame_queue.put_nowait(buffer.tobytes())
                    except:
                        pass

                time.sleep(0.016)  # ~60 FPS max

            except Exception as e:
                logger.error(f"Error in stream mixing: {str(e)}")
                time.sleep(0.016)