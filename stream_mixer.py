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
        # Increase queue sizes to reduce frame drops
        self.frame_queue = Queue(maxsize=10)
        self.buffer1 = Queue(maxsize=10)
        self.buffer2 = Queue(maxsize=10)
        self.running = False
        self.current_stream = 1
        self.last_transition = time.time()
        self.target_size = None
        self.frame_count = 0
        self.last_frame_time = time.time()
        self.fps_update_interval = 1.0  # Update FPS every second
        self.last_fps_time = time.time()
        self.fps_frame_count = 0
        self.current_fps = 0.0
        logger.info(f"Initialized mixer with {transition_interval}s interval, {transition_duration}s fade")

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

            return frame

        except Exception as e:
            logger.error(f"Error processing frame from stream {stream_id}: {str(e)}")
            return None

    def _mix_streams(self):
        """Main mixing loop with enhanced frame rate control and transition handling"""
        last_frame1 = None
        last_frame2 = None
        target_frame_time = 1.0 / 30.0  # Target 30 FPS
        last_frame_time = time.time()

        while self.running:
            try:
                current_time = time.time()
                frame_delta = current_time - last_frame_time

                # Frame rate control
                if frame_delta < target_frame_time:
                    time.sleep(target_frame_time - frame_delta)
                    continue

                last_frame_time = current_time

                # Get frames from both streams
                frame1 = self._get_frame(1)
                frame2 = self._get_frame(2)

                # Update frame cache
                if frame1 is not None:
                    last_frame1 = frame1.copy()
                elif last_frame1 is not None:
                    frame1 = last_frame1.copy()

                if frame2 is not None:
                    last_frame2 = frame2.copy()
                elif last_frame2 is not None:
                    frame2 = last_frame2.copy()

                # Skip if no valid frames
                if frame1 is None and frame2 is None:
                    logger.warning("No valid frames available from either stream")
                    continue

                # Create blank frame if needed
                if frame1 is None:
                    frame1 = np.zeros_like(frame2)
                if frame2 is None:
                    frame2 = np.zeros_like(frame1)

                # Calculate transition state
                time_since_last = current_time - self.last_transition
                in_transition = (time_since_last >= self.transition_interval and 
                               time_since_last < self.transition_interval + self.transition_duration)

                # Generate output frame
                if in_transition:
                    # Calculate transition progress
                    progress = (time_since_last - self.transition_interval) / self.transition_duration
                    progress = min(1.0, max(0.0, progress))  # Ensure progress is between 0 and 1

                    # Apply smooth easing function (cubic)
                    t = progress * progress * (3 - 2 * progress)

                    # Create crossfade
                    alpha = t if self.current_stream == 2 else (1.0 - t)
                    output_frame = cv2.addWeighted(frame1, 1.0 - alpha, frame2, alpha, 0)
                    logger.debug(f"Transition at {progress:.2f}, alpha: {alpha:.2f}")

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
                        # Update frame queue without blocking
                        if not self.frame_queue.full():
                            self.frame_queue.put_nowait(buffer.tobytes())
                        else:
                            # Clear one old frame to make space
                            try:
                                self.frame_queue.get_nowait()
                                self.frame_queue.put_nowait(buffer.tobytes())
                            except:
                                pass

                        # Update FPS calculation
                        self.fps_frame_count += 1
                        fps_time_delta = current_time - self.last_fps_time
                        if fps_time_delta >= self.fps_update_interval:
                            self.current_fps = self.fps_frame_count / fps_time_delta
                            logger.info(f"Current FPS: {self.current_fps:.1f}")
                            self.fps_frame_count = 0
                            self.last_fps_time = current_time

                    except Exception as e:
                        logger.warning(f"Failed to update frame queue: {str(e)}")

            except Exception as e:
                logger.error(f"Error in stream mixing: {str(e)}")
                time.sleep(target_frame_time)

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

    def __del__(self):
        self.stop()