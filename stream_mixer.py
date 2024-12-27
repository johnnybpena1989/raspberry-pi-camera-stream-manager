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

    def _buffer_frame(self, stream_id, buffer):
        """Buffer a frame from the specified stream"""
        frame_data = stream_proxy.get_frame(stream_id)
        if frame_data is None:
            return None

        try:
            # Decode frame
            nparr = np.frombuffer(frame_data, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            if frame is None:
                return None

            # Set or validate frame size
            if self.target_size is None and frame is not None:
                self.target_size = frame.shape[:2]
                logger.info(f"Set target size to {self.target_size}")
            elif self.target_size is not None:
                if frame.shape[:2] != self.target_size:
                    frame = cv2.resize(frame, (self.target_size[1], self.target_size[0]))

            # Update buffer
            try:
                while not buffer.empty():
                    buffer.get_nowait()
                buffer.put_nowait(frame)
            except:
                pass

            return frame
        except Exception as e:
            logger.error(f"Error processing frame from stream {stream_id}: {str(e)}")
            return None

    def _get_buffered_frame(self, stream_id):
        """Get frame from appropriate buffer"""
        buffer = self.buffer1 if stream_id == 1 else self.buffer2
        try:
            return buffer.get_nowait()
        except:
            return None

    def _mix_streams(self):
        """Main mixing loop with proper frame synchronization"""
        last_frame1 = None
        last_frame2 = None

        while self.running:
            try:
                # Buffer frames from both streams
                frame1 = self._buffer_frame(1, self.buffer1)
                frame2 = self._buffer_frame(2, self.buffer2)

                # Update last valid frames
                if frame1 is not None:
                    last_frame1 = frame1
                if frame2 is not None:
                    last_frame2 = frame2

                # Use last valid frames if current frames are missing
                if frame1 is None and last_frame1 is not None:
                    frame1 = last_frame1
                if frame2 is None and last_frame2 is not None:
                    frame2 = last_frame2

                # Skip if no valid frames available
                if frame1 is None and frame2 is None:
                    time.sleep(0.033)  # ~30 FPS
                    continue

                # Handle single missing frame
                if frame1 is None:
                    frame1 = np.zeros_like(frame2)
                if frame2 is None:
                    frame2 = np.zeros_like(frame1)

                # Calculate transition timing
                current_time = time.time()
                time_since_last = current_time - self.last_transition

                # Determine output frame
                output_frame = None

                # Handle transition period
                if time_since_last >= self.transition_interval:
                    transition_time = time_since_last - self.transition_interval
                    if transition_time < self.transition_duration:
                        # Calculate transition progress with smooth easing
                        progress = transition_time / self.transition_duration
                        # Smooth easing function (cubic)
                        t = progress * progress * (3 - 2 * progress)

                        # Apply crossfade
                        alpha = t if self.current_stream == 2 else (1.0 - t)
                        output_frame = cv2.addWeighted(frame1, 1.0 - alpha, frame2, alpha, 0)
                        logger.debug(f"Transition at {progress:.2f}, alpha={alpha:.2f}")
                    else:
                        # Transition complete
                        self.current_stream = 3 - self.current_stream
                        self.last_transition = current_time
                        output_frame = frame2 if self.current_stream == 2 else frame1
                        logger.info(f"Switched to stream {self.current_stream}")
                else:
                    # Normal playback
                    output_frame = frame2 if self.current_stream == 2 else frame1

                # Encode and queue output frame
                if output_frame is not None:
                    _, buffer = cv2.imencode('.jpg', output_frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                    try:
                        # Update frame queue
                        while not self.frame_queue.empty():
                            self.frame_queue.get_nowait()
                        self.frame_queue.put_nowait(buffer.tobytes())
                    except:
                        pass

                # Maintain consistent frame rate
                time.sleep(0.033)  # ~30 FPS

            except Exception as e:
                logger.error(f"Error in stream mixing: {str(e)}")
                time.sleep(0.033)

    def __del__(self):
        self.stop()