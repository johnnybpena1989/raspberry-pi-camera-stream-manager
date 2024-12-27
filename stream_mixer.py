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
        self.frame_queue = Queue(maxsize=1)  # Single frame buffer for lower latency
        self.running = False
        self.current_stream = 1
        self.last_transition = time.time()
        self.stream1_status = {'online': False, 'last_check': 0}
        self.stream2_status = {'online': False, 'last_check': 0}
        self.transition_in_progress = False
        self.target_size = None
        self.frame_interval = 1.0 / 30.0  # Target 30 FPS
        self.last_frame_time = 0
        logger.info(f"StreamMixer initialized with URLs: {url1}, {url2}")
        logger.info(f"Transition interval: {transition_interval}s, Duration: {transition_duration}s")

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

    def _get_frame(self, stream_id):
        """Get a frame from the stream proxy's buffer with size validation"""
        frame_data = stream_proxy.get_frame(stream_id)
        if frame_data is None:
            return None

        try:
            # Decode frame
            nparr = np.frombuffer(frame_data, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if frame is None:
                return None

            # Ensure frame size consistency
            if self.target_size is not None:
                height, width = self.target_size
                if frame.shape[:2] != (height, width):
                    frame = cv2.resize(frame, (width, height))
            elif frame is not None:
                self.target_size = frame.shape[:2]
                logger.info(f"Set target size to {self.target_size}")

            return frame
        except Exception as e:
            logger.error(f"Error decoding frame from stream {stream_id}: {str(e)}")
            return None

    def _apply_transition(self, frame1, frame2, progress):
        """Apply optimized transition effect"""
        # Smooth easing function
        t = progress * progress * (3 - 2 * progress)

        # Fast addWeighted operation
        return cv2.addWeighted(frame1, 1.0 - t, frame2, t, 0)

    def _mix_streams(self):
        """Optimized mixing loop with proper frame timing"""
        cached_frame1 = None
        cached_frame2 = None
        next_frame_time = time.time()

        while self.running:
            try:
                current_time = time.time()

                # Maintain consistent frame rate
                if current_time < next_frame_time:
                    time.sleep(max(0, next_frame_time - current_time))
                    continue

                next_frame_time = current_time + self.frame_interval

                # Get frames with caching
                frame1 = self._get_frame(1)
                frame2 = self._get_frame(2)

                # Update cache and status
                if frame1 is not None:
                    cached_frame1 = frame1.copy()
                    self.stream1_status['online'] = True
                elif cached_frame1 is not None:
                    frame1 = cached_frame1
                    self.stream1_status['online'] = False

                if frame2 is not None:
                    cached_frame2 = frame2.copy()
                    self.stream2_status['online'] = True
                elif cached_frame2 is not None:
                    frame2 = cached_frame2
                    self.stream2_status['online'] = False

                # Skip if no frames available
                if frame1 is None and frame2 is None:
                    time.sleep(self.frame_interval)
                    continue

                # Create output frame
                output_frame = None
                time_since_transition = current_time - self.last_transition

                if time_since_transition >= self.transition_interval and frame1 is not None and frame2 is not None:
                    if not self.transition_in_progress:
                        self.transition_in_progress = True
                        self.current_stream = 3 - self.current_stream  # Toggle between 1 and 2
                        self.last_transition = current_time
                        logger.info(f"Starting transition to stream {self.current_stream}")

                    # Calculate transition progress
                    progress = min(1.0, (current_time - self.last_transition) / self.transition_duration)

                    # Apply transition
                    if self.current_stream == 2:
                        output_frame = self._apply_transition(frame1, frame2, progress)
                    else:
                        output_frame = self._apply_transition(frame2, frame1, progress)

                    if progress >= 1.0:
                        self.transition_in_progress = False
                else:
                    # Show current stream
                    output_frame = frame2 if self.current_stream == 2 else frame1

                # Encode and queue frame
                if output_frame is not None:
                    _, buffer = cv2.imencode('.jpg', output_frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                    try:
                        # Clear queue before putting new frame
                        while not self.frame_queue.empty():
                            self.frame_queue.get_nowait()
                        self.frame_queue.put_nowait(buffer.tobytes())
                    except:
                        pass

            except Exception as e:
                logger.error(f"Error in stream mixing: {str(e)}")
                time.sleep(self.frame_interval)

    def __del__(self):
        self.stop()