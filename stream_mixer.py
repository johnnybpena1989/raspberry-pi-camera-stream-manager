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
        self.frame_queue = Queue(maxsize=2)
        self.buffer1 = Queue(maxsize=2)
        self.buffer2 = Queue(maxsize=2)
        self.running = False
        self.current_stream = 1
        self.last_transition = time.time()
        self.target_size = None
        self.frame_count = 0
        self.last_frame_time = time.time()
        logger.info(f"Initialized mixer with {transition_interval}s interval, {transition_duration}s fade")

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
        """Get frame from stream with detailed logging"""
        try:
            frame_data = stream_proxy.get_frame(stream_id)
            if frame_data is None:
                logger.debug(f"No frame data received from stream {stream_id}")
                return None

            # Decode frame
            nparr = np.frombuffer(frame_data, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            if frame is None:
                logger.debug(f"Failed to decode frame from stream {stream_id}")
                return None

            # Handle frame size
            if self.target_size is None:
                self.target_size = frame.shape[:2]
                logger.info(f"Set target frame size to {self.target_size}")
            elif frame.shape[:2] != self.target_size:
                frame = cv2.resize(frame, (self.target_size[1], self.target_size[0]))
                logger.debug(f"Resized frame from stream {stream_id} to {self.target_size}")

            return frame

        except Exception as e:
            logger.error(f"Error processing frame from stream {stream_id}: {str(e)}")
            return None

    def _mix_streams(self):
        """Main mixing loop with enhanced logging"""
        last_frame1 = None
        last_frame2 = None
        frame_time = time.time()

        while self.running:
            try:
                current_time = time.time()

                # Maintain consistent frame rate
                elapsed = current_time - frame_time
                if elapsed < 0.033:  # Target ~30 FPS
                    time.sleep(0.033 - elapsed)
                    continue

                frame_time = current_time

                # Get frames from both streams
                frame1 = self._get_frame(1)
                frame2 = self._get_frame(2)

                # Update frame cache
                if frame1 is not None:
                    last_frame1 = frame1.copy()
                elif last_frame1 is not None:
                    frame1 = last_frame1
                    logger.debug("Using cached frame for stream 1")

                if frame2 is not None:
                    last_frame2 = frame2.copy()
                elif last_frame2 is not None:
                    frame2 = last_frame2
                    logger.debug("Using cached frame for stream 2")

                # Skip if no valid frames
                if frame1 is None and frame2 is None:
                    logger.warning("No valid frames available from either stream")
                    continue

                # Create blank frame if needed
                if frame1 is None:
                    frame1 = np.zeros_like(frame2)
                    logger.debug("Created blank frame for stream 1")
                if frame2 is None:
                    frame2 = np.zeros_like(frame1)
                    logger.debug("Created blank frame for stream 2")

                # Calculate transition state
                time_since_last = current_time - self.last_transition
                in_transition = (time_since_last >= self.transition_interval and 
                               time_since_last < self.transition_interval + self.transition_duration)

                # Generate output frame
                if in_transition:
                    # Calculate transition progress
                    progress = (time_since_last - self.transition_interval) / self.transition_duration
                    progress = min(1.0, progress)

                    # Apply smooth easing
                    t = progress * progress * (3 - 2 * progress)

                    # Create crossfade
                    alpha = t if self.current_stream == 2 else (1.0 - t)
                    output_frame = cv2.addWeighted(frame1, 1.0 - alpha, frame2, alpha, 0)
                    logger.debug(f"Transition progress: {progress:.3f}, alpha: {alpha:.3f}")

                    # Check for transition completion
                    if progress >= 1.0:
                        self.current_stream = 3 - self.current_stream
                        self.last_transition = current_time
                        logger.info(f"Completed transition to stream {self.current_stream}")
                else:
                    # Normal playback
                    output_frame = frame2 if self.current_stream == 2 else frame1

                # Update frame queue
                if output_frame is not None:
                    _, buffer = cv2.imencode('.jpg', output_frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                    try:
                        # Clear old frames
                        while not self.frame_queue.empty():
                            self.frame_queue.get_nowait()
                        self.frame_queue.put_nowait(buffer.tobytes())
                        self.frame_count += 1

                        if self.frame_count % 30 == 0:  # Log every 30 frames
                            fps = 30 / (current_time - self.last_frame_time)
                            logger.debug(f"Current FPS: {fps:.1f}")
                            self.last_frame_time = current_time
                    except:
                        logger.warning("Failed to update frame queue")

            except Exception as e:
                logger.error(f"Error in stream mixing: {str(e)}")
                time.sleep(0.033)

    def __del__(self):
        self.stop()