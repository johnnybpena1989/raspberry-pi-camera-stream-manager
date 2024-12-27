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
        # Single small queue for output frames
        self.frame_queue = Queue(maxsize=2)
        self.running = False
        self.current_stream = 1
        self.last_transition = time.time()
        self.target_size = None

    def _get_frame(self, stream_id):
        """Get frame from stream without caching"""
        try:
            frame_data = stream_proxy.get_frame(stream_id)
            if frame_data is None:
                return None

            # Decode frame
            nparr = np.frombuffer(frame_data, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            if frame is None:
                return None

            # Handle frame size
            if self.target_size is None:
                self.target_size = frame.shape[:2]
            elif frame.shape[:2] != self.target_size:
                frame = cv2.resize(frame, (self.target_size[1], self.target_size[0]))

            return frame

        except Exception as e:
            logger.error(f"Error processing frame from stream {stream_id}: {str(e)}")
            return None

    def _mix_streams(self):
        """Main mixing loop optimized for 20 FPS"""
        target_frame_time = 1.0 / 20.0  # Target 20 FPS
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

                # Get frames directly without caching
                frame1 = self._get_frame(1)
                frame2 = self._get_frame(2)

                # Skip if no valid frames
                if frame1 is None and frame2 is None:
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
                    progress = min(1.0, max(0.0, progress))

                    # Apply smooth easing function (cubic)
                    t = progress * progress * (3 - 2 * progress)

                    # Create crossfade
                    alpha = t if self.current_stream == 2 else (1.0 - t)
                    output_frame = cv2.addWeighted(frame1, 1.0 - alpha, frame2, alpha, 0)

                    # Check for transition completion
                    if progress >= 1.0:
                        self.current_stream = 3 - self.current_stream
                        self.last_transition = current_time
                else:
                    # Normal playback
                    output_frame = frame2 if self.current_stream == 2 else frame1

                # Update frame queue
                if output_frame is not None:
                    _, buffer = cv2.imencode('.jpg', output_frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                    try:
                        if not self.frame_queue.full():
                            self.frame_queue.put_nowait(buffer.tobytes())
                        else:
                            # Clear old frame if queue is full
                            try:
                                self.frame_queue.get_nowait()
                                self.frame_queue.put_nowait(buffer.tobytes())
                            except:
                                pass
                    except Exception as e:
                        logger.error(f"Failed to update frame queue: {str(e)}")

            except Exception as e:
                logger.error(f"Error in stream mixing: {str(e)}")
                time.sleep(target_frame_time)

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

    def __del__(self):
        self.stop()