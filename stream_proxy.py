import logging
import requests
from flask import Response, stream_with_context
from urllib.parse import urlparse
import time

logger = logging.getLogger(__name__)

class StreamProxy:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'OctoPrint-Stream-Viewer/1.0'
        })
        self.stream_buffers = {}
        self.chunk_size = 1024

    def proxy_stream(self, stream_url):
        """Proxy an HTTP camera stream through a secure connection"""
        try:
            # Stream the response in chunks
            response = self.session.get(
                stream_url,
                stream=True,
                timeout=5
            )
            
            if response.status_code == 200:
                return Response(
                    stream_with_context(self._stream_generator(response)),
                    content_type=response.headers.get('content-type', 'multipart/x-mixed-replace;boundary=frame')
                )
            else:
                logger.error(f"Failed to proxy stream {stream_url}: HTTP {response.status_code}")
                return Response(status=response.status_code)
                
        except requests.RequestException as e:
            logger.error(f"Error proxying stream {stream_url}: {str(e)}")
            return Response(status=503)

    def _stream_generator(self, response):
        """Generate streaming response"""
        for chunk in response.iter_content(chunk_size=self.chunk_size):
            if chunk:
                yield chunk
            else:
                break

stream_proxy = StreamProxy()
