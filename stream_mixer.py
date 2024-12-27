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
        self.frame_queue = Queue(maxsize=10)
        self.running = False
        self.current_stream = 1
        self.last_transition = time.time()
        self.stream1_status = {'online': False, 'last_check': 0, 'retry_count': 0}
        self.stream2_status = {'online': False, 'last_check': 0, 'retry_count': 0}

    def start(self):
        """Start the stream mixing process"""
        self.running = True
        self.mixing_thread = threading.Thread(target=self._mix_streams)
        self.mixing_thread.daemon = True
        self.mixing_thread.start()
        logger.info(f"Stream mixer started with URLs: {self.url1}, {self.url2}")

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
            logger.debug(f"No frame available from stream {stream_id}")
            return None

        try:
            nparr = np.frombuffer(frame_data, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if frame is None:
                logger.warning(f"Failed to decode frame from stream {stream_id}")
                return None
            logger.debug(f"Successfully decoded frame from stream {stream_id}")
            return frame
        except Exception as e:
            logger.error(f"Error decoding frame from stream {stream_id}: {str(e)}")
            return None

    def _mix_streams(self):
        """Main mixing loop"""
        last_successful_frame1 = None
        last_successful_frame2 = None
        frames_processed = 0

        while self.running:
            try:
                current_time = time.time()
                time_since_transition = current_time - self.last_transition

                # Get frames from both streams
                frame1 = self._get_stream_frame(1)
                frame2 = self._get_stream_frame(2)

                # Update last successful frames if available
                if frame1 is not None:
                    last_successful_frame1 = frame1.copy()
                    logger.debug("Successfully received frame from stream 1")
                    self.stream1_status['online'] = True
                else:
                    self.stream1_status['online'] = False

                if frame2 is not None:
                    last_successful_frame2 = frame2.copy()
                    logger.debug("Successfully received frame from stream 2")
                    self.stream2_status['online'] = True
                else:
                    self.stream2_status['online'] = False

                # Use last successful frames if current frames are unavailable
                frame1 = frame1 if frame1 is not None else last_successful_frame1
                frame2 = frame2 if frame2 is not None else last_successful_frame2

                if frame1 is None and frame2 is None:
                    logger.warning("Both streams currently unavailable")
                    time.sleep(1)  # Longer sleep when both streams are down
                    continue

                # Create blank frame if one stream is missing
                if frame1 is None:
                    frame1 = np.zeros_like(frame2)
                    logger.debug("Using blank frame for stream 1")
                if frame2 is None:
                    frame2 = np.zeros_like(frame1)
                    logger.debug("Using blank frame for stream 2")

                # Check if it's time for transition
                if time_since_transition >= self.transition_interval:
                    # Start transition
                    transition_start = current_time
                    self.current_stream = 1 if self.current_stream == 2 else 2
                    self.last_transition = current_time
                    logger.info(f"Starting transition to stream {self.current_stream}")
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
                    frames_processed += 1
                    if frames_processed % 30 == 0:  # Log every 30 frames
                        logger.debug(f"Successfully processed {frames_processed} frames")
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