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
            if frame is not None:
                return frame
        except Exception as e:
            logger.error(f"Error decoding frame from stream {stream_id}: {str(e)}")
        return None

    def _mix_streams(self):
        """Main mixing loop"""
        last_successful_frame1 = None
        last_successful_frame2 = None
        target_size = None

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
                    if target_size is None:
                        target_size = frame1.shape[:2]
                else:
                    self.stream1_status['online'] = False

                if frame2 is not None:
                    last_successful_frame2 = frame2.copy()
                    self.stream2_status['online'] = True
                    if target_size is None:
                        target_size = frame2.shape[:2]
                else:
                    self.stream2_status['online'] = False

                # Use cached frames if current ones are unavailable
                frame1 = frame1 if frame1 is not None else last_successful_frame1
                frame2 = frame2 if frame2 is not None else last_successful_frame2

                if frame1 is None and frame2 is None:
                    time.sleep(0.016)  # ~60 FPS max
                    continue

                # Create blank frame if one stream is missing
                if frame1 is None:
                    frame1 = np.zeros((target_size[0], target_size[1], 3), dtype=np.uint8)
                if frame2 is None:
                    frame2 = np.zeros((target_size[0], target_size[1], 3), dtype=np.uint8)

                # Handle transition
                if time_since_transition >= self.transition_interval:
                    if not self.transition_in_progress:
                        self.transition_in_progress = True
                        self.current_stream = 1 if self.current_stream == 2 else 2
                        self.last_transition = current_time
                    transition_progress = min(1.0, (current_time - self.last_transition) / self.transition_duration)
                    alpha = transition_progress if self.current_stream == 2 else (1 - transition_progress)
                    if transition_progress >= 1.0:
                        self.transition_in_progress = False
                else:
                    alpha = 1.0 if self.current_stream == 2 else 0.0

                # Resize frames if needed
                if frame1.shape != frame2.shape:
                    height, width = target_size
                    frame1 = cv2.resize(frame1, (width, height))
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