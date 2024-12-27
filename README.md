# Raspberry Pi Camera Stream Manager

A professional-grade web application for managing and mixing multiple Raspberry Pi camera streams with smooth transitions.

## Features

- Real-time camera stream monitoring
- Automatic stream health checking
- Smooth crossfade transitions between cameras (20 FPS)
- Network-resilient stream buffering
- Secure stream proxy with local IP support
- Stream mixing with customizable transition timing
- Responsive web interface with Bootstrap

## Technical Stack

- Python 3.11 with Flask
- OpenCV for video processing
- Flask-SocketIO for real-time updates
- Bootstrap UI framework
- Network-adaptive streaming

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Configure camera stream URLs in `app.py` or set environment variables:
- `CAMERA_STREAM_1_URL`
- `CAMERA_STREAM_2_URL`
- `CAMERA_STREAM_3_URL`

3. Run the application:
```bash
python main.py
```

The application will be available at `http://localhost:5000`

## Environment Variables

- `FLASK_SECRET_KEY`: Secret key for Flask sessions
- `CAMERA_STREAM_X_URL`: URLs for camera streams (X = 1,2,3)

## Stream Configuration

Default stream URLs point to:
```
http://10.0.0.17:8080/webcam1/?action=stream
http://10.0.0.17:8080/webcam2/?action=stream
http://10.0.0.17:8080/webcam3/?action=stream
```

## Contributing

Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.
