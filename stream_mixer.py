import cv2
import numpy as np
import threading
import time
from queue import Queue
import logging
from stream_proxy import stream_proxy

logger = logging.getLogger(__name__)

class StreamMixer:
    def __init__(self, url1, url2, transition_interval=30, transition_duration=3):
        self.url1 = url1
        self.url2 = url2
        self.transition_interval = transition_interval
        self.transition_duration = transition_duration
        self.frame_queue = Queue(maxsize=1)
        self.running = False
        self.current_stream = 1
        self.last_transition = time.time()
        self.target_size = None
        logger.info(f"Initialized mixer: interval={transition_interval}s, duration={transition_duration}s")

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
        """Get and decode a frame from stream"""
        frame_data = stream_proxy.get_frame(stream_id)
        if frame_data is None:
            return None

        try:
            nparr = np.frombuffer(frame_data, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            if frame is not None and self.target_size is None:
                self.target_size = frame.shape[:2]
                logger.info(f"Set target size to {self.target_size}")

            return frame
        except Exception as e:
            logger.error(f"Error decoding frame from stream {stream_id}: {str(e)}")
            return None

    def _mix_streams(self):
        """Main mixing loop"""
        while self.running:
            try:
                # Get current frames
                frame1 = self._get_frame(1)
                frame2 = self._get_frame(2)

                # Skip if both frames are missing
                if frame1 is None and frame2 is None:
                    time.sleep(0.033)  # ~30 FPS
                    continue

                # Handle missing frames
                if frame1 is None and frame2 is not None:
                    frame1 = np.zeros_like(frame2)
                elif frame2 is None and frame1 is not None:
                    frame2 = np.zeros_like(frame1)

                # Ensure frames are same size
                if frame1.shape != frame2.shape:
                    height, width = self.target_size or frame1.shape[:2]
                    frame1 = cv2.resize(frame1, (width, height))
                    frame2 = cv2.resize(frame2, (width, height))

                # Calculate transition
                current_time = time.time()
                time_since_last = current_time - self.last_transition

                # Check for transition
                if time_since_last >= self.transition_interval:
                    # Start new transition
                    if time_since_last - self.transition_interval < self.transition_duration:
                        # Calculate transition progress (0 to 1)
                        progress = (time_since_last - self.transition_interval) / self.transition_duration
                        logger.debug(f"Transition progress: {progress:.2f}")

                        # Create transition effect
                        alpha = progress
                        if self.current_stream == 2:
                            alpha = 1.0 - progress

                        # Blend frames
                        output = cv2.addWeighted(frame1, 1.0 - alpha, frame2, alpha, 0)
                        logger.debug(f"Blending with alpha={alpha:.2f}")
                    else:
                        # Transition complete
                        self.current_stream = 3 - self.current_stream
                        self.last_transition = current_time
                        logger.info(f"Switched to stream {self.current_stream}")
                        output = frame2 if self.current_stream == 2 else frame1
                else:
                    # No transition, show current stream
                    output = frame2 if self.current_stream == 2 else frame1

                # Encode and queue frame
                _, buffer = cv2.imencode('.jpg', output, [cv2.IMWRITE_JPEG_QUALITY, 85])
                try:
                    # Update frame queue
                    while not self.frame_queue.empty():
                        self.frame_queue.get_nowait()
                    self.frame_queue.put_nowait(buffer.tobytes())
                except:
                    pass

                time.sleep(0.033)  # ~30 FPS

            except Exception as e:
                logger.error(f"Error in stream mixing: {str(e)}")
                time.sleep(0.033)

    def __del__(self):
        self.stop()