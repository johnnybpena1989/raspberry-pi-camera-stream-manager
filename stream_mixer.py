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
        self.transition_interval = transition_interval  # Time between transitions in seconds
        self.transition_duration = transition_duration  # Duration of crossfade in seconds
        self.frame_queue = Queue(maxsize=2)
        self.running = False
        self.current_stream = 1
        self.last_transition = time.time()
        self.stream1_status = {'online': False, 'last_check': 0}
        self.stream2_status = {'online': False, 'last_check': 0}
        self.transition_in_progress = False
        self.target_size = None
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

    def _get_stream_frame(self, stream_id):
        """Get a frame from the stream proxy's buffer"""
        frame_data = stream_proxy.get_frame(stream_id)
        if frame_data is None:
            return None

        try:
            nparr = np.frombuffer(frame_data, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if frame is None:
                return None

            # Initialize target size if not set
            if self.target_size is None and frame is not None:
                self.target_size = frame.shape[:2]
                logger.info(f"Set target size to {self.target_size}")

            return frame
        except Exception as e:
            logger.error(f"Error decoding frame from stream {stream_id}: {str(e)}")
            return None

    def _apply_smooth_transition(self, frame1, frame2, progress):
        """Apply smooth transition effect between frames"""
        # Use smooth easing function for transition
        smooth_progress = 0.5 * (1 - np.cos(progress * np.pi))
        return cv2.addWeighted(frame1, 1 - smooth_progress, frame2, smooth_progress, 0)

    def _mix_streams(self):
        """Main mixing loop with improved transition handling"""
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
                    frame1 = last_successful_frame1
                    self.stream1_status['online'] = False

                if frame2 is not None:
                    last_successful_frame2 = frame2.copy()
                    self.stream2_status['online'] = True
                else:
                    frame2 = last_successful_frame2
                    self.stream2_status['online'] = False

                if frame1 is None and frame2 is None:
                    time.sleep(0.016)
                    continue

                # Initialize or update target size
                if self.target_size is None and (frame1 is not None or frame2 is not None):
                    self.target_size = (frame1 or frame2).shape[:2]

                if self.target_size is None:
                    time.sleep(0.016)
                    continue

                # Create blank frames if needed
                height, width = self.target_size
                if frame1 is None:
                    frame1 = np.zeros((height, width, 3), dtype=np.uint8)
                if frame2 is None:
                    frame2 = np.zeros((height, width, 3), dtype=np.uint8)

                # Handle transition
                output_frame = None
                if time_since_transition >= self.transition_interval:
                    if not self.transition_in_progress:
                        self.transition_in_progress = True
                        self.current_stream = 1 if self.current_stream == 2 else 2
                        self.last_transition = current_time
                        logger.info(f"Starting transition to stream {self.current_stream}")

                    # Calculate transition progress
                    progress = min(1.0, (current_time - self.last_transition) / self.transition_duration)

                    # Apply transition effect
                    if self.current_stream == 2:
                        output_frame = self._apply_smooth_transition(frame1, frame2, progress)
                    else:
                        output_frame = self._apply_smooth_transition(frame2, frame1, progress)

                    if progress >= 1.0:
                        self.transition_in_progress = False
                else:
                    # Show current stream
                    output_frame = frame2 if self.current_stream == 2 else frame1

                # Resize output frame if needed
                if output_frame.shape[:2] != self.target_size:
                    output_frame = cv2.resize(output_frame, (width, height))

                # Convert to JPEG and update frame queue
                _, buffer = cv2.imencode('.jpg', output_frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
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